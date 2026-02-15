# PROJECT_STACK Comparison vs Previous Commit

Compared file: `PROJECT_STACK.md`  
Baseline commit: `6f4cfe1` (HEAD at comparison time)  
Comparison method: `git diff HEAD -- PROJECT_STACK.md`

## Diff Summary
- Files changed: `1`
- Net changes in `PROJECT_STACK.md`: `100 insertions`, `3 deletions`
- Scope: documentation and architecture specification updates only (no code execution logic changed in this report).

## What Changed and Why

### 1) Problem framing was made explicit
- Added `Problem & scope focus (report alignment)` near the top.
- Added `Current product gap (report alignment)` under current snapshot.
- Why:
  - Clarifies that jars are currently operational tags/categorization anchors.
  - Makes the gap explicit: no first-class monthly planning contract yet.
  - Aligns narrative with report scoring criteria (problem, who affected, why now).

### 2) Monthly planner was productized (planned)
- Added planned endpoints:
  - `POST /planner/monthly-targets`
  - `POST /planner/apply`
- Added planned tool:
  - `jar_targets_plan_v1`
- Updated repo responsibility note to include monthly plan UI screen.
- Why:
  - Converts jar guidance from static hinting into actionable monthly targets.
  - Defines a clear `generate -> approve -> persist` loop using existing primitives.

### 3) Planning logic now specifies monthly target semantics
- Added `Goal Planner + Monthly Jar Targets (planned MVP)` section.
- Introduced two target classes:
  - spending caps (monthly limits)
  - contribution targets (monthly savings toward goals)
- Added planner path:
  - read tools -> build 3 options -> run gates -> apply via `budgets_get_set` + `goals_get_set` -> audit.
- Why:
  - Directly addresses the core gap: "jar split" is not equal to "monthly plan target".

### 4) 3-option trade-off contract was formalized
- Added `Trade-off 3 Options Output Contract (v1, planned)`.
- Enforced exactly 3 options: `conservative`, `balanced`, `growth`.
- Added JSON payload contract with fields:
  - `jar_caps`, `jar_contributions`, `goal_eta_days_or_months`, `runway_days`,
  - `overspend_risk_flag`, `tradeoff_summary`, `who_it_fits`, `actions_to_apply`.
- Why:
  - Makes output deterministic, testable, and ready for UI "Apply" behavior.

### 5) Governance gates were strengthened and made always-on (planned)
- Added explicit heading `Best-interest + Data Sufficiency Gates (always-on, planned)`.
- Expanded planned guard set:
  - suitability, best-interest, data sufficiency.
- Added planned policy bundles and reason-code-driven decisions.
- Why:
  - Improves compliance posture and avoids implicit policy behavior.
  - Matches report requirement for suitability + best-interest + explainable decisions.

### 6) Tier1 monitoring now links to applied monthly targets (planned extension)
- Added Tier1 deviation monitor note:
  - compare month-to-date actuals against applied budgets/goals targets.
- Why:
  - Closes the loop from planning to proactive monitoring.
  - Enables meaningful alerts for goal/cap drift instead of only anomaly thresholds.

### 7) End-to-end and governance diagrams were updated
- Added "Monthly Plan + Apply" path in lifecycle sequence.
- Updated tool-selection flow to include planner and gating node.
- Updated governance flow to include planner + best-interest + data sufficiency tools.
- Why:
  - Keeps architecture docs consistent with newly added planner behavior.
  - Prevents mismatch between text and diagrams during review/demo.

### 8) KPI/experiment layer was expanded (planned)
- Added AWS experimentation/KPI stack:
  - AppConfig, EventBridge, Firehose, S3, Athena, QuickSight.
- Added KPI and pilot evaluation sections.
- Why:
  - Supports business-impact measurement required by the report.
  - Provides a practical path for offline + pilot validation.

## High-Impact Changes (Quick Index)
- Problem and gap sections: `PROJECT_STACK.md` (`Problem & scope focus`, `Current product gap`)
- Planner endpoints: `PROJECT_STACK.md` API endpoint table (`/planner/monthly-targets`, `/planner/apply`)
- Planner tool: `PROJECT_STACK.md` tool catalog (`jar_targets_plan_v1`)
- Monthly planner module: `PROJECT_STACK.md` (`Goal Planner + Monthly Jar Targets (planned MVP)`)
- 3-option contract: `PROJECT_STACK.md` (`Trade-off 3 Options Output Contract (v1, planned)`)
- Demo story: `PROJECT_STACK.md` (`Demo story (hackathon, 5 steps)`)

## Notes
- This comparison is against current working tree state vs `HEAD` (`6f4cfe1`).
- `PROJECT_STACK.md` is currently modified in both staged and unstaged states (`MM`), and the diff above reflects the aggregate current state.
