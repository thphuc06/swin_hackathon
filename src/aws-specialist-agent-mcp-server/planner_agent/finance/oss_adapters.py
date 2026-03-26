from __future__ import annotations

import statistics
import os
import warnings
from datetime import datetime
from typing import Any, Dict, List

import numpy as np


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
    latest_row = x[-1:].copy()

    latest_probability = 0.0
    latest_confidence = 0.0
    rejection_label = latest_label
    rejection_stats: Dict[str, Any] | None = None

    try:
        probability_rows = model.predict_proba(latest_row, method="linear")
        latest_probability = float(probability_rows[0][1])
    except Exception:
        latest_probability = 0.0

    try:
        latest_confidence = float(model.predict_confidence(latest_row)[0])
    except Exception:
        latest_confidence = 0.0

    try:
        rejection_pred, expected_rejection_rate, upperbound_rejection_rate, upperbound_cost = model.predict_with_rejection(
            latest_row,
            T=32,
            return_stats=True,
            c_r=0.1,
        )
        rejection_label = int(rejection_pred[0])
        rejection_stats = {
            "expected_rejection_rate": round(float(expected_rejection_rate), 6),
            "upperbound_rejection_rate": round(float(upperbound_rejection_rate), 6),
            "upperbound_cost": round(float(upperbound_cost), 6),
        }
    except Exception:
        rejection_label = latest_label

    sorted_scores = sorted(scores)
    rank = 0.0
    if sorted_scores:
        lower_count = sum(1 for value in sorted_scores if latest_score > value)
        equal_count = sum(1 for value in sorted_scores if latest_score == value)
        midpoint_rank = lower_count + (equal_count / 2.0)
        rank = midpoint_rank / len(sorted_scores)

    return {
        "available": True,
        "engine": "pyod_ecod",
        "ready": True,
        "outlier_flag": bool(latest_label == 1 or rank >= 0.98),
        "latest_score": round(latest_score, 6),
        "decision_score": round(latest_score, 6),
        "score_rank_pct": round(rank, 6),
        "outlier_probability": round(latest_probability, 6),
        "prediction_confidence": round(latest_confidence, 6),
        "predict_label": latest_label,
        "rejection_label": rejection_label,
        "rejected_low_confidence": rejection_label == -2,
        "rejection_stats": rejection_stats,
        "threshold": round(float(getattr(model, "threshold_", 0.0) or 0.0), 6),
    }


def ruptures_pelt_change_points(
    day_keys: List[str], series: List[float], *, penalty: float = 3.0
) -> Dict[str, Any]:
    """Ruptures Pelt change point detection adapter.

    Uses the Pelt algorithm (Pruned Exact Linear Time) for offline change point detection.
    Returns change points as date strings mapped from indices.

    Source: https://github.com/deepcharles/ruptures
    """

    try:
        import numpy as np
        import ruptures as rpt
    except Exception as exc:  # pragma: no cover
        return {"available": False, "engine": "ruptures_pelt", "error": str(exc)}

    if len(series) < 20:
        return {
            "available": True,
            "engine": "ruptures_pelt",
            "ready": False,
            "reason": "insufficient_samples",
            "change_points": [],
        }

    # Convert to numpy array and reshape for ruptures (requires 2D array)
    signal = np.asarray(series, dtype=float).reshape(-1, 1)

    # Use Pelt algorithm with rbf (radial basis function) kernel
    # Common models: "l1", "l2", "rbf", "linear", "normal", "ar"
    try:
        algo = rpt.Pelt(model="rbf", min_size=2, jump=1).fit(signal)
        # penalty controls sensitivity: higher = fewer change points
        change_point_indices = algo.predict(pen=penalty)
    except Exception as exc:  # pragma: no cover
        return {
            "available": True,
            "engine": "ruptures_pelt",
            "ready": False,
            "error": f"Detection failed: {str(exc)}",
            "change_points": [],
        }

    # ruptures returns indices including the end of the signal
    # Filter out the last index (signal length) and map to date strings
    points: List[str] = []
    for idx in change_point_indices:
        # ruptures uses 1-indexed, but returns the position after the change
        # We want the date where the change occurred
        if 0 < idx < len(day_keys):
            points.append(day_keys[idx])

    return {
        "available": True,
        "engine": "ruptures_pelt",
        "ready": True,
        "change_points": points[:10],
        "change_detected": bool(points),
        "penalty": penalty,
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

    def _env_int(name: str, default: int, *, lower: int, upper: int) -> int:
        raw = os.getenv(name, str(default)).strip()
        try:
            value = int(raw)
        except ValueError:
            value = default
        return max(lower, min(upper, value))

    min_samples = _env_int("DARTS_MIN_HISTORY", 30, lower=20, upper=365)
    if len(net_series) < min_samples:
        return {
            "available": True,
            "engine": "darts_exponential_smoothing",
            "ready": False,
            "reason": "insufficient_samples",
            "required_samples": min_samples,
            "points": [],
        }

    num_samples = _env_int("DARTS_NUM_SAMPLES", 200, lower=50, upper=1000)
    seasonal_periods = _env_int("DARTS_SEASONAL_PERIODS", 7, lower=2, upper=31)

    try:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(day_keys, errors="coerce").normalize(),
                "value": [float(value) for value in net_series],
            }
        )
        frame = frame.dropna(subset=["date"]).sort_values("date")
        if frame.empty:
            return {
                "available": True,
                "engine": "darts_exponential_smoothing",
                "ready": False,
                "reason": "invalid_day_keys",
                "points": [],
            }
        # Collapse duplicate dates to a single daily value before building dense index.
        collapsed = frame.groupby("date", as_index=False, sort=True)["value"].sum()
        dense_dates = pd.date_range(start=collapsed["date"].min(), end=collapsed["date"].max(), freq="D")
        dense_df = pd.DataFrame({"date": dense_dates}).merge(collapsed, on="date", how="left").fillna({"value": 0.0})
        dense_values = dense_df["value"].astype(float).tolist()
        series = TimeSeries.from_times_and_values(times=dense_dates, values=dense_values)
        model = ExponentialSmoothing(seasonal_periods=seasonal_periods, random_state=42)

        captured_warnings: List[str] = []
        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            model.fit(series)

        n_pred = 30 if horizon == "daily_30" else 84
        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            prediction = model.predict(n=n_pred, num_samples=num_samples)
            captured_warnings.extend(str(item.message) for item in records)
        pred_times = [str(ts)[:10] for ts in prediction.time_index]
        sample_values = prediction.all_values(copy=False)[:, 0, :]
    except Exception as exc:  # pragma: no cover
        return {
            "available": True,
            "engine": "darts_exponential_smoothing",
            "ready": False,
            "error": str(exc),
            "points": [],
        }

    points: List[Dict[str, Any]] = []
    if horizon == "daily_30":
        for index, day in enumerate(pred_times[:30]):
            distribution = sample_values[index]
            p10, p50, p90 = [float(value) for value in np.quantile(distribution, [0.1, 0.5, 0.9])]
            points.append(
                {
                    "period": day,
                    "p10": round(p10, 2),
                    "p50": round(p50, 2),
                    "p90": round(p90, 2),
                }
            )
    else:
        for idx in range(12):
            chunk = sample_values[idx * 7:(idx + 1) * 7]
            if not len(chunk):
                break
            aggregated_distribution = chunk.sum(axis=0)
            p10, p50, p90 = [float(value) for value in np.quantile(aggregated_distribution, [0.1, 0.5, 0.9])]
            points.append(
                {
                    "period": f"week_{idx + 1}",
                    "p10": round(p10, 2),
                    "p50": round(p50, 2),
                    "p90": round(p90, 2),
                }
            )

    interval_widths = [float(point["p90"] - point["p10"]) for point in points]

    return {
        "available": True,
        "engine": "darts_exponential_smoothing",
        "ready": True,
        "source": "darts_sampling_quantiles",
        "num_samples": num_samples,
        "seasonal_periods": seasonal_periods,
        "supports_probabilistic_prediction": True,
        "interval_width_avg": round(statistics.fmean(interval_widths), 2) if interval_widths else 0.0,
        "warning_count": len(captured_warnings),
        "points": points,
    }


