Jars Fintech Banking Simulator + AgentCore Advisory

System restatement (5-7 bullets)
- Web banking simulator: Tier1 = user-driven Jar pick in UI (fast transfer UX) with optional LLM Top-K hint; Tier1 insights land in inbox.
- Tier2 = deep advisory chat on AgentCore Runtime + LangGraph with citations, disclaimer, trace_id.
- External/recurring transactions are processed in a separate detect-and-attach flow (`llm_categorize_tx`), not by Tier2 chat.
- System of record in Postgres (Supabase MVP) -> Aurora PG; numbers must come from SQL.
- KB used only for policy/templates/services, with citations from Bedrock Knowledge Bases.
- Tool plane via AgentCore Gateway (MCP) + Policy/Cedar for deterministic access control.
- Guardrails for PII/prompt attacks + audit trail (trace_id, tool calls, decisions).
- Runtime cannot call localhost; tool endpoints must be public or behind Gateway.

Layer choices (refactor)
| Layer | Choice | Why it fits fintech | Responsibility |
| --- | --- | --- | --- |
| Frontend | Next.js/React (web) / React Native | Jar picker + inbox + chat UX | UI/UX, session id, display citations/disclaimers |
| AuthN (user) | Cognito User Pool (MVP) | Login + JWT tokens | JWT for API, optional JWT for Runtime/Gateway |
| API layer | API Gateway + BFF (Lambda/ECS) | Separates UI from data/agent | CRUD jars/goals/txns, chat streaming proxy |
| Event bus | EventBridge (+ SQS buffer) | Tier1 push event-driven | Route TransactionCreated -> workers |
| Workers | Lambda or ECS Fargate | Scale independently | Aggregates, triggers, notification writer |
| Data of record | Postgres (Supabase MVP) -> Aurora PG | Audit-friendly, authoritative data | Txns, goals, risk versions, audit logs |
| RAG KB | Bedrock Knowledge Bases + OpenSearch Serverless | Managed ingest/retrieve, scale | Chunk/embed, retrieve + citations metadata |
| LLM | Bedrock models (flexible) | AWS sponsor-friendly | Tier1 narrative, Tier2 reasoning |
| Agent runtime | AgentCore Runtime | Session isolation + long-running | Host Tier2 orchestrator (LangGraph) |
| Tool integration | AgentCore Gateway (MCP) + targets | Standardized tools + audit + auth | SQL read, signals/forecast, categorize, rules/budgets, goals, notify, KB retrieve |
| Tool authorization | AgentCore Policy (Cedar) | Deterministic compliance | Allow/deny tool calls by intent/scope |
| Memory | AgentCore Memory | Store summaries/prefs/goals only | Short-term + long-term memory |
| What-if compute | AgentCore Code Interpreter | ETA ranges with assumptions | Sandbox simulation |
| Safety | Bedrock Guardrails | PII/prompt attacks | Input/output filters + disclaimers |
| Observability | CloudWatch + AgentCore OTel | Trace + replay for audit | Logs/metrics/traces |
| IaC | Terraform/CDK (minimal) | Clear path to production | Repeatable deploy (gateway/runtime/roles) |

RAG KB notes
- Data source: S3 (policy/services/templates in md/csv/pdf)
- Vector store: OpenSearch Serverless (AWS-native, scales well)
- Option: Aurora PostgreSQL-Compatible Edition (pgvector) if SQL-only desired
- KB retrieval is served via MCP KB server (open-source) behind AgentCore Gateway

A) Implementation blueprint (MVP)

Related docs
- `README.md` (local run + deploy notes)
- `backend/docs/api.md` (API contracts)
- `backend/docs/schema.md` (schema design)
- `model_data_train.md` (model + data training plan)
- `src/aws-kb-retrieval-server/README.md` (MCP server)

Repo structure + responsibilities
- frontend/: Next.js + Tailwind, minimal UI, streaming chat, show citations/disclaimer/trace.
- backend/: FastAPI BFF, REST + /chat/stream proxy, JWT auth, EventBridge emit.
- agent/: LangGraph + AgentCore Runtime entrypoint, tool adapters, guard logic.
- workers/: aggregation + trigger + notification writer (Tier1).
- kb/: policy/templates/services corpus + metadata tags.
- iac/: Terraform/CDK skeleton (Runtime/Gateway/Policy/roles/networking).

API endpoints (BFF)
| Method | Path | Purpose | Notes |
| --- | --- | --- | --- |
| POST | /transactions/transfer | Create transfer (jar + category required) | emit TransactionCreated |
| POST | /transactions/suggest | Suggest jar + category | LLM tool (`llm_categorize_tx`) with confidence gating; auto-select only if high confidence |
| GET | /transactions | list txns (30/60d) | read-only |
| GET | /aggregates/summary | 30/60d summary | SQL view |
| GET | /notifications | inbox list | Tier1 outputs |
| GET | /jars | list jars | user-defined jars (name/description/keywords) |
| POST | /jars | create jar | improves categorization + personalization |
| GET | /jars/templates | list default jar templates | seed on first use |
| POST | /jars/seed-defaults | create default jars for user | one-time init |
| GET | /signals/summary | data-quality + behavior signals | % categorized, missing data, discipline score |
| GET | /forecast/cashflow | cashflow forecast | include 90d runway + confidence |
| POST | /rules/counterparty | map counterparty -> jar/category | "1-click fix" action from insights |
| GET | /budgets | list budgets | jar/category thresholds for Tier1 |
| POST | /budgets | set budget | CTA: set/adjust thresholds |
| POST | /goals | create/update goal | house goal |
| GET | /risk-profile | current profile | versioned |
| POST | /risk-profile | new version | immutable |
| POST | /chat/stream | stream proxy to AgentCore | SSE |
| GET | /audit/:trace_id | audit record | demo transparency |

Tool catalog (agent tools)
Training & data plan: see `model_data_train.md`.

| Tool | Source | Maps to | Purpose |
| --- | --- | --- | --- |
| sql_read_views | BFF/SQL | GET /aggregates/summary | numeric context |
| transactions_list | BFF/SQL | GET /transactions | largest txn, splits |
| llm_categorize_tx | LLM tool | POST /transactions/suggest | suggest jar + subcategory (Top-K + confidence, no training) |
| signals_read | BFF/SQL | GET /signals/summary | data quality + behavior signals |
| cashflow_forecast_90d | BFF/SQL | GET /forecast/cashflow | runway + 90d cashflow risk |
| rules_counterparty_set | BFF | POST /rules/counterparty | persist mapping for messy data |
| budgets_get_set | BFF | POST /budgets | set thresholds for proactive alerts |
| goals_get_set | BFF | POST /goals | goals update |
| risk_profile_get | BFF | GET /risk-profile | suitability |
| kb_retrieve | MCP KB server -> Bedrock KB | KB retrieve | citations + governance |
| code_interpreter_run | AgentCore CI | n/a | what-if ETA |
| audit_write | BFF/log | POST /audit | trace + decision |

DB schema (list, key fields)
- users (id, email, created_at)
- profiles (user_id, full_name, locale, risk_level)
- jar_templates (id, name, description, keywords_json, is_default, created_at)
- jars (id, user_id, template_id, name, description, keywords_json, target_amount)
- categories (id, parent_id, name, type)
- transactions (id, user_id, jar_id, category_id, amount, currency, counterparty, raw_narrative, user_note, channel, ts)
- rules_counterparty_map (id, user_id, counterparty_norm, jar_id, category_id, created_at)
- budgets (id, user_id, scope_type, scope_id, period, limit_amount, currency, created_at, updated_at, active)
- tx_label_events (id, user_id, txn_id, model_version, suggested_topk_json, final_jar_id, final_category_id, is_override, created_at)
- signals_daily (id, user_id, day, discipline_score, categorized_rate, missing_rate, runway_days, risk_90d_flag, payload_json)
- txn_agg_daily (user_id, date, spend, income, jar_spend_json)
- goals (id, user_id, type, target_amount, horizon_months, status)
- risk_profile_versions (id, user_id, risk_score, created_at)
- notifications (id, user_id, type, title, body, created_at, read)
- insights (id, user_id, rule_id, payload_json, created_at)
- income_sources (id, user_id, name, type)
- income_events (id, source_id, amount, ts)
- audit_event_log (trace_id, user_id, event_type, payload_hash, ts)
- audit_decision_log (trace_id, policy_id, decision, reason, ts)

KB corpus structure (S3)
- kb/policies/*.md (no-upsell, suitability, safety)
- kb/templates/*.md (summary templates, disclaimer templates)
- kb/services/*.md (product/service FAQs)
Metadata tags: doc_type=policy|template|service, region=vn, audience=retail

MCP KB server (open-source)
- Deploy MCP server (Docker/ECS/Fargate) with IAM role to call Bedrock KB.
- Register as AgentCore Gateway target.
- Tool signature: retrieve_from_aws_kb(query, knowledgeBaseId, n).

Tier1 pipeline spec
- Event: TransactionCreated (EventBridge)
- Worker A: aggregation update (txn_agg_daily)
- Worker B: signals/forecast compute (runway/90d risk, discipline, missing data)
- Worker C: triggers (rules/thresholds/anomaly) + format insight template + add disclaimer + write notification + audit
- UI inbox: list notifications sorted by created_at
- User-facing UX: transfer flow is **manual jar pick**; optional `llm_categorize_tx` gives Top-K hint; low confidence -> user must choose.

B) Agent behavior spec

Tier1 (insight generator)
- Template-first; only use KB for approved phrasing/disclaimers.
- No investment advice; include standard disclaimer.
- Prefer actionable outputs (CTA) when possible (set rule / recategorize / set budget).
- Low-confidence categorization must not auto-apply; require user confirmation.

Tier2 (LangGraph routing)
- Router: stats vs goal vs what-if vs risk/suitability.
- Sequence (tool-first): signals_read -> cashflow_forecast_90d -> sql_read_views -> kb_retrieve -> (code_interpreter if needed) -> reasoning.
- Citations mandatory when referencing KB.
- Numbers must come from SQL context only.

Risk/Suitability guard
- If intent = invest/buy/sell -> educational guidance only + refusal of advice.
- Always add disclaimer + trace_id.

Memory update
- Store: summaries, preferences, goal metadata.
- Never store: raw ledger rows, PII, full transaction details.

C) Security & compliance

Auth model
- Cognito User Pool JWT.
- Token propagation to tools via Gateway headers.
- Least-privilege scopes enforced by Policy/Cedar.

Prompt injection & PII
- Guardrails on input/output.
- System prompt forbids tool override.
- KB retrieval limited to doc_type=policy|template.
- KB tool routed via Gateway so Policy/Cedar can allow/deny by doc_type and scope.

Audit
- trace_id per request.
- log tool params hash + policy decision.
- store response hash for replay.

D) Hackathon deployment plan

MVP now
- Local frontend/backend + AWS AgentCore Runtime.
- Mock context when backend is localhost (runtime cannot reach local).
- JWT access token flow.

Post-hackathon
- Deploy backend public (API Gateway/Lambda or ECS).
- Move tools to Gateway/MCP + Policy/Cedar.
- Enable Guardrails + Memory + Observability export.

Day-by-day checklist

Day 1 (must have)
- Frontend chat streaming + inbox UI.
- Backend /chat/stream + /aggregates/summary.
- AgentCore Runtime deploy + AccessToken flow.
- Mock context for runtime.

Day 2 (nice to have)
- Tier1 pipeline workers + notifications.
- KB retrieval + citations.
- Basic audit logs + trace_id.

Day 3 (stretch)
- Gateway/MCP + Policy skeleton.
- Guardrails config + Memory summaries.
- Public backend endpoint (replace mock).

E) Architecture diagrams (future state)

1) Tier routing (Tier1 vs Tier2)

Tier1 and Tier2 are triggered by different inputs:
- **Tier1** is **event-driven** (transaction behavior -> proactive notification).
- **Tier2** is **prompt-driven** (user question -> tool-first explanation/advice).

```mermaid
flowchart TB
  IN["Input arrives"] --> SRC{"What triggered it?"}

  %% Tier1: proactive
  SRC -->|User transfer (UI)| T1["Tier1 (Proactive)<br/>Event-driven pipeline<br/>Jar picked manually; LLM hint optional"]
  T1 --> T1A["Read truth from SQL/views<br/>+ compute signals/forecast (90d)"]
  T1A --> T1B{"Any rule/threshold/anomaly triggered?"}
  T1B -->|Yes| N1["Output: Notification/Inbox insight<br/>+ CTA (fix mapping / set budget)"]
  T1B -->|No| N0["Output: No notification<br/>(still updates signals/views)"]

  %% Tier2: reactive
  SRC -->|User prompt / Why?| T2["Tier2 (Deep Advisor)<br/>AgentCore Runtime (Bedrock LLM)"]

  T2 --> R0["Intent router (cheap)<br/>choose minimal tools"]
  R0 --> R1["Read-only tools first:<br/>signals_read -> cashflow_forecast_90d -> sql_read_views<br/>(+ transactions_list if needed)"]
  R1 --> R2["KB (optional): policy/template phrasing<br/>with citations"]
  R2 --> OUT["Output: Advice/explanation<br/>disclaimer + trace_id"]

  %% Cross-link: explain a Tier1 insight
  N1 -. user taps Explain .-> T2
```

2) Backend overview (services + data planes)

```mermaid
flowchart TB
  subgraph Client
    UI["Web/Mobile UI<br/>Jar Picker + Chat + Inbox"]
  end

  subgraph Auth
    COG["Cognito<br/>User Auth (JWT)"]
  end

  subgraph API
    APIGW[API Gateway (AWS)]
    BFF["Backend BFF (Lambda/ECS/App Runner)<br/>CRUD + Chat Proxy + AuthZ"]
  end

  subgraph DataRecord["System of Record (SQL)"]
    PG[("Postgres<br/>Supabase (MVP) / Aurora PG (scale)")]
    AGG[("txn_agg_daily<br/>+ rolling views")]
    AUD[("audit_event_log<br/>+ audit_decision_log")]
  end

  subgraph Tier1["Tier1 Push Pipeline (Event-driven)"]
    EB[EventBridge (AWS)]
    Q["SQS (buffer)"]
    W1["Aggregation Worker (Lambda/ECS)<br/>update aggregates"]
    W2["Trigger/Template Worker (Lambda/ECS)<br/>rules -> insight draft"]
    NTFY["SNS/Pinpoint<br/>Notifications"]
  end

  subgraph Tier2["Tier2 Advisory (AgentCore)"]
    RT["AgentCore Runtime<br/>LangGraph Orchestrator"]
    MEM["AgentCore Memory<br/>short+long"]
    CI["AgentCore Code Interpreter<br/>what-if compute"]
  end

  subgraph ToolPlane["Tool Plane (Governed)"]
    GW["AgentCore Gateway (MCP)<br/>tool catalog + auth + transform"]
    INT["Gateway Interceptors<br/>FGAC / masking / header propagation"]
    POL["AgentCore Policy (Cedar)<br/>deterministic allow/deny"]
  end

  subgraph RAG["Managed RAG"]
    S3DOC["S3 Docs (AWS)<br/>Policies/Services/Templates<br/>+ metadata tags"]
    KB["Knowledge Bases for Amazon Bedrock<br/>Ingest + Retrieve (+citations)"]
    VEC["Vector Store (managed)<br/>OpenSearch Serverless (AWS) / Aurora pgvector"]
    LLM["Bedrock LLM<br/>(for detect/attach flow + Tier2 narrative)"]
  end

  subgraph Obs["Observability"]
    CW[CloudWatch Logs/Metrics/Traces]
    TR["AgentCore Observability<br/>OTel"]
  end

  UI --> COG --> APIGW --> BFF
  BFF --> PG
  PG --> AGG

  %% Tier1 push
  BFF --> EB
  EB --> Q --> W1 --> AGG
  W1 --> W2 --> NTFY --> UI
  W2 --> AUD

  %% Tier2 chat
  BFF -->|"chat (JWT)"| RT
  RT --> MEM
  RT -->|tool calls| GW --> INT --> POL
  POL -->|allow| PG
  POL -->|allow| CI
  POL -->|allow| KB
  POL -->|allow| LLM

  %% RAG
  S3DOC --> KB --> VEC
  RT -->|Retrieve / RAG| KB
  RT -->|LLM (Bedrock)| LLM

  %% Observability
  RT --> CW
  GW --> CW
  POL --> CW
  CW --> TR
```

Architecture notes
- Gateway turns API/Lambda/services into MCP tools for agents.
- Policy intercepts tool calls and decides allow/deny via Cedar.
- Observability emits OTel to CloudWatch.
- KB retrieval is a governed tool via MCP KB server for audit parity with SQL/compute/notify.

3) Retrieval layer (SQL truth + KB Managed + Memory)

```mermaid
flowchart LR
  Q["User Query"] --> IR["Intent Router<br/>(rule-first + LLM classifier)"]

  IR -->|stats| SQL1["SQL Read Views<br/>30/60d, largest txn, jar splits"]
  IR -->|goal/why/what-if| SQL2["SQL Read Views<br/>+ goals + risk version"]
  IR -->|health| SIGT["Signals Tool (read-only)<br/>discipline_score + categorized_rate + missing_rate"]
  IR -->|forecast| F90["Forecast Tool (read-only)<br/>runway_days + risk_90d_flag + confidence"]

  SQL1 --> CTX["Numeric Context Pack<br/>(ONLY truth numbers)"]
  SQL2 --> CTX

  SIGT --> SIG["Signals Pack<br/>data_quality + behavior"]
  F90 --> SIG

  Q --> MEM["AgentCore Memory<br/>prefs + prior assumptions"]

  Q --> KBTOOL["KB Retrieve Tool (governed)<br/>metadata filters: doc_type=policy/template"]
  KBTOOL --> CIT["Citation Pack<br/>(source uri + chunk id + version + tags)"]

  CTX --> REASON["LLM Reasoning<br/>must use CTX/SIG facts<br/>+ cite CIT"]
  SIG --> REASON
  MEM --> REASON
  CIT --> REASON

  REASON --> SAFE["Guardrails + Suitability Gate<br/>disclaimer + boundaries"]
  SAFE --> RESP["Response<br/>assumptions + what-if + citations"]
  RESP --> AUD["Audit logs<br/>(trace + decision + kb refs)"]
```

4) Tier1 Push pipeline (Transaction -> Insight -> Notification)

```mermaid
sequenceDiagram
  participant User
  participant API as Backend API
  participant CAT as Tx Categorizer
  participant EB as EventBridge
  participant Q as SQS
  participant Agg as Aggregation Worker
  participant Trig as Trigger Engine
  participant GW as Gateway (MCP)
  participant POL as Policy (Cedar)
  participant KB as Bedrock Knowledge Base
  participant Gate as Compliance Gate
  participant N as Notification(SNS/Pinpoint)
  participant Audit as Audit Logs

  User->>API: Initiate transfer (counterparty/amount/note?)
  opt Autocomplete jar/category (optional)
    API->>CAT: Predict Top-K (jar_id, category_id)
    CAT-->>API: suggestions + confidence
  end
  User->>API: Confirm Jar + Subcategory + Pay
  API->>EB: Publish TransactionCreated
  EB->>Q: Buffer event
  Q->>Agg: Consume
  Agg->>Agg: Update txn_agg_daily + rolling views
  Agg->>Trig: Emit "AggUpdated"
  Trig->>Trig: Rules/thresholds/anomaly checks

  opt Fetch approved templates / disclaimers (optional)
    Trig->>GW: Tool call (KB retrieve)
    GW->>POL: Evaluate
    POL-->>GW: ALLOW
    GW->>KB: Retrieve (templates/policy snippets)
    KB-->>GW: chunks + citations
    GW-->>Trig: citations pack
  end

  Trig->>Gate: Draft insight (template + variables + optional KB refs)
  Gate->>Gate: Guardrails + policy checks + disclaimers
  alt Approved
    Gate->>N: Send notification
  else Suppressed/Generic
    Gate->>N: Send safe generic guidance
  end
  Gate->>Audit: Write decision + content hash + trace_id (+ kb chunk ids if used)
```

4.1) End-to-end lifecycle (transaction -> signals -> insight -> action -> explanation)

```mermaid
sequenceDiagram
  participant U as User
  participant UI as Web/Mobile UI
  participant API as Backend BFF
  participant GW as AgentCore Gateway (MCP)
  participant POL as Policy (Cedar)
  participant CAT as Categorizer Tool
  participant PG as Postgres (truth)
  participant EB as EventBridge
  participant Q as SQS
  participant Agg as Aggregation Worker
  participant Sig as Signals/Forecast Worker
  participant Trig as Trigger/Template Worker
  participant KB as Bedrock Knowledge Base
  participant N as Inbox/Notifications
  participant RT as AgentCore Runtime (Tier2)

  opt First-time user (no jars)
    UI->>API: GET /jars
    API-->>UI: empty
    UI->>API: GET /jars/templates
    API-->>UI: default templates
    UI->>API: POST /jars/seed-defaults
    API->>PG: create default jars
  end

  U->>UI: Create transfer
  opt Optional LLM hint (Top-K)
    UI->>API: POST /transactions/suggest (draft txn)
    API->>GW: tools/call llm_categorize_tx
    GW->>POL: evaluate (read-only tool)
    POL-->>GW: ALLOW
    GW-->>API: suggestions + confidence
    API-->>UI: prefill if high confidence else show Top-K
  end

  U->>UI: Confirm jar + category
  UI->>API: POST /transactions/transfer
  API->>PG: write transaction (system of record)
  API->>EB: publish TransactionCreated
  EB->>Q: buffer
  Q->>Agg: consume
  Agg->>PG: update txn_agg_daily + rolling views
  Agg->>Sig: emit AggregateUpdated
  Sig->>PG: write signals_daily + forecast views
  Sig->>Trig: emit SignalsUpdated

  Trig->>Trig: evaluate rules/thresholds/anomalies (truth from views)
  opt Fetch approved phrasing (optional)
    Trig->>GW: tools/call kb_retrieve (templates/policy)
    GW->>POL: evaluate
    POL-->>GW: ALLOW
    GW->>KB: retrieve
    KB-->>GW: chunks + citations
    GW-->>Trig: citations pack
  end

  Trig->>PG: write notification + audit logs
  PG-->>N: notification ready
  N-->>UI: show insight card (+ CTA)

  opt User taps CTA ("fix it")
    UI->>API: POST /rules/counterparty (or budgets)
    API->>GW: tools/call rules_counterparty_set
    GW->>POL: evaluate (write tool)
    alt Allowed
      POL-->>GW: ALLOW
      GW-->>API: ok
      API-->>UI: confirmed
    else Denied
      POL-->>GW: DENY
      GW-->>API: denied
      API-->>UI: show safe explanation
    end
  end

  opt User asks "why am I at risk?"
    UI->>API: POST /chat/stream
    API->>RT: invoke (JWT)
    RT->>GW: tools/call signals_read + cashflow_forecast_90d + sql_read_views
    RT->>GW: tools/call kb_retrieve (policy/template citations)
    RT-->>API: response + citations + trace_id
    API-->>UI: SSE tokens
  end
```

5) Tier2 Agent (LangGraph on AgentCore Runtime)

```mermaid
stateDiagram-v2
  [*] --> Route
  Route --> QuickStats: intent=STATS & high_conf
  Route --> DeepAdvisory: intent in (WHY, WHAT_IF, GOAL_PLAN, INVESTING)\nOR low_conf

  QuickStats --> SQLFetch
  SQLFetch --> ComposeSafe
  ComposeSafe --> [*]

  DeepAdvisory --> LoadMemory
  LoadMemory --> SQLFetch2
  SQLFetch2 --> KBRetrieveTool
  KBRetrieveTool --> AssembleCitations
  AssembleCitations --> Plan
  Plan --> Compute: if needs what-if/ETA
  Compute --> SuitabilityGuard
  Plan --> SuitabilityGuard
  SuitabilityGuard --> ComposeCited
  ComposeCited --> GuardrailsCheck
  GuardrailsCheck --> MemoryUpdate
  MemoryUpdate --> [*]

  state KBRetrieveTool {
    [*] --> Retrieve: Retrieve (top-K chunks + metadata filters)
    Retrieve --> [*]
  }
```

5.1) Tier2 tool selection (future, tool-first)

Tool selection is not "LLM magic". The orchestrator must follow deterministic rules:
- read-only tools first (signals/forecast/views)
- KB only for approved phrasing/policy (citations mandatory)
- write tools only after explicit user confirmation (and policy allow)

```mermaid
flowchart TD
  Q["User prompt"] --> IR["Intent Router<br/>rules + lightweight classifier"]
  IR -->|always| S0["Tool: signals_read<br/>(data quality + discipline)"]
  IR -->|if risk/health/forecast| F0["Tool: cashflow_forecast_90d<br/>(runway + risk_90d_flag)"]
  IR -->|if needs numbers| SQL["Tool: sql_read_views<br/>(allowlisted views only)"]
  IR -->|if needs examples| TX["Tool: transactions_list<br/>(filtered, minimal)"]
  IR -->|if policy/phrasing| KB["Tool: kb_retrieve<br/>(doc_type allowlist + citations)"]
  IR -->|if what-if compute| CI["Tool: code_interpreter_run"]

  IR -->|if user requests change| C{"Need write?"}
  C -->|yes| CONF["Ask user to confirm action<br/>(UI confirm or explicit text)"]
  CONF --> W["Tool: rules_counterparty_set / budgets_get_set"]

  S0 --> PACK["Assemble Fact Pack<br/>(CTX + SIG + constraints)"]
  F0 --> PACK
  SQL --> PACK
  TX --> PACK
  KB --> PACK
  CI --> PACK
  W --> PACK

  PACK --> OUT["LLM: explain + recommend next action<br/>(no invented numbers)"]
```

Decision matrix (recommended MVP)
| User intent | Read tools (order) | Optional tools | Write tools |
| --- | --- | --- | --- |
| "Am I at risk in next 3 months?" | `signals_read` -> `cashflow_forecast_90d` -> `sql_read_views` | `kb_retrieve` | none |
| "Why was I flagged abnormal spend?" | `signals_read` -> `sql_read_views` -> `transactions_list` | `kb_retrieve` | `rules_counterparty_set` (only if user fixes mapping) |
| "Set a threshold rule" | `signals_read` | `sql_read_views` | `budgets_get_set` (user confirms) |

6) Tool governance layer (Gateway + Policy/Cedar + Audit)

```mermaid
flowchart TD
  A["Agent (Runtime)<br/>requests tool call"] --> GW["AgentCore Gateway (MCP)"]
  GW --> INT["Gateway Interceptors<br/>FGAC / masking / header propagation"]
  INT --> P["AgentCore Policy Engine<br/>Cedar evaluation"]

  P -->|ALLOW| T0["Tool: KB Retrieve (Bedrock KB)"]
  P -->|ALLOW| T1["Tool: SQL Read Views (least privilege)"]
  P -->|ALLOW| T2["Tool: Code Interpreter (what-if)"]
  P -->|ALLOW| T3["Tool: Notification Sender (SNS/Pinpoint)"]
  P -->|ALLOW| T4["Tool: Tx Categorizer (Jar + Category)"]
  P -->|ALLOW| T5["Tool: Signals/Forecast (read-only)"]
  P -->|ALLOW| T6["Tool: Rules/Budgets (write)"]

  P -->|DENY| D["Block + safe response<br/>(educate / escalate Tier2)"]

  T0 --> L["Log: tool + params hash + kb chunk ids"]
  T1 --> L
  T2 --> L
  T3 --> L
  T4 --> L
  T5 --> L
  T6 --> L
  D --> L
  L --> CW["CloudWatch + Audit Logs"]
```

7) Memory layer (short-term vs long-term) + "do not store ledger"

```mermaid
flowchart LR
  subgraph Session["Session (short-term)"]
    S1[Conversation state\ncurrent assumptions]
    S2[Pending scenario\nwhat-if knobs]
  end

  subgraph LongTerm["Long-term Memory"]
    L1[User preferences\nnotification cadence]
    L2[Goal summaries\nhouse horizon band]
    L3[Behavior summaries\noverspend travel pattern]
  end

  Agent[AgentCore Runtime] --> Session
  Agent --> LongTerm

  MWG["Memory Write Guard<br/>(PII/sensitive check)"]:::guard

  Session -. summarize .-> MWG -. store .-> LongTerm

  subgraph NoStore["Do NOT store in memory"]
    X1[Raw transaction ledger]
    X2[Account numbers / IDs / addresses]
    X3[Free-text sensitive notes]
  end
  NoStore -. excluded .- Agent

  classDef guard fill:#fff,stroke:#333,stroke-dasharray: 5 5;
```
