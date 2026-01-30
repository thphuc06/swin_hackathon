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
- name (text)
- target_amount (numeric)
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
- counterparty (text)
- created_at (timestamptz)
- direction (text) -- debit/credit

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
