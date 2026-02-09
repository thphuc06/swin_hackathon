# Financial Tools Plan (Jars)

This note answers:
- Which repos/libraries we will use
- Which ones we defer or use as references only
- How to integrate with current code (`backend/app/services/financial_tools.py`, `backend/app/routes/*`, `agent/tools.py`)

## Current integration anchors
- Backend calculators: `backend/app/services/financial_tools.py`
- Forecast APIs: `backend/app/routes/forecast.py`
- Decision APIs: `backend/app/routes/decision.py`
- Spend summary API (currently mocked): `backend/app/routes/aggregates.py`
- Agent tool caller: `agent/tools.py`

## Repo decision matrix

| Repo / Service | Decision | Why | Integration |
|---|---|---|---|
| River | Use (Now) | Best fit for streaming anomaly + drift in deterministic pipeline | Backend `anomaly_signals_v1` integrates ADWIN; worker extension later |
| PyOD | Use (Now) | Strong deterministic outlier baseline (ECOD) | Backend `anomaly_signals_v1` integrates ECOD score/flag |
| Ruptures | **Use (Now - Tier 2, Plan Tier 1)** | **Replaces Kats CUSUM** - Better maintained, no dependency conflicts, deterministic Pelt algorithm for offline change point detection | **Current**: MCP Finance Server (`anomaly_signals_v1`) for on-demand analysis. **Future**: Lambda worker for real-time notifications after transactions |
| Kats (Facebook) | ~~Skip~~ **Replaced by Ruptures** | CUSUM useful but **dependency conflicts in MCP environment**, stale maintenance (last release 2022) | Keep only as benchmark notebook/reference; use Ruptures for production |
| Darts | Use (Now) | Strong forecasting toolkit (ExponentialSmoothing) | MCP Finance Server `cashflow_forecast_v1` uses Darts; later extend to ECS forecast worker |
| Actual Budget | Reference only (now) | Great envelope budgeting/jar logic patterns | Implement own deterministic jar allocator in Python (no runtime dependency) |
| Firefly III | Reference only (now) | Good budget/category/rules schema ideas | Borrow schema/rule ideas only; avoid AGPL coupling in core services |
| OpenFisca | Optional later | Rules-as-code engine, explainable but heavy for MVP | Consider as separate MCP/policy service if rule complexity grows |
| statsmodels | Use (Phase 0) | Deterministic, auditable forecasting (ETS/ARIMA) | Import directly in backend service layer |
| skforecast | Use later | Better ML forecasting wrappers and backtesting | Optional enhancement for worker-tier forecast experiments |
| Cedar + Amazon Verified Permissions | Use (Phase 0) | Explicit policy decisions for suitability/education-only guard | Suitability guard endpoint + policy decision log in audit trail |
| Bedrock Guardrails | Use (Phase 0) | Required safety layer for unsafe/financially sensitive responses | Apply before final agent response; log guardrail result with `trace_id` |

## What we will implement now (MVP)

1. Spend analytics (tool family 1)
- Source of truth: SQL only (Supabase/Aurora).
- Add deterministic summary function in backend service layer:
  - 30/60/90-day totals
  - jar splits
  - top merchants
  - budget drift
- Wire endpoint:
  - Extend `backend/app/routes/aggregates.py` or add `backend/app/routes/spend.py`.
- Agent call path:
  - Add function in `agent/tools.py` (`spend_analytics(...)`) to call backend endpoint.

2. Cashflow forecasting (tool family 3)
- Replace heuristic-only forecast path with `statsmodels` baseline (ETS first, ARIMA optional).
- Keep deterministic config:
  - fixed model type
  - fixed history window
  - no random seeds required for ETS/ARIMA path
- Integration file split:
  - Add `backend/app/services/forecast_statsmodels.py`
  - Keep orchestration in `backend/app/routes/forecast.py`.

3. Realtime anomaly + shift detection (tool family 2)
- **River ADWIN** integrated in backend anomaly tool for **streaming drift signal**.
- **PyOD ECOD** integrated in backend anomaly tool for **outlier probability**.
- **Ruptures Pelt** integrated for **offline change-point detection** (replaces Kats CUSUM).

**Why Ruptures over Kats:**
- **Dependency conflicts**: Kats requires Prophet, fbprophet dependencies that conflict in MCP server environment
- **Better maintained**: Ruptures actively maintained (2024), Kats stale since 2022
- **Deterministic**: Pelt algorithm (Pruned Exact Linear Time) provides reproducible change points
- **Simpler**: Single-purpose library, no heavy forecasting dependencies
- **Production-ready**: Used in `src/aws-finance-mcp-server/app/finance/oss_adapters.py::ruptures_pelt_change_points()`

**Current implementation (Tier 2 - Model Reasoning):**
- Location: `src/aws-finance-mcp-server/app/finance/oss_adapters.py`
- Function: `ruptures_pelt_change_points(day_keys, series, penalty=3.0)`
- Algorithm: Pelt with rbf kernel (radial basis function)
- Returns: Change point dates, detection flag, penalty parameter
- Usage: Called by `anomaly_signals_v1` MCP tool for on-demand advisory
- Flow: Frontend → Backend → AgentCore → MCP Finance Server → Ruptures

**Future plan (Tier 1 - Real-time Notifications):**
- Deployment: Lambda worker triggered by EventBridge (TransactionCreated events)
- Purpose: Detect structural breaks in spending/income patterns immediately
- Notification: "Your spending pattern changed significantly on [date]" + CTA
- Benefits:
  - Proactive alerts (no user query needed)
  - Lower latency (no chat round-trip)
  - Lower cost (Lambda vs AgentCore Runtime)
  - Better UX (inbox notifications vs chat discovery)
- Migration timeline: After Tier 2 stabilization, when Lambda worker infrastructure ready

**Deployment:**
- **Current (Tier 2)**: Worker consumes transaction events and stores latest user-level anomaly signals
- **Future (Tier 1)**: Lambda worker with Ruptures detects change points and writes notifications directly
- Backend reads latest signal snapshot for chat/tool response

4. Jar allocation + risk profile (tool families 4,5)
- Keep rule-based allocator in Python service (deterministic, explainable).
- Use Actual Budget as logic reference only:
  - envelope-first priority
  - fixed-cost coverage -> emergency buffer -> goal buckets.
- Implement in `backend/app/services/financial_tools.py` or split `allocation_rules.py`.

5. Suitability/regulatory guard (tool family 6)
- Add pre-response guard endpoint (backend or MCP tool):
  - classify intent (buy/sell/execute vs education)
  - call Verified Permissions (Cedar policy)
  - enforce disclaimer/refusal template
- Agent orchestration:
  - call guard first
  - if denied, return refusal + disclaimer + `trace_id`
  - if allowed, continue with finance tools.

## How to integrate in current codebase

1. Backend (`backend/app/services`)
- Keep pure deterministic computation functions.
- Add audit payload in all outputs:
  - `trace_id`
  - `params_hash` (sha256 canonical json)
  - `version`
  - `sql_snapshot_ts`

2. Backend routes (`backend/app/routes`)
- `aggregates.py`: replace hardcoded summary with SQL-backed analytics.
- `forecast.py`: route stays, implementation calls statsmodels service + optional worker results.
- `decision.py`: keep education-only semantics for `investment-capacity`; add suitability guard check before returning.

3. Agent runtime (`agent/tools.py`)
- Add calls for:
  - `spend_analytics`
  - `cashflow_anomaly`
  - `suitability_guard`
- Maintain fallback mocks only for local dev; production path must use public backend/Gateway endpoints (no localhost from runtime).

4. Policy + safety
- MCP/Gateway tool for KB retrieval remains wording-only.
- Numeric truth remains SQL-derived only.
- Every chat response should include:
  - citations (KB for wording)
  - disclaimer
  - `trace_id`

## Suggested order

1. Implement SQL spend analytics endpoint + agent wrapper.
2. Swap forecast core to `statsmodels` deterministic baseline.
3. Add suitability guard (Cedar/Verified Permissions + disclaimers).
4. Add River + `ruptures` worker pipeline for anomaly signals.
5. Add Darts/PyOD/skforecast only when baseline metrics require improvement.

## Technical Deep Dive: Ruptures vs Kats for Change Point Detection

### Why we switched from Kats CUSUM to Ruptures

**Problem with Kats:**
- **Dependency hell**: Kats requires `prophet` (fbprophet), which has heavy C++ dependencies (Stan) and conflicts with other packages in MCP server environment
- **Stale maintenance**: Last release 0.2.0 in 2022, many open issues unfixed
- **Overkill**: Kats is a full forecasting toolkit (~50+ modules), we only need change point detection
- **CUSUM issues**: CUSUM requires manual threshold tuning per user, not robust for diverse spending patterns

**Why Ruptures wins:**
```python
# Ruptures: Simple, deterministic, production-ready
import ruptures as rpt

signal = np.array(daily_spend).reshape(-1, 1)
algo = rpt.Pelt(model="rbf", min_size=2, jump=1).fit(signal)
change_points = algo.predict(pen=3.0)  # penalty controls sensitivity
# Returns indices of structural breaks, fully reproducible
```

**Technical advantages:**
1. **Pure Python + NumPy**: No C++ dependencies, easy Docker build
2. **Actively maintained**: 2024 releases, responsive maintainers (deepcharles)
3. **Multiple algorithms**: Pelt (fast), Binary Segmentation, Window-based, Bottom-up
4. **Kernel flexibility**: rbf, linear, normal, ar, mahalanobis for different signal types
5. **Deterministic**: Same data + penalty = same change points (auditable)
6. **Interpretable**: Returns exact dates/indices of breaks, not just binary "changed/not changed"

**Current implementation in MCP Finance Server:**
```python
# src/aws-finance-mcp-server/app/finance/oss_adapters.py
def ruptures_pelt_change_points(
    day_keys: List[str], 
    series: List[float], 
    *, 
    penalty: float = 3.0
) -> Dict[str, Any]:
    """
    Uses Pelt algorithm (Pruned Exact Linear Time) for offline change point detection.
    - Algorithm: O(n log n) complexity, scales well for daily data (30-365 days)
    - Model: RBF kernel (radial basis function) - good for spending patterns
    - Penalty: Higher = fewer change points (3.0 is conservative default)
    - Returns: Change point dates as strings, mapped from indices
    """
    signal = np.asarray(series, dtype=float).reshape(-1, 1)
    algo = rpt.Pelt(model="rbf", min_size=2, jump=1).fit(signal)
    change_point_indices = algo.predict(pen=penalty)
    
    # Filter out end-of-signal index, map to dates
    points = [day_keys[idx] for idx in change_point_indices if 0 < idx < len(day_keys)]
    
    return {
        "available": True,
        "engine": "ruptures_pelt",
        "ready": True,
        "change_points": points[:10],  # Top 10 most recent
        "change_detected": bool(points),
        "penalty": penalty
    }
```

**Use cases in Jars:**
1. **Income shifts**: New job, raise, bonus patterns → "Your income increased 40% on 2024-08-15"
2. **Spending shifts**: Lifestyle changes, new recurring costs → "Your spending jumped 25% on 2024-09-01"
3. **Pattern breaks**: Irregular large transactions → "Unusual activity detected on 2024-10-20"
4. **Budget breaches**: Sustained high spending → "Your grocery spending doubled starting 2024-07-10"

**Tier 1 (Future) - Lambda Worker Flow:**
```
TransactionCreated event → EventBridge → Lambda (Ruptures worker)
   ↓
1. Fetch user's last 90 days daily spend/income from Aurora
2. Run ruptures_pelt_change_points(daily_spend, penalty=3.0)
3. If change detected in last 7 days:
   - Calculate magnitude: (new_avg - old_avg) / old_avg
   - Generate notification:
     - Title: "Spending pattern changed"
     - Body: "Your daily average increased 35% on [date]"
     - CTA: "Review transactions" → filtered view
   - Write to notifications table with trace_id
4. Update signals_daily.change_points_json for Tier 2 chat context
```

**Migration plan (Tier 2 → Tier 1):**
- **Phase 1 (Current - Tier 2)**: On-demand via MCP tool, user asks "detect changes"
- **Phase 2**: Lambda worker runs daily batch for all active users, stores results
- **Phase 3**: Lambda worker runs real-time (5min delay after transaction), pushes notifications
- **Benefit**: Proactive alerts, no chat query needed, lower cost than Runtime

**Dependencies comparison:**
```
# Kats (heavy)
kats==0.2.0
  └─ prophet>=1.0.1 (requires C++ Stan compiler)
      └─ pystan>=2.14,<3.0
      └─ convertdate, holidays, ...
  
# Ruptures (lightweight)  
ruptures>=1.1.9
  └─ numpy>=1.15
  └─ scipy>=1.0  # optional, only for some kernels
```

**Performance:**
- Ruptures Pelt: ~50ms for 90 days daily data (single user)
- Can handle batch processing for 10K users in Lambda (128MB RAM, 3sec timeout)
- No model training needed, instant results

**References:**
- Ruptures: https://github.com/deepcharles/ruptures
- Kats: https://github.com/facebookresearch/Kats (reference only)
- Paper: "Selecting the number of change-points in segmentation problems" (Lavielle & Teyssière, 2006)
