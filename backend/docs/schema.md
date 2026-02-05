# Supabase Schema Design (MVP)

This is a design-only schema. No migrations are generated in this MVP. Tables are structured to migrate to Aurora PostgreSQL later.

## users
- id (uuid, pk)
- email (text, unique)
- created_at (timestamptz)

## profiles
- user_id (uuid, pk, fk -> users.id)
- display_name (text)
- risk_profile_current (text)
- locale (text)
- updated_at (timestamptz)

## jars
- id (uuid, pk)
- user_id (uuid, fk)
- template_id (uuid, fk -> jar_templates.id, nullable)
- name (text)
- description (text, nullable)
- keywords (jsonb, nullable) -- array of strings
- target_amount (numeric)
- created_at (timestamptz)
- updated_at (timestamptz)

## jar_templates
Default jars for first-time users.
- id (uuid, pk)
- name (text)
- description (text, nullable)
- keywords (jsonb, nullable)
- is_default (bool)
- created_at (timestamptz)

## categories (hierarchical)
- id (uuid, pk)
- user_id (uuid, fk)
- parent_id (uuid, nullable)
- name (text)

## transactions
- id (uuid, pk)
- user_id (uuid, fk)
- jar_id (uuid, fk)
- category_id (uuid, fk)
- amount (numeric)
- currency (text)
- counterparty (text)
- raw_narrative (text, nullable) -- bank-generated memo/reference
- user_note (text, nullable) -- user-entered note
- channel (text, nullable) -- transfer/card/qr/cash/other
- occurred_at (timestamptz) -- when transaction happened
- created_at (timestamptz)
- direction (text) -- debit/credit

## rules_counterparty_map
User-confirmed mapping for messy data (counterparty -> jar/category).
- id (uuid, pk)
- user_id (uuid, fk)
- counterparty_norm (text)
- jar_id (uuid, fk)
- category_id (uuid, fk)
- created_at (timestamptz)

## budgets
User-defined thresholds used by Tier1 triggers (weekly/monthly).
- id (uuid, pk)
- user_id (uuid, fk)
- scope_type (text) -- overall/jar/category
- scope_id (uuid, nullable) -- jar_id or category_id when applicable
- period (text) -- weekly/monthly
- limit_amount (numeric)
- currency (text)
- active (bool)
- created_at (timestamptz)
- updated_at (timestamptz)

## tx_label_events
Supervision stream for training + evaluation (every confirm/override).
- id (uuid, pk)
- user_id (uuid, fk)
- txn_id (uuid, fk -> transactions.id)
- model_version (text)
- suggested_topk (jsonb) -- ids + scores
- final_jar_id (uuid)
- final_category_id (uuid)
- is_override (bool)
- created_at (timestamptz)

## signals_daily
Truth-aligned signals (computed from views) used by Tier1 and Tier2.
- id (uuid, pk)
- user_id (uuid, fk)
- day (date)
- discipline_score (int)
- categorized_rate (numeric)
- missing_rate (numeric)
- runway_days (int)
- risk_90d_flag (bool)
- payload (jsonb)

## txn_agg_daily
- id (uuid, pk)
- user_id (uuid, fk)
- day (date)
- total_spend (numeric)
- total_income (numeric)
- jar_breakdown (jsonb)
- category_breakdown (jsonb)

## goals
- id (uuid, pk)
- user_id (uuid, fk)
- name (text)
- target_amount (numeric)
- horizon_months (int)
- created_at (timestamptz)

## risk_profile_versions
- id (uuid, pk)
- user_id (uuid, fk)
- profile (text)
- notes (text)
- created_at (timestamptz)

## notifications
- id (uuid, pk)
- user_id (uuid, fk)
- title (text)
- detail (text)
- trace_id (text)
- created_at (timestamptz)
- is_read (bool)

## insights
- id (uuid, pk)
- user_id (uuid, fk)
- type (text)
- payload (jsonb)
- created_at (timestamptz)

## income_sources
- id (uuid, pk)
- user_id (uuid, fk)
- source_name (text)
- monthly_amount (numeric)
- updated_at (timestamptz)

## income_events
- id (uuid, pk)
- user_id (uuid, fk)
- source_id (uuid, fk)
- amount (numeric)
- occurred_at (timestamptz)

## audit_event_log
- id (uuid, pk)
- user_id (uuid, fk)
- trace_id (text)
- event_type (text)
- payload (jsonb)
- created_at (timestamptz)

## audit_decision_log
- id (uuid, pk)
- user_id (uuid, fk)
- trace_id (text)
- decision_type (text)
- decision (text)
- payload (jsonb)
- created_at (timestamptz)
