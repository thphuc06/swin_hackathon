# Service Agent Implementation Blueprint

## Executive Summary

Service Agent should be implemented as the third specialist in the existing runtime:

```text
frontend -> backend -> orchestrator -> gateway -> specialist MCP -> service agent
```

Its MVP remains narrowly focused:

> Personalized Financial Roadmap Generator

This document adopts a **hybrid Service Agent architecture**:

- Planner owns grounded financial analysis and planner-derived state.
- Service Agent owns journey design and roadmap generation.
- Layer 2 uses model reasoning to propose **structured roadmap candidates**.
- Layer 3 deterministically validates, ranks, and compiles the final roadmap contract.
- Layer 4 explains the finalized roadmap without changing it.

This is better than a deterministic-only framing because roadmap structure contains semantic nuance and trade-offs that static rules alone will not cover well. It is also safer than a pure LLM roadmap generator because final contract fields, numbers, milestones, projections, and visualization payloads remain deterministic, typed, and testable.

The final product rule is simple:

```text
Planner grounds the facts.
Layer 1 checks readiness.
Layer 2 proposes candidates.
Layer 3 decides and compiles.
Layer 4 explains.
Orchestrator routes and passes through.
Frontend renders the contract directly.
```

## Current Repo Fit Analysis

### Current Runtime Reality

The repo already runs a specialist-first architecture:

```text
frontend -> backend -> orchestrator -> gateway -> specialist MCP -> specialist
```

Relevant paths:

- [backend/app/routes/chat.py](/C:/Users/Admin/Desktop/swin_hackathon/backend/app/routes/chat.py)
- [agent/main.py](/C:/Users/Admin/Desktop/swin_hackathon/agent/main.py)
- [agent/strands_orchestrator/](/C:/Users/Admin/Desktop/swin_hackathon/agent/strands_orchestrator)
- [src/aws-specialist-agent-mcp-server/app/mcp.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/app/mcp.py)

### Planner Fit

Planner already owns:

- grounded financial analysis
- cashflow, savings capacity, runway, anomaly, risk, and readiness signals
- standardized financial contracts

Relevant paths:

- [planner_agent/agent.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/planner_agent/agent.py)
- [planner_agent/reporting.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/planner_agent/reporting.py)

Service Agent should **consume** planner-derived state, not recompute raw finance analysis.

### Stock Fit

Stock is already a separate specialist with its own boundary:

- [stock/adapter.py](/C:/Users/Admin/Desktop/swin_hackathon/src/aws-specialist-agent-mcp-server/stock/adapter.py)

This validates the correct product split:

- Planner = finance analysis
- Stock = market context
- Service = roadmap design

### Orchestrator Fit

Orchestrator already owns:

- routing
- specialist payload construction
- gateway invocation
- response packaging

Important runtime reality:

- the current live path is effectively **single-specialist per turn**
- Service Agent must respect that in MVP

### Frontend / Backend Fit

Backend already streams chat responses. Frontend already renders chat text. Service Agent should add a **structured roadmap side-channel**, not replace the existing flow.

Relevant paths:

- [frontend/package.json](/C:/Users/Admin/Desktop/swin_hackathon/frontend/package.json)
- [frontend/app/chat/page.tsx](/C:/Users/Admin/Desktop/swin_hackathon/frontend/app/chat/page.tsx)

## Updated MVP Scope Statement

### MVP Goal

Generate one personalized roadmap for one active user goal from:

- planner-derived financial state
- goal data
- user context

### MVP Must Preserve

- Service Agent = roadmap generator, not second Planner
- Planner remains source of grounded state
- output remains a structured roadmap contract
- partial / insufficient-data mode remains mandatory
- orchestrator does not rewrite roadmap content
- frontend renders contract directly

### MVP Non-Goals

- multi-goal optimization
- multi-specialist chaining in one turn
- prose-only roadmap output
- fine-tuning before hackathon
- heavy profile database expansion

## Implementation Principles

1. **No outer flow change**  
   Keep the existing frontend -> backend -> orchestrator -> gateway -> specialist MCP path.

2. **Planner-derived state first**  
   Service Agent should read planner-derived state such as cashflow state, savings capacity, liquidity pressure, runway, anomaly state, readiness, risk band, and feasibility.

3. **Hybrid over deterministic-only**  
   Deterministic-only is too rigid for roadmap structure selection. Hybrid candidate reasoning is more appropriate.

4. **Deterministic final contract**  
   Final roadmap contract, milestones, numbers, projections, maturity logic, and UI payload must be deterministic.

5. **No prose-as-contract**  
   Human-readable explanation is optional. Structured contract is the source of truth.

6. **Orchestrator pass-through for Service output**  
   Planner may be humanized. Service roadmap contract should be validated and forwarded with minimal framing only.

7. **Frontend renders directly from contract**  
   No parsing roadmap prose back into UI state.

8. **Safe degradation is mandatory**  
   If grounded input is insufficient, return partial/setup roadmap instead of invented certainty.

9. **Same valid input should produce stable output**  
   Layer 3 must be deterministic and testable.

## Recommended Tech Stack

| Layer | Choice | Reuse/Add | Why |
|---|---|---|---|
| Specialist runtime | FastAPI + existing MCP app | Reuse | Matches planner and stock |
| Validation | Pydantic v2 + JSON Schema | Reuse | Current repo pattern |
| LLM integration | existing Bedrock + Strands pattern | Reuse selectively | Fits current runtime |
| HTTP | `requests` | Reuse | Already used |
| Logging | Python `logging` | Reuse | Already used |
| Testing | `unittest` + fixtures + `jsonschema` | Reuse | Current repo style |
| Frontend | Next.js 14 + React 18 + TypeScript | Reuse | Existing app |
| Styling | Tailwind CSS | Reuse | Existing app |
| Client validation | `zod` | Add | Strong payoff for roadmap payloads |
| Charting | `recharts` | Add | Fastest polished chart path |

## Hybrid Architecture Overview

### Why Deterministic-Only Is Insufficient

Roadmap generation is not only arithmetic. It also requires:

- interpreting goal nuance
- choosing between journey patterns
- sequencing phases under trade-offs
- selecting service fit by phase

Static rules alone will become brittle too quickly.

### Why Pure LLM Is Insufficient

Pure LLM roadmap generation would make:

- contract stability weak
- numbers less trustworthy
- frontend rendering fragile
- QA much harder

### Recommended Hybrid Flow

```text
normalized input
-> Layer 1: deterministic sufficiency gate
-> Layer 2: LLM structured candidate proposal
-> Layer 3: deterministic validation, ranking, and contract compilation
-> Layer 4: read-only explanation
-> roadmap contract + optional explanation
```

## Layer-by-Layer Responsibilities

### Layer 1 - Deterministic Sufficiency Gate

Purpose:

- decide whether grounded roadmap generation is possible

Responsibilities:

- validate required goal fields
- validate planner-derived state availability
- classify request as:
  - `ready`
  - `partial_but_usable`
  - `insufficient_goal_data`
  - `insufficient_financial_state`
- emit `missing_fields`
- emit safe `next_best_action`

Rule:

- if input is insufficient, do not allow model-generated grounded roadmap decisions

### Layer 2 - LLM Reasoning / Candidate Proposal

Purpose:

- propose roadmap candidates, not final outputs

Responsibilities:

- interpret goal nuance
- propose candidate journey patterns
- propose candidate phase sequences
- suggest service fit by phase
- provide trade-off reasoning

Constraints:

- structured output only
- no hard numbers
- no final milestones
- no final projections
- no final maturity values
- no final contract
- must stay within predefined ontology

### Layer 3 - Deterministic Validation + Ranking + Contract Compiler

Purpose:

- turn model proposals into the final roadmap product artifact

This is the most important layer. It is not post-processing. It is the deterministic decision core.

Responsibilities:

1. validate Layer 2 candidate schema
2. canonicalize model labels into internal IDs
3. apply hard constraints from planner state and policy
4. reject unsafe, invalid, or ungrounded candidates
5. score remaining candidates deterministically
6. apply stable tie-break rules
7. select the winning candidate
8. compile final roadmap contract
9. generate milestones
10. generate projections
11. generate maturity and post-maturity logic
12. generate visualization payload

Layer 3 owns:

- final journey selection
- final phase sequence
- final service recommendations
- milestones
- projections
- maturity events
- next best action
- visualization support
- final structured roadmap contract

### Layer 4 - Read-only Explanation Layer

Purpose:

- explain the finalized roadmap

Responsibilities:

- roadmap summary
- why-fit explanation
- next-action explanation
- caution text

Constraint:

- Layer 4 cannot modify contract structure, numbers, milestones, projections, or phase order

## Layer 2 Structured Candidate Output Contract

### Candidate Ontology Constraints

Layer 2 may only use finite allowed sets:

- `journey_pattern`
- `phase_type`
- `service_id`
- `rationale_tag`

Unknown or non-canonical values must be rejected by Layer 3.

### Candidate Proposal Shape

```json
{
  "schema_version": "service_candidate_set_v1",
  "readiness_class": "ready",
  "candidates": [
    {
      "candidate_id": "cand_1",
      "journey_pattern": "stabilize_then_accumulate",
      "phase_types": ["stabilize", "build_buffer", "goal_funding"],
      "service_candidates": [
        {"phase_type": "stabilize", "service_ids": ["transaction_alerts", "budget_controls"]}
      ],
      "rationale_tags": ["liquidity_pressure_high", "goal_urgency_high"],
      "tradeoff_notes": ["safer but slower progress"],
      "proposal_confidence": 0.78
    }
  ]
}
```

## Layer 3 Deterministic Decision Core

### Layer 3 Mission

Layer 3 is the deterministic decision and compilation core that converts candidate proposals into the final roadmap output. Layer 2 may propose. Layer 3 must decide and compile.

### Layer 3 Pipeline

```text
candidate schema validation
-> canonicalization / normalization
-> hard-constraint filtering
-> deterministic scoring
-> stable tie-break
-> winning candidate selection
-> roadmap contract compilation
-> milestone engine
-> projection engine
-> maturity engine
-> visualization mapper
```

### Layer 3 Decision Boundaries

| Layer | Owns |
|---|---|
| Layer 2 | candidate proposals, trade-off reasoning, service fit suggestions |
| Layer 3 | candidate acceptance/rejection, ranking, winner selection, final contract |

### Deterministic Ranking Design

Recommended scoring structure:

| Score component | Meaning |
|---|---|
| `feasibility_score` | can this roadmap realistically support the goal |
| `liquidity_safety_score` | does it protect runway and liquidity first when needed |
| `goal_alignment_score` | does it match goal type, urgency, and timeline |
| `planner_state_alignment_score` | does it fit readiness, anomaly, risk, and savings state |
| `service_phase_coherence_score` | are service recommendations valid for the proposed phases |
| `complexity_penalty` | penalize unnecessarily complex paths |
| `partial_data_penalty` | penalize overconfidence under weak inputs |

Stable tie-break rules:

1. lower safety risk wins
2. fewer unnecessary phases wins
3. better goal alignment wins
4. earlier canonical candidate order wins
5. lexical candidate ID order wins

### Hard Constraint Examples

Layer 3 must reject or downgrade candidates when:

- low runway candidates skip liquidity protection
- non-positive savings capacity goes directly to aggressive accumulation
- missing planner state tries to produce grounded milestone dates
- invalid service-phase pairings appear
- active anomaly state is ignored

### Contract Compiler Responsibilities

Layer 3 compiler must materialize:

- phases
- milestones
- projections
- next best action
- maturity events
- service recommendations
- visualization payload

This is where the roadmap becomes the final product contract.

### Failure / Fallback Behavior

If Layer 3 rejects all candidates or Layer 2 is malformed:

- fall back to partial/setup roadmap
- emit explicit fallback reason
- emit `missing_fields`
- emit safe next best action such as `run planner first` or `provide target amount`

## Candidate Validation And Ranking Strategy

Layer 3 should handle candidate evaluation in three steps:

1. **Validate**
   - reject malformed candidate objects
   - reject unknown ontology values
   - reject invalid service-phase pairings

2. **Filter**
   - remove candidates that violate safety, liquidity, feasibility, or planner-state constraints

3. **Rank**
   - compute deterministic score from feasibility, liquidity safety, goal alignment, planner-state alignment, service-phase coherence, and penalties
   - apply fixed tie-break order

The ranking system should be transparent enough that the team can explain why one candidate won over another.

## Contract Compilation Strategy

After winner selection, Layer 3 must compile the final roadmap contract in a fixed order:

1. materialize journey pattern
2. materialize phase sequence
3. attach allowed services by phase
4. generate milestones
5. generate projections
6. generate next best action
7. generate maturity events
8. map visualization payload

Compilation must not depend on free-form explanation text. The final roadmap should be fully renderable even if Layer 4 is disabled.

## Fallback And Safe Degradation Modes

The Service Agent must degrade safely instead of fabricating confidence.

Recommended fallback modes:

| Mode | Trigger | Output behavior |
|---|---|---|
| `partial_but_usable` | some planner or goal fields missing but enough context exists | partial roadmap with caveats and constrained milestones |
| `insufficient_goal_data` | target amount, timeline, or goal type missing | setup roadmap plus missing fields and goal-completion CTA |
| `insufficient_financial_state` | planner state missing or too weak | planner-first CTA or setup roadmap without grounded projections |
| `candidate_rejected_fallback` | all Layer 2 candidates rejected | safe default path such as `setup_first` or `stabilize_first` |

In all fallback modes:

- do not invent planner facts
- do not invent hard milestone dates
- do not emit precise projections without support
- make `next_best_action` point to the missing requirement

## Contracts And Schemas

### Input Contract

```json
{
  "schema_version": "service_request_v1",
  "planner_state": {},
  "goal": {
    "goal_type": "buy_vehicle",
    "target_amount": 200000000,
    "target_timeline_months": 18,
    "priority": "high"
  },
  "user_context": {},
  "prompt_context": {}
}
```

### Final Output Contract

```json
{
  "schema_version": "service_roadmap_v1",
  "status": "ready",
  "missing_fields": [],
  "roadmap_contract": {
    "journey_pattern": "",
    "phases": [],
    "milestones": [],
    "projection": {},
    "maturity_events": [],
    "next_best_action": {},
    "service_recommendations": [],
    "visualization": {}
  },
  "explanation": {
    "summary": "",
    "why_fit": "",
    "next_action_why": "",
    "cautions": []
  }
}
```

## Data Model And Storage Plan

### DB Should Stay Minimal

Minimum goal schema:

- `goal_type`
- `target_amount`
- `target_date` or `target_timeline_months`
- `priority`

Optional:

- `status`
- `achieved_at`

### Planner-Derived State Should Remain Primary

Use Planner for:

- cashflow state
- savings capacity
- liquidity pressure
- runway
- anomaly state
- readiness
- feasibility
- risk band

Do not build a large new profile store for MVP.

## Roadmap Engine Implementation Strategy

High-level flow:

```text
normalize input
-> Layer 1 gate
-> Layer 2 candidates
-> Layer 3 deterministic decision core
-> Layer 4 explanation
```

Keep ontology intentionally small:

- journey patterns: 4-5
- phase types: 5-6
- service IDs: small static catalog

This keeps the hybrid model controllable in hackathon scope.

## Orchestrator Integration Plan

### Single-Specialist Runtime Reality

Current MVP should assume one dominant specialist per turn.

### Recommended Routing Rules

| Prompt shape | Specialist |
|---|---|
| current financial analysis | Planner |
| roadmap request with planner state available | Service |
| roadmap request without planner state | Planner first or partial Service setup mode |
| market/investment request | Stock |

### Service Output Handling

For Service output:

- validate contract
- pass through structured payload
- add minimal framing only if needed
- do not rewrite roadmap structure into prose

## Frontend Rendering Plan

Frontend should render directly from structured roadmap payload:

- timeline
- phase cards
- milestone cards
- projection chart
- current-vs-target panel
- next-action card
- maturity banner

If Service returns partial/setup mode:

- show provisional state
- surface missing fields
- promote `next_best_action` as the main CTA

## Updated Testing Strategy For Hybrid Model

Required tests:

- Layer 1 sufficiency tests
- candidate schema validation tests
- candidate rejection tests
- deterministic ranking tests
- stable tie-break tests
- contract compilation tests
- projection stability tests
- same-input same-output tests
- orchestrator pass-through tests
- frontend rendering fixture tests

## Updated Risk Register For Hybrid Model

| Risk | Severity | Mitigation |
|---|---|---|
| Layer 2 becomes hidden decision maker | High | make Layer 3 authoritative and heavily tested |
| Candidate ontology too broad | High | keep ontology small and explicit |
| Planner state missing or contradictory | High | strict Layer 1 gate and partial mode |
| Orchestrator rewrites service output | High | pass-through by design |
| Frontend receives only prose | High | forward structured contract through backend/orchestrator |
| LLM output malformed | Medium | schema validation and fallback |
| Same input yields different roadmap | High | deterministic scoring and tie-break tests |

## Build Priority Matrix

| Priority | Scope |
|---|---|
| Must Build | input/output schemas, Layer 1 gate, Layer 2 candidate output, Layer 3 decision core, contract compiler, milestones, next best action, partial/setup mode, small service catalog, orchestrator pass-through, basic roadmap UI |
| Should Build | projection chart, maturity banner, Layer 4 explanation, frontend `zod` validation, candidate rejection logs |
| Nice To Have | richer explanation polish, roadmap comparison view, extra chart polish |
| Do Not Build In MVP | multi-goal optimization, heavy catalog DB, fine-tuning pipeline, multi-specialist chaining, prose-only roadmap generation |

## Implementation Phases

### Phase 0 - Alignment

- freeze ontology
- freeze layer boundaries
- freeze output contract

### Phase 1 - Schemas

- input schema
- candidate schema
- output schema
- fixtures

### Phase 2 - Deterministic Backbone

- Layer 1
- Layer 3 validation, ranking, compiler
- milestone, projection, maturity engines

### Phase 3 - Candidate Reasoning

- Layer 2 prompts
- ontology-constrained candidate proposals

### Phase 4 - Integration

- specialist integration
- orchestrator pass-through
- frontend rendering

### Phase 5 - Polish

- Layer 4 explanation
- demo fixtures
- visual polish

## Final Recommendation

The strongest implementation approach for this repo is:

1. keep Planner as owner of grounded financial state
2. implement Service as a third specialist in the current runtime
3. use a 4-layer hybrid architecture
4. make Layer 3 the deterministic decision and contract compilation core
5. make orchestrator validate and pass through Service output
6. make frontend render roadmap directly from the structured contract

This keeps the system:

- smarter than deterministic-only
- safer than pure LLM
- aligned with current repo/runtime reality
- stable enough for hackathon demo and UI rendering
