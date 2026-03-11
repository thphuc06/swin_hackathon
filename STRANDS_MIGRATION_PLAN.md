## Strands Migration Plan

### Purpose

This document defines how to adopt Strands in this repo without breaking the target multi-agent architecture already described in `MULTI_AGENT_SPECIALIST_MCP_ARCHITECTURE.md`.

The target remains:

- one top-level orchestrator on AgentCore Runtime
- one `specialist-agent-mcp` plane behind AgentCore Gateway
- one planner specialist behind `run_planner_agent_v1`
- one stock specialist behind `run_stock_agent_v1`
- one raw finance MCP plane behind planner

### Scope And Non-Goals

In scope:

- migrate the orchestrator implementation from the current custom LangGraph-centric runtime toward Strands-based orchestration
- migrate planner implementation to Strands
- keep AWS AgentCore Runtime, Gateway, Identity, and the current multi-agent topology
- define what AWS-side changes are required, optional, or not needed

Out of scope:

- reimplementing the stock service
- changing frontend or backend API contracts
- replacing AgentCore Gateway with another integration layer
- moving deterministic finance tools out of the finance MCP plane

Hard constraint:

- `stock-agent` stays as an external HTTPS service running on App Runner
- `run_stock_agent_v1` remains a thin wrapper around that existing service

### Executive Summary

Adopting Strands does not require changing the high-level AWS topology. The main change is at the agent implementation layer.

Recommended target:

- orchestrator: Strands Graph on AgentCore Runtime
- planner: Strands-based specialist called through `specialist-agent-mcp`
- stock: unchanged external HTTPS specialist on App Runner
- finance tools: unchanged MCP plane

Do not convert the top-level orchestrator into a free-form autonomous tool loop. Keep top-level routing, safety, memory, audit, and delegation deterministic. Use model-assisted tool selection inside planner, not across the entire platform.

### Current Architecture

Current runtime behavior in this repo is effectively:

- semantic intent extraction
- deterministic fixed tool bundles by intent
- a hardcoded `planner_internal | stock_external` branch
- direct raw tool execution from the top-level runtime

This is workable for the current scope, but it does not match the target architecture where planner should own planning-domain tool strategy and the orchestrator should own delegation strategy only.

### Target Architecture With Strands

#### Topology

The topology does not need to change:

```text
Frontend
-> Backend
-> AgentCore Runtime Orchestrator
-> AgentCore Gateway
-> specialist-agent-mcp
   -> run_planner_agent_v1 -> planner specialist -> finance-tools-mcp / retrieval / future market tools
   -> run_stock_agent_v1   -> existing stock HTTPS service on App Runner
```

#### Framework Mapping

Recommended framework ownership:

| Service | Target implementation |
| --- | --- |
| `orchestrator-runtime` | Strands Graph on AgentCore Runtime |
| `specialist-agent-mcp` | Thin custom MCP server, not a reasoning-heavy agent |
| `planner-agent` | Strands specialist |
| `stock-agent` | Existing HTTPS service, unchanged |
| `finance-tools-mcp` | Existing MCP server, unchanged |

#### Control Model

Recommended control split:

- orchestrator chooses specialists
- planner chooses planning-domain raw tools
- stock service keeps its own domain logic
- top-level safety, policy, memory, and audit stay at orchestrator

This changes the current model from:

```text
orchestrator -> raw finance tools
```

to:

```text
orchestrator -> planner specialist -> raw finance tools
```

### What Changes In AWS

Strands is compatible with AgentCore Runtime and Gateway. AWS changes are mostly driven by deployment and optional feature adoption, not by a required platform redesign.

#### AWS Changes Required

| Area | Required change | Why |
| --- | --- | --- |
| AgentCore Runtime | Redeploy orchestrator image with Strands-based runtime code | Framework implementation changes live in the runtime container |
| Runtime dependencies | Add Strands packages and remove no-longer-needed orchestration dependencies | The runtime code changes from LangGraph-centric to Strands-centric |
| Gateway target config | Register `specialist-agent-mcp` if not already present in the final architecture | Required by the target specialist-as-tool design |

#### AWS Changes Optional

| Area | Optional change | Why |
| --- | --- | --- |
| AgentCore Memory | Create or wire AgentCore Memory if the orchestrator moves from local session memory to `AgentCoreMemorySessionManager` | Better managed memory and session persistence |
| Observability | Add ADOT instrumentation and map Strands hooks to AgentCore traces/metrics | Better debugging and per-hop visibility |
| IAM permissions | Add permissions for Memory or additional telemetry destinations if those features are enabled | Needed only if those features are adopted |
| Gateway auth details | Adjust inbound or outbound auth only if new gateway targets require it | Not required by Strands itself |

#### AWS Changes Not Required By Strands Itself

| Area | Keep as-is |
| --- | --- |
| AgentCore Gateway concept | Still the right integration layer |
| Inbound JWT authorizer model | Can stay unchanged |
| Workload access token pattern | Can stay unchanged |
| App Runner stock service | Can stay unchanged |
| Finance MCP plane | Can stay unchanged |

### Detailed Implementation Changes

#### 1. Orchestrator Runtime

Current role to keep:

- intake
- auth context handling
- routing
- policy gates
- delegation planning
- aggregation
- grounded response synthesis
- session memory ownership
- audit ownership

Implementation change:

- replace the current custom LangGraph-centric orchestration path with Strands Graph or an equivalent Strands workflow structure
- keep deterministic node boundaries rather than moving to a fully autonomous free-form loop

Do not change:

- runtime remains hosted on AgentCore Runtime
- orchestrator remains the only user-facing agent

#### 2. Planner Specialist

Planner is the main place where Strands should add value.

Planner responsibilities after migration:

- choose and call finance tools
- call retrieval when needed
- later call market or news tools when those planes exist
- return a structured planner result envelope

Planner should not own:

- user-facing session memory
- top-level audit record
- top-level policy gates

#### 3. Stock Specialist

Stock stays unchanged:

- existing HTTPS server on App Runner
- called via `run_stock_agent_v1`
- not reimplemented in this migration

The only expected change is architectural normalization:

- orchestrator no longer hardcodes a stock execution branch
- stock is invoked as a specialist tool through the specialist MCP plane

#### 4. Specialist MCP Plane

`specialist-agent-mcp` should remain thin.

Responsibilities:

- expose stable MCP tool contracts
- validate request schema
- forward planner calls to planner specialist
- forward stock calls to the existing App Runner stock service
- return structured outputs and error envelopes

Do not turn this layer into a second orchestrator.

#### 5. Finance MCP Plane

No architectural change is required.

Finance MCP remains:

- deterministic
- typed
- auditable
- owned by planner, not by the top-level orchestrator

### Tool Selection Strategy

#### Current State

Current behavior is:

- semantic intent extraction at the router
- fixed tool bundle mapping by intent
- policy gate before execution
- direct raw tool execution at the top-level runtime

#### Recommended Routing Logic

The target routing model should be explicitly two-level.

Level 1: orchestrator semantic delegation

- the orchestrator performs semantic understanding at the request level
- it decides which specialist should own the task
- it uses agent catalog metadata, policy constraints, and safety gates to produce a delegation decision
- it should choose between specialist tools such as `run_planner_agent_v1`, `run_stock_agent_v1`, and future specialist tools

Level 2: specialist semantic execution

- once a specialist is selected, that specialist performs semantic reasoning inside its own domain
- planner chooses planning-domain raw tools
- stock keeps its domain-specific reasoning in its own service

This means semantic reasoning is not limited to planner. It exists at both layers, but with different responsibilities.

Recommended responsibility split:

| Layer | Semantic responsibility | What it should choose |
| --- | --- | --- |
| Orchestrator | request-level delegation reasoning | specialist agent/tool |
| Planner specialist | planning-domain execution reasoning | raw finance, retrieval, and future planning tools |
| Stock specialist | investment-domain execution reasoning | its own domain logic and any internal downstream calls |

Important rule:

- top-level orchestrator should reason about `which specialist`
- planner should reason about `which raw tools`
- top-level orchestrator should not reason over the full raw tool universe for all domains

#### Recommended State

Top-level orchestrator:

- use semantic routing plus deterministic specialist delegation
- choose `run_planner_agent_v1`, `run_stock_agent_v1`, or future specialist tools
- do not let the top-level model freely choose from all raw finance tools

Planner specialist:

- use model-assisted tool selection inside a bounded planning-domain tool set
- optionally use Strands MCP tooling and agent-as-tool patterns internally

This is the recommended compromise:

- deterministic at the platform boundary
- flexible inside the domain specialist

#### What This Replaces

The migration should replace:

```text
semantic intent -> fixed raw tool bundle -> hardcoded planner vs stock branch
```

with:

```text
semantic request understanding -> specialist delegation -> specialist-owned semantic tool selection
```

In practical terms:

- the orchestrator should still reason
- the orchestrator should reason about specialists, not all raw tools
- planner should own the planning bundle
- stock remains an external specialist and is not reimplemented here

### Memory Plan

Recommended rule:

- only the orchestrator owns conversation state and persistent session memory
- specialists remain stateless from the end-user conversation point of view

Two valid implementation options exist:

#### Option A: Keep existing session memory first

Pros:

- lower migration risk
- avoids changing memory semantics during framework migration

Cons:

- less alignment with managed AgentCore Memory

#### Option B: Move orchestrator to AgentCore Memory

Pros:

- better alignment with AgentCore-native managed memory
- easier long-term standardization if the platform grows

Cons:

- adds AWS resource and configuration work
- requires memory migration testing

Recommendation:

- phase the memory migration after orchestration migration, not before

### Observability Plan

AgentCore Runtime already provides built-in metrics and traces. Strands adds useful hook and metric surfaces at the application layer.

Recommended observability model:

- keep AgentCore observability enabled
- keep business audit events in the orchestrator
- add Strands hooks for per-step runtime telemetry
- preserve trace correlation fields across all boundaries

Standard fields to propagate:

- `trace_id`
- `request_id`
- `session_id`
- `agent_name`
- `tool_name`
- `schema_version`
- `latency_ms`
- `reason_codes`
- `fallback_used`

### Identity And Auth Plan

Strands does not require changing the identity model.

Keep:

- inbound JWT authorizer for Runtime and Gateway
- workload access token model for first-party AgentCore services
- existing bearer-token propagation approach where required

Only change identity config if:

- the new specialist MCP plane needs different inbound auth
- new gateway targets need outbound auth setup
- AgentCore Memory or other first-party services are added and require additional permissions

### Repo-Level Change Plan

#### Keep

- `agent/main.py` as the AgentCore Runtime entrypoint pattern
- `agent/response/`
- `agent/policy/`
- backend and frontend API contracts
- `src/aws-finance-mcp-server/`

#### Refactor

- `agent/graph.py`
- `agent/orchestrator/`
- `agent/tools.py`
- `agent/memory/` if and only if moving to AgentCore Memory

#### Add

- `src/aws-specialist-agent-mcp-server/`
- `agent/subagents/contracts.py`
- `agent/subagents/catalog.py`
- `agent/subagents/selection.py`
- `planner_agent/` or another package for the Strands-based planner specialist
- `STRANDS_MIGRATION_PLAN.md` already added by this document

### Proposed Migration Phases

#### Phase 0: Freeze External Contracts

Deliverables:

- `AgentResultEnvelope`
- `PlannerResult`
- `StockResult`
- `agent_catalog.yaml`
- versioned MCP schemas for `run_planner_agent_v1` and `run_stock_agent_v1`

Success criteria:

- orchestrator can consume specialist results without caring about internal implementation

#### Phase 1: Create `specialist-agent-mcp`

Deliverables:

- thin MCP server exposing `run_planner_agent_v1`
- thin MCP server exposing `run_stock_agent_v1`
- stock wrapper forwarding to the existing App Runner HTTPS server

Success criteria:

- orchestrator can invoke planner and stock through Gateway
- no direct stock execution branch remains required in the orchestrator design

#### Phase 2: Introduce Strands Planner Specialist

Deliverables:

- Strands-based planner service or package
- planner contract adapters
- planner-owned tool selection for finance MCP

Success criteria:

- planner can call finance MCP and return a structured result envelope
- top-level runtime no longer owns planning-domain raw tool strategy

#### Phase 3: Migrate Orchestrator To Strands Graph

Deliverables:

- Strands Graph replacing the current LangGraph-centric orchestration path
- deterministic nodes for intake, route, safety, delegation, aggregation, response, and memory

Success criteria:

- top-level routing and audit behavior are preserved
- orchestration logic is slimmer and specialist-oriented

#### Phase 4: Wire Memory Strategy

Option A:

- keep current memory implementation

Option B:

- adopt AgentCore Memory at orchestrator level

Success criteria:

- only one memory owner exists for the user conversation
- session continuity survives the migration

#### Phase 5: Wire Observability And Telemetry

Deliverables:

- AgentCore traces enabled
- Strands hook mapping
- per-hop correlation fields propagated

Success criteria:

- specialist invocation paths are easy to debug
- planner tool usage is visible without reading mixed logs from unrelated layers

#### Phase 6: Cleanup And Hardening

Deliverables:

- remove obsolete LangGraph-only code paths once cutover is complete
- remove raw finance execution from the top-level orchestrator
- keep rollback switches until production confidence is achieved

Success criteria:

- architecture matches the target design
- no critical path depends on the old hardcoded branch model

### Risks

Main risks:

- migrating orchestration and memory semantics at the same time
- accidentally turning the top-level orchestrator into an unconstrained tool loop
- duplicating memory ownership between orchestrator and planner
- making `specialist-agent-mcp` too smart and turning it into another orchestrator
- schema drift between orchestrator, specialist MCP, planner, and finance tools

### Guardrails

- keep one top-level orchestrator only
- keep stock unchanged in this migration
- keep `specialist-agent-mcp` thin
- keep planner as the owner of planning-domain raw tools
- keep memory and audit at orchestrator
- keep versioned schemas everywhere
- keep delegation depth shallow

### Additional Sections That Should Be Added To `MULTI_AGENT_SPECIALIST_MCP_ARCHITECTURE.md`

The current multi-agent plan is strong on topology but still needs explicit Strands adoption sections.

Recommended additions:

1. `Strands Adoption Decision`
   - explain why Strands changes implementation, not the AWS topology
   - state that stock remains unchanged

2. `Framework Mapping`
   - orchestrator = Strands Graph
   - planner = Strands specialist
   - stock = existing HTTPS service
   - specialist MCP = thin wrapper

3. `AWS Delta`
   - required runtime redeploy changes
   - optional Memory and observability changes
   - no required Identity redesign

4. `Tool Selection Ownership`
   - orchestrator owns specialist delegation
   - planner owns finance tool selection

5. `Memory Ownership Rule`
   - only orchestrator owns conversation memory

6. `Observability Contract`
   - define the propagation fields and per-hop telemetry model

7. `Rollback Strategy`
   - preserve compatibility during migration

### Recommended Final Decision

Proceed with Strands adoption, but do it in a way that preserves the target multi-agent architecture.

Recommended final decision:

- yes to Strands for planner
- yes to Strands Graph for orchestrator
- no stock rewrite
- no Gateway replacement
- no Identity redesign
- no top-level free-form raw-tool selection

### Official References

Primary references used for this plan:

- AgentCore Runtime overview:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html
- AgentCore Gateway overview:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
- AgentCore Gateway quick start with Strands example:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-quick-start.html
- AgentCore Gateway agent integration:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-agent-integration.html
- AgentCore inbound JWT authorizer:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/inbound-jwt-authorizer.html
- AgentCore workload access tokens:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html
- AgentCore observability:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html
- AgentCore observability getting started:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html
- Strands deploy to AgentCore Runtime:
  https://strandsagents.com/latest/documentation/docs/user-guide/deploy/deploy_to_bedrock_agentcore/
- Strands session management:
  https://strandsagents.com/latest/documentation/docs/user-guide/concepts/agents/session-management/
- Strands AgentCore Memory session manager:
  https://strandsagents.com/latest/documentation/docs/community/session-managers/agentcore-memory/
- Strands MCP tools:
  https://strandsagents.com/latest/documentation/docs/user-guide/concepts/tools/mcp-tools/
- Strands Graph:
  https://strandsagents.com/latest/documentation/docs/user-guide/concepts/multi-agent/graph/
