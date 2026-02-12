from __future__ import annotations

import csv
import hashlib
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from config import (
    SERVICE_CATALOG_FORCE_RELOAD,
    SERVICE_CATALOG_STRICT_VALIDATION,
    SERVICE_CATALOG_TTL_SECONDS,
    SERVICE_CLARIFY_MARGIN_MIN,
    SERVICE_MATCH_MIN_SCORE,
    SERVICE_MATCH_TOP_K,
    SERVICE_MATCHER_MODE,
    SERVICE_SIGNAL_REQUIRED_STRICT,
)
from service_semantic import ServiceSemanticCandidate, rank_semantic_candidates

_CACHE_LOCK = threading.Lock()
_CACHE: "ServiceCatalogSnapshot | None" = None
_CACHE_TS: float = 0.0
_CACHE_SOURCE_PATH: str = ""

_RISK_ORDER = {"conservative": 1, "moderate": 2, "aggressive": 3}


@dataclass
class ServiceCatalogItem:
    service_id: str
    title: str
    summary: str
    family: str
    doc_path: str
    intents: list[str] = field(default_factory=list)
    trigger_facts: list[str] = field(default_factory=list)
    trigger_keywords_vi: list[str] = field(default_factory=list)
    trigger_keywords_en: list[str] = field(default_factory=list)
    required_signals: list[str] = field(default_factory=list)
    optional_signals: list[str] = field(default_factory=list)
    blocked_signals: list[str] = field(default_factory=list)
    min_risk: str = ""
    max_risk: str = ""
    requires_disclosure: bool = False
    disclosure_refs: list[str] = field(default_factory=list)
    priority: int = 50
    status: str = "active"
    metadata_errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.metadata_errors and self.status == "active"


@dataclass
class ServiceCatalogSnapshot:
    version: str
    loaded_at_epoch: float
    source_path: str
    items: dict[str, ServiceCatalogItem] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class ServiceMatchResult:
    service_id: str
    family: str
    title: str
    score: float
    matched_signals: list[str] = field(default_factory=list)
    disclosure_refs: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    priority: int = 50
    rank: int = 0
    embedding_score: float = 0.0
    margin_to_next: float = 0.0


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv_field(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    tokens = re.split(r"[|,;]", text)
    return [unicodedata.normalize("NFC", token.strip()).lower() for token in tokens if token and token.strip()]


def _resolve_kb_dir() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates: list[Path] = []

    kb_dir_env = str(os.getenv("KB_DIR") or "").strip()
    if kb_dir_env:
        candidates.append(Path(kb_dir_env).expanduser())

    candidates.extend([here.parent / "kb", here / "kb", Path.cwd() / "kb"])

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def _parse_front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out: dict[str, str] = {}
    for idx in range(1, len(lines)):
        line = lines[idx].strip()
        if line == "---":
            return out
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip().lower()] = value.strip()
    return {}


def _normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", str(text or "")).strip().lower()


def _normalize_text_ascii_fallback(text: str) -> str:
    normalized = _normalize_text(text)
    stripped = "".join(ch for ch in unicodedata.normalize("NFD", normalized) if unicodedata.category(ch) != "Mn")
    return stripped


def _mk_version(index_path: Path, doc_paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    digest.update(index_path.read_bytes())
    for path in sorted(doc_paths, key=lambda item: str(item)):
        try:
            stat = path.stat()
            digest.update(str(path).encode("utf-8"))
            digest.update(str(stat.st_mtime_ns).encode("utf-8"))
            digest.update(str(stat.st_size).encode("utf-8"))
        except OSError:
            continue
    return digest.hexdigest()[:16]


def _risk_in_band(risk_appetite: str, min_risk: str, max_risk: str) -> bool:
    risk = _RISK_ORDER.get(risk_appetite.strip().lower())
    if risk is None:
        return True
    min_rank = _RISK_ORDER.get(min_risk.strip().lower(), 1)
    max_rank = _RISK_ORDER.get(max_risk.strip().lower(), 3)
    return min_rank <= risk <= max_rank


def _safe_priority(raw: str) -> int:
    text = str(raw or "").strip()
    if not text:
        return 50
    try:
        value = int(float(text))
    except ValueError:
        return 50
    return max(1, min(99, value))


def _load_rows_from_index(index_path: Path) -> list[dict[str, str]]:
    with index_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        rows: list[dict[str, str]] = []
        for row in reader:
            normalized: dict[str, str] = {}
            for key, value in row.items():
                key_norm = str(key or "").strip()
                if not key_norm:
                    continue
                normalized[key_norm] = str(value or "").strip()
            if normalized:
                rows.append(normalized)
        return rows


def _bool_with_alias(row: dict[str, str], primary: str, alias: str, default: bool = False) -> bool:
    raw = str(row.get(primary) or row.get(alias) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _text_with_alias(row: dict[str, str], primary: str, alias: str, default: str = "") -> str:
    return str(row.get(primary) or row.get(alias) or default).strip()


def _build_item(row: dict[str, str], kb_dir: Path, strict: bool) -> ServiceCatalogItem | None:
    doc_type = str(row.get("doc_type") or "").strip().lower()
    if doc_type != "service":
        return None

    service_id = str(row.get("service_id") or "").strip().lower()
    doc_path_raw = str(row.get("doc_path") or "").strip()
    if not doc_path_raw:
        fallback_name = str(row.get("name") or "").strip()
        doc_path_raw = f"{fallback_name}.md" if fallback_name else ""

    title = str(row.get("title") or row.get("title_vi") or row.get("name") or service_id).strip()
    summary = str(row.get("summary") or "").strip()
    family = str(row.get("family") or "").strip().lower()
    intents = _split_csv_field(row.get("intents_csv", ""))
    trigger_facts = _split_csv_field(row.get("trigger_facts_csv", ""))
    trigger_keywords_vi = _split_csv_field(row.get("trigger_keywords_vi_csv", ""))
    trigger_keywords_en = _split_csv_field(row.get("trigger_keywords_en_csv", ""))
    required_signals = _split_csv_field(row.get("required_signals_csv", ""))
    optional_signals = _split_csv_field(row.get("optional_signals_csv", ""))
    blocked_signals = _split_csv_field(row.get("blocked_signals_csv", ""))
    min_risk = _text_with_alias(row, "risk_band_min", "min_risk").lower()
    max_risk = _text_with_alias(row, "risk_band_max", "max_risk").lower()
    requires_disclosure = _bool_with_alias(row, "disclosure_required", "requires_disclosure", default=False)
    disclosure_refs = [ref for ref in _split_csv_field(row.get("disclosure_refs_csv", "")) if ref]
    priority = _safe_priority(row.get("priority", "50"))
    status = str(row.get("status") or "active").strip().lower() or "active"

    errors: list[str] = []
    if not service_id:
        errors.append("service_id_missing")
    if not family:
        errors.append("family_missing")
    if not intents:
        errors.append("intents_missing")
    if not doc_path_raw:
        errors.append("doc_path_missing")
    if not status:
        errors.append("status_missing")

    doc_path = (kb_dir / doc_path_raw).resolve()
    if not doc_path.exists():
        errors.append("doc_missing")
    front_matter: dict[str, str] = {}
    if doc_path.exists():
        try:
            front_matter = _parse_front_matter(doc_path)
        except Exception:
            errors.append("doc_front_matter_parse_error")

    fm_service_id = str(front_matter.get("service_id") or "").strip().lower()
    fm_family = str(front_matter.get("family") or "").strip().lower()
    fm_requires_disclosure = str(
        front_matter.get("requires_disclosure") or front_matter.get("disclosure_required") or ""
    ).strip().lower()
    fm_disclosure_refs = _split_csv_field(front_matter.get("disclosure_refs", ""))

    if fm_service_id and service_id and fm_service_id != service_id:
        errors.append("service_id_mismatch_csv_md")
    if fm_family and family and fm_family != family:
        errors.append("family_mismatch_csv_md")
    if fm_requires_disclosure:
        fm_bool = fm_requires_disclosure in {"1", "true", "yes", "on"}
        if fm_bool != requires_disclosure:
            errors.append("requires_disclosure_mismatch_csv_md")
    if fm_disclosure_refs and disclosure_refs and set(fm_disclosure_refs) != set(disclosure_refs):
        errors.append("disclosure_refs_mismatch_csv_md")
    if requires_disclosure and not disclosure_refs:
        errors.append("disclosure_refs_missing")

    if strict and errors:
        status = "invalid"

    return ServiceCatalogItem(
        service_id=service_id,
        title=title or service_id,
        summary=summary or title or service_id,
        family=family,
        doc_path=str(Path(doc_path_raw).as_posix()),
        intents=intents,
        trigger_facts=trigger_facts,
        trigger_keywords_vi=trigger_keywords_vi,
        trigger_keywords_en=trigger_keywords_en,
        required_signals=required_signals,
        optional_signals=optional_signals,
        blocked_signals=blocked_signals,
        min_risk=min_risk,
        max_risk=max_risk,
        requires_disclosure=requires_disclosure,
        disclosure_refs=disclosure_refs,
        priority=priority,
        status=status,
        metadata_errors=errors,
    )


def load_catalog(*, force_reload: bool = False, kb_dir: Path | None = None) -> ServiceCatalogSnapshot:
    global _CACHE, _CACHE_TS, _CACHE_SOURCE_PATH

    now = time.time()
    ttl_seconds = max(30, int(SERVICE_CATALOG_TTL_SECONDS))
    root = kb_dir or _resolve_kb_dir()
    current_source = str(root.resolve()) if root is not None else ""

    with _CACHE_LOCK:
        if (
            not force_reload
            and _CACHE is not None
            and (now - _CACHE_TS) <= ttl_seconds
            and _CACHE_SOURCE_PATH == current_source
        ):
            return _CACHE

        if root is None:
            snapshot = ServiceCatalogSnapshot(
                version="na",
                loaded_at_epoch=now,
                source_path="",
                items={},
                errors=["kb_dir_not_found"],
            )
            _CACHE = snapshot
            _CACHE_TS = now
            _CACHE_SOURCE_PATH = ""
            return snapshot

        index_path = root / "kb_index.csv"
        if not index_path.exists():
            snapshot = ServiceCatalogSnapshot(
                version="na",
                loaded_at_epoch=now,
                source_path=str(index_path),
                items={},
                errors=["kb_index_missing"],
            )
            _CACHE = snapshot
            _CACHE_TS = now
            _CACHE_SOURCE_PATH = current_source
            return snapshot

        rows = _load_rows_from_index(index_path)
        strict_validation = SERVICE_CATALOG_STRICT_VALIDATION and _env_bool(
            "SERVICE_CATALOG_STRICT_VALIDATION", SERVICE_CATALOG_STRICT_VALIDATION
        )

        items: dict[str, ServiceCatalogItem] = {}
        errors: list[str] = []
        doc_paths: list[Path] = []
        for row in rows:
            item = _build_item(row, root, strict_validation)
            if item is None:
                continue
            doc_paths.append((root / item.doc_path).resolve())
            if not item.service_id:
                errors.append("service_id_missing")
                continue
            if item.service_id in items:
                errors.append(f"duplicate_service_id:{item.service_id}")
                continue
            items[item.service_id] = item
            if item.metadata_errors:
                errors.append(f"{item.service_id}:{','.join(item.metadata_errors)}")

        version = _mk_version(index_path, doc_paths)
        snapshot = ServiceCatalogSnapshot(
            version=version,
            loaded_at_epoch=now,
            source_path=str(index_path),
            items=items,
            errors=errors,
        )
        _CACHE = snapshot
        _CACHE_TS = now
        _CACHE_SOURCE_PATH = current_source
        return snapshot


def maybe_reload_catalog(*, kb_dir: Path | None = None) -> ServiceCatalogSnapshot:
    force_env = _env_bool("SERVICE_CATALOG_FORCE_RELOAD", SERVICE_CATALOG_FORCE_RELOAD)
    if force_env:
        os.environ["SERVICE_CATALOG_FORCE_RELOAD"] = "false"
        return load_catalog(force_reload=True, kb_dir=kb_dir)
    return load_catalog(force_reload=False, kb_dir=kb_dir)


def _collect_fact_ids(evidence_facts: list[Any]) -> list[str]:
    out: list[str] = []
    for fact in evidence_facts:
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        if fact_id:
            out.append(fact_id)
    return out


def _collect_fact_summaries(evidence_facts: list[Any], limit: int = 8) -> list[str]:
    rows: list[str] = []
    for fact in evidence_facts:
        fact_id = str(getattr(fact, "fact_id", "") or "").strip()
        value_text = str(getattr(fact, "value_text", "") or "").strip()
        if not fact_id:
            continue
        rows.append(f"{fact_id}:{value_text}" if value_text else fact_id)
        if len(rows) >= limit:
            break
    return rows


def _collect_kb_text(kb_matches: list[dict[str, Any]]) -> tuple[str, str]:
    corpus: list[str] = []
    for item in kb_matches:
        if not isinstance(item, dict):
            continue
        for key in ["text", "snippet", "context", "citation", "section"]:
            value = str(item.get(key) or "").strip()
            if value:
                corpus.append(value)
    joined = " ".join(corpus)
    return _normalize_text(joined), _normalize_text_ascii_fallback(joined)


def _trigger_overlap(trigger_prefixes: list[str], fact_ids: list[str]) -> tuple[float, list[str]]:
    if not trigger_prefixes:
        return 0.0, []
    matched: list[str] = []
    for trigger in trigger_prefixes:
        for fact_id in fact_ids:
            if fact_id.startswith(trigger):
                matched.append(trigger)
                break
    if not matched:
        return 0.0, []
    score = len(set(matched)) / max(len(trigger_prefixes), 1)
    return max(0.0, min(1.0, score)), sorted(set(matched))


def _keyword_overlap(
    keywords: list[str],
    *,
    prompt_text: str,
    kb_text: str,
    prompt_text_fallback: str,
    kb_text_fallback: str,
) -> tuple[float, list[str], bool]:
    if not keywords:
        return 0.0, [], False
    matched = [keyword for keyword in keywords if keyword and (keyword in prompt_text or keyword in kb_text)]
    fallback_used = False
    if not matched:
        # Accent-insensitive fallback: only used when primary (accent-preserving) matching misses.
        matched = [
            keyword
            for keyword in keywords
            if keyword
            and (
                _normalize_text_ascii_fallback(keyword) in prompt_text_fallback
                or _normalize_text_ascii_fallback(keyword) in kb_text_fallback
            )
        ]
        fallback_used = bool(matched)
    if not matched:
        return 0.0, [], False
    score = len(set(matched)) / max(len(keywords), 1)
    return max(0.0, min(1.0, score)), sorted(set(matched)), fallback_used


def _signal_overlap(
    *,
    required_signals: list[str],
    optional_signals: list[str],
    user_signals: set[str],
) -> tuple[float, list[str], list[str]]:
    req = [item for item in required_signals if item]
    opt = [item for item in optional_signals if item]
    req_matches = sorted(set(item for item in req if item in user_signals))
    opt_matches = sorted(set(item for item in opt if item in user_signals))

    if not req and not opt:
        return 0.0, req_matches, opt_matches

    req_ratio = (len(req_matches) / len(req)) if req else 1.0
    opt_ratio = (len(opt_matches) / len(opt)) if opt else 0.0
    if req and opt:
        score = (0.70 * req_ratio) + (0.30 * opt_ratio)
    elif req:
        score = req_ratio
    else:
        score = opt_ratio
    return max(0.0, min(1.0, score)), req_matches, opt_matches


def _build_service_semantic_text(item: ServiceCatalogItem) -> str:
    tokens: list[str] = [
        item.title,
        item.summary,
        item.family,
        " ".join(item.intents),
        " ".join(item.trigger_keywords_vi),
        " ".join(item.trigger_keywords_en),
        " ".join(item.required_signals),
        " ".join(item.optional_signals),
    ]
    return "\n".join([token for token in tokens if token and token.strip()])


def _build_query_text(
    *,
    user_prompt: str,
    intent: str,
    user_signals: list[str],
    fact_summaries: list[str],
    kb_text: str,
) -> str:
    sections = [
        str(user_prompt or "").strip(),
        f"intent:{intent}",
        "signals:" + ",".join(user_signals),
        "facts:" + "; ".join(fact_summaries),
        "kb:" + kb_text[:400],
    ]
    return "\n".join([section for section in sections if section and section.strip()])


def match_services(
    *,
    intent: str,
    user_prompt: str,
    evidence_facts: list[Any],
    kb_matches: list[dict[str, Any]],
    policy_flags: dict[str, Any] | None = None,
    service_signals: list[str] | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    kb_dir: Path | None = None,
    mode: str | None = None,
) -> tuple[list[ServiceMatchResult], dict[str, Any]]:
    effective_mode = str(mode or os.getenv("SERVICE_MATCHER_MODE") or SERVICE_MATCHER_MODE).strip().lower()
    if effective_mode not in {"dynamic", "dynamic_v2"}:
        return [], {
            "catalog_version": "",
            "candidates": [],
            "filtered_by_policy": [],
            "embedding_candidates": [],
            "signals": [],
            "selected": [],
            "clarification_triggered": False,
            "clarification_options": [],
            "margin": 0.0,
            "reason_codes": ["service_matcher_static_mode"],
            "mode": effective_mode,
        }

    snapshot = maybe_reload_catalog(kb_dir=kb_dir)
    if not snapshot.items:
        return [], {
            "catalog_version": snapshot.version,
            "candidates": [],
            "filtered_by_policy": [],
            "embedding_candidates": [],
            "signals": [],
            "selected": [],
            "clarification_triggered": False,
            "clarification_options": [],
            "margin": 0.0,
            "reason_codes": ["service_catalog_empty", *snapshot.errors],
            "mode": effective_mode,
        }

    limit = max(1, int(top_k if top_k is not None else SERVICE_MATCH_TOP_K))
    default_threshold = float(SERVICE_MATCH_MIN_SCORE)
    if effective_mode == "dynamic":
        default_threshold = min(default_threshold, 0.55)
    threshold = float(min_score if min_score is not None else default_threshold)
    strict_required_signals = _env_bool("SERVICE_SIGNAL_REQUIRED_STRICT", SERVICE_SIGNAL_REQUIRED_STRICT)
    margin_min = float(os.getenv("SERVICE_CLARIFY_MARGIN_MIN") or SERVICE_CLARIFY_MARGIN_MIN)

    prompt_norm = _normalize_text(user_prompt)
    prompt_norm_fallback = _normalize_text_ascii_fallback(user_prompt)
    kb_text, kb_text_fallback = _collect_kb_text(kb_matches)
    fact_ids = _collect_fact_ids(evidence_facts)
    fact_summaries = _collect_fact_summaries(evidence_facts, limit=8)
    risk_appetite = str((policy_flags or {}).get("risk_appetite") or "").strip().lower()
    education_only = bool((policy_flags or {}).get("education_only"))
    inferred_signals: list[str] = []
    if service_signals is None:
        try:
            from service_signals import extract_service_signals

            inferred_signals = extract_service_signals(
                facts=evidence_facts,
                policy_flags=policy_flags or {},
            ).signals
        except Exception:
            inferred_signals = []

    raw_signals = service_signals if service_signals is not None else inferred_signals
    normalized_signals = sorted(set(str(item or "").strip().lower() for item in raw_signals if str(item).strip()))
    user_signal_set = set(normalized_signals)

    service_items = [item for item in snapshot.items.values() if item.status == "active" and not item.metadata_errors]
    service_texts = {item.service_id: _build_service_semantic_text(item) for item in service_items}
    query_text = _build_query_text(
        user_prompt=user_prompt,
        intent=str(intent or "").strip().lower(),
        user_signals=normalized_signals,
        fact_summaries=fact_summaries,
        kb_text=kb_text,
    )
    semantic_candidates, semantic_reason_codes = rank_semantic_candidates(
        query_text=query_text,
        service_texts=service_texts,
        catalog_version=snapshot.version,
    )
    embedding_score_map = {row.service_id: float(row.normalized_similarity) for row in semantic_candidates}

    candidates: list[ServiceMatchResult] = []
    candidate_meta: list[dict[str, Any]] = []
    filtered_by_policy: list[dict[str, Any]] = []

    allowed_education_families = {"savings_deposit", "loans_credit", "cards_payments", "catalog"}
    intent_key = str(intent or "").strip().lower()
    for item in service_items:
        policy_reasons: list[str] = []
        if education_only and item.family not in allowed_education_families:
            policy_reasons.append("education_only_family_blocked")
        if not _risk_in_band(risk_appetite, item.min_risk, item.max_risk):
            policy_reasons.append("risk_band_blocked")
        if item.requires_disclosure and not item.disclosure_refs:
            policy_reasons.append("disclosure_missing")
        if intent_key == "invest" and item.family not in allowed_education_families:
            policy_reasons.append("invest_guard_blocked")
        if policy_reasons:
            filtered_by_policy.append(
                {"service_id": item.service_id, "family": item.family, "reason_codes": sorted(set(policy_reasons))}
            )
            continue

        blocked_hits = sorted(set(sig for sig in item.blocked_signals if sig in user_signal_set))
        if blocked_hits:
            filtered_by_policy.append(
                {
                    "service_id": item.service_id,
                    "family": item.family,
                    "reason_codes": ["blocked_signals_match", *[f"blocked:{sig}" for sig in blocked_hits]],
                }
            )
            continue

        req_matches = sorted(set(sig for sig in item.required_signals if sig in user_signal_set))
        if strict_required_signals and item.required_signals and not req_matches:
            filtered_by_policy.append(
                {
                    "service_id": item.service_id,
                    "family": item.family,
                    "reason_codes": ["required_signals_missing"],
                }
            )
            continue

        intent_fit = 1.0 if intent_key in set(item.intents) else 0.0
        signal_fit, req_signal_matches, opt_signal_matches = _signal_overlap(
            required_signals=item.required_signals,
            optional_signals=item.optional_signals,
            user_signals=user_signal_set,
        )
        fact_fit, fact_matches = _trigger_overlap(item.trigger_facts, fact_ids)
        kw_vi_fit, kw_vi_matches, kw_vi_fallback = _keyword_overlap(
            item.trigger_keywords_vi,
            prompt_text=prompt_norm,
            kb_text=kb_text,
            prompt_text_fallback=prompt_norm_fallback,
            kb_text_fallback=kb_text_fallback,
        )
        kw_en_fit, kw_en_matches, kw_en_fallback = _keyword_overlap(
            item.trigger_keywords_en,
            prompt_text=prompt_norm,
            kb_text=kb_text,
            prompt_text_fallback=prompt_norm_fallback,
            kb_text_fallback=kb_text_fallback,
        )
        keyword_fit = max(kw_vi_fit, kw_en_fit)
        keyword_matches = kw_vi_matches if kw_vi_fit >= kw_en_fit else kw_en_matches
        embedding_fit = max(0.0, min(1.0, float(embedding_score_map.get(item.service_id, 0.0))))
        priority_fit = max(0.0, min(1.0, (100.0 - float(item.priority)) / 99.0))

        score = (
            (0.25 * intent_fit)
            + (0.30 * signal_fit)
            + (0.20 * fact_fit)
            + (0.15 * embedding_fit)
            + (0.05 * keyword_fit)
            + (0.05 * priority_fit)
        )
        score = round(score, 6)

        matched_signals = sorted(
            set(
                [*req_signal_matches, *opt_signal_matches, *[f"fact:{token}" for token in fact_matches]]
            )
        )

        reason_codes: list[str] = []
        if intent_fit <= 0:
            reason_codes.append("intent_partial_match")
        if signal_fit <= 0:
            reason_codes.append("signal_no_overlap")
        if fact_fit <= 0:
            reason_codes.append("fact_no_overlap")
        if embedding_fit <= 0:
            reason_codes.append("embedding_no_overlap")
        if keyword_fit <= 0:
            reason_codes.append("keyword_no_overlap")
        elif kw_vi_fallback or kw_en_fallback:
            reason_codes.append("keyword_fallback_ascii")

        candidates.append(
            ServiceMatchResult(
                service_id=item.service_id,
                family=item.family,
                title=item.title,
                score=score,
                matched_signals=matched_signals,
                disclosure_refs=list(item.disclosure_refs),
                reason_codes=sorted(set(reason_codes)),
                priority=item.priority,
                rank=0,
                embedding_score=round(embedding_fit, 6),
                margin_to_next=0.0,
            )
        )
        candidate_meta.append(
            {
                "service_id": item.service_id,
                "family": item.family,
                "score": score,
                "intent_fit": round(intent_fit, 6),
                "signal_fit": round(signal_fit, 6),
                "fact_fit": round(fact_fit, 6),
                "embedding_fit": round(embedding_fit, 6),
                "keyword_fit": round(keyword_fit, 6),
                "priority_fit": round(priority_fit, 6),
                "matched_signals": matched_signals,
                "reason_codes": sorted(set(reason_codes)),
            }
        )

    scored = [item for item in candidates if item.score >= threshold]
    scored.sort(key=lambda item: (-item.score, item.priority, item.service_id))
    selected = scored[:limit]
    for idx, item in enumerate(selected, start=1):
        item.rank = idx
    for idx in range(len(selected)):
        if idx + 1 < len(selected):
            selected[idx].margin_to_next = round(selected[idx].score - selected[idx + 1].score, 6)
        else:
            selected[idx].margin_to_next = 1.0

    margin = 0.0
    if len(selected) >= 2:
        margin = round(selected[0].score - selected[1].score, 6)
    elif selected:
        margin = 1.0

    clarification_triggered = effective_mode == "dynamic_v2" and len(selected) >= 2 and margin < margin_min
    clarification_options: list[dict[str, Any]] = []
    if clarification_triggered:
        clarification_options = [
            {
                "service_id": selected[0].service_id,
                "family": selected[0].family,
                "title": selected[0].title,
                "score": selected[0].score,
            },
            {
                "service_id": selected[1].service_id,
                "family": selected[1].family,
                "title": selected[1].title,
                "score": selected[1].score,
            },
        ]

    meta_reason_codes = [*snapshot.errors, *semantic_reason_codes]
    if clarification_triggered:
        meta_reason_codes.append("service_clarify_low_margin")
    if not selected:
        meta_reason_codes.append("no_service_above_threshold")

    meta = {
        "catalog_version": snapshot.version,
        "mode": effective_mode,
        "signals": normalized_signals,
        "embedding_candidates": [
            {
                "service_id": row.service_id,
                "similarity": row.similarity,
                "normalized_similarity": row.normalized_similarity,
                "rank": row.rank,
            }
            for row in semantic_candidates
        ],
        "candidates": candidate_meta,
        "filtered_by_policy": filtered_by_policy,
        "selected": [row.service_id for row in selected],
        "clarification_triggered": clarification_triggered,
        "clarification_options": clarification_options,
        "margin": margin,
        "reason_codes": sorted(set(code for code in meta_reason_codes if str(code).strip())),
    }
    return selected, meta
