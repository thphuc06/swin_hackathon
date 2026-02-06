# Model + Data Training Plan (Jars MVP)

This document plans how to add trainable models to **Jars** while keeping the rule:

- **Truth layer** (numbers, balances, aggregates) comes **only** from Postgres views.
- Models provide **labels / signals** (categorization, anomaly/forecast), and the Tier2 LLM only **explains** outputs from tools/views.
- Every inference is treated as a **tool** (auditable, policy-able, versioned).

## 1) Models to add

### Core (MVP)

1) **`llm_categorize_tx` (LLM inline Jar/Category suggester)**
   - **Job:** use LLM + rules to suggest `jar_id` + `category_id` (Top-K + confidence) for a transaction; auto-select only if high confidence.
   - **Why it's needed:** reduce friction in transfer flow; keep UX "tap to confirm" while preserving correctness.
   - **Key requirement:** works with **user-defined jars** (dynamic labels) via Jar Profile text; no model training required for MVP.

2) **`anomaly_signal` (Tier1 alerts)**
   - **Job:** detect spend spikes, income drops, runway risk, abnormal category drift.
   - **MVP path:** start with deterministic SQL heuristics on views, then swap to ML when data grows.

### Optional (upgrade)

3) **`kb_reranker`**
   - **Job:** improve KB retrieval relevance for policy/template docs (reduce "wrong citation").

4) **`merchant_normalizer`**
   - **Job:** normalize noisy `counterparty/raw_narrative` into a canonical `merchant_id` (clustering / embeddings).

**Advisor model note (Tier2):** No fine-tune planned for MVP. Tier2 uses LLM + SQL views + rules; KB only for policy/templates with citations.

## 2) `llm_categorize_tx`: LLM-first design for user-defined jars

Because jars are **user-defined**, a fixed-head classifier is brittle. MVP uses **LLM + rules + Jar Profile text** to generate Top-K suggestions with confidence gating:

- Represent each user jar by a **Jar Profile** text blob (name/description/keywords/examples).
- Prompt LLM with transaction text/metadata + candidate jar profiles to produce scored Top-K.
- Apply deterministic rules (pinned mappings) before LLM; low confidence -> force manual selection.

### 2.1 Inputs (minimum viable)

Even if users do not type a note, you still need *some* signal. Store/collect these fields at ingestion time:

- `counterparty` (beneficiary / payer name)
- `raw_narrative` (bank-generated transfer narrative/reference, if available)
- `user_note` (optional, user-typed)
- `direction` (debit/credit)
- `amount`, `currency`
- `occurred_at` (timestamp)
- `channel` (transfer/card/qr/cash/other, if available)

If **all text is empty/default** and only `amount/time` remain, the model must return **low confidence** and force manual selection.

### 2.2 Jar Profile (per user, per jar)

Create a jar with:
- `name` (e.g., "Ví đi chơi với người yêu")
- optional `description` (purpose in 1-2 sentences)
- optional `keywords` (merchant names, places, emojis, slang)
- optional `examples` (a few example transactions the user confirms belong to this jar)

Jar profile text used for matching:

```
Jar: {name}
Description: {description}
Keywords: {kw1, kw2, ...}
Examples: {merchant1, merchant2, ...}
```

### 2.3 Scoring + confidence gating (LLM-first)

MVP scoring stack:

1) **Rules first (deterministic)**
   - `counterparty -> jar_id/category_id` pinned mappings (user confirms once, reuse forever)
   - keyword rules (regex/contains)

2) **LLM scoring**
   - Prompt: transaction fields + Jar Profiles; ask for Top-K with normalized confidence.
   - Apply safe output format (JSON top_k).

3) **Optional candidate pruning (later)**
   - Use embeddings to preselect Top-N jar profiles before LLM to save cost/latency.

Confidence gating defaults (hackathon):
- Autoselect only when `p_top1 >= 0.75` **and** `(p_top1 - p_top2) >= 0.20`.
- Otherwise show Top-K and require user confirmation.

Flow notes:
- **Tier1 transfer UX:** user picks jar manually; `llm_categorize_tx` only hints Top-K to speed selection.
- **Tier2 external/recurring feeds:** LLM auto-categorizes to **categories (not jars)**; surface to user to attach jar later.

## 3) Data to collect (datasets you can actually train)

Public datasets help with generic "category from description", but will not match:
- Vietnamese bank narratives
- your jar taxonomy (dynamic, user-defined)
- your product UX (confirm/correct loop)

So the most valuable dataset is **your own app telemetry** (with user consent). For LLM-first MVP, public datasets are **optional bootstrap** for prompt design/edge cases, not required.

### 3.1 Tables / events (recommended)

#### `jars` (add fields for ML)
- `id`, `user_id`, `name`
- `description` (text, nullable)
- `keywords` (text[], nullable) or `keywords_json` (jsonb)
- `created_at`, `updated_at`

#### `transactions` (keep raw signals)
- existing: `id`, `user_id`, `jar_id`, `category_id`, `amount`, `counterparty`, `created_at`, `direction`
- add: `raw_narrative`, `user_note`, `channel`, `currency`, `occurred_at`

#### `tx_label_events` (supervised labels + feedback loop)
Every time a user confirms/changes a suggestion, write one event:
- `id`, `user_id`, `txn_id`
- `model_version`
- `input_snapshot` (jsonb: the fields used for inference; redact if needed)
- `suggested_jar_id`, `suggested_category_id`, `scores_topk` (jsonb)
- `final_jar_id`, `final_category_id`
- `is_override` (bool)
- `created_at`

### 3.2 Derived training sets

**Pairwise ranking dataset** (best for dynamic jars):
- Positive: `(transaction, correct_jar_profile) = 1`
- Negatives: `(transaction, other_jar_profile) = 0` (sample 5-20 jars per txn)

This trains a model that can score **new jars** without changing the classifier head.

## 4) Categorization recipes (LLM-first, training optional later)

### 4.1 MVP (no training)
- Deterministic rules + pinned mappings.
- LLM prompt with Jar Profiles to return Top-K + confidence.
- Calibrate thresholds T/M on validation logs (`tx_label_events`), not by training.

### 4.2 Optional future fine-tune (if data arrives)
- Keep LLM prompt as orchestrator; optionally fine-tune embeddings for candidate pruning.
- If pursuing training: bi-encoder or cross-encoder as in previous plan, but **not required for hackathon**.

### 4.3 Evaluation metrics (UX-first)
- `top1_accuracy`, `top3_accuracy`
- `coverage@confidence`: % autoselected at thresholds T/M
- `override_rate`: % user changes model suggestion
- Calibration (ECE) only if auto-select is enabled

## 5) Integration into the project (tool-first, auditable)

### 5.1 Request-time UX flow (still "tap jar", but faster)

```mermaid
sequenceDiagram
  participant U as User
  participant UI as Frontend
  participant API as Backend BFF
  participant CAT as llm_categorize_tx (tool)
  participant DB as Postgres (truth)

  U->>UI: Enter transfer (counterparty/amount/note optional)
  UI->>API: POST /transactions/suggest (draft txn)
  API->>CAT: score Top-K jar/category
  CAT-->>API: suggestions + confidence
  API-->>UI: show preselected jar if confident
  U->>UI: Confirm (or override)
  UI->>API: POST /transactions/transfer (final jar/category)
  API->>DB: write transaction
  API->>DB: write tx_label_events (prediction + correction)
```

### 5.2 Service placement

Treat `llm_categorize_tx` as a deployable tool:
- LLM tool exposed via Gateway/BFF; no model training required for MVP.
- Version prompt/policy as `model_version` and log it on every prediction.

### 5.3 Governance & audit
- Do not send raw ledger rows to the Tier2 LLM.
- Log: `trace_id`, tool name, `input_hash`, `output_hash`, `model_version`, top-k ids.
- If you route categorization via Gateway/Policy, enforce:
  - user ownership (`user_id` matches token subject)
  - deny-by-default
  - allow only minimal fields for inference (no full history unless needed)

## 6) MVP checklist (2-3 days realistic)

1) Add `POST /transactions/suggest` returning Top-K jar/category + confidence.
2) Add jar fields: `description`, `keywords` in schema (design-level is enough for MVP).
3) Start logging `tx_label_events` for every confirmation/override.
4) Start with rules + `llm_categorize_tx` prompt (no training) with thresholds T=0.75, M=0.20.
5) Optional later: add embedding pruning or fine-tune if/when data volume justifies.

## 7) Forecast + Anomaly addendum (user total + per jar)

This section extends the plan for **forecasting** and **anomaly** beyond the rule-only MVP.

### 7.1 Dataset candidates (bootstrap only)
Public datasets help with text signals or anomaly patterns, but do **not** replace real user telemetry.
Use them to prototype pipelines, metrics, and thresholds.

**A) Text -> Category (llm_categorize_tx bootstrap, optional)**
- **HF: `mitulshah/transaction-categorization`**
  - Large dataset with `transaction_description` + `category`.
  - Good for baseline text classifier / embedding retrieval.
- **HF: `utkarshugale/BusinessTransactions`**
  - Smaller dataset; good for schema mock + pipeline tests.
- **GoMask sample datasets** (Bank Transaction Categorization)
  - Very small; good for demo and smoke tests.

**B) Anomaly / pattern datasets (Tier1 signals)**
- **PaySim (Kaggle)**
  - Synthetic financial transactions with balances/time steps.
  - Useful for testing anomaly logic and end-to-end alert pipeline.
- **Optional large synthetic fraud datasets** (for scale tests)
  - Only for load testing or feature exploration; not for production advice.

> NOTE: All public datasets must be license-checked before use.

### 7.2 Forecasting targets (MVP)
Forecast is **per user total** and **per jar**:
- **User total spend forecast** (daily or weekly)
- **Jar-level spend forecast** (daily or weekly)

#### 7.2.1 Required aggregates (SQL views)
- `txn_agg_daily` with:
  - `user_id`, `date`, `spend_total`, `income_total`, `jar_spend_json`
- Optional: `jar_spend_daily` view for faster per-jar series

#### 7.2.2 Feature pack
- Base: `spend_total`, `income_total`, `jar_spend`
- Calendar features: `day_of_week`, `week_of_month`, `month`, `is_weekend`
- (Optional) domain features: `payday_flag`, `holiday_flag`

#### 7.2.3 Model path (MVP -> scale)
**MVP baseline (no GPU):**
- **Prophet** or **SARIMAX** per user total spend
- **Prophet** per jar (top N jars by activity)
- If data is sparse: fallback to **rolling average + seasonality heuristics**

**Later (when data grows):**
- **N-BEATS** for univariate series
- **TFT** for multi-horizon + multiple regressors

#### 7.2.4 Metrics + gating
- Metrics: `MAE`, `MAPE`, `coverage@confidence`
- Gating: if series length < threshold (e.g., 30 days), **skip ML** and use rules.

### 7.3 Anomaly signals (MVP)
Anomaly detection is **advisory**, not fraud.

#### 7.3.1 MVP rules (Tier1)
- Spend spike vs 30d baseline
- Income drop vs 60d baseline
- Jar drift: jar share changes above threshold
- Low balance runway (from SQL views)

#### 7.3.2 ML upgrade (when logs exist)
- **IsolationForest** or **OneClassSVM** on daily features
- Feature vector: `spend_total`, `income_total`, `jar_spend_*`, `time_since_payday`, `txn_count`
- Output is a **signal score**; still pass through rule-based gating

### 7.4 Integration (tools + audit)
- Expose as tools:
  - `forecast_user_total`
  - `forecast_jar_spend`
  - `anomaly_score_daily`
- Tool outputs are logged with:
  - `trace_id`, `model_version`, `input_hash`, `output_hash`
- Tier2 LLM only **explains** tool outputs.

### 7.5 Data flywheel (logs you must capture)
- `forecast_events` (store model outputs vs realized actuals)
- `anomaly_events` (score + rule triggers + user feedback)
- Re-train only after data volume is sufficient.

### 7.6 MVP demo suggestion
- Show 30d jar history -> show 7d forecast band
- Trigger a spike alert based on rule + show advisory explanation
- Include `trace_id` and audit entry for transparency

### 7.7 ASSUMPTIONS
- Sufficient daily aggregates exist in SQL views.
- Dataset licenses are compatible with hackathon/demo use.
- Early MVP favors rule-based + light models over heavy deep learning.
