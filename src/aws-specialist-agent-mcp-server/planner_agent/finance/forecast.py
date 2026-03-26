from __future__ import annotations

import math
import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List

from .supabase_rest import SupabaseRestClient, get_supabase_client

from .common import (
    build_model_evidence,
    build_native_uncertainty,
    build_output,
    build_provenance,
    build_reliability,
    build_validation,
    build_window,
    clamp,
    daterange_start,
    ensure_user_scope,
    iso_utc,
    mean,
    new_trace_id,
    normalize_reason_codes,
    now_utc,
    parse_datetime,
    percentile,
    population_stddev,
    safe_div,
    safe_float,
    weighted_score,
)
from .data import fetch_forecast_actuals_history, fetch_transactions_in_window, write_audit_event, write_forecast_actuals_rows
from .oss_adapters import darts_forecast_points, river_adwin_drift
from .recalibration import extract_forecast_recalibration_samples, fit_recalibrated_probability
from .trust import build_trust, count_forecast_actuals

TOOL_NAME = "cashflow_forecast_v1"
MODEL_NAME = "deterministic_weekday_baseline_v2"
STATSMODELS_NAME = "statsmodels_ets_daily_v1"
SECONDS_DAY = 24 * 60 * 60
Z80 = 0.841621
Z90 = 1.281552


def _parse_overrides(payload: Dict[str, Any] | None) -> Dict[str, float]:
    raw = payload or {}
    return {
        "income_delta_pct": safe_float(raw.get("income_delta_pct")),
        "spend_delta_pct": safe_float(raw.get("spend_delta_pct")),
        "income_delta_abs": safe_float(raw.get("income_delta_abs")),
        "spend_delta_abs": safe_float(raw.get("spend_delta_abs")),
    }


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _build_dense_daily_series(
    rows: List[Dict[str, Any]],
    *,
    start_at: datetime,
    end_at: datetime,
) -> List[Dict[str, Any]]:
    daily_map: Dict[str, Dict[str, float]] = defaultdict(lambda: {"income": 0.0, "spend": 0.0})
    for row in rows:
        occurred = parse_datetime(row.get("occurred_at"))
        if not occurred:
            continue
        day_key = occurred.date().isoformat()
        amount = safe_float(row.get("amount"))
        direction = str(row.get("direction") or "debit").lower()
        if direction == "credit":
            daily_map[day_key]["income"] += amount
        else:
            daily_map[day_key]["spend"] += amount

    cursor = start_at
    dense_rows: List[Dict[str, Any]] = []
    while cursor.date() <= end_at.date():
        day_key = cursor.date().isoformat()
        income = daily_map.get(day_key, {}).get("income", 0.0)
        spend = daily_map.get(day_key, {}).get("spend", 0.0)
        dense_rows.append(
            {
                "day": day_key,
                "income": income,
                "spend": spend,
                "net": income - spend,
                "active": bool(income or spend),
            }
        )
        cursor += timedelta(days=1)
    return dense_rows


def _weekday_means(values: List[float], day_keys: List[str]) -> Dict[int, float]:
    grouped: Dict[int, List[float]] = defaultdict(list)
    for day_key, value in zip(day_keys, values):
        dt = parse_datetime(day_key)
        if not dt:
            continue
        grouped[dt.weekday()].append(float(value))
    overall = mean(values)
    return {weekday: mean(grouped.get(weekday, [overall])) for weekday in range(7)}


def _baseline_forecast(
    values: List[float],
    day_keys: List[str],
    *,
    horizon_days: int,
    as_of_dt: datetime,
) -> Dict[str, Any]:
    weekday_avg = _weekday_means(values, day_keys)
    forecast: List[float] = []
    for step in range(1, horizon_days + 1):
        point_dt = (as_of_dt + timedelta(days=step)).replace(hour=0, minute=0, second=0, microsecond=0)
        forecast.append(float(weekday_avg.get(point_dt.weekday(), mean(values))))
    residual_std = population_stddev(values, default=max(500_000.0, abs(mean(values)) * 0.2))
    return {
        "available": True,
        "ready": True,
        "engine": MODEL_NAME,
        "forecast": forecast,
        "residual_std": residual_std,
        "residuals": [],
    }


def _statsmodels_forecast(values: List[float], *, horizon_days: int) -> Dict[str, Any]:
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
    except Exception as exc:  # pragma: no cover
        return {"available": False, "ready": False, "engine": STATSMODELS_NAME, "error": str(exc)}

    if len(values) < 56:
        return {
            "available": True,
            "ready": False,
            "engine": STATSMODELS_NAME,
            "reason": "insufficient_history",
        }

    model_specs = [
        ("ets_additive_seasonal", {"trend": "add", "seasonal": "add", "seasonal_periods": 7}),
        ("ets_additive_trend", {"trend": "add"}),
        ("ets_simple", {}),
    ]
    last_error = ""
    for model_name, kwargs in model_specs:
        try:
            model = ExponentialSmoothing(values, initialization_method="estimated", **kwargs)
            fitted = model.fit(optimized=True)
            raw_forecast = fitted.forecast(horizon_days)
            fitted_values = [float(value) for value in list(getattr(fitted, "fittedvalues", []))]
            residuals = [actual - pred for actual, pred in zip(values[-len(fitted_values):], fitted_values)]
            residual_std = population_stddev(residuals, default=population_stddev(values, default=500_000.0))
            return {
                "available": True,
                "ready": True,
                "engine": STATSMODELS_NAME,
                "model_name": model_name,
                "forecast": [float(value) for value in raw_forecast],
                "residual_std": residual_std,
                "residuals": residuals,
            }
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)
    return {
        "available": True,
        "ready": False,
        "engine": STATSMODELS_NAME,
        "error": last_error or "statsmodels_fit_failed",
    }


def _statsmodels_ets_prediction_interval(
    day_keys: List[str],
    values: List[float],
    *,
    horizon_days: int,
    alpha: float = 0.2,
) -> Dict[str, Any]:
    try:
        import pandas as pd

        from statsmodels.tsa.exponential_smoothing.ets import ETSModel
    except Exception as exc:  # pragma: no cover
        return {
            "available": False,
            "ready": False,
            "engine": "statsmodels_ets_prediction_interval",
            "error": str(exc),
        }

    if len(values) < 56:
        return {
            "available": True,
            "ready": False,
            "engine": "statsmodels_ets_prediction_interval",
            "reason": "insufficient_history",
        }

    model_specs = [
        ("etsmodel_additive_seasonal", {"error": "add", "trend": "add", "seasonal": "add", "seasonal_periods": 7}),
        ("etsmodel_additive_trend", {"error": "add", "trend": "add"}),
        ("etsmodel_simple_additive", {"error": "add"}),
    ]
    base_day = parse_datetime(day_keys[-1]) if day_keys else None
    if not base_day:
        base_day = now_utc()
    start_day = (base_day - timedelta(days=len(values) - 1)).date().isoformat()
    indexed_values = pd.Series(
        [safe_float(value) for value in values],
        index=pd.date_range(start=start_day, periods=len(values), freq="D"),
        dtype="float64",
    )

    last_error = ""
    for model_name, kwargs in model_specs:
        try:
            model = ETSModel(indexed_values, initialization_method="estimated", **kwargs)
            fitted = model.fit(disp=False)
            prediction = fitted.get_prediction(start=len(indexed_values), end=len(indexed_values) + horizon_days - 1)
            frame = prediction.summary_frame(alpha=alpha)
            columns = [str(col) for col in frame.columns]
            lower_col = next((col for col in ("pi_lower", "obs_ci_lower", "mean_ci_lower") if col in columns), None)
            upper_col = next((col for col in ("pi_upper", "obs_ci_upper", "mean_ci_upper") if col in columns), None)
            if lower_col is None or upper_col is None:
                raise ValueError("prediction_interval_columns_missing")

            mean_col = "mean" if "mean" in columns else None
            if mean_col is not None:
                p50_values = [safe_float(value) for value in list(frame[mean_col])]
            else:
                p50_values = [safe_float(value) for value in list(prediction.predicted_mean)]
            p10_values = [safe_float(value) for value in list(frame[lower_col])]
            p90_values = [safe_float(value) for value in list(frame[upper_col])]

            if not p50_values or len(p50_values) != len(p10_values) or len(p10_values) != len(p90_values):
                raise ValueError("prediction_interval_shape_mismatch")
            points: List[Dict[str, Any]] = []
            prediction_index = list(getattr(prediction.predicted_mean, "index", []))
            for idx in range(min(horizon_days, len(p50_values))):
                if idx < len(prediction_index):
                    period = prediction_index[idx].date().isoformat()
                else:
                    period = (base_day + timedelta(days=idx + 1)).date().isoformat()
                points.append(
                    {
                        "period": period,
                        "p10": round(p10_values[idx], 2),
                        "p50": round(p50_values[idx], 2),
                        "p90": round(p90_values[idx], 2),
                    }
                )

            residuals = [safe_float(value) for value in list(getattr(fitted, "resid", []))]
            diagnostics: Dict[str, Any] = {
                "aic": safe_float(getattr(fitted, "aic", None), None),
                "bic": safe_float(getattr(fitted, "bic", None), None),
                "llf": safe_float(getattr(fitted, "llf", None), None),
                "residual_std": population_stddev(residuals, default=0.0) if residuals else None,
            }

            if residuals:
                try:
                    from statsmodels.stats.diagnostic import acorr_ljungbox

                    lb_lag = max(1, min(10, len(residuals) // 3))
                    lb_frame = acorr_ljungbox(residuals, lags=[lb_lag], return_df=True)
                    diagnostics["residual_serial_corr_ljungbox_pvalue"] = safe_float(lb_frame["lb_pvalue"].iloc[0], None)
                except Exception:
                    diagnostics["residual_serial_corr_ljungbox_pvalue"] = None
                try:
                    from scipy.stats import jarque_bera

                    _, jb_pvalue = jarque_bera(residuals)
                    diagnostics["residual_normality_jarque_bera_pvalue"] = safe_float(jb_pvalue, None)
                except Exception:
                    diagnostics["residual_normality_jarque_bera_pvalue"] = None

            return {
                "available": True,
                "ready": True,
                "engine": "statsmodels_ets_prediction_interval",
                "source": "statsmodels_ets_prediction_interval",
                "model_name": model_name,
                "alpha": alpha,
                "points": points,
                "interval_width_avg": round(mean(point["p90"] - point["p10"] for point in points), 2) if points else None,
                "diagnostics": diagnostics,
            }
        except Exception as exc:  # pragma: no cover
            last_error = str(exc)

    return {
        "available": True,
        "ready": False,
        "engine": "statsmodels_ets_prediction_interval",
        "error": last_error or "statsmodels_ets_prediction_failed",
    }


def _predict_series(
    values: List[float],
    day_keys: List[str],
    *,
    horizon_days: int,
    as_of_dt: datetime,
) -> Dict[str, Any]:
    statsmodels_result = _statsmodels_forecast(values, horizon_days=horizon_days)
    if statsmodels_result.get("available") and statsmodels_result.get("ready"):
        return statsmodels_result
    baseline_result = _baseline_forecast(values, day_keys, horizon_days=horizon_days, as_of_dt=as_of_dt)
    baseline_result["fallback_reason"] = statsmodels_result.get("reason") or statsmodels_result.get("error") or "statsmodels_unavailable"
    return baseline_result


def _predict_next_net(train_values: List[float], train_day_keys: List[str], target_day: str) -> Dict[str, float]:
    prediction = _predict_series(
        train_values,
        train_day_keys,
        horizon_days=1,
        as_of_dt=parse_datetime(target_day) - timedelta(days=1) if parse_datetime(target_day) else datetime.utcnow(),
    )
    p50 = float((prediction.get("forecast") or [0.0])[0])
    sigma = max(1.0, safe_float(prediction.get("residual_std"), population_stddev(train_values, default=500_000.0)))
    return {
        "p50": p50,
        "p10": p50 - Z90 * sigma,
        "p90": p50 + Z90 * sigma,
        "p20": p50 - Z80 * sigma,
        "p80": p50 + Z80 * sigma,
    }


def _rolling_backtest(day_keys: List[str], values: List[float]) -> Dict[str, Any]:
    if len(values) < 30:
        return {
            "available": False,
            "window_days": 0,
            "metrics": {},
            "residual_drift": {"available": False, "reason": "insufficient_history"},
        }

    window_days = min(28, max(14, len(values) // 4))
    predictions: List[float] = []
    actuals: List[float] = []
    p10_values: List[float] = []
    p20_values: List[float] = []
    p80_values: List[float] = []
    p90_values: List[float] = []
    residuals: List[float] = []

    for idx in range(len(values) - window_days, len(values)):
        forecast = _predict_next_net(values[:idx], day_keys[:idx], day_keys[idx])
        actual = float(values[idx])
        pred = forecast["p50"]
        predictions.append(pred)
        actuals.append(actual)
        p10_values.append(forecast["p10"])
        p20_values.append(forecast["p20"])
        p80_values.append(forecast["p80"])
        p90_values.append(forecast["p90"])
        residuals.append(actual - pred)

    abs_errors = [abs(actual - pred) for actual, pred in zip(actuals, predictions)]
    squared_errors = [(actual - pred) ** 2 for actual, pred in zip(actuals, predictions)]
    denom = sum(abs(actual) for actual in actuals)
    coverage_p80 = safe_div(
        sum(1 for actual, low, high in zip(actuals, p20_values, p80_values) if low <= actual <= high),
        len(actuals),
    )
    coverage_p90 = safe_div(
        sum(1 for actual, low, high in zip(actuals, p10_values, p90_values) if low <= actual <= high),
        len(actuals),
    )
    drift = river_adwin_drift(residuals) if residuals else {"available": False}
    return {
        "available": True,
        "window_days": window_days,
        "metrics": {
            "mae": round(mean(abs_errors), 4),
            "rmse": round(math.sqrt(mean(squared_errors)), 4),
            "wape": round(safe_div(sum(abs_errors), denom), 4) if denom > 0 else 0.0,
            "coverage_p80": round(coverage_p80, 4),
            "coverage_p90": round(coverage_p90, 4),
        },
        "residuals": residuals,
        "residual_drift": drift,
    }


def _apply_overrides(value: float, pct_delta: float, abs_delta: float) -> float:
    return max(0.0, value * (1 + pct_delta) + abs_delta)


def build_cashflow_projection(
    rows: List[Dict[str, Any]],
    *,
    as_of_dt: datetime,
    horizon_days: int,
    scenario_overrides: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    dense_rows = _build_dense_daily_series(rows, start_at=parse_datetime(rows[0]["occurred_at"]) if rows else daterange_start(as_of_dt, 180), end_at=as_of_dt) if rows else _build_dense_daily_series([], start_at=daterange_start(as_of_dt, 180), end_at=as_of_dt)
    if not dense_rows:
        dense_rows = _build_dense_daily_series([], start_at=daterange_start(as_of_dt, 180), end_at=as_of_dt)
    day_keys = [row["day"] for row in dense_rows]
    income_values = [float(row["income"]) for row in dense_rows]
    spend_values = [float(row["spend"]) for row in dense_rows]
    net_values = [float(row["net"]) for row in dense_rows]
    overrides = _parse_overrides(scenario_overrides)

    income_model = _predict_series(income_values, day_keys, horizon_days=horizon_days, as_of_dt=as_of_dt)
    spend_model = _predict_series(spend_values, day_keys, horizon_days=horizon_days, as_of_dt=as_of_dt)
    active_model = STATSMODELS_NAME if income_model.get("engine") == STATSMODELS_NAME and spend_model.get("engine") == STATSMODELS_NAME else MODEL_NAME
    base_income_forecast = [max(0.0, safe_float(value)) for value in (income_model.get("forecast") or [])[:horizon_days]]
    base_spend_forecast = [max(0.0, safe_float(value)) for value in (spend_model.get("forecast") or [])[:horizon_days]]
    income_sigma = max(1.0, safe_float(income_model.get("residual_std"), population_stddev(income_values, default=1_000_000.0)))
    spend_sigma = max(1.0, safe_float(spend_model.get("residual_std"), population_stddev(spend_values, default=1_000_000.0)))
    daily_predictions: List[Dict[str, Any]] = []

    for idx in range(horizon_days):
        point_dt = (as_of_dt + timedelta(days=idx + 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        income_est = _apply_overrides(base_income_forecast[idx], overrides["income_delta_pct"], overrides["income_delta_abs"])
        spend_est = _apply_overrides(base_spend_forecast[idx], overrides["spend_delta_pct"], overrides["spend_delta_abs"])
        sigma = max(300_000.0, math.sqrt(income_sigma ** 2 + spend_sigma ** 2))
        p50 = income_est - spend_est
        probability_negative_net = clamp(_normal_cdf((0.0 - p50) / sigma))
        daily_predictions.append(
            {
                "period": point_dt.date().isoformat(),
                "income_estimate": round(income_est, 2),
                "spend_estimate": round(spend_est, 2),
                "p10": round(p50 - Z90 * sigma, 2),
                "p50": round(p50, 2),
                "p90": round(p50 + Z90 * sigma, 2),
                "probability_negative_net": round(probability_negative_net, 4),
                "_sigma": sigma,
            }
        )

    backtest = _rolling_backtest(day_keys, net_values)
    coverage_p80 = safe_float(backtest.get("metrics", {}).get("coverage_p80"), 0.0)
    coverage_p90 = safe_float(backtest.get("metrics", {}).get("coverage_p90"), 0.0)
    calibration_quality = 0.0
    if backtest.get("available"):
        calibration_quality = clamp(
            1.0
            - (
                abs(coverage_p80 - 0.8) / 0.4
                + abs(coverage_p90 - 0.9) / 0.4
            )
            / 2.0
        )
    data_quality = clamp(
        0.6 * clamp(len(dense_rows) / 180.0) + 0.4 * safe_div(sum(1 for row in dense_rows if row["active"]), len(dense_rows))
    )
    backtest_quality = clamp(1.0 - safe_float(backtest.get("metrics", {}).get("wape"), 1.0))
    residual_drift = backtest.get("residual_drift", {})
    stability_score = clamp(
        1.0
        - (0.3 if residual_drift.get("drift_detected") else 0.0)
        - min(0.4, safe_float(backtest.get("metrics", {}).get("rmse"), 0.0) / max(abs(mean(net_values)), 1_000_000.0))
    )
    confidence_score = weighted_score(
        {
            "data_quality": data_quality,
            "backtest_quality": backtest_quality,
            "calibration": calibration_quality,
            "stability": stability_score,
        },
        {
            "data_quality": 0.2,
            "backtest_quality": 0.35,
            "calibration": 0.3,
            "stability": 0.15,
        },
    )
    reason_codes = []
    if len(dense_rows) < 56:
        reason_codes.append("low_history")
    if not backtest.get("available"):
        reason_codes.append("backtest_insufficient_history")
    if residual_drift.get("drift_detected"):
        reason_codes.append("residual_drift_detected")
    if active_model == MODEL_NAME:
        reason_codes.append("statsmodels_fallback")

    darts_result = {"available": False, "engine": "darts_exponential_smoothing"}
    ets_interval_result = {"available": False, "engine": "statsmodels_ets_prediction_interval"}
    if os.getenv("USE_DARTS_FORECAST", "true").strip().lower() in {"1", "true", "yes", "on"}:
        if horizon_days == 30:
            darts_result = darts_forecast_points(day_keys, net_values, horizon="daily_30")
        else:
            darts_result = {
                "available": True,
                "engine": "darts_exponential_smoothing",
                "ready": False,
                "reason": "dynamic_horizon_not_supported_by_legacy_adapter",
                "requested_horizon_days": horizon_days,
                "points": [],
            }
    if os.getenv("USE_STATSMODELS_ETS_INTERVAL", "true").strip().lower() in {"1", "true", "yes", "on"}:
        ets_interval_result = _statsmodels_ets_prediction_interval(day_keys, net_values, horizon_days=horizon_days, alpha=0.2)

    return {
        "daily_predictions": daily_predictions,
        "dense_rows": dense_rows,
        "model_meta": {
            "model": active_model,
            "history_days": len(dense_rows),
            "active_days_ratio": round(safe_div(sum(1 for row in dense_rows if row["active"]), len(dense_rows)), 4),
            "low_history": len(dense_rows) < 56,
            "income_engine": income_model.get("engine"),
            "spend_engine": spend_model.get("engine"),
        },
        "backtest": {
            "window_days": backtest.get("window_days", 0),
            "metrics": backtest.get("metrics", {}),
            "residual_drift": residual_drift,
        },
        "probability_negative_net": round(mean(point["probability_negative_net"] for point in daily_predictions), 4) if daily_predictions else 0.0,
        "external_engines": {
            "darts_exponential_smoothing": darts_result,
            "statsmodels_ets_prediction_interval": ets_interval_result,
        },
        "reliability": build_reliability(
            confidence_score=confidence_score,
            components={
                "data_quality": data_quality,
                "model_quality": backtest_quality,
                "stability": stability_score,
                "calibration": calibration_quality,
            },
            reason_codes=reason_codes,
        ),
        "validation": build_validation(
            backtest_window_days=backtest.get("window_days", 0),
            metrics=backtest.get("metrics", {}),
            residual_drift=residual_drift,
        ),
        "provenance": build_provenance(
            library="statsmodels" if active_model == STATSMODELS_NAME else "deterministic",
            model=active_model,
            model_version="forecast_v2",
            base_model=MODEL_NAME if active_model != MODEL_NAME else None,
            feature_set_version="daily_cashflow_v2",
            extra={
                "secondary_engine": darts_result.get("engine") if darts_result.get("available") else None,
                "tertiary_engine": ets_interval_result.get("engine") if ets_interval_result.get("available") else None,
            },
        ),
    }


def aggregate_daily_predictions(
    daily_predictions: List[Dict[str, Any]],
    *,
    granularity: str,
    limit: int,
) -> List[Dict[str, Any]]:
    if granularity == "daily":
        return [
            {
                "period": row["period"],
                "income_estimate": row["income_estimate"],
                "spend_estimate": row["spend_estimate"],
                "p10": row["p10"],
                "p50": row["p50"],
                "p90": row["p90"],
                "probability_negative_net": row["probability_negative_net"],
                "_sigma": row["_sigma"],
            }
            for row in daily_predictions[:limit]
        ]

    grouped: List[List[Dict[str, Any]]] = []
    if granularity == "weekly":
        for start_idx in range(0, min(len(daily_predictions), limit * 7), 7):
            chunk = daily_predictions[start_idx:start_idx + 7]
            if chunk:
                grouped.append(chunk)
    elif granularity == "monthly":
        bucket_map: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        order: List[str] = []
        for row in daily_predictions:
            bucket = row["period"][:7]
            if bucket not in bucket_map:
                order.append(bucket)
            bucket_map[bucket].append(row)
        for bucket in order[:limit]:
            grouped.append(bucket_map[bucket])
    else:
        return []

    points: List[Dict[str, Any]] = []
    for index, chunk in enumerate(grouped, start=1):
        sigma = math.sqrt(sum(float(item["_sigma"]) ** 2 for item in chunk))
        income_est = sum(float(item["income_estimate"]) for item in chunk)
        spend_est = sum(float(item["spend_estimate"]) for item in chunk)
        p50 = income_est - spend_est
        period = chunk[0]["period"][:7] if granularity == "monthly" else f"{parse_datetime(chunk[-1]['period']).year}-W{parse_datetime(chunk[-1]['period']).isocalendar().week:02d}"
        points.append(
            {
                "period": period,
                "income_estimate": round(income_est, 2),
                "spend_estimate": round(spend_est, 2),
                "p10": round(p50 - Z90 * sigma, 2),
                "p50": round(p50, 2),
                "p90": round(p50 + Z90 * sigma, 2),
                "probability_negative_net": round(mean(item["probability_negative_net"] for item in chunk), 4),
                "_sigma": sigma,
            }
        )
    return points[:limit]


def monthly_distribution(points: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    normalized_points = [dict(point) for point in points]
    sigma_values = [
        max(1.0, safe_div(float(point["p90"]) - float(point["p10"]), 2 * Z90, default=1_000_000.0))
        for point in normalized_points
    ]
    return {
        "means": [float(point["p50"]) for point in normalized_points],
        "sigmas": sigma_values,
        "points": normalized_points,
    }


def _confidence_band(points: List[Dict[str, Any]]) -> Dict[str, float]:
    if not points:
        return {"p10_avg": 0.0, "p50_avg": 0.0, "p90_avg": 0.0}
    return {
        "p10_avg": round(mean(point["p10"] for point in points), 2),
        "p50_avg": round(mean(point["p50"] for point in points), 2),
        "p90_avg": round(mean(point["p90"] for point in points), 2),
    }


def _aggregate_interval_points(
    points: List[Dict[str, Any]],
    *,
    granularity: str,
    limit: int,
) -> List[Dict[str, Any]]:
    normalized = [
        {
            "period": str(point.get("period") or ""),
            "p10": safe_float(point.get("p10")),
            "p50": safe_float(point.get("p50")),
            "p90": safe_float(point.get("p90")),
        }
        for point in points
        if point.get("period") is not None
    ]
    if granularity == "daily":
        return normalized[:limit]

    if granularity == "weekly":
        grouped: List[List[Dict[str, Any]]] = []
        for start_idx in range(0, min(len(normalized), limit * 7), 7):
            chunk = normalized[start_idx:start_idx + 7]
            if chunk:
                grouped.append(chunk)
        aggregated: List[Dict[str, Any]] = []
        for chunk in grouped:
            sigmas = [max(1.0, safe_div(item["p90"] - item["p10"], 2 * Z90, default=1_000_000.0)) for item in chunk]
            sigma = math.sqrt(sum(value ** 2 for value in sigmas))
            p50 = sum(item["p50"] for item in chunk)
            chunk_end = parse_datetime(chunk[-1]["period"])
            week_label = f"{chunk_end.year}-W{chunk_end.isocalendar().week:02d}" if chunk_end else chunk[-1]["period"]
            aggregated.append(
                {
                    "period": week_label,
                    "p10": round(p50 - Z90 * sigma, 2),
                    "p50": round(p50, 2),
                    "p90": round(p50 + Z90 * sigma, 2),
                }
            )
        return aggregated[:limit]

    return normalized[:limit]


def build_forecast_actuals_rows(
    *,
    user_id: str,
    trace_id: str,
    tool_name: str,
    horizon: str,
    granularity: str,
    as_of_dt: datetime,
    model_name: str,
    daily_predictions: List[Dict[str, Any]],
    reliability_score: float,
    overrides: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if granularity == "daily":
        for item in daily_predictions[:30]:
            rows.append(
                {
                    "user_id": user_id,
                    "trace_id": trace_id,
                    "tool_name": tool_name,
                    "model_name": model_name,
                    "horizon": horizon,
                    "granularity": granularity,
                    "forecast_as_of": iso_utc(as_of_dt),
                    "target_start": item["period"],
                    "target_end": item["period"],
                    "predicted_p10": item["p10"],
                    "predicted_p50": item["p50"],
                    "predicted_p90": item["p90"],
                    "payload": {
                        "probability_negative_net": item["probability_negative_net"],
                        "confidence_score": round(reliability_score, 4),
                        "scenario_overrides": overrides,
                    },
                }
            )
        return rows

    for start_idx in range(0, min(len(daily_predictions), 12 * 7), 7):
        chunk = daily_predictions[start_idx:start_idx + 7]
        if not chunk:
            continue
        sigma = math.sqrt(sum(float(item["_sigma"]) ** 2 for item in chunk))
        p50 = sum(float(item["income_estimate"]) - float(item["spend_estimate"]) for item in chunk)
        rows.append(
            {
                "user_id": user_id,
                "trace_id": trace_id,
                "tool_name": tool_name,
                "model_name": model_name,
                "horizon": horizon,
                "granularity": granularity,
                "forecast_as_of": iso_utc(as_of_dt),
                "target_start": chunk[0]["period"],
                "target_end": chunk[-1]["period"],
                "predicted_p10": round(p50 - Z90 * sigma, 2),
                "predicted_p50": round(p50, 2),
                "predicted_p90": round(p50 + Z90 * sigma, 2),
                "payload": {
                    "probability_negative_net": round(mean(item["probability_negative_net"] for item in chunk), 4),
                    "confidence_score": round(reliability_score, 4),
                    "scenario_overrides": overrides,
                },
            }
        )
    return rows


def _historical_logged_validation(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows:
        return {
            "available": False,
            "actual_count": 0,
        }
    abs_errors = [safe_float(row.get("error_abs")) for row in rows if row.get("error_abs") is not None]
    within_p80 = [1.0 if bool(row.get("within_p80")) else 0.0 for row in rows if row.get("within_p80") is not None]
    within_p90 = [1.0 if bool(row.get("within_p90")) else 0.0 for row in rows if row.get("within_p90") is not None]
    return {
        "available": True,
        "actual_count": len(rows),
        "mae": round(mean(abs_errors), 4) if abs_errors else None,
        "coverage_p80": round(mean(within_p80), 4) if within_p80 else None,
        "coverage_p90": round(mean(within_p90), 4) if within_p90 else None,
        "last_actual_target_end": str(rows[0].get("target_end") or ""),
    }


def historical_logged_validation(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _historical_logged_validation(rows)


def _build_forecast_calibration_monitoring(
    *,
    confidence_score: float,
    confidence_level: str,
    backtest_metrics: Dict[str, Any],
    historical_actuals: Dict[str, Any],
    native_uncertainty_source: str,
    interval_width_avg: float | None,
    recalibration: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    def _gap(value: Any, target: float) -> float | None:
        if value is None:
            return None
        return round(abs(safe_float(value) - target), 4)

    backtest_cov_p80 = backtest_metrics.get("coverage_p80")
    backtest_cov_p90 = backtest_metrics.get("coverage_p90")
    historical_cov_p80 = historical_actuals.get("coverage_p80")
    historical_cov_p90 = historical_actuals.get("coverage_p90")
    historical_actual_count = int(safe_float(historical_actuals.get("actual_count"), 0.0))
    gaps = [
        value
        for value in (
            _gap(backtest_cov_p80, 0.8),
            _gap(backtest_cov_p90, 0.9),
            _gap(historical_cov_p80, 0.8),
            _gap(historical_cov_p90, 0.9),
        )
        if value is not None
    ]
    if not gaps and historical_actual_count <= 0:
        status = "insufficient_data"
    else:
        worst_gap = max(gaps) if gaps else 0.0
        if worst_gap <= 0.1:
            status = "healthy"
        elif worst_gap <= 0.2:
            status = "watch"
        else:
            status = "alert"

    payload = {
        "confidence_score": round(clamp(confidence_score), 4),
        "recommended_confidence_score": round(clamp(confidence_score), 4),
        "recommended_confidence_path": "reliability.confidence_score",
        "decision_confidence_source": "raw_reliability_score",
        "agent_use_guidance": "Use reliability.confidence_score for downstream decisions; treat calibrated_confidence_score as monitoring only.",
        "confidence_bucket": str(confidence_level or "low"),
        "native_uncertainty_source": str(native_uncertainty_source or ""),
        "interval_width_avg": round(safe_float(interval_width_avg), 2) if interval_width_avg is not None else None,
        "backtest_coverage_p80": backtest_cov_p80,
        "backtest_coverage_p90": backtest_cov_p90,
        "historical_coverage_p80": historical_cov_p80,
        "historical_coverage_p90": historical_cov_p90,
        "coverage_gap_p80": _gap(backtest_cov_p80, 0.8),
        "coverage_gap_p90": _gap(backtest_cov_p90, 0.9),
        "historical_actual_count": historical_actual_count,
        "monitoring_status": status,
    }
    if recalibration:
        payload["recalibration"] = dict(recalibration)
        calibrated_score = recalibration.get("calibrated_score")
        if calibrated_score is not None:
            calibrated = round(clamp(safe_float(calibrated_score)), 4)
            payload["calibrated_confidence_score"] = calibrated
            payload["calibrated_confidence_score_monitoring_only"] = True
            payload["calibrated_confidence_gap"] = round(abs(calibrated - clamp(confidence_score)), 4)
    return payload


def update_forecast_actuals_for_user(
    client: SupabaseRestClient,
    *,
    user_id: str,
    tool_name: str = TOOL_NAME,
    available_until: datetime,
    lookback_days: int = 365,
) -> Dict[str, Any]:
    try:
        rows = client.fetch_rows(
            "forecast_actuals_log",
            select="id,user_id,trace_id,tool_name,model_name,horizon,granularity,forecast_as_of,target_start,target_end,predicted_p10,predicted_p50,predicted_p90,actual_value,payload",
            filters={
                "user_id": f"eq.{user_id}",
                "tool_name": f"eq.{tool_name}",
            },
            order="forecast_as_of.asc",
        )
    except Exception:
        return {"updated_count": 0, "eligible_count": 0, "available_until": iso_utc(available_until)}

    start_dt = daterange_start(available_until, max(30, int(lookback_days or 365)))
    pending_rows: List[Dict[str, Any]] = []
    min_target_start = None
    for row in rows:
        forecast_as_of = parse_datetime(row.get("forecast_as_of"))
        target_start = parse_datetime(str(row.get("target_start") or ""))
        target_end = parse_datetime(str(row.get("target_end") or ""))
        if not forecast_as_of or not target_start or not target_end:
            continue
        if forecast_as_of < start_dt:
            continue
        if target_end.date() > available_until.date():
            continue
        if row.get("actual_value") is not None:
            continue
        pending_rows.append(row)
        if min_target_start is None or target_start < min_target_start:
            min_target_start = target_start

    if not pending_rows or min_target_start is None:
        return {"updated_count": 0, "eligible_count": 0, "available_until": iso_utc(available_until)}

    txns = fetch_transactions_in_window(client, user_id=user_id, start_at=min_target_start, end_at=available_until)
    daily_net: Dict[str, float] = defaultdict(float)
    for tx in txns:
        occurred = parse_datetime(tx.get("occurred_at"))
        if not occurred:
            continue
        day_key = occurred.date().isoformat()
        amount = safe_float(tx.get("amount"))
        direction = str(tx.get("direction") or "debit").lower()
        if direction == "credit":
            daily_net[day_key] += amount
        else:
            daily_net[day_key] -= amount

    update_rows: List[Dict[str, Any]] = []
    for row in pending_rows:
        target_start = parse_datetime(str(row.get("target_start") or ""))
        target_end = parse_datetime(str(row.get("target_end") or ""))
        if not target_start or not target_end:
            continue
        actual_value = 0.0
        cursor = target_start
        while cursor.date() <= target_end.date():
            actual_value += safe_float(daily_net.get(cursor.date().isoformat()))
            cursor += timedelta(days=1)
        p10 = safe_float(row.get("predicted_p10"))
        p50 = safe_float(row.get("predicted_p50"))
        p90 = safe_float(row.get("predicted_p90"))
        sigma = max(1.0, safe_div(p90 - p10, 2 * Z90, default=1_000_000.0))
        p20 = p50 - Z80 * sigma
        p80 = p50 + Z80 * sigma
        existing_payload = dict(row.get("payload") or {})
        existing_payload["actualized_by"] = "forecast_actuals_pipeline_v1"
        existing_payload["actualized_at"] = iso_utc(available_until)
        update_rows.append(
            {
                "user_id": user_id,
                "trace_id": row.get("trace_id"),
                "tool_name": row.get("tool_name") or tool_name,
                "model_name": row.get("model_name"),
                "horizon": row.get("horizon"),
                "granularity": row.get("granularity"),
                "forecast_as_of": row.get("forecast_as_of"),
                "target_start": row.get("target_start"),
                "target_end": row.get("target_end"),
                "predicted_p10": row.get("predicted_p10"),
                "predicted_p50": row.get("predicted_p50"),
                "predicted_p90": row.get("predicted_p90"),
                "actual_value": round(actual_value, 2),
                "actual_recorded_at": iso_utc(available_until),
                "error_signed": round(actual_value - p50, 2),
                "error_abs": round(abs(actual_value - p50), 2),
                "within_p80": bool(p20 <= actual_value <= p80),
                "within_p90": bool(p10 <= actual_value <= p90),
                "payload": existing_payload,
            }
        )

    write_forecast_actuals_rows(client, update_rows)
    return {
        "updated_count": len(update_rows),
        "eligible_count": len(pending_rows),
        "available_until": iso_utc(available_until),
    }


def cashflow_forecast(
    *,
    auth_user_id: str,
    user_id: str,
    horizon_days: int = 84,
    scenario_overrides: Dict[str, Any] | None = None,
    as_of: str | None = None,
    trace_id: str | None = None,
    client: SupabaseRestClient | None = None,
) -> Dict[str, Any]:
    started_at = now_utc()
    trace = new_trace_id(trace_id)
    ensure_user_scope(auth_user_id, user_id)

    horizon_days = max(1, int(safe_float(horizon_days, 84)))
    horizon = f"daily_{horizon_days}"
    granularity = "daily"
    as_of_dt = parse_datetime(as_of) or now_utc()
    history_start = daterange_start(as_of_dt, 180)
    sql = client or get_supabase_client()
    txns = fetch_transactions_in_window(sql, user_id=user_id, start_at=history_start, end_at=as_of_dt)
    actualization_summary = update_forecast_actuals_for_user(
        sql,
        user_id=user_id,
        tool_name=TOOL_NAME,
        available_until=as_of_dt,
        lookback_days=365,
    )
    overrides = _parse_overrides(scenario_overrides)
    projection = build_cashflow_projection(
        txns,
        as_of_dt=as_of_dt,
        horizon_days=horizon_days,
        scenario_overrides=overrides,
    )
    points = aggregate_daily_predictions(projection["daily_predictions"], granularity=granularity, limit=horizon_days)
    confidence_band = _confidence_band(points)
    darts_result = dict(projection.get("external_engines", {}).get("darts_exponential_smoothing") or {})
    ets_interval_result = dict(projection.get("external_engines", {}).get("statsmodels_ets_prediction_interval") or {})
    if ets_interval_result.get("ready"):
        native_uncertainty_points = _aggregate_interval_points(
            ets_interval_result.get("points") or [],
            granularity=granularity,
            limit=horizon_days,
        )
    else:
        native_uncertainty_points = darts_result.get("points") if darts_result.get("ready") else points
    if not isinstance(native_uncertainty_points, list):
        native_uncertainty_points = points
    if ets_interval_result.get("ready"):
        native_uncertainty_source = "statsmodels_ets_prediction_interval"
    elif darts_result.get("ready"):
        native_uncertainty_source = str(darts_result.get("source") or "darts_sampling_quantiles")
    else:
        native_uncertainty_source = "heuristic_sigma_band"
    native_uncertainty_summary = _confidence_band(native_uncertainty_points)
    historical_actuals = fetch_forecast_actuals_history(
        sql,
        user_id=user_id,
        start_at=daterange_start(as_of_dt, 365),
        end_at=as_of_dt,
        tool_name=TOOL_NAME,
    )
    matching_actuals = [
        row
        for row in historical_actuals
        if str(row.get("horizon") or "") == horizon and str(row.get("granularity") or "") == granularity
    ]

    forecast_reason_codes = normalize_reason_codes(
        projection["reliability"].get("reason_codes", []),
        ["no_transactions_in_window"] if not txns else [],
        ["negative_net_risk_elevated"] if projection["probability_negative_net"] >= 0.5 else [],
    )
    reliability = build_reliability(
        confidence_score=safe_float(projection["reliability"]["confidence_score"]),
        components=projection["reliability"].get("components", {}),
        reason_codes=forecast_reason_codes,
    )
    forecast_log_rows = build_forecast_actuals_rows(
        user_id=user_id,
        trace_id=trace,
        tool_name=TOOL_NAME,
        horizon=horizon,
        granularity=granularity,
        as_of_dt=as_of_dt,
        model_name=str(projection["model_meta"].get("model") or MODEL_NAME),
        daily_predictions=projection["daily_predictions"],
        reliability_score=safe_float(reliability["confidence_score"]),
        overrides=overrides,
    )
    validation = build_validation(
        **projection["validation"],
        historical_actuals=_historical_logged_validation(matching_actuals),
        forecast_log_rows=len(forecast_log_rows),
        actualization_summary=actualization_summary,
    )
    recalibration = fit_recalibrated_probability(
        raw_score=safe_float(reliability["confidence_score"]),
        samples=extract_forecast_recalibration_samples(matching_actuals),
    )
    calibration_monitoring = _build_forecast_calibration_monitoring(
        confidence_score=safe_float(reliability["confidence_score"]),
        confidence_level=str(reliability.get("confidence_level") or "low"),
        backtest_metrics=projection.get("backtest", {}).get("metrics", {}),
        historical_actuals=validation.get("historical_actuals", {}),
        native_uncertainty_source=native_uncertainty_source,
        interval_width_avg=ets_interval_result.get("interval_width_avg")
        if ets_interval_result.get("ready")
        else darts_result.get("interval_width_avg"),
        recalibration=recalibration,
    )
    forecast_outcomes = count_forecast_actuals(matching_actuals, horizon=horizon, granularity=granularity)
    trust_bundle = build_trust(
        confidence_score=safe_float(reliability["confidence_score"]),
        reliability_components=reliability.get("components"),
        abstain_recommended=bool(reliability.get("abstain_recommended")),
        prior_alpha=8.0,
        prior_beta=2.0,
        monitoring_status=str(calibration_monitoring.get("monitoring_status") or ""),
        success_count=forecast_outcomes["success_count"],
        failure_count=forecast_outcomes["failure_count"],
    )

    tool_input = {
        "user_id": user_id,
        "horizon_days": horizon_days,
        "as_of": iso_utc(as_of_dt),
        "scenario_overrides": overrides,
    }
    payload = {
        "horizon_days": horizon_days,
        "horizon": horizon,
        "granularity": granularity,
        "points": [{key: value for key, value in point.items() if not key.startswith("_")} for point in points],
        "confidence_band": confidence_band,
        "confidence_band_source": "heuristic_sigma_band",
        "model_meta": projection["model_meta"],
        "backtest": projection["backtest"],
        "probability_negative_net": projection["probability_negative_net"],
        "budget_risk": {
            "probability_negative_net": projection["probability_negative_net"],
        },
        "assumptions": [
            "Primary forecast uses statsmodels ETS when enough history is available.",
            "Fallback forecast uses dense daily weekday baseline when model fit is unavailable.",
        ],
        "external_engines": projection["external_engines"],
    }

    result = build_output(
        tool_name=TOOL_NAME,
        tool_input=tool_input,
        payload=payload,
        trace_id=trace,
        started_at=started_at,
        sql_snapshot_ts=iso_utc(),
        as_of=iso_utc(as_of_dt),
        window=build_window(history_start, as_of_dt),
        reliability=reliability,
        trust=trust_bundle["trust"],
        agent_use=trust_bundle["agent_use"],
        model_evidence=build_model_evidence(
            native_uncertainty=build_native_uncertainty(
                source=native_uncertainty_source,
                p10=native_uncertainty_summary.get("p10_avg"),
                p50=native_uncertainty_summary.get("p50_avg"),
                p90=native_uncertainty_summary.get("p90_avg"),
                granularity=granularity,
                points=[{key: value for key, value in point.items() if not key.startswith("_")} for point in native_uncertainty_points],
                legacy_output_band_source="heuristic_sigma_band",
                used_for_output=False,
                num_samples=darts_result.get("num_samples") if darts_result.get("ready") else None,
                interval_width_avg=darts_result.get("interval_width_avg") if darts_result.get("ready") else None,
                interval_alpha=ets_interval_result.get("alpha") if ets_interval_result.get("ready") else None,
                aic=(ets_interval_result.get("diagnostics") or {}).get("aic") if ets_interval_result.get("ready") else None,
                bic=(ets_interval_result.get("diagnostics") or {}).get("bic") if ets_interval_result.get("ready") else None,
                llf=(ets_interval_result.get("diagnostics") or {}).get("llf") if ets_interval_result.get("ready") else None,
            )
        ),
        provenance=projection["provenance"],
        validation=build_validation(
            **validation,
            calibration_monitoring=calibration_monitoring,
            native_diagnostics={
                "darts_exponential_smoothing": {
                    "available": darts_result.get("available"),
                    "ready": darts_result.get("ready"),
                    "source": darts_result.get("source"),
                    "num_samples": darts_result.get("num_samples"),
                    "interval_width_avg": darts_result.get("interval_width_avg"),
                    "error": darts_result.get("error"),
                    "reason": darts_result.get("reason"),
                },
                "statsmodels_ets_prediction_interval": {
                    "available": ets_interval_result.get("available"),
                    "ready": ets_interval_result.get("ready"),
                    "source": ets_interval_result.get("source"),
                    "model_name": ets_interval_result.get("model_name"),
                    "alpha": ets_interval_result.get("alpha"),
                    "interval_width_avg": ets_interval_result.get("interval_width_avg"),
                    "aic": (ets_interval_result.get("diagnostics") or {}).get("aic"),
                    "bic": (ets_interval_result.get("diagnostics") or {}).get("bic"),
                    "llf": (ets_interval_result.get("diagnostics") or {}).get("llf"),
                    "residual_serial_corr_ljungbox_pvalue": (ets_interval_result.get("diagnostics") or {}).get("residual_serial_corr_ljungbox_pvalue"),
                    "residual_normality_jarque_bera_pvalue": (ets_interval_result.get("diagnostics") or {}).get("residual_normality_jarque_bera_pvalue"),
                    "error": ets_interval_result.get("error"),
                    "reason": ets_interval_result.get("reason"),
                },
                "native_uncertainty_source": native_uncertainty_source,
            },
        ),
    )
    write_forecast_actuals_rows(sql, forecast_log_rows)
    write_audit_event(
        sql,
        user_id=user_id,
        trace_id=trace,
        event_type=TOOL_NAME,
        payload={
            "params": tool_input,
            "result": {
                "points": len(points),
                "model": projection["model_meta"]["model"],
                "confidence_score": reliability["confidence_score"],
            },
        },
    )
    return result


