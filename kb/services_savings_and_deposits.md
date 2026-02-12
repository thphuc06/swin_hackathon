---
service_id: svc_savings_deposit
family: savings_deposit
requires_disclosure: true
disclosure_refs: disclaimers.md#education-only
---

# Banking Services - Savings And Deposits

## Scope
This document describes neutral, educational guidance for common savings services.
It is product-category guidance only, not product recommendation.

## Service Categories

### 1) Demand Deposit Account (Thanh toan)
- Purpose: daily cash management, salary receive, bill payment.
- Typical behavior:
- High liquidity, low return.
- Good for emergency cash and monthly spending.
- Advisory use:
- Suggest when user needs flexible cash access.

### 2) Term Deposit (Tiet kiem ky han)
- Purpose: preserve capital and earn fixed return for a defined term.
- Typical behavior:
- User commits amount for a tenor (for example 1m, 3m, 6m, 12m).
- Early withdrawal may reduce benefit.
- Advisory use:
- Suggest when user has stable surplus cash and clear time horizon.

### 3) Recurring Savings Plan
- Purpose: build discipline by saving monthly toward a goal.
- Typical behavior:
- User commits periodic contribution.
- Useful for home down payment, tuition, emergency fund.
- Advisory use:
- Suggest when cashflow is positive but user lacks saving discipline.

### 4) Goal-Based Savings Bucket
- Purpose: separate money by target (emergency, housing, education).
- Typical behavior:
- Multiple buckets with target amount and target date.
- Advisory use:
- Suggest when user has multiple goals and mixed priorities.

## Decision Hints For Advisor
- If runway < 3 months: prioritize liquidity and emergency buffer first.
- If monthly net cashflow > 0 and horizon >= 6 months: consider term/recurring savings category.
- If net cashflow is volatile: use conservative monthly contribution estimate.

## Data Needed Before Suggesting Category
- Net cashflow trend (30d/60d/90d).
- Emergency runway months.
- Goal amount and target date.
- Income stability signal.

## Compliance Notes
- Do not state exact rates unless retrieved from validated source.
- Do not compare specific bank products without current pricing data.
- Keep language educational and user-first.
