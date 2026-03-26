from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from .common import clamp, parse_datetime, safe_div, safe_float


def _brier_score(labels: List[int], probs: List[float]) -> float | None:
    if not labels or len(labels) != len(probs):
        return None
    total = 0.0
    for label, prob in zip(labels, probs):
        p = clamp(safe_float(prob))
        y = 1.0 if int(label) == 1 else 0.0
        total += (p - y) ** 2
    return total / len(labels)


def extract_forecast_recalibration_samples(rows: Iterable[Dict[str, Any]]) -> List[Tuple[float, int]]:
    samples: List[Tuple[float, int]] = []
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        score = safe_float(payload.get("confidence_score"), None)
        if score is None:
            continue
        if row.get("within_p90") is None:
            continue
        label = 1 if bool(row.get("within_p90")) else 0
        samples.append((clamp(score), label))
    return samples


def extract_anomaly_recalibration_samples(
    *,
    audit_rows: Iterable[Dict[str, Any]],
    feedback_rows: Iterable[Dict[str, Any]],
) -> List[Tuple[float, int]]:
    dataset = build_anomaly_recalibration_dataset(audit_rows=audit_rows, feedback_rows=feedback_rows)
    return list(dataset.get("samples") or [])


def build_anomaly_recalibration_dataset(
    *,
    audit_rows: Iterable[Dict[str, Any]],
    feedback_rows: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    feedback_by_trace: Dict[str, Dict[str, Any]] = {}
    fallback_score_by_trace: Dict[str, Dict[str, Any]] = {}
    for row in feedback_rows:
        trace_id = str(row.get("trace_id") or "").strip()
        if not trace_id:
            continue
        label_text = str(row.get("feedback_label") or "").strip().lower()
        if label_text == "confirmed":
            label = 1
        elif label_text in {"false_positive", "expected"}:
            label = 0
        else:
            continue
        created_at = parse_datetime(row.get("created_at"))
        current = feedback_by_trace.get(trace_id)
        current_created = parse_datetime(current.get("created_at")) if current else None
        if current is None or (created_at and current_created and created_at > current_created):
            feedback_by_trace[trace_id] = {
                "label": label,
                "feedback_label": label_text,
                "created_at": row.get("created_at"),
            }
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        fallback_score = safe_float(payload.get("source_confidence_score"), None)
        if fallback_score is not None:
            current_fallback = fallback_score_by_trace.get(trace_id)
            current_fallback_created = parse_datetime(current_fallback.get("created_at")) if current_fallback else None
            if current_fallback is None or (created_at and current_fallback_created and created_at > current_fallback_created):
                fallback_score_by_trace[trace_id] = {
                    "score": clamp(fallback_score),
                    "created_at": row.get("created_at"),
                }

    audit_score_by_trace: Dict[str, float] = {}
    for row in audit_rows:
        trace_id = str(row.get("trace_id") or "").strip()
        if not trace_id:
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        score = safe_float(result.get("confidence_score"), None)
        if score is None:
            continue
        if trace_id not in audit_score_by_trace:
            audit_score_by_trace[trace_id] = clamp(score)

    score_by_trace: Dict[str, float] = dict(audit_score_by_trace)
    for trace_id, score_row in fallback_score_by_trace.items():
        if trace_id not in score_by_trace:
            score_by_trace[trace_id] = clamp(safe_float(score_row.get("score")))

    labeled_trace_ids = [trace_id for trace_id in feedback_by_trace if trace_id in score_by_trace]
    samples: List[Tuple[float, int]] = [
        (score_by_trace[trace_id], int(feedback_by_trace[trace_id]["label"]))
        for trace_id in labeled_trace_ids
    ]
    labels = [label for _, label in samples]
    total_trace_count = len(score_by_trace)
    labeled_trace_count = len(samples)
    feedback_trace_count = len(feedback_by_trace)
    return {
        "samples": samples,
        "total_trace_count": total_trace_count,
        "feedback_trace_count": feedback_trace_count,
        "labeled_trace_count": labeled_trace_count,
        "fallback_trace_count": len(fallback_score_by_trace),
        "trace_feedback_coverage": round(safe_div(labeled_trace_count, total_trace_count, 0.0), 4),
        "positive_rate_labeled": round(safe_div(sum(labels), len(labels), 0.0), 4) if labels else None,
    }


def fit_recalibrated_probability(
    *,
    raw_score: float,
    samples: Iterable[Tuple[float, int]],
    min_samples: int = 25,
    min_positive_rate: float | None = None,
    max_positive_rate: float | None = None,
) -> Dict[str, Any]:
    pairs = [(clamp(safe_float(score)), int(label)) for score, label in samples]
    if len(pairs) < min_samples:
        return {
            "available": False,
            "reason": "insufficient_samples",
            "sample_count": len(pairs),
            "raw_score": round(clamp(raw_score), 4),
        }

    labels = [label for _, label in pairs]
    if len(set(labels)) < 2:
        return {
            "available": False,
            "reason": "single_class_samples",
            "sample_count": len(pairs),
            "raw_score": round(clamp(raw_score), 4),
        }

    positive_rate = safe_div(sum(labels), len(labels), 0.0)
    if min_positive_rate is not None and positive_rate < float(min_positive_rate):
        return {
            "available": False,
            "reason": "class_imbalance_low_positive_rate",
            "sample_count": len(pairs),
            "positive_rate": round(positive_rate, 4),
            "raw_score": round(clamp(raw_score), 4),
        }
    if max_positive_rate is not None and positive_rate > float(max_positive_rate):
        return {
            "available": False,
            "reason": "class_imbalance_high_positive_rate",
            "sample_count": len(pairs),
            "positive_rate": round(positive_rate, 4),
            "raw_score": round(clamp(raw_score), 4),
        }

    scores = [score for score, _ in pairs]
    raw_probs = [clamp(score) for score in scores]
    raw_brier = _brier_score(labels, raw_probs)

    candidates: Dict[str, Dict[str, Any]] = {
        "identity": {
            "method": "identity",
            "score": clamp(raw_score),
            "brier": raw_brier,
        }
    }

    try:
        from sklearn.isotonic import IsotonicRegression

        isotonic = IsotonicRegression(out_of_bounds="clip")
        iso_train = [clamp(float(value)) for value in isotonic.fit_transform(scores, labels)]
        iso_brier = _brier_score(labels, iso_train)
        iso_score = clamp(float(isotonic.predict([clamp(raw_score)])[0]))
        candidates["isotonic"] = {
            "method": "isotonic",
            "score": iso_score,
            "brier": iso_brier,
        }
    except Exception:
        pass

    try:
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(max_iter=500)
        x = [[value] for value in scores]
        clf.fit(x, labels)
        platt_train = [clamp(float(value)) for value in clf.predict_proba(x)[:, 1]]
        platt_brier = _brier_score(labels, platt_train)
        platt_score = clamp(float(clf.predict_proba([[clamp(raw_score)]])[0][1]))
        candidates["platt"] = {
            "method": "platt",
            "score": platt_score,
            "brier": platt_brier,
        }
    except Exception:
        pass

    def _rank_key(item: Dict[str, Any]) -> float:
        value = item.get("brier")
        return float(value) if value is not None else 1e9

    chosen = min(candidates.values(), key=_rank_key)
    return {
        "available": True,
        "sample_count": len(pairs),
        "positive_rate": round(positive_rate, 4),
        "raw_score": round(clamp(raw_score), 4),
        "calibrated_score": round(clamp(chosen.get("score", raw_score)), 4),
        "method": str(chosen.get("method") or "identity"),
        "brier_raw": round(raw_brier, 6) if raw_brier is not None else None,
        "brier_isotonic": round(candidates["isotonic"]["brier"], 6) if "isotonic" in candidates and candidates["isotonic"].get("brier") is not None else None,
        "brier_platt": round(candidates["platt"]["brier"], 6) if "platt" in candidates and candidates["platt"].get("brier") is not None else None,
    }


