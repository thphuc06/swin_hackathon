from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Iterable

import boto3
from botocore.config import Config
from pydantic import ValidationError

from config import AWS_REGION, BEDROCK_CONNECT_TIMEOUT, BEDROCK_MODEL_ID, BEDROCK_READ_TIMEOUT

from .contracts import AdvisoryContextV1, AnswerPlanV2
from .schemas import validate_answer_plan_payload

logger = logging.getLogger(__name__)
PROMPT_VERSION = "answer_synth_v2"
DEFAULT_DISCLAIMER = "Educational guidance only. We do not provide investment advice."
_FACT_PLACEHOLDER_PATTERN = re.compile(r"\[F:([a-zA-Z0-9._-]+)\]")
_NON_FACT_PLACEHOLDER_PATTERN = re.compile(r"\[(?:A|I):[^\]]+\]")

# Boto3 client cache with timeout config
_bedrock_client = None

def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        config = Config(
            connect_timeout=BEDROCK_CONNECT_TIMEOUT,
            read_timeout=BEDROCK_READ_TIMEOUT,
            retries={'max_attempts': 2, 'mode': 'adaptive'}
        )
        _bedrock_client = boto3.client(
            "bedrock-runtime",
            region_name=AWS_REGION,
            config=config
        )
        logger.info(
            "Initialized Bedrock client with timeout config (connect=%ds, read=%ds)",
            BEDROCK_CONNECT_TIMEOUT,
            BEDROCK_READ_TIMEOUT,
        )
    return _bedrock_client


def _build_prompt(
    *,
    user_prompt: str,
    intent: str,
    route_decision: Dict[str, Any],
    advisory_context: AdvisoryContextV1,
    policy_flags: Dict[str, Any],
    corrective_feedback: str = "",
) -> str:
    context_json = json.dumps(
        {
            "schema_version": advisory_context.schema_version,
            "intent": advisory_context.intent,
            "language": advisory_context.language,
            "facts": [
                {
                    "fact_id": fact.fact_id,
                    "label": fact.label,
                    "value_text": fact.value_text,
                    "timeframe": fact.timeframe,
                    "source_tool": fact.source_tool,
                }
                for fact in advisory_context.facts
            ],
            "insights": [
                {
                    "insight_id": insight.insight_id,
                    "kind": insight.kind,
                    "severity": insight.severity,
                    "message_seed": insight.message_seed,
                    "supporting_fact_ids": insight.supporting_fact_ids,
                }
                for insight in advisory_context.insights
            ],
            "actions": [
                {
                    "action_id": action.action_id,
                    "priority": action.priority,
                    "action_type": action.action_type,
                    "params": action.params,
                    "supporting_insight_ids": action.supporting_insight_ids,
                }
                for action in advisory_context.actions
            ],
            "citations": advisory_context.citations,
            "policy_flags": advisory_context.policy_flags,
        },
        ensure_ascii=True,
    )
    route_json = json.dumps(route_decision, ensure_ascii=True)
    policy_json = json.dumps(policy_flags, ensure_ascii=True)
    correction = f"\nPrevious attempt issues: {corrective_feedback}" if corrective_feedback else ""

    return (
        "You are a compliant fintech advisor response synthesizer.\n"
        "Return ONLY one valid JSON object. No markdown.\n"
        "The object must follow schema answer_plan_v2 with no extra properties.\n"
        "schema_version must be 'answer_plan_v2'.\n"
        "language must be 'vi' or 'en'.\n"
        "summary_lines must contain 3 to 5 concise lines.\n"
        "actions must contain 2 to 4 concise items.\n"
        "Use plain, persuasive advisory wording (bank-advisor style), but keep every claim grounded.\n"
        "You are NOT allowed to invent new numbers.\n"
        "For any metric number in free text, use fact placeholders [F:fact_id] only.\n"
        "Small operational cadence numbers (for example 2 weeks, 14 days) are allowed only if they are in user prompt/policy context.\n"
        "Do not print raw numeric literals in summary_lines/actions/assumptions/limitations.\n"
        "key_metrics must be array of {fact_id,label} referencing known fact_ids.\n"
        "used_fact_ids must include every fact referenced by key_metrics or placeholders.\n"
        "used_insight_ids must reference provided insight IDs only.\n"
        "used_action_ids must reference provided action IDs only.\n"
        "If education_only is true, avoid buy/sell/trade execution advice.\n"
        "If intent is invest and user asks buy/sell recommendation, refuse recommendation and redirect to non-investment planning.\n"
        "Personalize suggestions with policy_flags.risk_appetite: conservative -> prioritize safety/liquidity; "
        "moderate -> balance stability and progress; aggressive -> accept higher uncertainty while staying non-investment.\n"
        "If risk_appetite is unknown and intent is planning/scenario/invest, include one concise follow-up question "
        "asking user to choose risk appetite (thap/vua/cao) and keep guidance provisional.\n"
        "For Vietnamese output, use simple daily wording and avoid internal tool names/IDs.\n"
        "Vietnamese terminology contract:\n"
        "- Use exact, professional banking terms from facts.\n"
        "- Use the exact term 'dòng tiền ròng' for net cashflow.\n"
        "- Never use malformed variants such as 'dòng tiền rỗng' or 'dòng tiền rộng'.\n"
        "- Use 'thu nhập', 'chi tiêu', 'khẩu vị rủi ro', 'bất thường', 'khả thi' consistently.\n"
        "- For risk labels in Vietnamese, map low/medium/high to thấp/trung bình/cao.\n"
        "- Do not output mixed bilingual tokens in one phrase (for example 'thấp low').\n"
        "- Avoid duplicated adjacent values or repeated percentages in the same sentence.\n"
        "- For each metric/count, mention the numeric value only once per sentence.\n"
        "- Never append orphan numeric suffixes at sentence end (for example '... 1.').\n"
        "- Do not output unaccented Vietnamese in final prose when language='vi'.\n"
        "- Never output malformed or pseudo-Vietnamese spellings (for example 'thiềt tân', 'dềch vụ', 'têng tốc').\n"
        "- If you produce a malformed Vietnamese phrase, rewrite it to standard Vietnamese before final JSON.\n"
        "- If generated metric wording conflicts with fact semantics, rewrite wording to match fact meaning.\n"
        "When facts include kb.service_category.*, include at least one practical banking service suggestion in actions.\n"
        "Map service suggestion to context: savings_capacity -> savings/deposit; goal_gap or negative cashflow -> loan/credit support; spend anomaly -> card/payment control.\n"
        "If any fact with prefix anomaly.latest_change_point. exists and context is risk/anomaly (or user asks anomaly date/time), include it explicitly in summary_lines and key_metrics.\n"
        "If facts include anomaly.flag_reason.* and context is risk/anomaly, explicitly explain one or two top anomaly reasons in summary_lines.\n"
        "Do not expose internal fact IDs, insight IDs, action IDs, or tool IDs in prose.\n"
        "When scenario best variant is base, still provide concrete next actions grounded by available facts.\n"
        "If data is missing, write it in limitations without inventing facts.\n"
        "JSON example:\n"
        "{\"schema_version\":\"answer_plan_v2\",\"language\":\"vi\","
        "\"summary_lines\":[\"DÃ²ng tiá»n rÃ²ng [F:spend.net_cashflow.30d]\",\"...\",\"...\"],"
        "\"key_metrics\":[{\"fact_id\":\"spend.net_cashflow.30d\",\"label\":\"DÃ²ng tiá»n rÃ²ng\"}],"
        "\"actions\":[\"Æ¯u tiÃªn á»•n Ä‘á»‹nh dÃ²ng tiá»n theo [F:spend.net_cashflow.30d]\",\"...\"],"
        "\"assumptions\":[],\"limitations\":[],"
        "\"disclaimer\":\"Educational guidance only. We do not provide investment advice.\","
        "\"used_fact_ids\":[\"spend.net_cashflow.30d\"],"
        "\"used_insight_ids\":[\"insight.cashflow_pressure\"],"
        "\"used_action_ids\":[\"stabilize_cashflow\"]}\n"
        f"{correction}\n"
        f"User prompt: {user_prompt}\n"
        f"Intent: {intent}\n"
        f"Route decision: {route_json}\n"
        f"Policy flags: {policy_json}\n"
        f"Advisory context: {context_json}\n"
    )


def _extract_text_from_converse_payload(payload: Dict[str, Any]) -> str:
    output = payload.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []
    texts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                texts.append(item["text"])
    return "\n".join(texts).strip()


def _try_parse_json(raw_text: str) -> Dict[str, Any] | None:
    text = _normalize_json_text(raw_text or "")
    if not text:
        return None

    direct = _load_json_candidate(text)
    if isinstance(direct, dict):
        return direct

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        parsed = _load_json_candidate(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = text[start : end + 1]
    parsed = _load_json_candidate(candidate)
    return parsed if isinstance(parsed, dict) else None


def _normalize_json_text(text: str) -> str:
    normalized = str(text or "").strip().lstrip("\ufeff")
    replacements = {
        "\u201c": "\"",
        "\u201d": "\"",
        "\u2018": "'",
        "\u2019": "'",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"^\s*json\s*[:\-]?\s*", "", normalized, flags=re.IGNORECASE)
    return normalized.strip()


def _load_json_candidate(text: str) -> Dict[str, Any] | None:
    candidate = _normalize_json_text(text)
    if not candidate:
        return None

    candidates = [candidate, re.sub(r",(\s*[}\]])", r"\1", candidate)]
    for item in candidates:
        try:
            parsed = json.loads(item)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            return parsed[0]
        if isinstance(parsed, str):
            try:
                nested = json.loads(parsed)
            except json.JSONDecodeError:
                continue
            if isinstance(nested, dict):
                return nested
    return None


def _invoke_bedrock_converse(prompt: str, *, model_id: str) -> str:
    client = _get_bedrock_client()
    logger.debug("Invoking Bedrock converse for answer synthesis (model=%s)", model_id)
    response = client.converse(
        modelId=model_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": 0.0, "topP": 0.01, "maxTokens": 900},
    )
    return _extract_text_from_converse_payload(response)


def _dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        key = str(item).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _coerce_key_metrics(value: Any) -> list[Dict[str, str]]:
    metrics: list[Dict[str, str]] = []
    if value is None:
        return metrics

    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            fact_id = str(item.get("fact_id") or "").strip()
            if not fact_id:
                continue
            metrics.append(
                {
                    "fact_id": fact_id,
                    "label": str(item.get("label") or "").strip(),
                }
            )
        return metrics

    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).strip()
            if not key_text:
                continue
            if isinstance(item, dict):
                metrics.append(
                    {
                        "fact_id": str(item.get("fact_id") or key_text).strip(),
                        "label": str(item.get("label") or "").strip(),
                    }
                )
                continue
            metrics.append({"fact_id": key_text, "label": ""})
    return metrics


_ADJACENT_PHRASE_REPEAT_PATTERN = re.compile(
    r"\b(?P<phrase>[0-9A-Za-zÀ-ỹ]+(?:\s+[0-9A-Za-zÀ-ỹ]+){0,3})\s+(?P=phrase)\b",
    flags=re.IGNORECASE,
)


def _collapse_adjacent_phrase_repetition(text: str) -> str:
    current = str(text or "")
    for _ in range(3):
        updated = _ADJACENT_PHRASE_REPEAT_PATTERN.sub(lambda match: str(match.group("phrase") or ""), current)
        if updated == current:
            break
        current = updated
    return current


def _sanitize_prose_line(text: str, *, language: str) -> str:
    line = str(text or "").strip()
    if not line:
        return ""

    # Remove non-fact placeholders leaked by model.
    line = _NON_FACT_PLACEHOLDER_PATTERN.sub("", line)
    line = _collapse_adjacent_phrase_repetition(line)

    # Collapse obvious duplicate adjacent numeric tokens.
    line = re.sub(r"\b(\d+(?:[.,]\d+)?%?)\s+\1\b", r"\1", line, flags=re.IGNORECASE)

    # Keep one representation when model repeats amount in two adjacent formats.
    line = re.sub(
        r"(\b\d+(?:[.,]\d+)?\s*(?:ty|tỷ|trieu|triệu|k|nghin|ngan|million|billion|bn|m)\b)\s+\d[\d,\.]*(?=\b)",
        r"\1",
        line,
        flags=re.IGNORECASE,
    )

    # Collapse obvious duplicate adjacent percentages.
    line = re.sub(r"(\d+(?:\.\d+)?%)\s+\1", r"\1", line)

    if language == "vi":
        replacements = {
            "Dòng tiền rỗng": "Dòng tiền ròng",
            "dòng tiền rỗng": "dòng tiền ròng",
            "Dòng tiền rộng": "Dòng tiền ròng",
            "dòng tiền rộng": "dòng tiền ròng",
            "Ngay bat thuong gan nhat la": "Ngày bất thường gần nhất là",
            "Ban uu tien khau vi rui ro nao: thap, vua hay cao? Toi se tinh chinh ke hoach sau khi ban chon.": (
                "Bạn ưu tiên khẩu vị rủi ro nào: thấp, vừa hay cao? Tôi sẽ tinh chỉnh kế hoạch sau khi bạn chọn."
            ),
            "Cần thiềt tân đánh chi tiêu để đầt mục tiêu.": "Cần thắt chặt chi tiêu để đạt mục tiêu.",
            "Hãy xác đọnh mục rui ro để cá nhan hơ khuyen nghi.": (
                "Hãy xác định mức rủi ro để cá nhân hóa khuyến nghị."
            ),
            "Tối đáo thiết lệp kặ hoạch chi tiêu và tân đánh chi tiêu thợ vàn.": (
                "Thiết lập kế hoạch chi tiêu và theo dõi chi tiêu hằng tuần."
            ),
            "Sử dụng dềch vụ tiết kiệm để têng tốc đó tiền.": "Sử dụng dịch vụ tiết kiệm để tăng tốc tích lũy.",
            "Giới hạn: Không có thông tin về sử thàch của ngươi dùng.": (
                "Giới hạn: Không có thông tin về sở thích của người dùng."
            ),
            "Co the can nhac goi tiet kiem dinh ky hoac tiet kiem ky han de tang ky luat tich luy.": (
                "Có thể cân nhắc gói tiết kiệm định kỳ hoặc tiết kiệm kỳ hạn để tăng kỷ luật tích lũy."
            ),
            "Có thể cần nhắc gọi tiết kiệm định kỳ hoặc tiết kiệm kỳ hạn để tăng ký lưu tích lũy.": (
                "Có thể cân nhắc gói tiết kiệm định kỳ hoặc tiết kiệm kỳ hạn để tăng kỷ luật tích lũy."
            ),
        }
        for src, dst in replacements.items():
            line = line.replace(src, dst)

        # Fix common unaccented Vietnamese phrases (light cleanup only, no numeric/fact changes).
        vi_phrase_replacements = [
            (r"\bngay qua\b", "ngày qua"),
            (r"\b6 thang\b", "6 tháng"),
            (r"\b90 ngay\b", "90 ngày"),
            (r"\bchua kha thi\b", "chưa khả thi"),
            (r"\bkhau vi rui ro\b", "khẩu vị rủi ro"),
            (r"\bmuc rui ro\b", "mức rủi ro"),
            (r"\bkhuyen nghi\b", "khuyến nghị"),
            (r"\bca nhan hoa\b", "cá nhân hóa"),
            (r"\bthiet lap\b", "thiết lập"),
            (r"\bke hoach\b", "kế hoạch"),
            (r"\btheo doi\b", "theo dõi"),
            (r"\bhang tuan\b", "hằng tuần"),
            (r"\bnguoi dung\b", "người dùng"),
            (r"\bso thich\b", "sở thích"),
            (r"\bdich vu tiet kiem\b", "dịch vụ tiết kiệm"),
            (r"\btang toc tich luy\b", "tăng tốc tích lũy"),
            (r"\bgoi tiet kiem\b", "gói tiết kiệm"),
            (r"\bgoi vay\b", "gói vay"),
            (r"\bgui tiet kiem\b", "gửi tiết kiệm"),
            (r"\bky luu tich luy\b", "kỷ luật tích lũy"),
        ]
        for pattern, replacement in vi_phrase_replacements:
            line = re.sub(pattern, replacement, line, flags=re.IGNORECASE)

        # Normalize mixed bilingual risk labels.
        line = re.sub(r"\bthấp\s+low\b", "thấp", line, flags=re.IGNORECASE)
        line = re.sub(r"\btrung bình\s+medium\b", "trung bình", line, flags=re.IGNORECASE)
        line = re.sub(r"\bcao\s+high\b", "cao", line, flags=re.IGNORECASE)

        # Remove orphan number tails like "... 90 ngày qua 1."
        line = re.sub(r"(\b\d+\s+ngày qua)\s+\d+\.$", r"\1.", line, flags=re.IGNORECASE)

    line = re.sub(r"\s{2,}", " ", line).strip()
    return line


def _sanitize_prose_lines(lines: Iterable[str], *, language: str) -> list[str]:
    sanitized: list[str] = []
    for item in lines:
        cleaned = _sanitize_prose_line(str(item or ""), language=language)
        if cleaned:
            sanitized.append(cleaned)
    return sanitized


def _dedupe_actions(actions: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for action in actions:
        text = str(action or "").strip()
        if not text:
            continue
        key = _normalize_prompt_for_match(text)
        if not key:
            continue
        if any(marker in key for marker in ["khau vi rui ro", "muc rui ro", "risk appetite"]):
            key = "risk_appetite_follow_up"
        key = re.sub(r"\s+", " ", key).strip()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def _normalize_prompt_for_match(text: str) -> str:
    lowered = str(text or "").lower()
    replacements = str.maketrans(
        {
            "á": "a",
            "à": "a",
            "ả": "a",
            "ã": "a",
            "ạ": "a",
            "ă": "a",
            "ắ": "a",
            "ằ": "a",
            "ẳ": "a",
            "ẵ": "a",
            "ặ": "a",
            "â": "a",
            "ấ": "a",
            "ầ": "a",
            "ẩ": "a",
            "ẫ": "a",
            "ậ": "a",
            "é": "e",
            "è": "e",
            "ẻ": "e",
            "ẽ": "e",
            "ẹ": "e",
            "ê": "e",
            "ế": "e",
            "ề": "e",
            "ể": "e",
            "ễ": "e",
            "ệ": "e",
            "í": "i",
            "ì": "i",
            "ỉ": "i",
            "ĩ": "i",
            "ị": "i",
            "ó": "o",
            "ò": "o",
            "ỏ": "o",
            "õ": "o",
            "ọ": "o",
            "ô": "o",
            "ố": "o",
            "ồ": "o",
            "ổ": "o",
            "ỗ": "o",
            "ộ": "o",
            "ơ": "o",
            "ớ": "o",
            "ờ": "o",
            "ở": "o",
            "ỡ": "o",
            "ợ": "o",
            "ú": "u",
            "ù": "u",
            "ủ": "u",
            "ũ": "u",
            "ụ": "u",
            "ư": "u",
            "ứ": "u",
            "ừ": "u",
            "ử": "u",
            "ữ": "u",
            "ự": "u",
            "ý": "y",
            "ỳ": "y",
            "ỷ": "y",
            "ỹ": "y",
            "ỵ": "y",
            "đ": "d",
        }
    )
    return lowered.translate(replacements)


def _asks_anomaly_date(user_prompt: str) -> bool:
    normalized = _normalize_prompt_for_match(user_prompt)
    asks_date = any(term in normalized for term in ["ngay", "date", "when", "luc nao", "bao gio"])
    anomaly_hint = any(
        term in normalized
        for term in [
            "bat thuong",
            "giao dich la",
            "anomaly",
            "change point",
            "change_point",
        ]
    )
    return asks_date and anomaly_hint


def _has_anomaly_context(user_prompt: str, intent: str) -> bool:
    normalized = _normalize_prompt_for_match(user_prompt)
    anomaly_terms = [
        "bat thuong",
        "giao dich la",
        "anomaly",
        "change point",
        "change_point",
        "suspicious transaction",
    ]
    if any(term in normalized for term in anomaly_terms):
        return True
    return str(intent or "").strip().lower() == "risk"


def _asks_anomaly_reason(user_prompt: str) -> bool:
    normalized = _normalize_prompt_for_match(user_prompt)
    asks_reason = any(
        term in normalized
        for term in [
            "la gi",
            "gi vay",
            "vi sao",
            "tai sao",
            "what is",
            "what are",
            "why",
        ]
    )
    anomaly_hint = any(
        term in normalized
        for term in [
            "canh bao",
            "bat thuong",
            "giao dich la",
            "anomaly",
            "flag",
        ]
    )
    return asks_reason and anomaly_hint


def _requested_anomaly_reason_limit(user_prompt: str, *, default: int = 2, max_limit: int = 5) -> int:
    normalized = _normalize_prompt_for_match(user_prompt)
    if not normalized:
        return default
    if "tat ca canh bao" in normalized or "all anomaly" in normalized:
        return max_limit

    match = re.search(r"(\d+)\s*(canh bao|ly do|reasons?|alerts?)", normalized)
    if match:
        try:
            return max(1, min(max_limit, int(match.group(1))))
        except ValueError:
            return default

    word_to_num = {
        "mot": 1,
        "một": 1,
        "hai": 2,
        "ba": 3,
        "bon": 4,
        "bốn": 4,
        "nam": 5,
        "năm": 5,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
    }
    for word, value in word_to_num.items():
        if re.search(rf"\b{re.escape(word)}\b\s*(canh bao|ly do|reasons?|alerts?)", normalized):
            return max(1, min(max_limit, value))
    return default


def _resolve_anomaly_latest_fact_id(valid_fact_ids: set[str]) -> str:
    candidates = [item for item in valid_fact_ids if item.startswith("anomaly.latest_change_point.")]
    if not candidates:
        return ""

    def _sort_key(fact_id: str) -> int:
        match = re.search(r"(\d+)d$", fact_id)
        if not match:
            return -1
        return int(match.group(1))

    candidates.sort(key=_sort_key, reverse=True)
    return candidates[0]


def _resolve_anomaly_count_fact_id(valid_fact_ids: set[str]) -> str:
    candidates = [item for item in valid_fact_ids if item.startswith("anomaly.flags_count.")]
    if not candidates:
        return ""

    def _sort_key(fact_id: str) -> int:
        match = re.search(r"(\d+)d$", fact_id)
        if not match:
            return -1
        return int(match.group(1))

    candidates.sort(key=_sort_key, reverse=True)
    return candidates[0]


def _resolve_anomaly_reason_fact_ids(valid_fact_ids: set[str], *, limit: int = 2) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    pattern = re.compile(r"^anomaly\.flag_reason\.(\d+)\.(\d+)d$")
    for fact_id in valid_fact_ids:
        match = pattern.match(fact_id)
        if not match:
            continue
        rank = int(match.group(1))
        window_days = int(match.group(2))
        ranked.append((rank, window_days, fact_id))
    if not ranked:
        return []
    max_window = max(item[1] for item in ranked)
    selected = [item for item in ranked if item[1] == max_window]
    selected.sort(key=lambda item: (item[0], item[2]))
    return [item[2] for item in selected[: max(1, limit)]]


def _should_force_anomaly_date(user_prompt: str, intent: str, anomaly_latest_fact_id: str) -> bool:
    if not anomaly_latest_fact_id:
        return False
    return _asks_anomaly_date(user_prompt) or _has_anomaly_context(user_prompt, intent)


def _should_force_anomaly_reasons(user_prompt: str, intent: str, anomaly_reason_fact_ids: list[str]) -> bool:
    if not anomaly_reason_fact_ids:
        return False
    return _has_anomaly_context(user_prompt, intent) or _asks_anomaly_reason(user_prompt)


def _has_existing_anomaly_reason_summary(summary_lines: list[str]) -> bool:
    for line in summary_lines:
        normalized = _normalize_prompt_for_match(line)
        if _is_anomaly_reason_line(normalized):
            return True
    return False


def _is_anomaly_reason_line(normalized_line: str) -> bool:
    has_reason_word = any(term in normalized_line for term in ["ly do", "reason", "vi sao"])
    has_anomaly_word = any(
        term in normalized_line
        for term in ["canh bao", "bat thuong", "anomaly", "giao dich la", "runway", "category", "danh muc", "grocery"]
    )
    return has_reason_word and has_anomaly_word


def _normalize_anomaly_semantics_line(line: str, *, language: str) -> str:
    text = str(line or "")
    if language == "vi":
        text = re.sub(r"(?i)\bgiao dịch bất thường\b", "cảnh báo bất thường", text)
        text = re.sub(r"(?i)\bgiao dich bat thuong\b", "cảnh báo bất thường", text)
    else:
        text = re.sub(r"(?i)\babnormal transaction(s)?\b", "anomaly signal\\1", text)
    return text


def _normalize_vi_risk_wording_line(line: str, *, language: str) -> str:
    text = str(line or "")
    if language != "vi":
        return text

    normalized = _normalize_prompt_for_match(text)
    is_risk_line = any(marker in normalized for marker in ["muc rui ro", "mức rủi ro", "risk band", "khau vi rui ro"])
    if not is_risk_line:
        return text

    replacements = {
        r"(?i)\bmoderate\b": "trung bình",
        r"(?i)\bmedium\b": "trung bình",
        r"(?i)\blow\b": "thấp",
        r"(?i)\bhigh\b": "cao",
        r"(?i)\bunknown\b": "chưa xác định",
    }
    for pattern, replacement in replacements.items():
        text = re.sub(pattern, replacement, text)
    return text


def _ensure_anomaly_count_summary_line(
    summary_lines: list[str],
    *,
    user_prompt: str,
    intent: str,
    anomaly_count_fact_id: str,
    language: str,
) -> list[str]:
    if not anomaly_count_fact_id:
        return summary_lines
    if not _has_anomaly_context(user_prompt, intent):
        return summary_lines

    has_count_line = any(
        anomaly_count_fact_id in line
        or (
            "canh bao bat thuong" in _normalize_prompt_for_match(line)
            and "giao dich bat thuong" not in _normalize_prompt_for_match(line)
        )
        for line in summary_lines
    )
    if has_count_line:
        return summary_lines

    canonical_line = (
        f"Có [F:{anomaly_count_fact_id}] cảnh báo bất thường (dấu hiệu giao dịch lạ) trong cửa sổ hiện tại."
        if language == "vi"
        else f"There are [F:{anomaly_count_fact_id}] anomaly alerts in the current window."
    )
    if len(summary_lines) < 5:
        return [canonical_line, *summary_lines]

    reason_lines: list[str] = []
    date_lines: list[str] = []
    other_lines: list[str] = []
    for line in summary_lines:
        normalized = _normalize_prompt_for_match(line)
        if _is_anomaly_reason_line(normalized):
            reason_lines.append(line)
            continue
        if _is_anomaly_date_line(normalized):
            date_lines.append(line)
            continue
        other_lines.append(line)

    selected: list[str] = [canonical_line]
    for line in reason_lines:
        if len(selected) >= 5:
            break
        selected.append(line)
    if len(selected) < 5 and date_lines:
        selected.append(date_lines[0])
    for line in other_lines:
        if len(selected) >= 5:
            break
        selected.append(line)
    return selected[:5]


def _canonical_anomaly_reason_line(fact_id: str, *, index: int, language: str) -> str:
    if language == "vi":
        return f"Lý do cảnh báo nổi bật {index}: [F:{fact_id}]"
    return f"Top anomaly reason {index}: [F:{fact_id}]"


def _is_anomaly_date_line(normalized_line: str) -> bool:
    return ("ngay" in normalized_line and "bat thuong" in normalized_line) or (
        "date" in normalized_line and "anomaly" in normalized_line
    )


def _enforce_anomaly_reason_summary_lines(
    summary_lines: list[str],
    *,
    user_prompt: str,
    intent: str,
    language: str,
    anomaly_reason_fact_ids: list[str],
) -> list[str]:
    if not _has_anomaly_context(user_prompt, intent):
        return summary_lines
    if not anomaly_reason_fact_ids:
        return summary_lines

    canonical_reason_lines = [
        _canonical_anomaly_reason_line(fact_id, index=index, language=language)
        for index, fact_id in enumerate(anomaly_reason_fact_ids, start=1)
    ]
    non_reason_lines: list[str] = []
    for line in summary_lines:
        normalized = _normalize_prompt_for_match(line)
        if _is_anomaly_reason_line(normalized):
            continue
        non_reason_lines.append(line)

    max_non_reason = max(1, 5 - len(canonical_reason_lines))
    selected_non_reason = non_reason_lines[:max_non_reason]

    if non_reason_lines:
        has_date_line_in_selected = any(_is_anomaly_date_line(_normalize_prompt_for_match(line)) for line in selected_non_reason)
        if not has_date_line_in_selected:
            first_date_line = next(
                (line for line in non_reason_lines if _is_anomaly_date_line(_normalize_prompt_for_match(line))),
                "",
            )
            if first_date_line:
                if len(selected_non_reason) >= max_non_reason:
                    selected_non_reason = [*selected_non_reason[: max_non_reason - 1], first_date_line]
                else:
                    selected_non_reason.append(first_date_line)

    return [*selected_non_reason, *canonical_reason_lines]


def _fallback_summary_lines(language: str) -> list[str]:
    if language == "vi":
        return [
            "Đã tổng hợp thông tin từ các fact đã xác thực.",
            "Nội dung đang giới hạn trong phạm vi dữ liệu từ tool.",
            "Bạn có thể bổ sung mục tiêu cụ thể để nhận khuyến nghị sắc nét hơn.",
        ]
    return [
        "The response is synthesized from verified facts only.",
        "Guidance is constrained to tool-grounded evidence.",
        "You can provide a more specific goal for a sharper recommendation.",
    ]


def _fallback_actions(language: str) -> list[str]:
    if language == "vi":
        return [
            "Xác nhận ưu tiên tài chính ngắn hạn (an toàn dòng tiền, trả nợ, hay tích lũy).",
            "Cập nhật dữ liệu mới và đánh giá lại sau hai tuần.",
        ]
    return [
        "Confirm your top short-term financial priority.",
        "Refresh your data and re-evaluate in two weeks.",
    ]


def _sanitize_answer_payload(
    payload: Dict[str, Any],
    *,
    user_prompt: str,
    intent: str,
    risk_appetite: str,
    default_language: str,
    default_disclaimer: str,
    valid_fact_ids: set[str],
    valid_insight_ids: set[str],
    valid_action_ids: set[str],
) -> Dict[str, Any]:
    allowed_keys = {
        "schema_version",
        "language",
        "summary_lines",
        "key_metrics",
        "actions",
        "assumptions",
        "limitations",
        "disclaimer",
        "used_fact_ids",
        "used_insight_ids",
        "used_action_ids",
    }
    normalized = {key: value for key, value in dict(payload).items() if key in allowed_keys}
    language = str(normalized.get("language") or default_language or "en").strip().lower()
    if language not in {"vi", "en"}:
        language = default_language if default_language in {"vi", "en"} else "en"
    normalized["language"] = language
    normalized["schema_version"] = "answer_plan_v2"

    summary_lines = _coerce_str_list(normalized.get("summary_lines"))
    anomaly_latest_fact_id = _resolve_anomaly_latest_fact_id(valid_fact_ids)
    anomaly_count_fact_id = _resolve_anomaly_count_fact_id(valid_fact_ids)
    reason_limit = _requested_anomaly_reason_limit(user_prompt, default=2, max_limit=5)
    anomaly_reason_fact_ids = _resolve_anomaly_reason_fact_ids(valid_fact_ids, limit=reason_limit)
    force_anomaly_reasons = _should_force_anomaly_reasons(user_prompt, intent, anomaly_reason_fact_ids)
    has_existing_reason_summary = _has_existing_anomaly_reason_summary(summary_lines)
    if force_anomaly_reasons and not has_existing_reason_summary:
        for index, fact_id in enumerate(anomaly_reason_fact_ids, start=1):
            forced_line = _canonical_anomaly_reason_line(fact_id, index=index, language=language)
            has_reason_line = any(fact_id in line for line in summary_lines)
            if not has_reason_line:
                if len(summary_lines) < 5:
                    summary_lines.append(forced_line)
                else:
                    summary_lines[-1] = forced_line

    force_anomaly_date = _should_force_anomaly_date(user_prompt, intent, anomaly_latest_fact_id)
    if force_anomaly_date and anomaly_latest_fact_id:
        forced_line = (
            f"Ngày bất thường gần nhất là [F:{anomaly_latest_fact_id}]."
            if language == "vi"
            else f"The latest anomaly date is [F:{anomaly_latest_fact_id}]."
        )
        has_anomaly_date_line = any(
            anomaly_latest_fact_id in line
            or (
                "ngay" in _normalize_prompt_for_match(line)
                and "bat thuong" in _normalize_prompt_for_match(line)
            )
            or (
                "date" in _normalize_prompt_for_match(line)
                and "anomaly" in _normalize_prompt_for_match(line)
            )
            for line in summary_lines
        )
        if not has_anomaly_date_line:
            if len(summary_lines) < 5:
                summary_lines.append(forced_line)
            else:
                summary_lines[-1] = forced_line
    if _asks_anomaly_date(user_prompt) and _has_anomaly_context(user_prompt, intent) and not anomaly_latest_fact_id:
        missing_line = (
            (
                f"Chưa đủ dữ liệu để xác định ngày bất thường cụ thể trong cửa sổ [F:{anomaly_count_fact_id}]."
                if anomaly_count_fact_id
                else "Chưa đủ dữ liệu để xác định ngày bất thường cụ thể trong cửa sổ hiện tại."
            )
            if language == "vi"
            else (
                f"There is not enough data to determine a specific anomaly date in the current window [F:{anomaly_count_fact_id}]."
                if anomaly_count_fact_id
                else "There is not enough data to determine a specific anomaly date in the current window."
            )
        )
        has_missing_date_line = any(
            "xac dinh ngay bat thuong" in _normalize_prompt_for_match(line)
            or "specific anomaly date" in _normalize_prompt_for_match(line)
            for line in summary_lines
        )
        if not has_missing_date_line:
            if len(summary_lines) < 5:
                summary_lines.append(missing_line)
            else:
                summary_lines[-1] = missing_line
    if force_anomaly_reasons:
        summary_lines = _enforce_anomaly_reason_summary_lines(
            summary_lines,
            user_prompt=user_prompt,
            intent=intent,
            language=language,
            anomaly_reason_fact_ids=anomaly_reason_fact_ids,
        )
    summary_lines = [
        _normalize_vi_risk_wording_line(_normalize_anomaly_semantics_line(line, language=language), language=language)
        for line in summary_lines
    ]
    summary_lines = _ensure_anomaly_count_summary_line(
        summary_lines,
        user_prompt=user_prompt,
        intent=intent,
        anomaly_count_fact_id=anomaly_count_fact_id,
        language=language,
    )
    summary_lines = _sanitize_prose_lines(summary_lines, language=language)
    if len(summary_lines) < 3:
        summary_lines = [*summary_lines, *_fallback_summary_lines(language)]
    normalized["summary_lines"] = summary_lines[:5]

    key_metrics = _coerce_key_metrics(normalized.get("key_metrics"))
    key_metrics = [item for item in key_metrics if str(item.get("fact_id") or "").strip() in valid_fact_ids]
    if not key_metrics and valid_fact_ids:
        key_metrics = [{"fact_id": fact_id, "label": ""} for fact_id in sorted(valid_fact_ids)[:3]]
    if force_anomaly_date and anomaly_latest_fact_id:
        has_change_point_metric = any(
            str(item.get("fact_id") or "").strip() == anomaly_latest_fact_id
            for item in key_metrics
        )
        if not has_change_point_metric:
            key_metrics = [
                {"fact_id": anomaly_latest_fact_id, "label": "Ngày bất thường gần nhất"},
                *key_metrics,
            ]
    if force_anomaly_reasons:
        for index, fact_id in enumerate(anomaly_reason_fact_ids, start=1):
            has_reason_metric = any(
                str(item.get("fact_id") or "").strip() == fact_id
                for item in key_metrics
            )
            if has_reason_metric:
                continue
            metric_label = f"Lý do cảnh báo {index}" if language == "vi" else f"Anomaly reason {index}"
            key_metrics = [{"fact_id": fact_id, "label": metric_label}, *key_metrics]
    normalized["key_metrics"] = key_metrics

    actions = _coerce_str_list(normalized.get("actions"))
    normalized_intent = str(intent or "").strip().lower()
    normalized_risk = str(risk_appetite or "").strip().lower()
    if normalized_risk not in {"conservative", "moderate", "aggressive"}:
        normalized_risk = "unknown"
    if normalized_risk == "unknown" and normalized_intent in {"planning", "scenario", "invest"}:
        follow_up_line = (
            "Bạn ưu tiên khẩu vị rủi ro nào: thấp, vừa hay cao? Tôi sẽ tinh chỉnh kế hoạch sau khi bạn chọn."
            if language == "vi"
            else "Which risk appetite fits you best: low, medium, or high? I will refine the plan after your choice."
        )
        follow_up_markers = [
            "khau vi rui ro",
            "khẩu vị rủi ro",
            "risk appetite",
            "low, medium, or high",
            "thap, vua hay cao",
            "thấp, vừa hay cao",
        ]
        if not any(any(marker in item.lower() for marker in follow_up_markers) for item in actions):
            actions = [follow_up_line, *actions]
    actions = _sanitize_prose_lines(actions, language=language)
    actions = _dedupe_actions(actions)
    if len(actions) < 2:
        actions = [*actions, *_fallback_actions(language)]
    normalized["actions"] = actions[:4]
    normalized["assumptions"] = _sanitize_prose_lines(_coerce_str_list(normalized.get("assumptions")), language=language)
    normalized["limitations"] = _sanitize_prose_lines(_coerce_str_list(normalized.get("limitations")), language=language)

    text_sections = [
        *normalized["summary_lines"],
        *normalized["actions"],
        *normalized["assumptions"],
        *normalized["limitations"],
    ]
    placeholder_fact_ids = [
        fact_id
        for fact_id in _extract_placeholder_fact_ids(text_sections)
        if fact_id in valid_fact_ids
    ]
    metric_fact_ids = [
        str(item.get("fact_id") or "").strip()
        for item in key_metrics
        if str(item.get("fact_id") or "").strip() in valid_fact_ids
    ]
    used_fact_ids = _coerce_str_list(normalized.get("used_fact_ids"))
    used_fact_ids = _dedupe_keep_order([*used_fact_ids, *metric_fact_ids, *placeholder_fact_ids])
    used_fact_ids = _dedupe_keep_order(item for item in used_fact_ids if item in valid_fact_ids)
    if not used_fact_ids and key_metrics:
        used_fact_ids = _dedupe_keep_order(
            str(item.get("fact_id") or "").strip()
            for item in key_metrics
            if str(item.get("fact_id") or "").strip() in valid_fact_ids
        )
    normalized["used_fact_ids"] = used_fact_ids

    used_insight_ids = _dedupe_keep_order(
        item for item in _coerce_str_list(normalized.get("used_insight_ids")) if item in valid_insight_ids
    )
    if not used_insight_ids and valid_insight_ids:
        used_insight_ids = sorted(valid_insight_ids)[:2]
    normalized["used_insight_ids"] = used_insight_ids

    used_action_ids = _dedupe_keep_order(
        item for item in _coerce_str_list(normalized.get("used_action_ids")) if item in valid_action_ids
    )
    if not used_action_ids and valid_action_ids:
        used_action_ids = sorted(valid_action_ids)[: min(4, max(2, len(valid_action_ids)))]
    normalized["used_action_ids"] = used_action_ids

    disclaimer = str(normalized.get("disclaimer") or "").strip()
    normalized["disclaimer"] = disclaimer or default_disclaimer or DEFAULT_DISCLAIMER
    return normalized


def _extract_placeholder_fact_ids(sections: Iterable[str]) -> list[str]:
    found: list[str] = []
    for section in sections:
        text = str(section or "")
        for fact_id in _FACT_PLACEHOLDER_PATTERN.findall(text):
            value = str(fact_id).strip()
            if value:
                found.append(value)
    return _dedupe_keep_order(found)


def synthesize_answer_plan_with_bedrock(
    *,
    user_prompt: str,
    intent: str,
    route_decision: Dict[str, Any],
    advisory_context: AdvisoryContextV1,
    policy_flags: Dict[str, Any],
    allowed_numeric_tokens: set[str] | None = None,
    retry_attempts: int = 1,
    model_id: str | None = None,
    corrective_feedback: str = "",
) -> tuple[AnswerPlanV2 | None, list[str], Dict[str, Any]]:
    errors: list[str] = []
    runtime_meta: Dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "attempts": retry_attempts + 1,
        "raw_text": "",
    }
    _ = allowed_numeric_tokens
    resolved_model = (model_id or BEDROCK_MODEL_ID or "").strip()
    runtime_meta["model_id"] = resolved_model
    if not resolved_model:
        errors.append("model_not_configured")
        return None, errors, runtime_meta

    prompt_text = _build_prompt(
        user_prompt=user_prompt,
        intent=intent,
        route_decision=route_decision,
        advisory_context=advisory_context,
        policy_flags=policy_flags,
        corrective_feedback=corrective_feedback,
    )

    valid_fact_ids = {fact.fact_id for fact in advisory_context.facts}
    valid_insight_ids = {insight.insight_id for insight in advisory_context.insights}
    valid_action_ids = {action.action_id for action in advisory_context.actions}

    for attempt in range(retry_attempts + 1):
        runtime_meta["attempt"] = attempt + 1
        try:
            raw_text = _invoke_bedrock_converse(prompt_text, model_id=resolved_model)
            runtime_meta["raw_text"] = raw_text
        except Exception as exc:  # pragma: no cover - runtime/network path
            errors.append(f"bedrock_invoke_error:{type(exc).__name__}")
            logger.warning("Answer synthesis invoke failed on attempt %s: %s", attempt + 1, exc)
            continue

        payload = _try_parse_json(raw_text)
        if payload is None:
            errors.append("answer_invalid_json")
            continue

        payload = _sanitize_answer_payload(
            payload,
            user_prompt=user_prompt,
            intent=intent,
            risk_appetite=str(policy_flags.get("risk_appetite") or ""),
            default_language=advisory_context.language,
            default_disclaimer=str(policy_flags.get("required_disclaimer") or DEFAULT_DISCLAIMER),
            valid_fact_ids=valid_fact_ids,
            valid_insight_ids=valid_insight_ids,
            valid_action_ids=valid_action_ids,
        )
        schema_errors = validate_answer_plan_payload(payload)
        if schema_errors:
            errors.append("answer_invalid_schema")
            errors.extend([f"schema:{msg}" for msg in schema_errors[:3]])
            continue

        try:
            answer_plan = AnswerPlanV2.model_validate(payload)
            return answer_plan, errors, runtime_meta
        except ValidationError as exc:
            errors.append("answer_invalid_contract")
            errors.append(str(exc))
            continue

    return None, errors, runtime_meta
