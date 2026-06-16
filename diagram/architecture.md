# System Architecture — Multi-Agent Fintech Advisory Platform

## Full System Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                   CLIENT / FRONTEND                                  │
│                              (Web App / Mobile App)                                  │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │  HTTPS  (JWT / Bearer token)
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                               BACKEND API  (FastAPI)                                 │
│                              backend/app/  — port 8010                               │
│                                                                                      │
│   • Session management          • REST endpoints                                     │
│   • Auth relay (Cognito/JWT)    • Chat history (Supabase)                            │
│   • Request enrichment          • User profile / goals                               │
└──────────────────────────────────────┬──────────────────────────────────────────────┘
                                       │  HTTP POST  /invocations  (AgentCore protocol)
                                       │  Authorization: Bearer <user_token>
                                       ▼
╔═════════════════════════════════════════════════════════════════════════════════════╗
║                    ORCHESTRATOR AGENT  (AWS Bedrock AgentCore)                      ║
║                         agent/main.py  — BedrockAgentCoreApp                        ║
║                                                                                      ║
║  ┌──────────────────────────────────────────────────────────────────────────────┐   ║
║  │                    STRANDS GraphBuilder Pipeline                              │   ║
║  │                                                                               │   ║
║  │  [intake] → [safety] → [routing] → [delegation] → [tool_invocation]          │   ║
║  │      ↓           ↓          ↓            ↓                ↓                  │   ║
║  │  load memory  suitability  Bedrock     catalog        call Gateway            │   ║
║  │  + encode     guard        intent      selection       (MCP JSON-RPC)         │   ║
║  │  gate         (local)      extract     + specialist                           │   ║
║  │                            (LLM)       routing                                │   ║
║  │                                                                               │   ║
║  │  [aggregation] → [response] → [memory_update]                                 │   ║
║  │        ↓               ↓              ↓                                       │   ║
║  │  merge outputs     Bedrock LLM    save session                                │   ║
║  │  specialist resp   synthesize     (in-memory TTL                              │   ║
║  │  render contract   answer plan    or AgentCore STM)                           │   ║
║  └──────────────────────────────────────────────────────────────────────────────┘   ║
║                                                                                      ║
║  Internal Modules:                                                                   ║
║  ┌────────────┐  ┌─────────────┐  ┌───────────────┐  ┌──────────────────────────┐  ║
║  │ router/    │  │ policy/     │  │ encoding/     │  │ observability/           │  ║
║  │ extractor  │  │ engine.py   │  │ gate.py       │  │ audit_logger             │  ║
║  │ (Bedrock   │  │ (Simple /   │  │ (mojibake     │  │ trace_context            │  ║
║  │  Converse) │  │  Cedar)     │  │  detection +  │  │ CloudWatch exporter      │  ║
║  │            │  │             │  │  UTF-8 repair)│  │                          │  ║
║  └────────────┘  └─────────────┘  └───────────────┘  └──────────────────────────┘  ║
║                                                                                      ║
║  ┌────────────────────────────────────────────────────────────────────────────────┐  ║
║  │  subagents/catalog  (agent_catalog.v1.json)                                    │  ║
║  │                                                                                │  ║
║  │  ┌──────────────┐   ┌─────────────────┐   ┌───────────────────────────────┐   │  ║
║  │  │  planner     │   │  service        │   │  stock                        │   │  ║
║  │  │  priority=10 │   │  priority=15    │   │  priority=20                  │   │  ║
║  │  │  domains:    │   │  domains:       │   │  domains:                     │   │  ║
║  │  │  planning,   │   │  planning,      │   │  investing, portfolio, equity  │   │  ║
║  │  │  budgeting,  │   │  goals, cashflow│   │  suitability_required=true    │   │  ║
║  │  │  goals,      │   │  parallel=false │   │  parallel=false               │   │  ║
║  │  │  cashflow    │   │                 │   │                               │   │  ║
║  │  │  parallel=T  │   │                 │   │                               │   │  ║
║  │  └──────────────┘   └─────────────────┘   └───────────────────────────────┘   │  ║
║  └────────────────────────────────────────────────────────────────────────────────┘  ║
║                                                                                      ║
║  Auth:  infra/auth/  →  CognitoAuthProvider (prod)  /  JwtAuthProvider (local)      ║
║  KB:    tools.py  →  local kb/ markdown files  (replaces Bedrock KB / OpenSearch)   ║
╚═══════════════════════════════════════════╤═════════════════════════════════════════╝
                                            │
                          MCP JSON-RPC  over  HTTPS
                          (AgentCore Gateway  →  /mcp endpoint)
                          Bearer <user_token>  forwarded
                                            │
                                            ▼
╔═════════════════════════════════════════════════════════════════════════════════════╗
║              SPECIALIST AGENT MCP SERVER  (FastAPI + MCP Streamable HTTP)           ║
║            src/aws-specialist-agent-mcp-server/  — port 8000                        ║
║                                                                                      ║
║  MCP Tools exposed to AgentCore Gateway:                                             ║
║  ┌───────────────────────┐  ┌───────────────────────┐  ┌──────────────────────────┐ ║
║  │  run_planner_agent_v1 │  │ run_service_agent_v1  │  │  run_stock_agent_v1      │ ║
║  │                       │  │                       │  │                          │ ║
║  │  Input/Output         │  │  Input/Output         │  │  Input/Output            │ ║
║  │  schema-validated     │  │  schema-validated     │  │  schema-validated        │ ║
║  │  (JSON Schema v2020)  │  │  (JSON Schema v2020)  │  │  (JSON Schema v2020)     │ ║
║  └──────────┬────────────┘  └──────────┬────────────┘  └───────────┬──────────────┘ ║
╚════════════╪═══════════════════════════╪════════════════════════════╪═══════════════╝
             │                           │                            │
             ▼                           ▼                            ▼
╔════════════════════╗    ╔═════════════════════════════╗    ╔════════════════════════╗
║   PLANNER AGENT    ║    ║      SERVICE AGENT          ║    ║    STOCK AGENT         ║
║  (Strands Agent)   ║    ║   (Multi-layer pipeline)    ║    ║  (External adapter     ║
║                    ║    ║                             ║    ║   or local stub)       ║
║  planner_agent/    ║    ║  service_agent/             ║    ║  stock/adapter.py      ║
║  agent.py          ║    ║  agent.py                   ║    ║                        ║
║                    ║    ║                             ║    ║  Capabilities:         ║
║  Capabilities:     ║    ║  Layer 1: sufficiency       ║    ║  • stock_analysis      ║
║  • cashflow        ║    ║  Layer 2: reasoning         ║    ║  • portfolio_guidance  ║
║    analysis        ║    ║  Layer 3: roadmap compile   ║    ║  • suitability check   ║
║  • budget tracking ║    ║  Layer 4: explanation LLM   ║    ║  • education-only      ║
║  • anomaly detect  ║    ║                             ║    ║    guardrail           ║
║  • goal planning   ║    ║  Outputs:                   ║    ║                        ║
║  • scenario what-if║    ║  • phase-by-phase roadmap   ║    ║  Guarded by:           ║
║  • risk profile    ║    ║  • milestone engine         ║    ║  suitability_required  ║
║                    ║    ║  • service recommendations  ║    ║  =true in catalog      ║
║  Uses Strands      ║    ║  • visualization map        ║    ║                        ║
║  @tool decorator   ║    ║                             ║    ╚════════════════════════╝
╚════════╤═══════════╝    ╚══════════╤══════════════════╝
         │                           │
         │  calls finance tools      │  optionally calls planner
         │  via tool_router.py       │  (hidden prefetch for context)
         ▼                           │
╔═════════════════════════════════════════════════════════════════════════════════════╗
║                  FINANCE MCP SERVER  (FastAPI + JSON-RPC)                           ║
║               src/aws-finance-mcp-server/  — port 8020                              ║
║                                                                                      ║
║  Finance Tools (deterministic, SQL-backed, no LLM):                                 ║
║                                                                                      ║
║  ┌─────────────────────┐  ┌──────────────────────┐  ┌────────────────────────────┐  ║
║  │ spend_analytics_v1  │  │ anomaly_signals_v1   │  │ cashflow_forecast_v1       │  ║
║  │ (30/60/90d SQL)     │  │ (CUSUM + drift)      │  │ (time-series forecast)     │  ║
║  └─────────────────────┘  └──────────────────────┘  └────────────────────────────┘  ║
║  ┌─────────────────────┐  ┌──────────────────────┐  ┌────────────────────────────┐  ║
║  │ jar_allocation_v1   │  │ risk_profile_non_    │  │ suitability_guard_v1       │  ║
║  │ (rule-based alloc)  │  │ investment_v1        │  │ (education-only policy)    │  ║
║  └─────────────────────┘  └──────────────────────┘  └────────────────────────────┘  ║
║  ┌─────────────────────┐  ┌──────────────────────┐  ┌────────────────────────────┐  ║
║  │ recurring_cashflow_ │  │ goal_feasibility_v1  │  │ what_if_scenario_v1        │  ║
║  │ detect_v1           │  │ (target + horizon)   │  │ (variant comparison)       │  ║
║  └─────────────────────┘  └──────────────────────┘  └────────────────────────────┘  ║
║                                                                                      ║
║  Auth:  JWT verify on every call                                                     ║
╚════════════════════════════════════╤════════════════════════════════════════════════╝
                                     │  Supabase REST API  (SQL queries)
                                     │  auth_user_id  enforced per query
                                     ▼
                    ┌─────────────────────────────────┐
                    │         SUPABASE (PostgreSQL)    │
                    │                                  │
                    │  • transactions                  │
                    │  • goals                         │
                    │  • jars / budget categories      │
                    │  • user profiles                 │
                    │  • chat sessions (backend)       │
                    └─────────────────────────────────┘


────────────────────────────────────────────────────────────────────────────────────────
  SUPPORTING SERVICES
────────────────────────────────────────────────────────────────────────────────────────

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │  AWS BEDROCK  (used by Orchestrator)                                             │
  │                                                                                  │
  │  • converse API  →  intent extraction  (router/extractor_bedrock.py)             │
  │  • converse API  →  answer synthesis   (response/synthesizer_bedrock.py)         │
  │  • Guardrails    →  content safety     (optional, enforced in prod)              │
  │  • Titan Embed   →  semantic service matching  (service_semantic.py)             │
  └──────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │  AWS COGNITO  (prod auth)                                                        │
  │                                                                                  │
  │  • User Pool  →  JWT access tokens                                               │
  │  • JWKS endpoint  →  token verification in CognitoAuthProvider                  │
  └──────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │  AGENTCORE GATEWAY  (AWS managed)                                                │
  │                                                                                  │
  │  • Exposes specialist-agent-mcp-server tools to orchestrator                    │
  │  • MCP protocol over HTTPS                                                       │
  │  • Session management  (mcp-session-id header)                                  │
  │  • Tool name alias resolution  (specialist-agent-mcp___run_planner_agent_v1)    │
  └──────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │  LOCAL KNOWLEDGE BASE  (agent/kb/)                                               │
  │                                                                                  │
  │  • advisory_playbook_banking_services.md                                         │
  │  • services_cards_and_payments.md                                                │
  │  • services_loans_and_credit.md                                                  │
  │  • services_savings_and_deposits.md                                              │
  │  • policies.md  /  disclaimers.md  /  service_terms_glossary.md                 │
  │                                                                                  │
  │  Loaded at startup into memory, keyword + intent-scored retrieval                │
  │  (replaced Bedrock KB + OpenSearch — saves ~$700-1000/month)                    │
  └──────────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │  WORKERS  (background)                                                           │
  │                                                                                  │
  │  • aggregate_worker.py  →  batch aggregation jobs                               │
  │  • trigger_worker.py    →  scheduled event triggers                              │
  │  • tier1/               →  tiered processing workers                            │
  └──────────────────────────────────────────────────────────────────────────────────┘


────────────────────────────────────────────────────────────────────────────────────────
  PLANNED: BEHAVIOR ANALYSIS AGENT  (not yet built)
────────────────────────────────────────────────────────────────────────────────────────

  ┌──────────────────────────────────────────────────────────────────────────────────┐
  │  BEHAVIOR AGENT  (future — add to agent_catalog.v1.json)                         │
  │                                                                                  │
  │  id: "behavior_analyst"                                                          │
  │  domains: ["clickstream", "behavior", "recommendation"]                          │
  │  intent: "behavior"  (new intent class needed in extractor prompt)               │
  │                                                                                  │
  │  Tools (via AgentCore Gateway):                                                  │
  │  ┌──────────────────────────┐  ┌──────────────────────────────────────────────┐  │
  │  │ clickstream_access_v1    │  │ behavior_aggregation_v1                      │  │
  │  │ (user event stream)      │  │ (session patterns, feature extraction)       │  │
  │  └──────────────────────────┘  └──────────────────────────────────────────────┘  │
  │  ┌──────────────────────────┐  ┌──────────────────────────────────────────────┐  │
  │  │ ml_scoring_v1            │  │ service_recommender_v1                       │  │
  │  │ (attention model,        │  │ (rule + ML hybrid, context-aware)            │  │
  │  │  engagement scoring)     │  │                                              │  │
  │  └──────────────────────────┘  └──────────────────────────────────────────────┘  │
  │                                                                                  │
  │  Requires:                                                                       │
  │  • AgentCore LTM  (persist behavior signals across sessions)                    │
  │  • New intent "behavior" in router/extractor_bedrock.py prompt                  │
  │  • _INTENT_DOMAIN_MAP update in strands_orchestrator/specialist.py              │
  │  • Clickstream data store  (DynamoDB or Kinesis → S3 → query layer)             │
  └──────────────────────────────────────────────────────────────────────────────────┘
```

---

## Request Lifecycle (single user turn)

```
User message
    │
    ▼
Backend API  →  enriches with session context, forwards to Orchestrator
    │
    ▼
Orchestrator [intake]
    • load session memory
    • apply encoding gate (Vietnamese UTF-8 repair)
    │
    ▼
Orchestrator [safety]
    • suitability check (local guard)
    • if invest+execution → hard refusal, short-circuit
    │
    ▼
Orchestrator [routing]
    • Bedrock Converse → extract intent + slots + target_agent_id
    • intents: summary | risk | planning | scenario | invest | out_of_scope
    • if low confidence → clarification loop (max 2 rounds)
    │
    ▼
Orchestrator [delegation]
    • specialist catalog lookup → select by intent / domain / priority / confidence
    • outputs: selected_specialist_id
    │
    ▼
Orchestrator [tool_invocation]
    • if service agent: hidden planner prefetch first (for financial context)
    • build specialist payload (SpecialistRequestEnvelope)
    • call AgentCore Gateway → MCP JSON-RPC → tools/call
    • validate output against JSON Schema
    │
    ▼
Specialist Agent MCP Server
    • authenticates token
    • routes to planner / service / stock handler
    • runs agent with finance tools
    • returns AgentResultEnvelope
    │
    ▼
Planner/Service/Stock Agent
    • calls Finance MCP Server tools (SQL-backed, deterministic)
    • Finance MCP → Supabase → raw transaction data
    • Strands agent reasons over tool results
    │
    ▼
Orchestrator [aggregation]
    • merge agent outputs, KB citations, tool traces
    │
    ▼
Orchestrator [response]
    • apply specialist_response renderer (standardized contract → human text)
    • or Bedrock LLM synthesizer (answer_plan_v2 schema)
    │
    ▼
Orchestrator [memory_update]
    • persist session summary, last planner contract, stock context
    │
    ▼
Backend API → Client
```

---

## Component Summary Table

| Component | Technology | Role |
|---|---|---|
| Backend API | FastAPI | Session, auth relay, REST gateway |
| Orchestrator | BedrockAgentCoreApp + Strands GraphBuilder | Main multi-agent pipeline controller |
| Specialist MCP Server | FastAPI + MCP Streamable HTTP | Exposes sub-agents as MCP tools |
| Planner Agent | Strands Agent + @tool | Financial planning & analysis |
| Service Agent | Multi-layer pipeline (no LLM except explanation) | Banking service roadmap generation |
| Stock Agent | External adapter / local stub | Investment education (suitability-gated) |
| Finance MCP Server | FastAPI + JSON-RPC | Deterministic SQL-backed finance tools |
| AgentCore Gateway | AWS managed | MCP proxy between orchestrator and specialists |
| Bedrock Converse | AWS | Intent extraction + answer synthesis |
| Cognito | AWS | Production JWT auth |
| Supabase | PostgreSQL | Transaction + user data store |
| Local KB | Markdown files in kb/ | Policy, services, disclaimers (no OpenSearch) |
| Workers | Python scripts | Background aggregation + triggers |
| Behavior Agent | **Planned** | Clickstream ML + service recommendation |
