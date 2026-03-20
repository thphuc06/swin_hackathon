# Service Agent Implementation Blueprint

## Executive Summary

The best implementation approach for this repo is to add **Service Agent as the third specialist** in the existing specialist-first runtime:

```text
frontend -> backend -> orchestrator -> gateway -> specialist MCP -> service agent
```

This is the strongest approach because it is:

- architecturally aligned with the production path already running in the repo
- product-correct with the Service Agent vision in [SERVICE_AGENT_DESIGN.md](/C:/Users/Admin/Desktop/swin_hackathon/SERVICE_AGENT_DESIGN.md)
- implementation-realistic for a hackathon team
- demo-friendly because it creates a visually rich, roadmap-first output rather than another chat-only advisory reply

The Service Agent should be implemented as a dedicated roadmap specialist, not as a second Planner Agent and not as a generic service recommender. Its MVP must stay narrow and sharp:

> **Personalized Financial Roadmap Generator**

The implementation should reuse:

- the current request envelope pattern
- the current specialist MCP pattern
- the current JSON Schema + Pydantic validation style
- the current orchestrator specialist catalog and delegation model
- the current backend `/chat/stream` and frontend chat integration

The core logic should be deterministic and rule-based, with optional LLM assistance only for explanation polish. The roadmap contract, phase logic, milestones, projections, and maturity flow should not depend on free-form model reasoning.

This gives the team a build path that feels modern, grounded, and impressive to judges:

- Planner explains the user's finances.
- Service Agent designs the user's path forward.
- Frontend turns that roadmap into a visual experience.

That is a much stronger hackathon story than "another finance chatbot."

## Current Repo Fit Analysis

### Production Architecture Already In Place

The repo already has one clear production flow:

```text
frontend -> backend -> orchestrator -> gateway -> specialist MCP -> planner -> database
```

Relevant source-of-truth paths:

- [README.md](/C:/Users/Admin/Desktop/swin_hackathon/README.md)
- [backend/app/routes/chat.py](/C:/Users/Admin/Desktop/swin_hackathon/backend/app/routes/chat.py)
- [agent/main.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/main.py)
- [agent/strands_orchestrator/](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator)
- [src/aws-specialist-agent-mcp-server/app/mcp.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/app/mcp.py)

### What Planner Already Does

Planner is already a strong in-process finance specialist:

- reads finance data from Supabase
- calls finance-core tools
- computes spend, cashflow, forecast, recurring patterns, anomaly, risk, goal feasibility, and allocations
- emits:
  - `result`
  - `summary`
  - `warnings`
  - `standardized_contract`

Key files:

- [planner_agent/agent.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/planner_agent/agent.py)
- [planner_agent/contracts.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/planner_agent/contracts.py)
- [planner_agent/reporting.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/planner_agent/reporting.py)

This is exactly the right upstream source for Service Agent.

### What Stock Already Does

Stock is already a separate domain specialist:

- different capability boundary
- different response schema
- different external dependency pattern

Key file:

- [stock/adapter.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/stock/adapter.py)

That separation is a useful template: Service Agent should be added as a parallel specialist, not folded into Planner or Stock.

### What Orchestrator Already Does

The orchestrator already has the right structural responsibilities:

- intent routing
- specialist selection
- specialist payload building
- gateway invocation
- final response shaping

Key files:

- [agent/strands_orchestrator/specialist.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator/specialist.py)
- [agent/strands_orchestrator/nodes/delegation_node.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator/nodes/delegation_node.py)
- [agent/strands_orchestrator/nodes/tool_invocation_node.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator/nodes/tool_invocation_node.py)
- [agent/strands_orchestrator/specialist_response.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator/specialist_response.py)

Important current reality:

- the live specialist path is effectively single-specialist per turn
- Service Agent implementation must respect this, especially for MVP routing

### What Backend And Frontend Already Do

Backend:

- `/chat/stream` is already the thin streaming entrypoint
- it forwards prompts to the orchestrator runtime
- it emits SSE text and selected metadata

Frontend:

- Next.js 14 + React 18 + Tailwind
- current chat page renders markdown text from SSE
- current client parses metadata like `Trace`, `Tools`, `ResponseMode`

Key files:

- [frontend/package.json](/C:/Users/Admin/Desktop/swin_hackathon/frontend/package.json)
- [frontend/app/chat/page.tsx](/C:/Users/Admin/Desktop/swin_hackathon/frontend/app/chat/page.tsx)

Important current reality:

- frontend does not yet render structured roadmap UI
- backend SSE currently favors user-facing text, not structured roadmap payloads

### What Already Exists That Service Agent Can Reuse

The repo already has service-related logic worth reusing conceptually:

- [agent/service_catalog.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/service_catalog.py)
- [agent/service_signals.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/service_signals.py)
- [agent/service_semantic.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/service_semantic.py)

These files are not yet a Service Agent, but they provide strong clues:

- service metadata pattern
- signal extraction pattern
- semantic ranking fallback pattern

The implementation blueprint should reuse their ideas and metadata shape rather than inventing a disconnected service system.

## Implementation Principles

### 1. No Outer Flow Change

Do not change the outer architecture.

The implementation must remain:

```text
frontend -> backend -> orchestrator -> gateway -> specialist MCP
```

Service Agent is added as a new specialist inside the existing runtime model.

### 2. Planner-Derived State First

Service Agent should consume planner-derived financial state whenever available.

This includes fields such as:

- income stability
- savings capacity
- liquidity pressure
- runway
- anomaly state
- planning readiness
- feasibility signals
- risk band

Service Agent should not re-run raw transaction analytics as its main strategy.

### 3. Structured Output Is The Product Surface

Service Agent output must be a structured roadmap contract.

The roadmap contract is the source of truth for:

- orchestrator pass-through
- frontend rendering
- QA fixtures
- demo payloads
- future API interoperability

### 4. Orchestrator Pass-Through For Service Output

For Planner:

- orchestrator may synthesize and humanize analytical output

For Service Agent:

- orchestrator should validate and forward the roadmap contract
- orchestrator should only add minimal user-facing framing when needed
- orchestrator should not paraphrase the contract into lossy prose

### 5. Frontend Renders Roadmap Directly

The frontend should render:

- timeline
- phase cards
- milestone cards
- projected progress
- maturity states
- next-best-action panel

directly from the Service Agent contract.

### 6. No Prose-As-Contract

Human-readable text is helpful, but it is not the contract.

The contract must stay structured, typed, and validation-friendly.

### 7. Deterministic Core, Optional LLM Explanation

The roadmap engine should be deterministic for:

- phase selection
- milestone rules
- projection math
- maturity transitions
- insufficiency handling

LLM use is optional and should only improve:

- explanation phrasing
- short user-friendly summaries
- phase descriptions

LLM should not decide the core roadmap structure in MVP.

### 8. Minimal Schema Change

Do not build a heavy profile database.

Use:

- existing goals storage pattern
- existing risk profile route
- planner-derived state
- lightweight optional fields only where roadmap quality really depends on them

### 9. Demo-First But Production-Shaped

The implementation should be:

- stable enough to demo repeatedly
- visually rich enough to impress judges
- small enough to finish
- structured enough to evolve after the hackathon

## Recommended Tech Stack

### Stack Summary

| Layer | Recommended choice | Reuse or add | Why it fits this repo |
|---|---|---|---|
| Language | Python 3.11+ | Reuse | Matches backend, agent, specialist runtime |
| Specialist runtime | FastAPI + existing MCP app | Reuse | Already powers planner and stock |
| Validation | Pydantic v2 + JSON Schema Draft 2020-12 | Reuse | Current schema pattern already uses both |
| Orchestrator runtime | Existing Strands/AgentCore runtime | Reuse | Current live path already stable |
| Config | env vars + existing config modules | Reuse | Matches repo config style |
| DB access | Existing Supabase REST client / planner-derived state | Reuse | Avoids new DB layer |
| HTTP client | `requests` | Reuse | Already used in backend/specialist |
| LLM SDK | `strands-agents` + BedrockModel only for optional explanation | Reuse selectively | Keeps consistency without making roadmap logic model-dependent |
| Logging | Python `logging` + existing trace helpers | Reuse | Aligns with current observability |
| Testing | `unittest` + `jsonschema` + fixture/golden files | Reuse | Matches repo test style |
| Frontend | Next.js 14 + React 18 + TypeScript | Reuse | Already the app stack |
| Styling | Tailwind CSS | Reuse | Already present and fast for hackathon UI |
| Markdown fallback | `react-markdown` + `remark-gfm` | Reuse | Already in frontend |
| Charting | `recharts` | Add | Fastest path to polished roadmap/projection charts |
| Client validation | `zod` | Add | Clean browser-side validation for service contract payloads |
| Deploy/runtime | Existing AWS AgentCore Runtime + Gateway + Specialist MCP | Reuse | No architectural drift |

### Why These Choices Are Better Than Alternatives Here

#### Python + FastAPI + Pydantic

This repo already uses these patterns in:

- backend
- specialist MCP
- planner contracts

Introducing a second runtime stack would slow the team down and weaken maintainability.

#### JSON Schema + Pydantic Dual Validation

The current repo already validates:

- specialist input schemas
- specialist output schemas
- runtime envelopes

Service Agent should follow the same pattern because it improves:

- contract safety
- backend/orchestrator alignment
- frontend fixture generation
- demo repeatability

#### Rule Engine Over Heavy Model Dependence

For roadmap generation, rule-based logic is the right choice for MVP because it is:

- testable
- explainable
- stable under demo pressure
- less likely to hallucinate

Using an LLM as the primary roadmap engine would be riskier and harder to QA.

#### Recharts For Visualization

For hackathon speed and polish, `recharts` is a strong choice because it:

- integrates easily with React
- is fast to wire
- looks clean enough for judge demos
- handles line/bar/area compositions well

`visx` is more flexible but slower to assemble under time pressure.

#### Zod For Frontend Contract Safety

The frontend currently has no typed roadmap contract parser. Adding `zod` is worth it because it:

- protects the UI from malformed payloads
- helps development move faster
- supports mock/demo fixture validation

It is a small addition with strong payoff.

## Proposed Implementation Architecture

### External System Flow

#### MVP Runtime Flow

```text
User
-> Frontend chat UI
-> Backend /chat/stream
-> Orchestrator runtime
-> Gateway
-> Specialist MCP runtime
   -> Service Agent
-> Orchestrator pass-through / minimal synthesis
-> Backend stream + structured payload forwarding
-> Frontend roadmap rendering
```

#### Cross-Specialist Product Positioning

```text
Planner Agent
-> understands the user's financial state

Service Agent
-> designs the personalized roadmap

Stock Agent
-> provides investment/market specialist context when explicitly relevant
```

### Internal Service Agent Architecture

```text
Service Agent input envelope
-> request normalization
-> planner state mapper
-> sufficiency checker
-> journey pattern selector
-> phase selector
-> service selection by phase
-> milestone engine
-> projection engine
-> maturity engine
-> visualization mapper
-> explanation layer
-> service roadmap result envelope
```

### Layer Separation

#### Deterministic Layer

- planner state mapping
- insufficiency checks
- feasibility labels
- phase selection
- milestone rules
- projection math
- maturity transitions
- service eligibility

#### Reasoning Layer

- optional explanation polish
- short human summary
- phase narration
- CTA phrasing

#### Visualization / Output Layer

- timeline nodes
- milestone cards
- projection series
- progress panels
- next-best-action cards

## Internal Module Design

### Recommended Specialist-Side Module Layout

This structure stays close to the repo's current specialist style:

```text
src/aws-specialist-agent-mcp-server/
  service_agent/
    __init__.py
    agent.py
    contracts.py
    planner_state_mapper.py
    sufficiency.py
    roadmap_engine.py
    phase_selector.py
    service_selector.py
    milestone_engine.py
    projection_engine.py
    maturity_engine.py
    visualization.py
    explainability.py
    catalog.py
    constants.py
```

### Module Responsibilities

| Module | Responsibility |
|---|---|
| `agent.py` | Entrypoint for `run_service_agent_v1`; validates request and returns result envelope |
| `contracts.py` | Pydantic models for service input/output and roadmap contract |
| `planner_state_mapper.py` | Converts planner-derived state into normalized roadmap input |
| `sufficiency.py` | Detects missing data, partial-data mode, and fallback states |
| `roadmap_engine.py` | Main orchestrator of roadmap construction |
| `phase_selector.py` | Determines phase sequence and current phase |
| `service_selector.py` | Chooses services per phase based on goal + signals |
| `milestone_engine.py` | Defines milestone thresholds and unlock conditions |
| `projection_engine.py` | Generates projected outcomes and timeline checkpoints |
| `maturity_engine.py` | Handles maturity events and post-maturity transitions |
| `visualization.py` | Maps roadmap contract into frontend-ready visualization payload |
| `explainability.py` | Produces concise human-readable explanation from structured contract |
| `catalog.py` | Local service metadata and grouping rules for MVP |
| `constants.py` | Journey types, labels, thresholds, enums |

### Supporting Repo Touchpoints

These are the repo paths the implementation should connect to:

- [src/aws-specialist-agent-mcp-server/app/mcp.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/app/mcp.py)
- [src/aws-specialist-agent-mcp-server/schemas/](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/schemas)
- [agent/subagents/agent_catalog.v1.json](/C:/Users/Admin/Desktop/swin_hackathon/agent/subagents/agent_catalog.v1.json)
- [agent/subagents/schemas/](/C:/Users/Admin/Desktop/swin_hackathon/agent/subagents/schemas)
- [agent/strands_orchestrator/specialist.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator/specialist.py)
- [agent/strands_orchestrator/specialist_response.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator/specialist_response.py)
- [backend/app/routes/chat.py](/C:/Users/Admin/Desktop/swin_hackathon/backend/app/routes/chat.py)
- [frontend/app/chat/page.tsx](/C:/Users/Admin/Desktop/swin_hackathon/frontend/app/chat/page.tsx)

## Contracts And Schemas

### Contract Strategy

Follow the same pattern used by Planner and Stock:

- request envelope with `actor`, `correlation`, `request`, `routing`
- JSON Schema files for MCP validation
- Pydantic models for specialist-side implementation
- orchestrator-side schema mirror under `agent/subagents/schemas`

### Proposed Input Contract

Service Agent should reuse the current envelope shape and specialize its content.

#### Input Pseudo-JSON

```json
{
  "schema_version": "v1",
  "actor": {
    "actor_id": "usr_123",
    "user_id": "usr_123",
    "tenant_id": "tenant_a",
    "scopes": ["chat:invoke", "finance:read"]
  },
  "correlation": {
    "session_id": "chat_abc",
    "request_id": "req_abc",
    "trace_id": "trc_xyz",
    "parent_request_id": "req_root",
    "request_timestamp": "2026-03-21T10:00:00Z"
  },
  "request": {
    "prompt": "Help me build a plan to buy a car in 18 months",
    "intent": "service",
    "policy_flags": {
      "education_only": true
    },
    "user_context": {
      "planner_state": {
        "financial_stability": "watch",
        "planning_readiness": "cautious",
        "net_cashflow": 4200000,
        "baseline_monthly_income": 18500000,
        "savings_capacity_monthly": 3500000,
        "runway_months": 4.5,
        "liquidity_pressure": "moderate",
        "income_stability": "medium",
        "risk_band": "moderate",
        "anomaly_state": "stable"
      },
      "risk_profile": {
        "profile": "balanced"
      },
      "life_context": {
        "employment_type": "salaried",
        "dependents": 0,
        "household_context": "single"
      }
    },
    "goals": [
      {
        "goal_type": "buy_car",
        "name": "Buy a car",
        "target_amount": 180000000,
        "target_timeline_months": 18,
        "priority": "high"
      }
    ],
    "session_summary": "User previously reviewed 6-month spending and wants a concrete action path."
  },
  "routing": {
    "specialist_id": "service",
    "tool_name": "run_service_agent_v1"
  }
}
```

### Proposed Output Contract

The output should mirror the planner envelope style while introducing a service-specific contract.

#### Output Pseudo-JSON

```json
{
  "schema_version": "v1",
  "agent_id": "service",
  "agent_version": "0.1.0",
  "tool_name": "run_service_agent_v1",
  "status": "ok",
  "correlation": {
    "session_id": "chat_abc",
    "request_id": "req_abc",
    "trace_id": "trc_xyz",
    "parent_request_id": "req_root",
    "request_timestamp": "2026-03-21T10:00:00Z"
  },
  "summary": "A balanced 18-month roadmap is feasible if monthly savings discipline improves slightly.",
  "contract": {
    "contract_spec_version": "service_roadmap_contract_v1",
    "journey_type": "goal_roadmap",
    "goal": {},
    "roadmap": {},
    "visualization": {},
    "human_readable": {}
  },
  "warnings": [],
  "errors": []
}
```

### Roadmap Schema

```json
{
  "roadmap_id": "roadmap_buy_car_18m",
  "journey_pattern": "stabilize_then_accumulate",
  "current_phase_id": "phase_accumulate",
  "feasibility_label": "cautious_but_feasible",
  "phases": [],
  "milestones": [],
  "projected_outcomes": [],
  "maturity_events": [],
  "next_best_action": {},
  "service_recommendations": []
}
```

### Phase Schema

```json
{
  "phase_id": "phase_accumulate",
  "phase_type": "accumulate",
  "sequence": 2,
  "title": "Build the car fund steadily",
  "objective": "Accumulate the planned down payment while protecting liquidity",
  "entry_conditions": ["runway_months >= 3"],
  "exit_conditions": ["goal_progress_ratio >= 0.7"],
  "target_window_months": 8,
  "recommended_actions": [],
  "recommended_services": [],
  "expected_result": "Target savings reach the readiness zone",
  "status": "current"
}
```

### Milestone Schema

```json
{
  "milestone_id": "ms_50pct_goal",
  "title": "Reach 50% of target fund",
  "type": "progress_threshold",
  "target_amount": 90000000,
  "target_date": "2027-01-01",
  "unlocks": ["phase_readiness_review"],
  "status": "pending"
}
```

### Projection Schema

```json
{
  "series_id": "goal_balance_projection",
  "granularity": "monthly",
  "points": [
    { "label": "M1", "projected_amount": 12000000 },
    { "label": "M6", "projected_amount": 68000000 },
    { "label": "M12", "projected_amount": 121000000 }
  ],
  "assumption_summary": "Projection uses planner-derived monthly savings capacity with conservative buffer protection.",
  "confidence_label": "directional"
}
```

### Maturity Event Schema

```json
{
  "event_id": "maturity_goal_reached",
  "event_type": "goal_reached",
  "trigger": "projected_amount >= target_amount",
  "decision_points": [
    "proceed_with_goal",
    "delay_and_hold_cash",
    "reallocate_to_next_goal"
  ],
  "recommended_next_step": "Run readiness review before purchase execution"
}
```

### Service Recommendation Schema

```json
{
  "service_id": "auto_save_activation",
  "title": "Activate auto-save",
  "group": "savings_accumulation",
  "phase_id": "phase_accumulate",
  "priority": "high",
  "required": true,
  "why_it_fits": "Supports consistent monthly accumulation toward the car goal",
  "expected_outcome": "Less manual friction and better milestone reliability"
}
```

### Visualization Payload Schema

```json
{
  "timeline_nodes": [],
  "phase_cards": [],
  "milestones": [],
  "projection_series": [],
  "goal_progress": {},
  "state_comparison": {},
  "maturity_markers": [],
  "next_best_action_card": {}
}
```

### Frontend Rendering Payload Schema

This payload should be nested inside the service contract, not invented separately.

```json
{
  "render_version": "v1",
  "primary_goal_card": {},
  "timeline_nodes": [],
  "phase_cards": [],
  "milestone_cards": [],
  "projection_chart": {},
  "next_action": {},
  "empty_state": null,
  "insufficient_data_state": null
}
```

## Data Model And Storage Plan

### What Should Come From DB

The DB should continue holding durable facts:

- goals
- risk profile
- notification/audit support
- finance transactions and balances through planner path

### What Should Usually Come From Planner-Derived State

Do not overbuild DB columns for transient analytical state.

The following should usually come from Planner output:

- income stability
- savings capacity
- liquidity pressure
- runway
- anomaly state
- planning readiness
- forecast caution
- feasibility hints
- current cashflow status

### Minimum Goal Schema

Current backend goal route is very light:

- `name`
- `target_amount`
- `horizon_months`

For Service Agent roadmap quality, the minimum goal schema should become:

| Field | Required | Why |
|---|---|---|
| `goal_type` | Yes | Needed for journey pattern selection |
| `name` | Yes | User-facing title |
| `target_amount` | Yes | Needed for milestone and projection logic |
| `target_date` or `target_timeline_months` | Yes | Needed for roadmap timing |
| `priority` | Yes | Needed when multiple goals exist |
| `status` | Optional | Useful for UI and maturity handling |
| `achieved_at` | Optional | Useful for post-maturity logic |

### Personal Profile Storage Principle

Current personal profile support is still thin.

That is acceptable.

For MVP:

- keep profile storage minimal
- reuse risk profile
- derive the rest from Planner
- accept additional user context transiently in the request/session rather than over-modeling it in DB

### What Should Not Be Persisted Aggressively In MVP

- every roadmap phase transition
- temporary feasibility labels
- every projection revision
- UI-only visualization state
- LLM explanation text

Persisting these too early would overbuild the system.

## Roadmap Engine Implementation Strategy

### Design Goal

Build a roadmap engine that is:

- stable
- easy to test
- grounded in planner state
- expressive enough to wow judges
- not fragile under prompt variation

### Step 1. Normalize Inputs

Normalize:

- goal type
- target amount
- target timeline
- planner-derived state
- risk profile
- life context

Produce a single internal `RoadmapContext`.

### Step 2. Run Sufficiency Check

Before any roadmap generation, detect:

- missing goal amount
- missing goal timing
- missing savings/cashflow estimate
- missing planner-derived state

Possible labels:

- `ready`
- `partial_but_usable`
- `insufficient_goal_data`
- `insufficient_financial_state`

If insufficient, the agent should still return a valid contract with:

- `status = partial`
- `insufficient_data = true`
- `missing_fields`
- a reduced roadmap or setup-only path

### Step 3. Select Journey Pattern

Map the normalized context to a small set of journey patterns.

Recommended MVP patterns:

- `stabilize_then_accumulate`
- `protect_then_accumulate`
- `steady_accumulation`
- `goal_readiness_then_execute`
- `maturity_and_transition`

This should be rule-based.

Example:

- low runway + negative cashflow -> `stabilize_then_accumulate`
- stable positive cashflow + medium timeline -> `steady_accumulation`
- goal nearly funded -> `goal_readiness_then_execute`

### Step 4. Select Phases

Choose phases based on:

- journey pattern
- risk profile
- timeline pressure
- liquidity need
- feasibility label

Recommended common phase types:

- `stabilize`
- `protect_liquidity`
- `accumulate`
- `readiness_review`
- `maturity_transition`

### Step 5. Build Milestones

Milestones should be concrete and user-meaningful:

- first buffer target reached
- 25% goal funded
- 50% goal funded
- readiness threshold reached
- goal matured

Milestones should include:

- amount or condition
- target timing
- unlock effect
- status

### Step 6. Generate Projections

Projection logic should use:

- planner-derived monthly savings capacity
- conservative safety haircut when readiness is weak
- timeline-based checkpoints

Projection output should be labeled as:

- `directional`
- `moderately_grounded`
- `grounded`

depending on input quality.

### Step 7. Select Next Best Action

The next best action should be:

- immediate
- singular
- high leverage
- tied to current phase

Examples:

- activate auto-save
- cut online shopping category by target amount
- review milestone after next salary cycle
- create emergency fund bucket first

### Step 8. Add Maturity And Post-Maturity Logic

Roadmap does not end when target is reached.

The engine should define:

- what maturity means
- what decision happens then
- where funds go next
- whether rollover, withdrawal, or reallocation is recommended

### Step 9. Optional Explanation Layer

If an LLM explanation layer is used, it should consume the finished contract and produce:

- short summary
- per-phase plain-language explanation
- brief "why this fits" note

It should never change:

- numbers
- phases
- milestones
- projections
- decision states

## Service Catalog Implementation Strategy

### MVP Catalog Shape

For MVP, the catalog should be a checked-in metadata catalog, not a product database.

This is enough for:

- phase-linked service recommendation
- judge-facing clarity
- stable demo behavior

### Recommended Service Groups

| Group | Purpose |
|---|---|
| Foundational / Stabilization | Reduce chaos and establish control |
| Protection / Liquidity | Protect emergency liquidity and buffer health |
| Savings / Accumulation | Build toward target outcome |
| Monitoring / Control | Detect drift and keep the plan on track |
| Goal Progression | Support phase transitions and readiness |
| Milestone / Review | Trigger reviews and decisions at key points |
| Maturity / Transition | Handle post-maturity decisions |

### Metadata Per Service

Each service entry should have:

- `service_id`
- `title`
- `group`
- `summary`
- `eligible_phase_types`
- `goal_types`
- `required_signals`
- `blocked_signals`
- `priority`
- `required_vs_optional`
- `user_facing_reason`
- `expected_outcome`
- `cta_label`

### Example MVP Services

- `emergency_fund_setup`
- `auto_save_activation`
- `goal_bucket_allocation`
- `spending_alert_activation`
- `anomaly_monitoring`
- `recurring_bill_cleanup`
- `liquidity_guardrail`
- `milestone_review`
- `readiness_check`
- `maturity_rollover`
- `next_goal_transition`

### Implementation Strategy

Best practical approach:

1. Start with a small static service catalog under the specialist runtime.
2. Reuse naming and grouping ideas from:
   - [agent/service_catalog.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/service_catalog.py)
   - [agent/service_signals.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/service_signals.py)
3. Keep catalog logic deterministic and local for MVP.
4. Do not build a dynamic product database yet.

## LLM Usage Strategy

### Core Rule

The LLM is not the source of truth for the roadmap.

The deterministic layer must decide:

- journey pattern
- phases
- milestones
- projections
- maturity states
- next best action
- insufficiency labels

The LLM may only improve wording and explanation after the contract is already finalized.

### Reuse The Existing Model Pattern

The repo already has a clear model/provider pattern:

- `strands-agents`
- `BedrockModel`
- env-driven model selection
- deterministic fallback when models are disabled or inappropriate

Relevant reference:

- [planner_agent/agent.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/planner_agent/agent.py)

For Service explainability, the implementation should reuse the same general pattern:

- same Bedrock region and runtime assumptions
- same optional-model behavior
- same "deterministic first, model optional" discipline

Best MVP recommendation:

- default demo mode should work with **no model call required**
- model-assisted explanation can be enabled only as a polish layer

### Recommended LLM Role In Service Agent

The model should only help with:

- roadmap summary wording
- "why this roadmap fits" explanation
- "why this is the next best action" explanation
- milestone explanation
- maturity explanation
- insufficient-data explanation copy

The model should not be allowed to create or edit:

- numeric projections
- phase order
- milestone thresholds
- service eligibility
- feasibility labels
- warning states

### Prompt Layer Placement

Prompt templates should live close to the Service Agent, not in the orchestrator.

Recommended path:

```text
src/aws-specialist-agent-mcp-server/
  service_agent/
    prompts.py
    explainability.py
```

Recommended prompt groups:

- `roadmap_summary_prompt`
- `roadmap_fit_explanation_prompt`
- `next_best_action_explanation_prompt`
- `insufficient_data_explanation_prompt`
- `maturity_explanation_prompt`

This keeps:

- prompts near the contract they describe
- specialist ownership clean
- orchestrator free from service-domain prose logic

### Prompting And Guardrails

Recommended prompt strategy:

1. pass the finalized deterministic roadmap contract into the explainability layer
2. instruct the model to explain, not decide
3. request short, bounded text fragments only
4. reject outputs that try to introduce new facts or unsupported recommendations

For MVP, the safest output format is not a free-form paragraph blob and not a second full JSON contract.

Best practical choice:

- small text fragments or a tiny explanation object
- fields such as:
  - `summary_text`
  - `why_fit_text`
  - `next_action_reason_text`
  - `caution_text`

If the model response fails validation or is empty:

- discard it
- keep deterministic text fallback
- never block roadmap generation

### Deterministic vs LLM-Assisted Matrix

| Field type | Owner |
|---|---|
| `goal`, `phases`, `milestones`, `projected_outcomes`, `maturity_events` | Deterministic only |
| `next_best_action.action` | Deterministic only |
| `feasibility_label`, `confidence_label`, `missing_fields` | Deterministic only |
| `summary_text`, `why_fit_text`, `milestone_meaning_text` | LLM-assisted allowed |
| `warnings`, `caution labels`, `insufficient_data status` | Deterministic only |
| `service display copy` | LLM-assisted optional, deterministic fallback required |

### When Not To Call The Model

Do not call the model when:

- the deterministic response is already sufficient
- planner state is too incomplete
- the result is in `insufficient_data` mode
- latency budget is tight
- demo mode prioritizes stability
- the model path is disabled or unavailable

In other words:

- no model for unstable or low-signal cases
- no model if it adds risk without meaningful UX gain

### Explainability Architecture

The explainability layer should run last:

```text
deterministic roadmap contract
-> optional explainability layer
-> final service contract with explanation fragments
```

The explainability layer may describe:

- why this roadmap fits
- why the current phase matters
- why this is the next best action
- what the next milestone means
- what maturity means in plain language

The explainability layer must never mutate:

- roadmap facts
- roadmap numbers
- roadmap states
- contract structure

### Hackathon Guidance

For hackathon MVP, the strongest default is:

- build the whole roadmap flow so it is excellent without LLM
- add LLM explanation only if the deterministic output is already stable
- treat the model as polish, not as infrastructure

## Orchestrator Integration Plan

### Key Reality To Respect

The current live orchestrator path is effectively single-specialist per turn.

That means the MVP integration should avoid assuming full planner-plus-service chaining on every request.

### MVP Runtime Reality

For hackathon MVP, the safest operating assumption is:

- one specialist does the main work for a turn
- mixed prompts should be resolved to one primary specialist
- follow-up actions and CTAs are better than hidden multi-step chaining
- planner state reuse should come from prior turn context or explicit payload attachment, not from an invisible planner rerun by default

This keeps the live path aligned with the current repo and reduces demo failure risk.

### Single-Specialist Decision Matrix

| Prompt shape | Primary specialist in MVP | Secondary behavior | Notes |
|---|---|---|---|
| Personal finance analysis only | Planner | None | Default analytical finance path |
| Goal roadmap only, planner state already available | Service | None | Best Service Agent case |
| Goal roadmap only, no planner state, but goal + some context available | Service | Return `partial` roadmap | Use conservative setup mode |
| Goal roadmap only, goal exists but finance context is too thin | Service | Return setup-first roadmap + ask for planner first | Do not pretend projections are grounded |
| Analysis + roadmap in one prompt | Planner | Add explicit follow-up CTA to generate roadmap next | No hidden chaining in MVP |
| Analysis + stock/invest question | Planner or Stock based on dominant ask | Defer the non-primary branch | Keep one specialist per turn |
| Roadmap + stock/invest question | Service if goal-path dominates; Stock if invest decision dominates | Defer the other branch | Do not merge market analysis into roadmap by default |
| Analysis + roadmap + stock mixed prompt | Planner | Recommend split follow-up turns | This is the highest-risk mixed case |

### Mixed Prompt Handling Rules

Use these practical rules in MVP:

1. If the user is asking "what is happening in my finances," route to Planner.
2. If the user is asking "what path should I take to reach a goal," route to Service.
3. If the user is asking "should I buy/invest," route to Stock.
4. If two asks are mixed, choose the specialist that answers the more foundational question first.
5. Prefer explicit follow-up turns over hidden multi-specialist choreography.

Foundational priority in MVP:

```text
Planner state
-> Service roadmap
-> Stock context
```

That means:

- financial understanding comes before roadmap generation when both are requested together
- roadmap generation comes before optional investment context when the user is clearly goal-oriented
- stock context is deferred unless it is the dominant ask

### When Planner Should Come First

Planner should come first when:

- the prompt asks for analysis and roadmap together
- no grounded planner state is available yet
- the user is asking to understand spending, cashflow, anomaly, or readiness before taking action
- the roadmap would otherwise be based on too many assumptions

In MVP, this should usually produce:

- a strong planner answer
- a roadmap CTA
- a suggestion to continue with Service Agent next

### When Service Can Run Without Planner State

Service Agent can still run in a constrained mode when planner-derived state is missing, but it must degrade gracefully.

Allowed fallback modes:

| Available input | Service mode | Output quality |
|---|---|---|
| Goal + planner state + risk context | `grounded_roadmap` | Best case |
| Goal + partial financial context | `partial_roadmap` | Usable with caution |
| Goal only | `setup_roadmap` | Provisional, low confidence |
| No goal and no planner state | `insufficient_data` | Do not generate a real roadmap |

When planner state is missing, Service should:

- mark the result as `partial`
- expose `missing_fields`
- label projections as `directional` or `not_ready`
- surface assumptions explicitly
- make the next best action "run planner first" or "add missing goal/finance inputs"

What Service must not do in this mode:

- invent savings capacity
- invent runway
- invent affordability
- pretend milestone dates are grounded

### Planner-State-Missing UI Mode

When the user has a goal but does not have enough planner-derived state, the UI should render a clear provisional mode.

Recommended UI behavior:

| UI element | Behavior in provisional mode |
|---|---|
| Header | Show `Provisional roadmap` or `Setup roadmap` label |
| Timeline | Render only the first safe phases, not the full journey with strong confidence |
| Projection chart | Mute, badge, or caution-label as `Directional only` |
| Milestones | Show setup milestones and data-collection milestones first |
| Current vs target panel | Show target clearly; current-state fields can show `needs planner data` |
| Next best action | Prioritize `Run planner first` or `Confirm monthly savings capacity` |
| CTA | Encourage sync/review of finance data before final roadmap |

Safe phase set for provisional mode:

- `Confirm goal`
- `Stabilize basics`
- `Collect planner state`
- `Start conservative accumulation`

Unsafe things to show confidently in provisional mode:

- aggressive projection curve
- precise maturity date
- confident affordability claims
- detailed phase unlocks based on unknown cashflow

### Service Payload Construction

In [agent/strands_orchestrator/specialist.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator/specialist.py), payload building for Service Agent should:

- preserve the standard envelope
- include `request.goals`
- include planner-derived state under `request.user_context.planner_state` when available
- include risk profile and life context

### Service Output Handling

The orchestrator should treat Service output differently from Planner output:

- validate schema
- retain the structured roadmap contract
- attach it to runtime result
- emit only minimal human-readable framing if needed
- do not flatten the roadmap into plain prose

### Recommended Decision Table

| Output type | Orchestrator behavior |
|---|---|
| Planner standardized contract | human-readable synthesis allowed |
| Service roadmap contract | pass-through structured contract |
| Stock result | synthesize or merge when explicitly relevant |

## Frontend Rendering Plan

### Current Frontend Reality

Current frontend chat:

- renders markdown text from SSE
- does not yet render roadmap components

This is the main product gap for Service Agent.

### Rendering Goal

The frontend should render Service Agent output as a roadmap experience, not a text dump.

### Recommended Component Set

| Component | Purpose |
|---|---|
| `RoadmapHeader` | Goal title, status, feasibility label |
| `CurrentVsTargetPanel` | Current state vs target goal |
| `RoadmapTimeline` | Journey progression across phases |
| `PhaseCardList` | Each phase with actions and services |
| `MilestoneCards` | Milestone checkpoints |
| `ProjectionChart` | Projected amount or progress over time |
| `NextBestActionCard` | Immediate CTA |
| `MaturityBanner` | Post-maturity or next-goal marker |
| `InsufficientDataCard` | Missing fields + what to add |

### Field-To-UI Mapping

| Contract field | UI component |
|---|---|
| `goal` | `RoadmapHeader` |
| `roadmap.phases` | `PhaseCardList`, `RoadmapTimeline` |
| `roadmap.milestones` | `MilestoneCards` |
| `roadmap.projected_outcomes` | `ProjectionChart` |
| `roadmap.next_best_action` | `NextBestActionCard` |
| `roadmap.maturity_events` | `MaturityBanner` |
| `visualization.state_comparison` | `CurrentVsTargetPanel` |
| `insufficient_data` | `InsufficientDataCard` |

### Transport Plan For Frontend

Because current `/chat/stream` is SSE-text-first, the implementation should use a dual output model:

- user-facing service summary text for chat continuity
- structured roadmap payload forwarded to frontend for direct rendering

Recommended practical implementation:

1. orchestrator runtime includes the service contract in its JSON result payload
2. backend forwards that structured contract through the existing chat flow
3. frontend parses and renders roadmap UI when the contract is present

For MVP, the cleanest option is:

- keep `/chat/stream`
- add one structured contract side-channel in the response flow
- keep markdown as a fallback display only

### Empty / Loading / Error / Insufficient Data States

The frontend must explicitly support:

- loading skeleton for roadmap
- no roadmap yet
- partial roadmap due to missing goal data
- backend/orchestrator errors
- contract validation failure fallback to text-only mode

## API / Interface Plan

### Service Specialist Exposure

Service Agent should be exposed exactly like the other specialists:

- tool name: `run_service_agent_v1`
- input schema: `run_service_agent_v1.input.json`
- output schema: `run_service_agent_v1.output.json`

### Interface Boundaries

#### Orchestrator -> Service

- standard request envelope
- goals and planner state attached in `request`

#### Service -> Orchestrator

- standard agent result envelope
- service roadmap contract embedded as the primary result payload

#### Orchestrator -> Backend

- keep user-facing message
- include service contract in structured runtime result

#### Backend -> Frontend

- stream text as usual
- also pass roadmap contract so the UI can render it directly

### Error And Partial Response Shape

Service Agent must support:

- `ok`
- `partial`
- `error`
- `blocked`

Partial states should include:

- `missing_fields`
- `insufficient_data_reason`
- reduced roadmap with setup-oriented next step

## Testing Strategy

### Unit Tests

Required:

- planner state mapper tests
- sufficiency logic tests
- phase selector tests
- milestone engine tests
- projection engine tests
- maturity engine tests
- service selector tests

### Contract Tests

Required:

- input schema validation
- output schema validation
- Pydantic model validation
- visualization payload validation

### Integration Tests

Required:

- MCP dispatch for `run_service_agent_v1`
- catalog registration test
- orchestrator specialist selection test
- orchestrator pass-through test for service contract
- backend forwarding test for structured service payload

### Scenario Tests

Required before demo:

- buy a car in 18 months
- build emergency fund
- save for wedding or education
- insufficient goal data
- weak cashflow but roadmap still returns setup path

### Nice-To-Have Tests

- snapshot/golden tests for roadmap contracts
- frontend component tests
- session-memory-based service routing tests
- chained planner-to-service tests for future enhancement

## Observability / Reliability / Debugging

### Logging Strategy

Reuse the current trace and logging style.

Log:

- selected journey pattern
- sufficiency label
- current phase
- phase count
- milestone count
- projection mode
- maturity mode
- fallback reasons

### Correlation

All logs and envelopes should preserve:

- `trace_id`
- `request_id`
- `session_id`

### Metrics To Track

For demo-safe observability, track:

- service agent latency
- validation failures
- partial vs ok ratio
- missing field frequency
- most selected journey pattern
- most selected next-best action category

### Debug-Friendly Artifacts

Useful debug artifacts:

- roadmap contract fixture files
- partial-response fixtures
- scenario-specific snapshots
- frontend mock payloads

## Build Priority Matrix

This section is the anti-scope-creep control for hackathon execution.

### Scope Triage Table

| Priority bucket | Items | Why |
|---|---|---|
| Must Build | service input/output schemas, roadmap contract, planner-to-service state mapper, deterministic roadmap engine, milestone generation, next best action, partial/insufficient-data mode, small static service catalog, orchestrator pass-through for service contract, basic roadmap UI with timeline + phase cards + next action | Without these, the demo does not show the Service Agent product clearly |
| Should Build | projection series, projection chart, milestone cards, current-vs-target panel, maturity banner, one polished explanation layer, scenario fixtures, contract tests, orchestrator routing rules for roadmap prompts | These materially improve clarity and judge impact |
| Nice To Have | richer service ranking, roadmap comparison variants, improved copy polish, animated transitions, CTA deep links, secondary charts, session-memory reuse polish | Good polish, but not required to prove the concept |
| Do Not Build In MVP | full product catalog DB, complex multi-agent chaining, proactive trigger engine, broad suitability engine, advanced portfolio integration, multi-goal optimization, autonomous background agents, large profile schema expansion | These are classic hackathon traps and will slow delivery |

### Must Build Checklist

These are the hard MVP gates:

- `run_service_agent_v1` schema pair
- service result envelope with structured roadmap contract
- deterministic phase and milestone engine
- planner-state-aware input mapper
- graceful partial mode when planner state is missing
- clear next best action
- frontend rendering for:
  - roadmap header
  - timeline or phase cards
  - next best action
- at least 3 stable demo scenarios

If any of these are missing, the MVP story weakens materially.

### Should Build Checklist

Build these once the must-build list is stable:

- projection chart with directional labeling
- maturity banner / next-step marker
- current-vs-target summary panel
- LLM-assisted explanation polish
- better orchestration rules for roadmap-first prompts
- better partial-mode messaging in UI

### Nice To Have Checklist

Only do these if the core flow is already demo-safe:

- multiple roadmap presentation styles
- advanced service ranking margin logic
- richer milestone animations
- more refined copy variations
- richer frontend empty-state polish

### Do Not Build In MVP

Avoid these during the hackathon:

- hidden planner-plus-service-plus-stock chaining in one turn
- a big dynamic service-product database
- complex proactive recommendations engine
- full lifecycle CRM-style profile store
- advanced investment-aware roadmap branches
- heavy LLM dependency for roadmap generation

These are tempting, but they reduce finish probability.

## Implementation Phases

### Phase 0. Alignment

**Objective**

Lock the MVP and contract boundaries.

**Tasks**

- confirm MVP scope
- confirm routing intent family for Service Agent
- confirm minimum goal schema
- confirm frontend roadmap components

**Deliverables**

- approved implementation blueprint
- approved contract outline

**Dependencies**

- design alignment

**Risks**

- scope drift

**Success criteria**

- team agrees on `Service Agent = Personalized Financial Roadmap Generator`

### Phase 1. Schemas And Contracts

**Objective**

Define stable specialist contracts.

**Tasks**

- define input/output schemas
- define roadmap contract
- define visualization payload
- define partial/error shape

**Deliverables**

- `run_service_agent_v1` schemas
- roadmap contract fixtures

**Dependencies**

- Phase 0 alignment

**Risks**

- over-complex schema

**Success criteria**

- contract validates end-to-end

### Phase 2. Roadmap Engine MVP

**Objective**

Build deterministic roadmap generation.

**Tasks**

- planner state mapper
- sufficiency rules
- journey pattern selection
- phase generation
- service selection
- milestone generation
- projections
- maturity logic

**Deliverables**

- working service roadmap engine
- scenario fixtures

**Dependencies**

- Phase 1 contracts

**Risks**

- logic gets too broad

**Success criteria**

- three core demo scenarios work predictably

### Phase 3. Specialist MCP + Orchestrator Integration

**Objective**

Wire Service Agent into the live specialist path.

**Tasks**

- add specialist tool entry
- add catalog entry
- add schema mirror
- add orchestrator payload build logic
- add service output handling logic

**Deliverables**

- live callable `run_service_agent_v1`
- orchestrator-integrated service path

**Dependencies**

- Phase 2 engine

**Risks**

- routing ambiguity
- structured contract not preserved

**Success criteria**

- orchestrator can successfully route and return service output

### Phase 4. Frontend Rendering

**Objective**

Turn the contract into a visual roadmap experience.

**Tasks**

- add roadmap components
- parse structured payload
- render timeline, milestones, projections, next action
- implement partial/error states

**Deliverables**

- roadmap UI
- contract-to-component mapping

**Dependencies**

- Phase 1 and Phase 3

**Risks**

- frontend receives only prose

**Success criteria**

- roadmap renders directly from structured payload

### Phase 5. Polish And Demo Readiness

**Objective**

Make the experience feel impressive and reliable.

**Tasks**

- improve copy and CTA phrasing
- tighten visual hierarchy
- finalize scenarios and fixtures
- add golden tests
- rehearse demo flows

**Deliverables**

- polished demo-ready roadmap flow

**Dependencies**

- all previous phases

**Risks**

- last-minute UI instability

**Success criteria**

- demo runs cleanly and tells a strong story

## Team Task Breakdown

### Backend / Agent Engineer

**Responsibilities**

- specialist schemas
- service agent core
- planner state mapper
- contract validation

**Deliverables**

- service specialist implementation
- roadmap engine fixtures

**Dependencies**

- final contract decisions

**Handoff points**

- output contract to frontend
- route shape to orchestrator owner

### Orchestrator / Backend Integration Owner

**Responsibilities**

- specialist catalog integration
- payload construction
- response pass-through
- backend streaming behavior for structured payloads

**Deliverables**

- orchestrator routing and output handling
- backend forwarding path

**Dependencies**

- service schema finalized

**Handoff points**

- structured payload contract to frontend

### Frontend Engineer

**Responsibilities**

- roadmap rendering components
- contract parser
- empty/error/loading states
- chart rendering

**Deliverables**

- roadmap UI
- service roadmap demo screen

**Dependencies**

- visualization payload stability

**Handoff points**

- scenario review with demo owner

### Data / Schema Owner

**Responsibilities**

- minimal goal field alignment
- risk profile compatibility
- planner-derived field mapping

**Deliverables**

- data contract table
- field ownership map

**Dependencies**

- planner and service schema review

**Handoff points**

- backend and service agent teams

### QA / Test Owner

**Responsibilities**

- fixture scenarios
- contract tests
- partial/insufficient-data coverage
- regression checks

**Deliverables**

- must-pass demo checklist

**Dependencies**

- stable fixtures and schemas

**Handoff points**

- final demo readiness signoff

### Demo / Pitch Owner

**Responsibilities**

- story arc
- scenario selection
- wow-moment sequencing
- script and screenshots

**Deliverables**

- demo script
- pitch narrative

**Dependencies**

- polished frontend and stable fixtures

**Handoff points**

- final judge presentation flow

## Risk Register And Mitigation

| Risk | Severity | Impact | Mitigation |
|---|---|---|---|
| Goal data too thin | High | Weak roadmap quality | Add only minimal goal fields: type, amount, date/timeline, priority |
| Planner-derived state unavailable | High | Service roadmap loses grounding | Support partial mode and use explicit missing-field output |
| Orchestrator rewrites service output | High | Roadmap contract becomes lossy | Make service output pass-through by design |
| Frontend only receives prose | High | No roadmap UI wow moment | Forward structured contract through backend/orchestrator |
| Service catalog becomes too large | Medium | Slows implementation | Start with small static MVP catalog |
| Projection too optimistic | High | Trust damage | Use conservative assumptions and directional labels |
| LLM explanation drifts from contract | Medium | Inconsistency | Make LLM read-only on finalized contract |
| Routing ambiguity with planner | Medium | Wrong specialist selected | Keep MVP service intents explicit and narrow |
| Single-specialist runtime limits combined asks | Medium | Mixed prompts become awkward | Route combined asks to planner in MVP and suggest roadmap follow-up |
| Demo breaks on missing fields | High | Judge-facing failure | Add insufficient-data roadmap state and fixture coverage |

## Demo / Judge Impact Plan

### The Wow Moment

The wow moment is not "the AI answered a finance question."

The wow moment is:

> "The system looked at my financial state and turned it into a personalized journey I can actually follow."

That should appear visually as:

- current state
- target goal
- phase-based roadmap
- milestones
- projection curve
- next best action
- what happens after maturity

### What Judges Should See First

Open with:

1. current financial state vs target goal
2. roadmap timeline with named phases
3. next best action card
4. projected outcome chart

That sequence instantly communicates that this is not a generic chatbot.

### What Makes This Different From Typical Finance Chatbots

- grounded by planner-derived financial state
- roadmap-first, not answer-first
- phase-based progression
- milestone and maturity logic
- structured output ready for UI
- direct action path rather than vague advice

### Best Demo Scenarios

Use the three strongest scenarios from the design doc:

- buy a car in 18 months
- build emergency fund
- save for wedding or education

Recommended primary scenario:

- **Buy a car in 18 months**

It is visually intuitive, concrete, and easy for judges to follow.

### Suggested Pitch Line

> "Planner tells you where your finances stand. Service Agent tells you what road to take next."

### Suggested Product Message

> "We are not just generating advice. We are generating a personalized financial journey."

## Final Recommendation

The best implementation approach is:

1. add Service Agent as a third specialist in the existing specialist MCP runtime
2. keep the MVP focused on **Personalized Financial Roadmap Generator**
3. make the roadmap engine deterministic, planner-derived, and strongly typed
4. make orchestrator validate and pass through Service output rather than rewrite it
5. make frontend render the roadmap directly from structured contract

### Recommended Primary Stack

- Python + FastAPI + Pydantic + JSON Schema on the specialist side
- existing orchestrator + AgentCore + Gateway for runtime flow
- Next.js + Tailwind + `recharts` + `zod` on the frontend

### Recommended Integration Principle

```text
Planner -> financial state
Service -> roadmap contract
Orchestrator -> pass-through / minimal framing
Frontend -> direct roadmap rendering
```

### Why This Plan Is Both Modern And Practical

It is modern because it:

- uses specialist boundaries correctly
- treats structured contracts as product surfaces
- separates deterministic logic from explanation
- enables visual, multi-step user experiences

It is practical because it:

- reuses the repo's actual architecture
- minimizes new moving parts
- avoids database overbuild
- keeps MVP narrow
- fits hackathon delivery speed

### Why This Is Strong For Hackathon Judges

It creates a demo that feels:

- intelligent
- grounded
- visually compelling
- actionable
- different from standard chatbot demos

That is the right combination of engineering credibility and product storytelling.
