# Data & Modeling Addendum (Forecast + Anomaly)

This file supplements `model_data_train.md` with the **forecast/anomaly** path and **dataset candidates** for bootstrapping.

## 0) Scope (aligned with project rules)
- **Truth numbers** come only from SQL/Postgres views.
- **LLM** only explains results; no direct numeric generation.
- **KB** is only for policy/template/service and must include citations.
- Any model inference is a **tool** with `trace_id` and audit logs.

## 1) Dataset candidates (bootstrap only)
Public datasets help with text signals or anomaly patterns, but do **not** replace real user telemetry.
Use them to prototype pipelines, metrics, and thresholds.

### A) Text ? Category (tx_categorizer bootstrap)
- **HF: `mitulshah/transaction-categorization`**
  - Large dataset with `transaction_description` + `category`.
  - Good for baseline text classifier / embedding retrieval.
- **HF: `utkarshugale/BusinessTransactions`**
  - Smaller dataset; good for schema mock + pipeline tests.
- **GoMask sample datasets** (Bank Transaction Categorization)
  - Very small; good for demo and smoke tests.

### B) Anomaly / pattern datasets (Tier1 signals)
- **PaySim (Kaggle)**
  - Synthetic financial transactions with balances/time steps.
  - Useful for testing anomaly logic and end-to-end alert pipeline.
- **Optional large synthetic fraud datasets** (for scale tests)
  - Only for load testing or feature exploration; not for production advice.

> NOTE: All public datasets must be license-checked before use.

## 2) Forecasting targets (MVP)
Forecast is **per user total** and **per jar** (requested):
- **User total spend forecast** (daily or weekly)
- **Jar-level spend forecast** (daily or weekly)

### 2.1 Required aggregates (SQL views)
- `txn_agg_daily` with:
  - `user_id`, `date`, `spend_total`, `income_total`, `jar_spend_json`
- Optional: `jar_spend_daily` view for faster per-jar series

### 2.2 Feature pack
- Base: `spend_total`, `income_total`, `jar_spend`
- Calendar features: `day_of_week`, `week_of_month`, `month`, `is_weekend`
- (Optional) domain features: `payday_flag`, `holiday_flag`

### 2.3 Model path (MVP -> scale)
**MVP baseline (no GPU):**
- **Prophet** or **SARIMAX** per user total spend
- **Prophet** per jar (top N jars by activity)
- If data is sparse: fallback to **rolling average + seasonality heuristics**

**Later (when data grows):**
- **N-BEATS** for univariate series
- **TFT** for multi-horizon + multiple regressors

### 2.4 Metrics + gating
- Metrics: `MAE`, `MAPE`, `coverage@confidence`
- Gating: if series length < threshold (e.g., 30 days), **skip ML** and use rules.

## 3) Anomaly signals (MVP)
Anomaly detection is **advisory**, not fraud.

### 3.1 MVP rules (Tier1)
- Spend spike vs 30d baseline
- Income drop vs 60d baseline
- Jar drift: jar share changes above threshold
- Low balance runway (from SQL views)

### 3.2 ML upgrade (when logs exist)
- **IsolationForest** or **OneClassSVM** on daily features
- Feature vector: `spend_total`, `income_total`, `jar_spend_*`, `time_since_payday`, `txn_count`
- Output is a **signal score**; still pass through rule-based gating

## 4) Integration (tools + audit)
- Expose as tools:
  - `forecast_user_total`
  - `forecast_jar_spend`
  - `anomaly_score_daily`
- Tool outputs are logged with:
  - `trace_id`, `model_version`, `input_hash`, `output_hash`
- Tier2 LLM only **explains** tool outputs.

## 5) Data flywheel (logs you must capture)
- `forecast_events` (store model outputs vs realized actuals)
- `anomaly_events` (score + rule triggers + user feedback)
- Re-train only after data volume is sufficient.

## 6) MVP demo suggestion
- Show 30d jar history ? show 7d forecast band
- Trigger a spike alert based on rule + show advisory explanation
- Include `trace_id` and audit entry for transparency

## 7) ASSUMPTIONS
- Sufficient daily aggregates exist in SQL views.
- Dataset licenses are compatible with hackathon/demo use.
- Early MVP favors rule-based + light models over heavy deep learning.
