# Service Agent Design

## Executive Summary

Service Agent should exist as a **dedicated financial journey design layer** in the current specialist-first architecture.

Its purpose is not to re-run transaction analysis and not to replace the Planner Agent. Its purpose is to answer a different product question:

> Given this user's financial state, goal, constraints, and context, what is the best path from current state to target outcome?

That path should be expressed as a **personalized financial roadmap**, not just a flat recommendation list.

The roadmap should include:

- phase-based progression
- goal execution path
- service recommendations bound to each phase
- milestones and unlock conditions
- projected outcomes by timeline
- next best action
- maturity and post-maturity next steps
- visualization-friendly structures

This is why Service Agent matters:

- Planner Agent explains the user's finances.
- Service Agent designs the user's journey.
- Stock Agent explains investment or equity-specific questions.
- Orchestrator routes, validates, and only synthesizes when needed.

The best product interpretation is:

**Service Agent = Personalized Financial Roadmap Generator**

That should be the MVP and the product center of gravity.

## Product Positioning In The Current System

This proposal fits the current architecture and does not change the existing flow.

Current production flow:

```text
User
-> Frontend chat UI
-> Backend /chat/stream
-> Orchestrator runtime
-> AgentCore Gateway
-> Specialist MCP runtime (agent-as-tools)
   -> Planner Agent
   -> Stock Agent
-> Orchestrator synthesis
-> User
```

Proposed positioning with Service Agent added as another specialist capability:

```text
User
-> Frontend chat UI
-> Backend /chat/stream
-> Orchestrator runtime
-> AgentCore Gateway
-> Specialist MCP runtime (agent-as-tools)
   -> Planner Agent
   -> Service Agent
   -> Stock Agent
-> Orchestrator synthesis
-> User
```

Nothing in the outer architecture changes:

- no change to frontend/backend protocol
- no change to orchestrator flow
- no change to Gateway role
- no change to Planner Agent responsibilities
- no change to Stock Agent responsibilities

The new capability is a specialist boundary, not an architecture redesign.

## Why Service Agent Must Be Separate

If Planner Agent both analyzes finances and designs the full service journey, the system will blur two different responsibilities:

- financial understanding
- journey design and progression planning

That creates three risks:

1. Planner becomes overloaded and harder to reason about.
2. Roadmap generation becomes mixed with low-level finance analysis.
3. Team boundaries become unclear, making iteration slower.

Separating Service Agent keeps the system cleaner:

- Planner produces structured financial state.
- Service Agent consumes that state and turns it into a path.
- Orchestrator remains the composition layer.

## Boundary And Responsibility

### Boundary Matrix

| Component | Core job | Primary input | Primary output | Must not become |
|---|---|---|---|---|
| Planner Agent | Analyze personal finance state | Supabase-backed user finance data | Financial state, signals, planning facts, grounded recommendations | A journey designer |
| Service Agent | Design personalized financial roadmap | Planner financial state + goals + user context | Phase-based roadmap, service plan, milestones, projected outcome | A second planner |
| Stock Agent | Provide stock and investment-specific guidance | Investment-domain prompt and optional context | Stock analysis, market notes, investment guidance | A personal finance roadmap engine |
| Orchestrator | Route and synthesize | User request + specialist outputs | Final combined response | A hidden reasoning monolith |

### Planner Agent

Planner Agent remains responsible for:

- reading user financial data from Supabase
- computing income, expense, cashflow, recurring patterns, anomaly, risk, goal feasibility, allocation, and scenario outputs
- generating grounded planning facts
- producing finance-domain recommendations and next actions

Planner Agent remains the source of truth for:

- financial state
- finance-core signals
- trust, confidence, and reliability context
- planning facts grounded in actual user data

Planner Agent should **not** own:

- service journey design
- phase sequencing beyond finance-planning facts
- maturity rollover logic as a first-class product layer
- personalized service-path composition

### Service Agent

Service Agent is responsible for:

- turning financial state into a **goal execution path**
- deciding the best **phase progression**
- binding services and actions to each phase
- defining milestones and unlock conditions
- projecting likely outcomes
- determining next best action
- handling maturity and post-maturity transitions
- producing roadmap output designed for product/UI presentation

Service Agent should **not**:

- re-run raw transaction analytics if Planner already produced structured state
- duplicate anomaly, risk, or cashflow engines
- become a generic service recommender with no journey logic

### Stock Agent

Stock Agent is responsible for:

- stock-specific educational analysis
- investment-specific reasoning
- portfolio or market-oriented context
- optional market context when investment questions appear

Stock Agent should not own:

- cashflow roadmap generation
- service journey design
- non-investment financial lifecycle planning

### Orchestrator

Orchestrator remains responsible for:

- routing to the correct specialist path
- deciding whether multiple specialists are needed
- composing planner, service, and stock outputs when needed
- preserving traceability, policy, and final response shaping

Orchestrator should not become the place where roadmap logic or financial journey design lives, and it should not paraphrase structured Service Agent output when a pass-through contract is enough.

## Core Mission

Service Agent should be defined as:

> A dedicated specialist that transforms financial state + user goal + user context into a personalized roadmap with phases, services, milestones, projected outcomes, and next best actions.

This is not just recommendation.

This is **financial journey design**.

The agent should answer:

- Where is the user right now?
- What is the target state?
- What path makes sense for this specific user?
- What phase should the user be in now?
- Which service or support should be activated in that phase?
- What milestone unlocks the next step?
- What happens when the goal matures or reaches a decision point?

The correct mental model is:

```text
Planner Agent
-> Financial state engine

Service Agent
-> Personalized roadmap engine

Stock Agent
-> Market and investing specialist
```

## Core Product Promise

The user should not only hear:

- what their financial situation looks like
- what generic advice is available

The user should hear:

- what path fits them now
- what phase they are in
- what they should do next
- what they can reasonably expect if they stay on that path
- what happens after they reach the target

That is the product promise of Service Agent.

## Current Data Reality And Minimal Schema

This design should reflect the current hackathon reality of the repo and database.

### What The System Already Has

- Planner can already derive a large amount of useful financial state from existing finance data.
- Goal data exists conceptually, but goal timing and maturity-related fields are still thin.
- Personal profile depth is limited; risk profile is clearer than a rich personal-profile model.

### What Is Still Thin

- some goals may not yet carry enough timing information for roadmap maturity logic
- achieved and post-maturity timestamps are not guaranteed to exist
- user profile data is not rich enough to justify a large profile-driven design

### Minimal Goal Fields Needed For Roadmap Support

For hackathon scope, the database should keep only the minimum goal facts that roadmap generation truly needs:

- `goal_type`
- `target_amount`
- `target_date` or `target_timeline_months`
- `priority`

Useful but optional additions:

- `status`
- `achieved_at`

### Design Principle

Do not overbuild the database for Service Agent.

The roadmap engine should not depend on:

- a full personal profile store
- dozens of new columns
- a large service-product catalog

Instead, the system should:

- keep persistent facts minimal
- derive state from Planner wherever possible
- add only the smallest schema changes that materially improve roadmap quality

This is the right tradeoff for a hackathon and for the current repo reality.

## Planner-Derived State First

Service Agent should follow one core rule:

**Prefer derived state from Planner over new database dependencies whenever possible.**

### Why This Matters

Planner already has access to the user's grounded financial state and can compute many values that are more useful than raw profile fields.

That means Service Agent does not need to wait for a large user-profile schema to become useful.

### Facts That Should Usually Stay In DB

- goal type
- target amount
- target date or target timeline
- priority
- optional goal status
- optional achieved timestamp

### State That Should Usually Come From Planner

- income stability
- liquidity pressure
- planning readiness
- anomaly state
- savings capacity
- runway
- feasibility
- readiness for next phase
- recurring burden
- current pace vs required pace

### Design Principle

```text
DB
-> stores minimum durable facts

Planner
-> derives structured financial state

Service Agent
-> consumes derived state to design roadmap
```

This keeps the hackathon scope realistic and avoids unnecessary schema work.

## Inputs

Service Agent should consume structured inputs, not rely on re-parsing prose when structured planner output is available.

### Required Inputs

#### 1. Financial State From Planner

- income baseline
- expense baseline
- net cashflow
- savings capacity
- emergency runway or buffer
- liquidity pressure
- recurring obligations
- anomaly flags
- non-investment risk signals
- planning readiness
- feasibility
- readiness for next phase
- suitability boundary if present

#### 2. User Goals

- goal type
- target amount
- target date or target timeline
- priority
- flexibility
- urgency

#### 3. User Context

- risk preference
- liquidity need
- income stability
- life stage
- household or family context
- budget discipline
- debt sensitivity
- session-level intent framing

### Optional Inputs

#### 4. Market Context

- optional market context from Stock Agent
- only relevant when the roadmap has investment-aware phases
- should not be required for core roadmap generation

#### 5. Policy Context

- education-only boundaries
- suitability boundaries
- execution restrictions

## Personalization Dimensions

This section is critical.

The roadmap should not be a static template with the goal name swapped in. It should be personalized across multiple dimensions.

### Personalization Inputs

Service Agent should personalize based on:

- `financial_state`
  - positive vs negative cashflow
  - stable vs unstable baseline
  - low vs high runway
- `goal_type`
  - emergency fund
  - vehicle purchase
  - wedding
  - education
  - housing
- `target_amount`
  - small, medium, or heavy target relative to savings capacity
- `target_timeline`
  - near-term vs medium-term vs long-term
- `risk_preference`
  - conservative, moderate, growth-leaning
- `liquidity_need`
  - whether the user must preserve fast access to funds
- `income_stability`
  - salary stability vs variable income dependence
- `life_context`
  - single, family, parent, early-career, mid-career, etc.
- `urgency`
  - can the target be delayed or not
- `feasibility`
  - on-track, stretched, or unrealistic under current baseline
- `readiness_for_next_step`
  - whether the user is ready to accelerate, maintain, pause, or stabilize

### Personalization Principle

The same goal should produce different roadmaps for different users.

Example:

- two users may both want to buy a car
- one may receive `stabilize -> buffer -> accelerate -> purchase-readiness`
- another may receive `maintain -> accumulate -> compare options -> purchase-ready`

The roadmap is a **fit engine**, not a fixed template.

## Output Contract

The output should be a roadmap contract, not a free-form narrative only.

Core output elements:

- `roadmap_summary`
- `current_phase`
- `journey_type`
- `phase_sequence`
- `phases`
- `milestones`
- `service_recommendations`
- `projected_outcomes`
- `next_best_action`
- `fit_explanation`
- `maturity_events`
- `post_maturity_options`
- `visualization_support`

If data is insufficient, the same structure should still be returned with explicit markers:

- `insufficient_data`
- `not_applicable`

## Orchestrator Behavior By Output Type

This section is important for implementation clarity.

Orchestrator should not treat every specialist output the same way.

### 1. Planner Output

Planner output is often analytical and finance-heavy.

For Planner output, orchestrator may still need to:

- synthesize
- summarize
- merge planning facts into a user-facing response
- convert analytical output into clearer presentation when the frontend expects prose or mixed UI

Planner output is the place where orchestrator reasoning is most justified.

### 2. Service Output

Service output should be treated differently.

Service Agent should return a structured roadmap contract that is already product-shaped and UI-ready enough to render directly.

For Service output, orchestrator should primarily:

- route
- validate
- preserve correlation and trace metadata
- pass through the structured contract
- merge only the smallest amount of extra context when truly necessary

Orchestrator should **not**:

- paraphrase the roadmap from text
- re-reason phase logic from prose
- flatten structured roadmap output back into generic summary text

### 3. Stock Output

Stock output should be merged only when relevant to the user request.

For Stock output, orchestrator may:

- include it when investing context is part of the user journey
- attach market context to a larger response when needed
- keep it separate when the product surface expects a dedicated investing block

### Practical Rule

```text
Planner output
-> may require synthesis

Service output
-> should be pass-through structured contract

Stock output
-> merge only when relevant
```

This keeps Service Agent useful as a roadmap engine instead of turning it into another text-only advisory layer.

## Personalized Roadmap Design

This is the heart of Service Agent.

Service Agent should build a roadmap from:

- current state
- target goal
- constraints
- phase readiness
- available service actions

### Roadmap Construction Logic

#### Step 1. Read Current State

From Planner output, determine:

- current financial stability
- surplus or deficit
- savings ability
- anomaly or instability state
- runway or liquidity buffer
- readiness for acceleration

#### Step 2. Define Target State

Determine:

- what success looks like
- when the user wants it
- what minimum safe conditions are required

#### Step 3. Select Journey Pattern

Examples:

- `stabilize -> protect -> accumulate -> execute`
- `protect liquidity -> build reserve -> maintain`
- `clean recurring burden -> accelerate goal -> maturity review`
- `stabilize -> build bucket -> milestone review -> transition`

#### Step 4. Split Into Phases

Each phase should define:

- objective
- why this phase exists
- actions
- services
- expected result
- entry condition
- exit condition

#### Step 5. Define Milestones

Milestones should be measurable progress points tied to phase transitions.

Examples:

- first stable month
- first automated transfer active
- emergency fund hits 1 month runway
- 25 percent of target reached
- anomaly watch period cleared

#### Step 6. Project Outcomes

Service Agent should estimate:

- expected progress by milestone
- expected time to next phase
- expected target attainment path
- whether the plan is on-track, stretched, or needs re-scope

#### Step 7. Emit Next Best Action

Service Agent should always identify the single highest-value immediate move for the user's current phase.

#### Step 8. Define Maturity And Transition

The roadmap must continue beyond milestone completion:

- what happens at maturity
- what action is recommended on milestone completion
- what the user should do after goal completion

## Phase-Based Service Model

This section should be one of the defining strengths of Service Agent.

Service Agent is not just selecting services. It is selecting **phase-appropriate services**.

### Common Phase Types

#### Phase 1. Stabilize

Used when:

- cashflow is unstable
- anomalies are unresolved
- recurring burden is too high
- baseline savings behavior is weak

Typical services:

- recurring bill cleanup
- spending alert or anomaly monitoring
- budget reset support
- cashflow discipline coaching

Why these services fit:

- the user is not yet ready for acceleration
- stabilizing the baseline improves every later phase

Exit conditions:

- positive monthly cashflow for a defined period
- anomaly review completed
- recurring burden reduced below threshold

#### Phase 2. Protect Liquidity

Used when:

- runway is low
- liquidity need is high
- the goal cannot safely advance without buffer protection

Typical services:

- emergency fund setup
- liquidity protection
- auto-save activation
- buffer threshold guidance

Why these services fit:

- they reduce fragility before stronger goal execution

Exit conditions:

- minimum buffer threshold reached
- emergency runway target met

#### Phase 3. Accumulate Toward Goal

Used when:

- the baseline is stable enough
- savings behavior can be made systematic
- the user is ready to move toward the target goal

Typical services:

- goal bucket allocation
- auto-save activation
- savings ladder or fixed deposit strategy
- milestone-based savings review

Why these services fit:

- the user now benefits from systematic accumulation rather than just stabilization

Exit conditions:

- target progress threshold reached
- projected path remains on track

#### Phase 4. Readiness Review

Used when:

- the user approaches a target milestone
- the target decision is near
- the user needs fit, timing, or affordability confirmation

Typical services:

- milestone review
- readiness check
- affordability review
- timeline adjustment guidance

Why these services fit:

- this phase decides whether to proceed, pause, or re-scope

Exit conditions:

- proceed to goal execution
- extend accumulation phase
- re-scope target

#### Phase 5. Maturity And Transition

Used when:

- the goal has matured
- the user has reached the target
- the system must decide what comes next

Typical services:

- maturity rollover
- withdraw guidance
- reallocate surplus
- transition to next-goal planning
- reinvest or rebalance support when applicable

Why these services fit:

- roadmap value should continue after milestone completion

Exit conditions:

- next-goal transition defined
- post-goal allocation decision completed

## Maturity And Post-Maturity Flow

This is a key area where the document should be stronger than a generic recommender design.

The roadmap must not end at:

- `milestone achieved`
- `goal amount reached`
- `target date arrived`

Instead, Service Agent should explicitly model:

- maturity events
- maturity decision points
- rollover choices
- reallocation choices
- next-goal transitions

### Example Maturity Events

- emergency fund reaches target runway
- vehicle purchase fund reaches threshold
- education fund reaches deadline
- fixed-term savings product matures
- savings bucket is completed earlier than expected

### Post-Maturity Decision Points

Service Agent should be able to answer:

- should the funds be held, rolled over, reallocated, or used now?
- should the user preserve liquidity instead of deploying funds immediately?
- should surplus move into the next goal?
- should the user transition from accumulation to maintenance?

### Example Post-Maturity Actions

- `rollover`: keep funds in a new savings instrument
- `withdraw`: use the funds for the intended purchase
- `reallocate`: move part of the amount to a new goal
- `transition`: switch roadmap to the next priority goal
- `rebalance`: preserve liquidity while reassigning surplus

### Why This Matters

This is what makes Service Agent a **journey designer** rather than a pre-goal recommender.

## Service Catalog

Service Agent should expose a service catalog that is easy to reason about as a **journey support system**, not as a flat product list.

The catalog should be grouped by functional role in the roadmap.

### 1. Foundational / Stabilization Services

Used when the user is not ready to accelerate toward the goal because the baseline is weak or unstable.

Typical services:

- recurring bill cleanup
- budget reset support
- baseline cashflow discipline setup
- spending control nudges

Use when:

- cashflow is inconsistent
- recurring burden is too high
- there is leakage in spending habits

Best-fit phases:

- `Phase 1. Stabilize`

Required inputs:

- net cashflow
- recurring obligations
- anomaly or volatility signals
- budget discipline context

Expected outcome:

- more predictable monthly surplus
- reduced variance
- better readiness for the next phase

### 2. Protection / Liquidity Services

Used when the user needs a safer base before moving toward a bigger target.

Typical services:

- emergency fund setup
- liquidity protection
- emergency buffer guardrails
- reserve preservation path

Use when:

- emergency runway is low
- liquidity need is high
- the user is vulnerable to short-term shocks

Best-fit phases:

- `Phase 2. Protect Liquidity`

Required inputs:

- runway or buffer
- liquidity need
- income stability
- risk preference

Expected outcome:

- safer baseline
- clearer transition condition into accumulation

### 3. Savings / Accumulation Services

Used when the user is ready to start compounding progress toward the target.

Typical services:

- auto-save activation
- goal bucket allocation
- savings ladder strategy
- fixed deposit strategy
- contribution pacing plan

Use when:

- baseline is stable
- a clear target exists
- accumulation can begin systematically

Best-fit phases:

- `Phase 3. Accumulate Toward Goal`

Required inputs:

- target amount
- target timeline
- savings capacity
- liquidity constraints

Expected outcome:

- measurable goal progress
- more disciplined accumulation
- clearer milestone tracking

### 4. Monitoring / Control Services

Used to keep the user on track while a roadmap is running.

Typical services:

- spending alerts
- anomaly monitoring
- recurring drift watch
- progress deviation alerts

Use when:

- the system needs to detect deviation early
- the user is in a long roadmap with risk of drift

Best-fit phases:

- `Phase 1. Stabilize`
- `Phase 2. Protect Liquidity`
- `Phase 3. Accumulate Toward Goal`

Required inputs:

- anomaly signals
- recurring patterns
- projection vs actual drift

Expected outcome:

- fewer silent regressions
- better roadmap correction timing

### 5. Goal Progression Services

Used to move a user from one stage of the goal to the next.

Typical services:

- goal pacing support
- pace adjustment guidance
- target re-scope guidance
- acceleration recommendations

Use when:

- a goal is on-track but needs pacing control
- the target becomes unrealistic under the current baseline

Best-fit phases:

- `Phase 3. Accumulate Toward Goal`
- `Phase 4. Readiness Review`

Required inputs:

- target amount
- target timeline
- projected outcome
- feasibility signal

Expected outcome:

- clearer path to target
- fewer unrealistic goal assumptions

### 6. Milestone / Review Services

Used when the system needs a formal checkpoint before unlocking the next step.

Typical services:

- milestone review
- readiness check
- affordability review
- progress review checkpoint

Use when:

- the user reaches a milestone
- a transition depends on readiness
- a decision point is approaching

Best-fit phases:

- `Phase 4. Readiness Review`

Required inputs:

- milestone status
- projected outcome
- liquidity and buffer state
- target readiness context

Expected outcome:

- proceed, pause, extend, or re-scope decision

### 7. Maturity / Transition Services

Used when the target is reached or the saving instrument or goal reaches maturity.

Typical services:

- maturity rollover
- withdrawal guidance
- reallocation guidance
- next-goal transition
- reinvest or rebalance support when suitable

Use when:

- a target is achieved
- maturity date is reached
- a completed goal creates surplus capacity

Best-fit phases:

- `Phase 5. Maturity And Transition`

Required inputs:

- maturity event
- current goal state
- liquidity need
- next-goal availability
- suitability or policy context when relevant

Expected outcome:

- clean transition after success
- no dead-end after milestone completion

## Suggested Capability Stack

Service Agent can eventually support many features, but they are not equally important for MVP.

### Core Capability

- Personalized roadmap generation

### Supporting Capabilities

- service recommendation
- next best action selection
- milestone planning
- projected outcome generation
- explainability

### Later-Phase Capabilities

- recommendation ranking
- bundling and package recommendation
- trigger-based recommendation
- advanced suitability interpretation
- richer visualization support
- cross-goal optimization

## Proposed Roadmap Schema

### Input Schema Example

```json
{
  "user_id": "sub-or-canonical-user-id",
  "financial_state": {
    "income_monthly_baseline": 42535000.0,
    "expense_monthly_baseline": 39000000.0,
    "net_cashflow": 3535000.0,
    "emergency_runway_months": 4.2,
    "income_stability": "stable",
    "risk_band": "moderate",
    "planning_readiness": "cautious",
    "anomaly_flags": [],
    "recurring_obligations": [
      {
        "name": "rent",
        "amount": 8500000.0,
        "frequency": "monthly"
      }
    ]
  },
  "goals": [
    {
      "goal_id": "goal_vehicle",
      "goal_type": "car_purchase",
      "target_amount": 300000000.0,
      "target_timeline_months": 24,
      "priority": "high",
      "urgency": "medium"
    }
  ],
  "user_context": {
    "risk_preference": "moderate",
    "liquidity_need": "medium",
    "life_context": "young_professional",
    "household_context": "single"
  },
  "market_context": {
    "status": "not_applicable"
  }
}
```

### Output Schema Example

```json
{
  "agent_id": "service",
  "mission": "personalized_financial_roadmap_generator",
  "journey_type": "stabilize_then_accelerate",
  "roadmap_summary": "Stabilize baseline, protect liquidity, then accelerate toward the vehicle goal with milestone reviews.",
  "fit_explanation": "The user has enough income to pursue the goal, but current runway and readiness suggest a stabilization-first path.",
  "current_phase": "phase_1_stabilize",
  "next_best_action": {
    "title": "Activate a fixed monthly transfer after recurring expense review",
    "reason": "This improves consistency before the goal-acceleration phase.",
    "priority": "high"
  },
  "phases": [],
  "milestones": [],
  "projected_outcomes": [],
  "maturity_events": [],
  "post_maturity_options": [],
  "visualization_support": {}
}
```

### Phase Schema Example

```json
{
  "phase_id": "phase_2_accumulate",
  "title": "Accumulate Goal Fund",
  "objective": "Build a dedicated savings path toward the target amount.",
  "why_now": "Baseline stability and minimum liquidity protection have been achieved.",
  "entry_condition": "Positive cashflow baseline and minimum runway threshold met",
  "actions": [
    "activate auto-save",
    "fund a dedicated goal bucket",
    "review savings pace monthly"
  ],
  "recommended_services": [
    {
      "service_type": "goal_bucket_allocation",
      "reason": "Creates visible separation between goal money and day-to-day spend.",
      "priority": "high"
    },
    {
      "service_type": "savings_ladder_or_fixed_deposit_strategy",
      "reason": "Supports more structured accumulation while preserving clarity on maturity dates.",
      "priority": "medium"
    }
  ],
  "expected_result": {
    "goal_progress_target": 0.25,
    "projected_phase_duration_months": 6
  },
  "exit_condition": "Goal progress reaches 25 percent and liquidity protection remains intact"
}
```

### Milestone Schema Example

```json
{
  "milestone_id": "m_goal_25pct",
  "phase_id": "phase_2_accumulate",
  "title": "25 Percent Goal Progress",
  "target_metric": "goal_progress",
  "target_value": 0.25,
  "current_value": 0.12,
  "status": "pending",
  "unlocks": "phase_3_readiness_review"
}
```

### Projected Outcome Schema Example

```json
{
  "timeline_month": 6,
  "projected_goal_progress": 0.28,
  "projected_buffer": 95000000.0,
  "projected_state": "on_track_if_baseline_holds",
  "assumptions": [
    "income remains stable",
    "auto-save stays active",
    "no unresolved anomaly spike"
  ]
}
```

### Maturity Event Schema Example

```json
{
  "event_id": "mat_goal_vehicle_ready",
  "trigger": "goal_progress >= 1.0 or target_date_reached",
  "decision_points": [
    "buy_now",
    "delay_purchase",
    "rollover_funds",
    "reallocate_to_next_goal"
  ],
  "recommended_default": "buy_now_if_buffer_preserved"
}
```

## Visualization Contract

Visualization is an output and support layer.

It should not become the reasoning layer and should not redefine roadmap logic. The role of the visualization contract is to let frontend or demo surfaces render the roadmap consistently from Service Agent output.

### Supported Visualization Types

- roadmap timeline
- phase cards
- milestone cards
- progress-to-goal widget
- projected amount or balance over time
- current state vs target state comparison
- maturity and next-step markers
- next-best-action card

### Visualization Payload Example

```json
{
  "visualization_support": {
    "timeline_nodes": [
      {
        "id": "phase_1_stabilize",
        "label": "Stabilize",
        "status": "current",
        "start_month": 0,
        "end_month": 2,
        "objective": "Make monthly surplus predictable"
      },
      {
        "id": "phase_2_protect",
        "label": "Protect Liquidity",
        "status": "upcoming",
        "start_month": 2,
        "end_month": 5,
        "objective": "Reach minimum protected runway"
      }
    ],
    "phase_cards": [
      {
        "phase_id": "phase_1_stabilize",
        "title": "Stabilize Monthly Baseline",
        "objective": "Reduce variance and make savings behavior repeatable",
        "services": [
          "recurring_bill_cleanup",
          "spending_alert_monitoring"
        ],
        "milestone_ids": [
          "m_stable_cashflow_2m"
        ],
        "exit_condition": "Two consecutive months of positive cashflow"
      }
    ],
    "milestones": [
      {
        "milestone_id": "m_stable_cashflow_2m",
        "title": "2 Stable Months",
        "current_value": 1,
        "target_value": 2,
        "unit": "months",
        "status": "in_progress"
      }
    ],
    "projection_series": [
      {
        "series_id": "goal_progress",
        "label": "Goal Progress",
        "points": [
          {"month": 0, "value": 0.12},
          {"month": 3, "value": 0.18},
          {"month": 6, "value": 0.28},
          {"month": 12, "value": 0.49}
        ]
      },
      {
        "series_id": "buffer_balance",
        "label": "Emergency Buffer",
        "points": [
          {"month": 0, "value": 42000000.0},
          {"month": 3, "value": 56000000.0},
          {"month": 6, "value": 71000000.0}
        ]
      }
    ],
    "goal_progress": {
      "current_amount": 36000000.0,
      "target_amount": 300000000.0,
      "current_ratio": 0.12,
      "required_monthly_pace": 12500000.0,
      "projected_monthly_pace": 11800000.0
    },
    "state_comparison": {
      "current_state": {
        "net_cashflow": 4200000.0,
        "runway_months": 2.4
      },
      "target_state": {
        "net_cashflow": 7000000.0,
        "runway_months": 4.0
      }
    },
    "maturity_markers": [
      {
        "event_id": "mat_goal_vehicle_ready",
        "month": 18,
        "label": "Vehicle Goal Maturity",
        "next_options": [
          "buy_now",
          "delay_purchase",
          "reallocate_to_next_goal"
        ]
      }
    ],
    "next_best_action_card": {
      "title": "Activate auto-save",
      "reason": "This is the highest-leverage action for the current phase.",
      "priority": "high"
    }
  }
}
```

### UI Mapping

The contract should make frontend rendering obvious.

| Roadmap field | UI component |
|---|---|
| `phase_sequence`, `phases`, `timeline_nodes` | roadmap timeline |
| `phases[*]` | phase cards |
| `milestones` | milestone cards |
| `projected_outcomes`, `projection_series` | progress chart / projected amount chart |
| `goal_progress`, `state_comparison` | current vs target summary widgets |
| `maturity_events`, `maturity_markers` | maturity banner / next-step markers |
| `next_best_action` or `next_best_action_card` | CTA card |

### Visualization Principles

- visualization should never replace roadmap reasoning
- visualization should be derivable directly from structured roadmap output
- the same roadmap should render consistently across demo screens and future product surfaces

## Frontend Rendering Model

Frontend should render Service Agent roadmap output directly from structured fields whenever possible.

The target rendering model is:

```text
Planner
-> structured financial state

Service Agent
-> structured roadmap contract

Orchestrator
-> pass-through or minimal merge

Frontend
-> direct roadmap rendering
```

### Rendering Principles

- frontend should not depend on orchestrator paraphrasing Service output into prose
- frontend should read UI-ready fields from Service Agent output
- visualization is a render layer over structured roadmap fields
- prose can still exist as support text, but it should not be the primary contract for roadmap UI

### Field-To-UI Mapping

| Service output field | Frontend render target |
|---|---|
| `roadmap_summary`, `fit_explanation` | roadmap header / overview panel |
| `current_phase`, `phase_sequence`, `phases` | roadmap timeline and phase cards |
| `milestones` | milestone cards / progress checkpoints |
| `projected_outcomes`, `projection_series` | projected chart / goal trajectory |
| `goal_progress`, `state_comparison` | current vs target summary widgets |
| `maturity_events`, `maturity_markers`, `post_maturity_options` | maturity banner / next-step panel |
| `next_best_action`, `next_best_action_card` | CTA card |
| `service_recommendations` | per-phase service block or recommendation drawer |

### Why This Matters

If Service Agent output is already structured and product-shaped:

- orchestrator does less unnecessary rewriting
- frontend becomes easier to build
- demo quality improves immediately
- roadmap UI remains faithful to the agent contract

## Demo-Ready Scenarios

The scenarios below are written for hackathon demo and pitch use, not just internal examples. Each one is structured so a team can present:

- the user
- the goal
- the current state
- why the roadmap fits
- the phase progression
- the services by phase
- the milestones and projected outcomes
- what happens at maturity
- what the UI would show

### Scenario 1. Buy A Car In 18 Months

#### 1. User Profile / Context

- 27 years old
- salaried office worker
- moderate risk preference
- medium liquidity need
- wants to buy a car in 18 months

#### 2. Goal

- buy a car worth `300,000,000 VND`
- target timeline: `18 months`
- priority: `high`

#### 3. Current Financial State

- monthly income baseline: `42,500,000 VND`
- monthly expense baseline: `38,300,000 VND`
- net cashflow: `4,200,000 VND`
- emergency runway: `2.4 months`
- current saved toward goal: `36,000,000 VND`
- anomaly state: `none active`
- readiness: `cautious`

#### 4. Why This Roadmap Fits

The user has enough income to pursue the car goal, but not enough buffer to accelerate safely from day one. A stabilization-first, then liquidity-protection, then accumulation path fits better than an aggressive save-now path.

#### 5. Phase-By-Phase Roadmap

Journey pattern:

`stabilize -> protect liquidity -> accumulate -> readiness review -> maturity decision`

Phase 1. Stabilize (`Month 0-2`)

- objective: make monthly surplus consistent
- services: recurring bill cleanup, spending alert monitoring
- expected result: net cashflow improves from `4.2M` to `6.0M VND`
- milestone: `2 stable months of positive cashflow`

Phase 2. Protect Liquidity (`Month 2-5`)

- objective: raise runway before aggressive saving
- services: emergency fund setup, auto-save activation, liquidity guardrails
- expected result: runway improves from `2.4` to `4.0 months`
- milestone: protected buffer reaches `70,000,000 VND`

Phase 3. Accumulate (`Month 5-14`)

- objective: build dedicated car fund
- services: goal bucket allocation, savings ladder or fixed deposit strategy
- expected result: goal progress reaches `65-75%`
- milestones:
  - `25% goal progress` by `Month 8`
  - `50% goal progress` by `Month 11`

Phase 4. Readiness Review (`Month 14-16`)

- objective: confirm affordability and timeline feasibility
- services: milestone review, readiness check
- expected result: decision on `buy now vs extend 3 months`
- milestone: `purchase-ready review completed`

Phase 5. Maturity Decision (`Month 16-18`)

- objective: choose the post-goal action
- services: maturity rollover or use-now decision support
- expected result: one of:
  - `buy now`
  - `delay purchase`
  - `reallocate to next goal`

#### 6. Recommended Services By Phase

- `Month 0-2`: recurring bill cleanup, spending alert monitoring
- `Month 2-5`: emergency fund setup, liquidity protection, auto-save activation
- `Month 5-14`: goal bucket allocation, savings ladder strategy
- `Month 14-16`: readiness check, milestone review
- `Month 16-18`: maturity rollover or deploy-now guidance

#### 7. Milestones

- `Month 2`: 2 stable months achieved
- `Month 5`: runway reaches `4.0 months`
- `Month 8`: 25% of goal funded
- `Month 11`: 50% of goal funded
- `Month 16`: readiness review decision
- `Month 18`: maturity / final choice

#### 8. Projected Outcome

- projected goal progress at `Month 6`: `28%`
- projected goal progress at `Month 12`: `56%`
- projected outcome at `Month 18`: `buy-now ready if monthly savings pace reaches 11-12M`

#### 9. Maturity / What Happens Next

At maturity:

- if buffer remains above threshold -> proceed with purchase
- if buffer drops below threshold -> extend by `3 months`
- if priorities change -> reallocate to next goal

#### 10. Next Best Action Right Now

- activate auto-save and bind it to a dedicated vehicle bucket this month

#### 11. Visualization Highlights

- roadmap timeline with 5 nodes
- progress-to-goal chart
- milestone cards at `Month 2`, `5`, `8`, `11`, `16`
- maturity decision marker at `Month 18`

#### 12. If User Falls Behind

If goal progress is below `45%` by `Month 11`:

- the system should keep the user in accumulation phase longer
- reduce aggressiveness of the purchase timeline
- re-run readiness path with a revised target date

### Scenario 2. Build An Emergency Fund

#### 1. User Profile / Context

- 31 years old
- moderate income stability
- low risk appetite
- very high liquidity need

#### 2. Goal

- build an emergency fund equal to `6 months` of essential expenses
- target timeline: `12 months`

#### 3. Current Financial State

- monthly income baseline: `29,000,000 VND`
- monthly essential expenses: `18,000,000 VND`
- net cashflow: `3,500,000 VND`
- emergency runway: `1.2 months`
- anomaly state: `none active`
- readiness: `cautious`

#### 4. Why This Roadmap Fits

The user is not trying to buy a large asset. The primary problem is fragility. The roadmap should focus on protection first, not acceleration.

#### 5. Phase-By-Phase Roadmap

Journey pattern:

`stabilize -> protect liquidity -> scale reserve -> maturity maintenance`

Phase 1. Stabilize (`Month 0-1`)

- objective: stop leakages and define a fixed reserve contribution
- services: spending alerts, recurring bill cleanup
- milestone: first consistent monthly reserve contribution

Phase 2. Protect Liquidity (`Month 1-4`)

- objective: reach `3 months` runway
- services: emergency fund setup, auto-save activation, liquidity guardrails
- milestone: runway reaches `3.0 months`

Phase 3. Scale Reserve (`Month 4-10`)

- objective: move from `3` to `6 months` runway
- services: reserve contribution plan, goal bucket allocation
- milestones:
  - `4 months runway`
  - `6 months runway`

Phase 4. Maturity Maintenance (`Month 10-12`)

- objective: protect the fund after completion
- services: maturity rollover, buffer maintenance guidance
- outcome: reserve remains ring-fenced and not diluted prematurely

#### 6. Recommended Services By Phase

- `Month 0-1`: spending alerts, recurring bill cleanup
- `Month 1-4`: emergency fund setup, auto-save activation, liquidity guardrails
- `Month 4-10`: reserve contribution plan, goal bucket allocation
- `Month 10-12`: maturity rollover, maintenance guidance

#### 7. Milestones

- `Month 1`: first reserve contribution locked in
- `Month 4`: 3 months runway
- `Month 7`: 4 months runway
- `Month 10`: 6 months runway
- `Month 12`: reserve maintenance decision

#### 8. Projected Outcome

- projected runway at `Month 4`: `3.0 months`
- projected runway at `Month 10`: `6.0 months`
- projected state: `fragile -> watch -> stable`

#### 9. Maturity / What Happens Next

At maturity:

- preserve fund as ring-fenced liquidity reserve
- only redirect new surplus to another goal after the reserve is stable for `2-3 months`

#### 10. Next Best Action Right Now

- activate a dedicated emergency transfer immediately after salary receipt

#### 11. Visualization Highlights

- runway-over-time chart
- reserve milestone cards
- current state vs safe state comparison
- maturity maintenance banner

### Scenario 3. Save For Wedding Or Education

#### 1. User Profile / Context

- 29 years old
- stable salary
- moderate risk preference
- moderate liquidity need
- emotionally important medium-term goal

#### 2. Goal

- save `180,000,000 VND`
- target timeline: `15 months`
- use case: wedding or education fund

#### 3. Current Financial State

- monthly income baseline: `35,000,000 VND`
- monthly expenses: `27,000,000 VND`
- net cashflow: `8,000,000 VND`
- current goal savings: `22,000,000 VND`
- runway: `3.2 months`
- anomaly state: mild spend volatility

#### 4. Why This Roadmap Fits

The user has a workable monthly surplus, but the goal is emotionally important and time-bound. The roadmap should focus on disciplined accumulation with milestone reviews and an explicit decision path near maturity.

#### 5. Phase-By-Phase Roadmap

Journey pattern:

`stabilize -> accumulate -> milestone review -> maturity -> next-goal transition`

Phase 1. Stabilize (`Month 0-2`)

- objective: reduce volatility and protect contribution discipline
- services: recurring bill cleanup, spending alert monitoring
- milestone: two clean months with stable contribution behavior

Phase 2. Accumulate (`Month 2-11`)

- objective: build the dedicated goal fund
- services: auto-save activation, goal bucket allocation, savings ladder strategy
- milestones:
  - `25% funded` by `Month 5`
  - `50% funded` by `Month 8`
  - `75% funded` by `Month 11`

Phase 3. Milestone Review (`Month 11-13`)

- objective: confirm whether target timing remains realistic
- services: milestone review, target pace review
- decision point: keep pace or extend `2-3 months`

Phase 4. Maturity (`Month 13-15`)

- objective: decide deployment at target date
- services: maturity decision support
- decision point: deploy now, partially deploy, or hold buffer

Phase 5. Next-Goal Transition (`Post-Maturity`)

- objective: turn a completed goal into a clean next chapter
- services: transition recommendation, next-goal setup

#### 6. Recommended Services By Phase

- `Month 0-2`: recurring bill cleanup, spending alerts
- `Month 2-11`: auto-save activation, goal bucket allocation, savings ladder
- `Month 11-13`: milestone review, pace review
- `Month 13-15`: maturity decision support
- `Post-Maturity`: next-goal transition

#### 7. Milestones

- `Month 2`: contribution behavior stabilized
- `Month 5`: 25% funded
- `Month 8`: 50% funded
- `Month 11`: 75% funded
- `Month 13`: review decision
- `Month 15`: maturity action

#### 8. Projected Outcome

- projected progress at `Month 5`: `27%`
- projected progress at `Month 8`: `52%`
- projected progress at `Month 11`: `74%`
- projected maturity state: `on-track if monthly contribution remains >= 10.5M`

#### 9. Maturity / What Happens Next

At maturity:

- if target is fully reached -> deploy to the intended purpose
- if short by less than `10%` -> extend accumulation by `2-3 months`
- if priorities shift -> reallocate part of the fund and transition to the next goal

#### 10. Next Best Action Right Now

- activate a dedicated goal bucket and lock a fixed monthly transfer this cycle

#### 11. Visualization Highlights

- phase cards with monthly markers
- goal-progress chart with projected vs required pace
- milestone cards at `25%`, `50%`, `75%`
- maturity marker with deploy / extend / transition choices

## Hackathon Fit

This direction is strong for a hackathon because it is:

- **user-centric**
  - users see a path, not just a diagnosis
- **easy to demo**
  - phases and milestones create a compelling story
- **high wow factor**
  - roadmap output feels like a real product, not just a model response
- **differentiated**
  - stronger than a plain recommender or a generic budgeting assistant
- **compatible with the existing stack**
  - Planner provides the state
  - Service Agent turns that state into a path
  - Stock Agent remains optional context for investing-specific cases
- **visualization-friendly**
  - roadmap cards and maturity events are demo-ready

For hackathon storytelling, this moves the system from:

`financial analysis assistant`

to:

`personalized financial journey designer`

## Recommended MVP Scope

This must be extremely clear:

**The MVP should focus on one core function only.**

That function is:

**Personalized Financial Roadmap Generator**

### MVP Goal

Take:

- planner financial state
- one primary user goal
- user context

and produce:

- roadmap summary
- current phase
- 2 to 4 phases
- service recommendations bound to each phase
- milestones
- projected outcome
- next best action
- maturity and post-maturity next step

### Supporting Features In MVP

These can exist only in support of the roadmap:

- simple recommendation ranking
- simple explainability
- simple milestone projection
- simple visualization payloads

### Not Core To MVP

These should be clearly treated as later-phase enhancements:

- advanced recommendation ranking
- sophisticated bundling
- trigger-based recommendation engines
- advanced suitability logic
- deep catalog optimization
- broad multi-goal orchestration
- visualization polish beyond roadmap support

### Why This MVP Is The Right One

- it is tightly aligned with product vision
- it is distinct from Planner Agent
- it is easier to explain to judges and users
- it can reuse the current architecture and grounded finance state

## Implementation Guidance For Hackathon

### 1. Database Principle

- add only minimal goal schema needed for roadmap timing and maturity
- avoid building a large profile store
- prefer durable goal facts over speculative profile fields

### 2. Planner Integration Principle

- Planner remains the source of structured financial state
- Service Agent should consume planner-derived state first
- do not duplicate finance analytics in Service Agent

### 3. Orchestrator Integration Principle

- Planner output may need synthesis
- Service output should be validated and passed through as structured contract
- keep merge behavior minimal when roadmap UI is the target surface

### 4. Frontend Integration Principle

- frontend should render roadmap directly from Service Agent fields
- visualization payloads should be consumed as-is where possible
- prose should support the UI, not replace the roadmap contract

## Best Recommendation And Final Proposal

The best final framing is:

**Service Agent = Personalized Financial Roadmap Agent**

More specifically:

**Service Agent = a journey-design specialist that converts financial state + user goal + user context into a phase-based execution path with services, milestones, projected outcomes, and maturity transitions.**

That is the strongest, clearest, and most differentiated interpretation for the current system.

## Non-Goals

Service Agent should **not**:

- become a second Planner Agent
- re-run raw transaction analytics when Planner already produced structured state
- duplicate risk, anomaly, recurring, or cashflow engines
- become a loose recommendation engine with no journey logic
- produce generic service lists detached from phase and goal progression
- collapse planning, service, and stock logic into one opaque layer
- change the orchestrator flow
- replace Stock Agent for investment-specific questions

## Final Design Principle

The clean long-term split should be:

```text
Planner Agent
-> Understand the user's financial state

Service Agent
-> Design the user's personalized financial journey

Stock Agent
-> Explain investment and stock-specific opportunities and risks

Orchestrator
-> Route, combine, and present the right specialist outputs
```

This is the most stable interpretation of Service Agent for the current repo and the best fit for the product vision.
