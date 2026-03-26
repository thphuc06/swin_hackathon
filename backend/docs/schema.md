# Supabase Public REST Contract

This document reflects the current Supabase public REST schema used by the
production flow:

`frontend -> backend -> orchestrator -> gateway -> specialist -> planner -> database`

It replaces the earlier design-only MVP notes. If this document drifts from the
live project, regenerate it from the Supabase OpenAPI spec and update the repo.

## Identity Contract

- `users.id` is the canonical application user id.
- On the deployed path, `Cognito sub == backend user_id == orchestrator actor_id == specialist/planner user_id`.
- Runtime code must not remap a Cognito subject to a different data user through
  env or per-request overrides.

## Required Tables Exposed In Supabase REST

### `users`
- `id`
- `email`
- `created_at`

### `profiles`
- `user_id`
- `display_name`
- `risk_profile_current`
- `locale`
- `updated_at`

### `jars`
- `id`
- `user_id`
- `template_id`
- `name`
- `description`
- `keywords`
- `target_amount`
- `created_at`
- `updated_at`

### `categories`
- `id`
- `user_id`
- `parent_id`
- `name`

### `transactions`
- `id`
- `user_id`
- `jar_id`
- `category_id`
- `amount`
- `currency`
- `counterparty`
- `raw_narrative`
- `user_note`
- `channel`
- `occurred_at`
- `created_at`
- `direction`

### `budgets`
- `id`
- `user_id`
- `scope_type`
- `scope_id`
- `period`
- `limit_amount`
- `currency`
- `active`
- `created_at`
- `updated_at`

### `goals`
- `id`
- `user_id`
- `name`
- `target_amount`
- `horizon_months`
- `created_at`

### `income_sources`
- `id`
- `user_id`
- `source_name`
- `monthly_amount`
- `updated_at`

### `income_events`
- `id`
- `user_id`
- `source_id`
- `amount`
- `occurred_at`

### `balance_daily`
- `id`
- `user_id`
- `balance_date`
- `scope_type`
- `scope_id`
- `currency`
- `opening_balance`
- `inflow_total`
- `outflow_total`
- `closing_balance`
- `source`
- `quality_flag`
- `payload`
- `created_at`
- `updated_at`

### `forecast_actuals_log`
- `id`
- `user_id`
- `trace_id`
- `tool_name`
- `model_name`
- `horizon`
- `granularity`
- `forecast_as_of`
- `target_start`
- `target_end`
- `predicted_p10`
- `predicted_p50`
- `predicted_p90`
- `actual_value`
- `actual_recorded_at`
- `error_signed`
- `error_abs`
- `within_p80`
- `within_p90`
- `payload`
- `created_at`

### `anomaly_feedback_log`
- `id`
- `user_id`
- `trace_id`
- `tool_name`
- `anomaly_type`
- `detector_name`
- `entity_type`
- `entity_id`
- `feedback_label`
- `feedback_source`
- `note`
- `payload`
- `resolved_at`
- `created_at`

### `allocation_decision_log`
- `id`
- `user_id`
- `trace_id`
- `tool_name`
- `decision_status`
- `monthly_income_reference`
- `recommendation_payload`
- `final_allocation_payload`
- `execution_payload`
- `note`
- `decided_at`
- `created_at`

## Optional / Not Exposed In Current REST Schema

These tables are not currently exposed in the live Supabase public REST OpenAPI
schema. Runtime code must treat them as optional capabilities, not mandatory
dependencies.

### `audit_event_log`
- not exposed in current REST schema

### `audit_decision_log`
- not exposed in current REST schema

## Provisioning Notes

- Production runtime depends on real user-scoped data existing under the live
  `users.id` / `user_id`.
- Fixture/demo assets under [backend/seed](/C:/Users/Admin/Desktop/swin_hackathon/backend/seed)
  are not the source of truth for deployed users.
- For smoke users or Cognito-sub migration, use a provisioning/sync script to
  copy user-scoped data into the live target user id instead of reintroducing
  runtime identity remapping.
