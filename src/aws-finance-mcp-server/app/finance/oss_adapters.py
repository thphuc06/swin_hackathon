from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any, Dict, List


def river_adwin_drift(series: List[float], *, delta: float = 0.002) -> Dict[str, Any]:
    """River ADWIN drift detector.

    Source: https://riverml.xyz/
    """

    try:
        from river.drift import ADWIN
    except Exception as exc:  # pragma: no cover
        return {"available": False, "engine": "river_adwin", "error": str(exc)}

    detector = ADWIN(delta=delta)
    drift_points: List[int] = []
    means: List[float] = []

    for idx, value in enumerate(series):
        in_drift = bool(detector.update(float(value)))
        means.append(float(getattr(detector, "estimation", 0.0)))
        if in_drift:
            drift_points.append(idx)

    return {
        "available": True,
        "engine": "river_adwin",
        "drift_detected": bool(drift_points),
        "drift_points": drift_points[-5:],
        "mean_estimate": round(means[-1], 4) if means else 0.0,
        "window_width": int(getattr(detector, "width", 0) or 0),
        "delta": delta,
    }


def pyod_ecod_outlier(series: List[float]) -> Dict[str, Any]:
    """PyOD ECOD outlier baseline.

    Source: https://pyod.readthedocs.io/
    """

    try:
        import numpy as np
        from pyod.models.ecod import ECOD
    except Exception as exc:  # pragma: no cover
        return {"available": False, "engine": "pyod_ecod", "error": str(exc)}

    if len(series) < 10:
        return {
            "available": True,
            "engine": "pyod_ecod",
            "ready": False,
            "reason": "insufficient_samples",
            "outlier_flag": False,
            "outlier_probability": 0.0,
        }

    x = np.asarray(series, dtype=float).reshape(-1, 1)
    model = ECOD(contamination=0.1)
    model.fit(x)

    scores = model.decision_scores_.tolist()
    labels = model.labels_.tolist()
    latest_score = float(scores[-1])
    latest_label = int(labels[-1])

    sorted_scores = sorted(scores)
    rank = 0.0
    if sorted_scores:
        idx = 0
        for i, value in enumerate(sorted_scores):
            if latest_score >= value:
                idx = i
        rank = (idx + 1) / len(sorted_scores)

    return {
        "available": True,
        "engine": "pyod_ecod",
        "ready": True,
        "outlier_flag": bool(latest_label == 1 or rank >= 0.98),
        "latest_score": round(latest_score, 6),
        "score_rank_pct": round(rank, 6),
        "outlier_probability": round(rank, 6),
    }


def kats_cusum_change_points(day_keys: List[str], series: List[float]) -> Dict[str, Any]:
    """Optional Kats CUSUM change point adapter.

    Source: https://facebookresearch.github.io/Kats/
    """

    try:
        import pandas as pd
        from kats.consts import TimeSeriesData
        from kats.detectors.cusum_detection import CUSUMDetector
    except Exception as exc:  # pragma: no cover
        return {"available": False, "engine": "kats_cusum", "error": str(exc)}

    if len(series) < 20:
        return {
            "available": True,
            "engine": "kats_cusum",
            "ready": False,
            "reason": "insufficient_samples",
            "change_points": [],
        }

    timestamps = [datetime.fromisoformat(f"{d}T00:00:00") for d in day_keys]
    df = pd.DataFrame({"time": timestamps, "value": series})
    ts_data = TimeSeriesData(df=df)
    detector = CUSUMDetector(ts_data)
    cps = detector.detector()

    points: List[str] = []
    for cp in cps:
        time_value = cp.cp_index if hasattr(cp, "cp_index") else None
        if time_value is None:
            continue
        try:
            points.append(str(time_value))
        except Exception:
            continue

    return {
        "available": True,
        "engine": "kats_cusum",
        "ready": True,
        "change_points": points[:10],
        "change_detected": bool(points),
    }


def darts_forecast_points(
    day_keys: List[str],
    net_series: List[float],
    *,
    horizon: str,
) -> Dict[str, Any]:
    """Optional Darts forecaster adapter (deterministic ExponentialSmoothing).

    Source: https://unit8co.github.io/darts/
    """

    try:
        import pandas as pd
        from darts import TimeSeries
        from darts.models import ExponentialSmoothing
    except Exception as exc:  # pragma: no cover
        return {"available": False, "engine": "darts_exponential_smoothing", "error": str(exc)}

    if len(net_series) < 30:
        return {
            "available": True,
            "engine": "darts_exponential_smoothing",
            "ready": False,
            "reason": "insufficient_samples",
            "points": [],
        }

    dates = pd.to_datetime(day_keys)
    series = TimeSeries.from_times_and_values(times=dates, values=net_series)
    model = ExponentialSmoothing()
    model.fit(series)

    n_pred = 30 if horizon == "daily_30" else 84
    prediction = model.predict(n=n_pred)
    pred_values = prediction.values().flatten().tolist()
    pred_times = [str(ts)[:10] for ts in prediction.time_index]

    hist_std = statistics.pstdev(net_series) if len(net_series) > 1 else max(500_000.0, abs(net_series[-1]) * 0.2)

    points: List[Dict[str, Any]] = []
    if horizon == "daily_30":
        for day, p50 in zip(pred_times[:30], pred_values[:30]):
            width = max(300_000.0, hist_std * 1.28)
            points.append(
                {
                    "period": day,
                    "p10": round(p50 - width, 2),
                    "p50": round(p50, 2),
                    "p90": round(p50 + width, 2),
                }
            )
    else:
        for idx in range(12):
            chunk = pred_values[idx * 7:(idx + 1) * 7]
            if not chunk:
                break
            p50 = sum(chunk)
            width = max(800_000.0, hist_std * 2.56)
            points.append(
                {
                    "period": f"week_{idx + 1}",
                    "p10": round(p50 - width, 2),
                    "p50": round(p50, 2),
                    "p90": round(p50 + width, 2),
                }
            )

    return {
        "available": True,
        "engine": "darts_exponential_smoothing",
        "ready": True,
        "points": points,
    }
