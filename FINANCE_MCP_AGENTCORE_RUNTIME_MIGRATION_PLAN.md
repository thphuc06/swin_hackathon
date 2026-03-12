# Finance MCP Migration To AgentCore Runtime

## Purpose

This document explains how to move `finance-tools-mcp` from the current App Runner deployment model to AgentCore Runtime without changing its role in the overall architecture.

The goal is not to redesign the finance tool plane. The goal is to keep it as:

- a separate raw tool plane
- deterministic
- typed
- auditable
- owned by planner or another specialist, not by the top-level orchestrator

## Current State In This Repo

Today the repo uses this shape:

```text
Frontend / Backend
-> AgentCore Runtime orchestrator
-> AgentCore Gateway
-> finance-tools-mcp on App Runner
-> Supabase
```

Evidence in repo:

- `src/aws-finance-mcp-server/README.md` documents App Runner as the current deploy target.
- `src/aws-finance-mcp-server/Dockerfile` exposes port `8080` for App Runner.
- `SETUP_E2E_AWS_REAL_UNIFIED.md` describes the current E2E path as `Gateway -> Finance MCP (App Runner) -> Supabase`.

The current MCP server already exposes:

- `GET /mcp`
- `POST /mcp`
- `tools/list`
- `tools/call`

That means the business contract is already close to what we want. The main migration work is around the hosting model and MCP runtime compatibility, not around the tool semantics.

## Target State

Recommended target shape:

```text
Frontend / Backend
-> AgentCore Runtime orchestrator
-> AgentCore Gateway
-> finance-tools-mcp on AgentCore Runtime
-> Supabase
```

This preserves the separation of concerns:

- orchestrator still calls tools through Gateway
- finance MCP still stays a raw tool plane
- Supabase access and financial logic remain inside the finance MCP workload

## Why Move Finance MCP To AgentCore Runtime

Potential advantages:

- the finance MCP workload becomes a first-party AgentCore-hosted workload
- observability is better for the runtime-hosted boundary than for a generic external service
- hosting model becomes more consistent with the rest of the agent platform
- you reduce one generic service type from the stack if you are already standardizing on AgentCore

Potential tradeoffs:

- AgentCore Runtime has a stricter MCP service contract than the current App Runner setup
- you may need code changes for MCP transport compatibility
- runtime hosting does not automatically make downstream Supabase calls fully observable
- if the current App Runner service is stable and already operationally acceptable, the migration may not be urgent

## What Changes And What Stays The Same

Things that should stay the same:

- tool names
- tool schemas
- business logic in `app/finance/`
- Supabase data access pattern
- authentication semantics for business `user_id`
- finance MCP as a separate tool plane

Things that change:

- deployment substrate: App Runner -> AgentCore Runtime
- runtime service contract: MCP runtime contract instead of generic FastAPI hosting assumptions
- container port/path expectations
- target registration details in Gateway
- observability and runtime logs location

## Recommended Migration Approach

### Phase 0: Freeze Tool Contracts

Before changing hosting:

- keep the current tool names stable
- keep JSON schemas stable
- keep `tools/list` and `tools/call` responses backward compatible

Success criteria:

- existing callers do not need to change tool arguments
- Gateway synchronization after cutover does not introduce tool drift

### Phase 1: Make The Server Runtime-Compatible

AgentCore Runtime MCP hosting expects:

- host `0.0.0.0`
- port `8000`
- mount path `/mcp`
- streamable HTTP MCP transport

Current repo mismatch:

- current Dockerfile exposes `8080`
- current start command uses `${PORT:-8080}`
- current server is a custom FastAPI MCP surface, not yet explicitly documented as AgentCore Runtime MCP compliant

Required code-level checks:

- change runtime container port from `8080` to `8000`
- keep MCP endpoint at `/mcp`
- verify stateless streamable HTTP compatibility
- verify `tools/list` and `tools/call` still behave correctly under the Runtime MCP contract

Recommended implementation options:

- preferred: migrate to an official MCP SDK shape such as FastMCP and keep finance logic behind MCP tool wrappers
- acceptable: keep the current FastAPI server only if it is hardened to match the Runtime MCP contract exactly

Success criteria:

- local server can be tested at `http://localhost:8000/mcp`
- local MCP client can `initialize`, `tools/list`, and `tools/call`

### Phase 2: Package The Existing Repo Layout For Runtime

Recommended code shape:

```text
src/aws-finance-mcp-server/
  app/
    main.py
    mcp.py
    auth.py
    finance/
      common.py
      data.py
      spend.py
      anomaly.py
      forecast.py
      allocation.py
      risk.py
      suitability.py
      recurring.py
      goal.py
      scenario.py
  requirements.txt
  Dockerfile
```

Recommended interpretation:

- keep `app/finance/` as the domain layer
- keep `app/mcp.py` as the protocol layer
- adjust only the hosting and MCP-runtime compatibility pieces first
- avoid mixing planner logic into this workload

### Phase 3: Deploy Finance MCP To AgentCore Runtime

Deploy the `finance-tools-mcp` workload as an MCP server on AgentCore Runtime.

The important design rule is:

- finance MCP becomes a runtime-hosted MCP server
- finance MCP does not become a user-facing agent
- finance MCP still acts like a raw tool plane

Success criteria:

- the runtime-hosted finance MCP can be invoked through its runtime MCP endpoint
- `tools/list` returns the same tool catalog as before
- smoke tests pass against the runtime-hosted endpoint

### Phase 4: Repoint Gateway

After runtime deploy succeeds:

- update the Gateway target so it points to the runtime-hosted finance MCP endpoint instead of the App Runner URL
- run target synchronization again
- verify prefixed tool names remain stable from the orchestrator point of view

Recommended first cutover shape:

```text
orchestrator
-> AgentCore Gateway
-> finance-tools-mcp on AgentCore Runtime
```

Success criteria:

- top-level agent code in `agent/tools.py` keeps working with the same base tool names
- only Gateway target configuration changes

### Phase 5: Observability And Audit

Moving finance MCP to AgentCore Runtime improves visibility for the finance MCP workload boundary.

What you get more easily:

- runtime-level traces and logs for the finance MCP workload
- better consistency with other runtime-hosted workloads
- easier correlation with AgentCore-native runtime telemetry

What you still need to do yourself:

- emit business audit events for tool inputs and outputs where needed
- propagate `trace_id`, `request_id`, and `session_id`
- instrument downstream HTTP/database spans if you want deep visibility into Supabase calls

Important rule:

- AgentCore observability helps you see the runtime-hosted finance MCP workload
- it does not eliminate the need for application-level audit for financial decisions

### Phase 6: Rollback Plan

Keep rollback simple:

- keep the App Runner version alive until runtime-hosted finance MCP is verified
- use Gateway target switching as the rollback lever
- do not change tool contracts during the hosting migration

Rollback success criteria:

- you can switch Gateway back to the App Runner target without changing orchestrator code

## Concrete Changes Needed In This Repo

### Code

- update `src/aws-finance-mcp-server/Dockerfile` for Runtime MCP hosting expectations
- verify whether `src/aws-finance-mcp-server/app/mcp.py` fully matches Runtime MCP transport requirements
- add local tests that hit `localhost:8000/mcp`

### Config

- replace App Runner deployment config with AgentCore Runtime deployment config for finance MCP
- update Gateway target endpoint after runtime deploy
- keep auth envs for Cognito and Supabase unless business auth design changes

### Docs

- update `src/aws-finance-mcp-server/README.md` with a Runtime deployment path
- update `SETUP_E2E_AWS_REAL_UNIFIED.md` if runtime hosting becomes the new default

## When This Migration Is Worth It

Move finance MCP to AgentCore Runtime when:

- you want a more unified hosting model across orchestrator and MCP workloads
- you want better runtime-native observability
- you are already investing in AgentCore as the main hosting platform

Do not rush this migration if:

- the App Runner deployment is stable and low-friction
- the current bottleneck is not hosting but tool correctness or policy
- you have not yet validated MCP runtime compatibility locally

## Recommended Decision For This Repo

The most pragmatic order is:

1. create and stabilize `specialist-agent-mcp`
2. keep `finance-tools-mcp` where it is while specialist migration is still moving
3. migrate `finance-tools-mcp` from App Runner to AgentCore Runtime only after the specialist topology is stable

Reason:

- moving hosting and changing multi-agent control boundaries at the same time creates avoidable complexity
- finance MCP is already nicely isolated, so it is a good candidate for a later substrate migration
- the specialist MCP migration is the more important architectural move right now

## Official References

- AgentCore Runtime can host agents or tools:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agents-tools-runtime.html
- Deploy MCP servers in AgentCore Runtime:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html
- AgentCore Runtime service contract:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-service-contract.html
- MCP protocol contract for AgentCore Runtime:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp-protocol-contract.html
- MCP server targets in AgentCore Gateway:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html
- AgentCore Observability getting started:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html
- Add observability to AgentCore resources:
  https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html
