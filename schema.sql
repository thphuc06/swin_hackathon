-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.allocation_decision_log (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  trace_id text,
  tool_name text NOT NULL DEFAULT 'jar_allocation_suggest_v1'::text,
  decision_status text NOT NULL CHECK (decision_status = ANY (ARRAY['accepted'::text, 'modified'::text, 'rejected'::text, 'auto_applied'::text, 'ignored'::text])),
  monthly_income_reference numeric,
  recommendation_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  final_allocation_payload jsonb,
  execution_payload jsonb,
  note text,
  decided_at timestamp with time zone NOT NULL DEFAULT now(),
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT allocation_decision_log_pkey PRIMARY KEY (id),
  CONSTRAINT allocation_decision_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.anomaly_feedback_log (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  trace_id text,
  tool_name text NOT NULL DEFAULT 'anomaly_signals_v1'::text,
  anomaly_type text NOT NULL,
  detector_name text,
  entity_type text NOT NULL CHECK (entity_type = ANY (ARRAY['transaction'::text, 'merchant'::text, 'category'::text, 'daily_signal'::text, 'other'::text])),
  entity_id text NOT NULL,
  feedback_label text NOT NULL CHECK (feedback_label = ANY (ARRAY['confirmed'::text, 'false_positive'::text, 'expected'::text, 'ignored'::text])),
  feedback_source text NOT NULL DEFAULT 'user'::text CHECK (feedback_source = ANY (ARRAY['user'::text, 'analyst'::text, 'system'::text])),
  note text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  resolved_at timestamp with time zone,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT anomaly_feedback_log_pkey PRIMARY KEY (id),
  CONSTRAINT anomaly_feedback_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.balance_daily (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  balance_date date NOT NULL,
  scope_type text NOT NULL DEFAULT 'overall'::text CHECK (scope_type = ANY (ARRAY['overall'::text, 'jar'::text, 'account'::text])),
  scope_id uuid,
  currency text NOT NULL DEFAULT 'VND'::text,
  opening_balance numeric NOT NULL DEFAULT 0,
  inflow_total numeric NOT NULL DEFAULT 0,
  outflow_total numeric NOT NULL DEFAULT 0,
  closing_balance numeric NOT NULL DEFAULT 0,
  source text NOT NULL DEFAULT 'derived'::text CHECK (source = ANY (ARRAY['bank_feed'::text, 'ledger'::text, 'derived'::text, 'manual'::text])),
  quality_flag text NOT NULL DEFAULT 'unverified'::text CHECK (quality_flag = ANY (ARRAY['verified'::text, 'estimated'::text, 'unverified'::text, 'reconciled'::text])),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT balance_daily_pkey PRIMARY KEY (id),
  CONSTRAINT balance_daily_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.budgets (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  scope_type text NOT NULL,
  scope_id uuid,
  period text NOT NULL,
  limit_amount numeric NOT NULL,
  currency text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT budgets_pkey PRIMARY KEY (id),
  CONSTRAINT budgets_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.categories (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  parent_id uuid,
  name text NOT NULL,
  CONSTRAINT categories_pkey PRIMARY KEY (id),
  CONSTRAINT categories_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT categories_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.categories(id)
);
CREATE TABLE public.forecast_actuals_log (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  trace_id text,
  tool_name text NOT NULL DEFAULT 'cashflow_forecast_v1'::text,
  model_name text,
  horizon text NOT NULL,
  granularity text NOT NULL CHECK (granularity = ANY (ARRAY['daily'::text, 'weekly'::text, 'monthly'::text])),
  forecast_as_of timestamp with time zone NOT NULL,
  target_start date NOT NULL,
  target_end date NOT NULL,
  predicted_p10 numeric,
  predicted_p50 numeric,
  predicted_p90 numeric,
  actual_value numeric,
  actual_recorded_at timestamp with time zone,
  error_signed numeric,
  error_abs numeric,
  within_p80 boolean,
  within_p90 boolean,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT forecast_actuals_log_pkey PRIMARY KEY (id),
  CONSTRAINT forecast_actuals_log_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.goals (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  name text NOT NULL,
  target_amount numeric NOT NULL,
  horizon_months integer NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT goals_pkey PRIMARY KEY (id),
  CONSTRAINT goals_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.income_events (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  source_id uuid NOT NULL,
  amount numeric NOT NULL,
  occurred_at timestamp with time zone NOT NULL,
  CONSTRAINT income_events_pkey PRIMARY KEY (id),
  CONSTRAINT income_events_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT income_events_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.income_sources(id)
);
CREATE TABLE public.income_sources (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  source_name text NOT NULL,
  monthly_amount numeric NOT NULL,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT income_sources_pkey PRIMARY KEY (id),
  CONSTRAINT income_sources_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.jars (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  template_id uuid,
  name text NOT NULL,
  description text,
  keywords jsonb,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  target_pct numeric CHECK (target_pct IS NULL OR target_pct >= 0::numeric AND target_pct <= 100::numeric),
  allocated_amount numeric NOT NULL DEFAULT 0 CHECK (allocated_amount >= 0::numeric),
  used_amount numeric NOT NULL DEFAULT 0 CHECK (used_amount >= 0::numeric),
  remaining_amount numeric DEFAULT (allocated_amount - used_amount),
  CONSTRAINT jars_pkey PRIMARY KEY (id),
  CONSTRAINT jars_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.profiles (
  user_id uuid NOT NULL,
  display_name text,
  risk_profile_current text,
  locale text,
  updated_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT profiles_pkey PRIMARY KEY (user_id),
  CONSTRAINT profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id)
);
CREATE TABLE public.tier1_audit_anomalies (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  jar_id uuid NOT NULL,
  anomaly_type text NOT NULL CHECK (anomaly_type = ANY (ARRAY['upward_drift'::text, 'downward_drift'::text, 'other'::text])),
  cusum_value numeric,
  threshold numeric,
  transaction_id uuid,
  trace_id text NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT tier1_audit_anomalies_pkey PRIMARY KEY (id),
  CONSTRAINT tier1_audit_anomalies_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT tier1_audit_anomalies_jar_id_fkey FOREIGN KEY (jar_id) REFERENCES public.jars(id),
  CONSTRAINT tier1_audit_anomalies_transaction_id_fkey FOREIGN KEY (transaction_id) REFERENCES public.transactions(id)
);
CREATE TABLE public.tier1_baseline_stats (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  jar_id uuid NOT NULL,
  mean_daily_spend numeric NOT NULL,
  std_dev_daily_spend numeric NOT NULL,
  sample_size integer NOT NULL,
  period_start date NOT NULL,
  period_end date NOT NULL,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT tier1_baseline_stats_pkey PRIMARY KEY (id),
  CONSTRAINT tier1_baseline_stats_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT tier1_baseline_stats_jar_id_fkey FOREIGN KEY (jar_id) REFERENCES public.jars(id)
);
CREATE TABLE public.tier1_cusum_state (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  jar_id uuid NOT NULL,
  cumsum_pos numeric NOT NULL DEFAULT 0,
  cumsum_neg numeric NOT NULL DEFAULT 0,
  reference_mean numeric NOT NULL,
  reference_sigma numeric NOT NULL,
  k_parameter numeric DEFAULT 0.5,
  h_parameter numeric DEFAULT 5.0,
  drift_detected_up boolean DEFAULT false,
  drift_detected_down boolean DEFAULT false,
  last_updated_at timestamp with time zone DEFAULT now(),
  transaction_count integer DEFAULT 0,
  last_transaction_ts timestamp with time zone,
  CONSTRAINT tier1_cusum_state_pkey PRIMARY KEY (id),
  CONSTRAINT tier1_cusum_state_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT tier1_cusum_state_jar_id_fkey FOREIGN KEY (jar_id) REFERENCES public.jars(id)
);
CREATE TABLE public.tier1_notifications (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  jar_id uuid NOT NULL,
  anomaly_type text NOT NULL CHECK (anomaly_type = ANY (ARRAY['upward_drift'::text, 'downward_drift'::text, 'other'::text])),
  title text NOT NULL,
  detail text,
  channels jsonb DEFAULT '["push"]'::jsonb,
  severity text DEFAULT 'medium'::text CHECK (severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'critical'::text])),
  trace_id text,
  read_at timestamp with time zone,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT tier1_notifications_pkey PRIMARY KEY (id),
  CONSTRAINT tier1_notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT tier1_notifications_jar_id_fkey FOREIGN KEY (jar_id) REFERENCES public.jars(id)
);
CREATE TABLE public.transactions (
  id uuid NOT NULL,
  user_id uuid NOT NULL,
  jar_id uuid NOT NULL,
  category_id uuid NOT NULL,
  amount numeric NOT NULL,
  currency text NOT NULL,
  counterparty text NOT NULL,
  raw_narrative text,
  user_note text,
  channel text,
  occurred_at timestamp with time zone NOT NULL,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  direction text NOT NULL CHECK (direction = ANY (ARRAY['debit'::text, 'credit'::text])),
  affects_jar_balance boolean NOT NULL DEFAULT false,
  CONSTRAINT transactions_pkey PRIMARY KEY (id),
  CONSTRAINT transactions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id),
  CONSTRAINT transactions_jar_id_fkey FOREIGN KEY (jar_id) REFERENCES public.jars(id),
  CONSTRAINT transactions_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.categories(id)
);
CREATE TABLE public.users (
  id uuid NOT NULL,
  email text NOT NULL UNIQUE,
  created_at timestamp with time zone NOT NULL DEFAULT now(),
  CONSTRAINT users_pkey PRIMARY KEY (id)
);