# Agentic AI Financial Advisor with Suitability

*Anonymous Author(s) — Anonymous Affiliation*

---

## Abstract

Retail financial advisory is still costly and human dependent, so mass retail users with cashflows spread across banks and e-wallets often receive generic, product-centric guidance that does not match goals, liquidity needs, or risk tolerance. We propose an agentic financial advisor that runs a continuous **plan-act-check loop** to consolidate transactions, allocate budget jars, build goal-based plans, monitor deviations and abnormal spending, and present explainable tradeoffs (conservative/balanced/growth). Recommendations are gated by suitability/best-interest guardrails, explained transparently, and logged for auditability, with user approval required for high-impact actions or low-confidence cases. Expected impact includes higher personalization and trust, lower cost-to-serve, and improved compliance, measured via acceptance, retention, goal-progress proxies, complaint/override rate, and cost per served user. We will prototype Money Inbox, auto-categorization, jar allocation, early alerts, a goal planner, and an audit pipeline, and evaluate via simulation and a small pilot.

**Index Terms:** agentic AI, fintech, financial advisory, suitability, best-interest, audit trail, AWS

---

## I. Executive Summary

| | |
|---|---|
| **Problem** | Due to lack of knowledge, Vietnamese consumers struggle with financial literacy, leading to irrational spending with uncoordinated and unsystematic personal finance. |
| **Who affected** | Mass retail segment and financial institutions/platforms. |
| **Why now** | A significant advice gap exists between the vast demand of financial guidance and the limited supply of qualified professionals, a situation further exacerbated by rising operational costs. Moreover, the rapid explosion of AI and Fintech has raised the urgent need for transparency. |
| **Proposed solution** | An agentic financial advisor automates goal-based budgeting via a multi-jar system, providing transparent recommendations with suitability guardrails and full audit trails. |

**Business Value & KPIs:**
- **Value:** Increase retention and trust.
- **KPIs:** Acceptance rate of suggestions, D30 retention.

---

## II. Innovation

### A. Novelty

- **Continuous Advisor (vs. One-shot Chatbot):** Unlike standard chatbots, it runs a continuous loop including monitoring cash flow, updating plans, and suggesting proactive adjustments.
- **Audit Trail Engine:** Not only does it suggest plans, but it also runs suitability checks and generates an automated audit trail. This is surfaced within the explanation module to provide users with absolute clarity and transparency regarding every action taken.
- **Trade-off Options (conservative/balanced/growth) + Explanation:** Instead of prescriptive advice, our agent provides a multi-scenario decision framework. By merging behavioral patterns with financial objectives, it empowers users with clear trade-offs between liquidity, speed, and risk.
- **Macro-Responsive Budgeting:** The system dynamically adjusts jar allocation recommendations in response to real-time macroeconomic signals (CPI, interest rates, VN-Index), a capability not present in existing Vietnamese fintech apps.

### B. Autonomy of the Agentic AI

The system autonomously plans jar allocations, retrieves transactions under suitability constraints, proposes 2–3 trade-off scenarios, provides transparent explanations, and triggers Human-in-the-Loop approval for high-impact actions. All decisions are logged for audit and anomaly detection.

### C. Business Value Alignment

| KPI | Target | Stretch |
|---|---|---|
| Acceptance rate | 35–45% | 45–55% |
| D30 retention | 20–30% | 30–40% |
| Overspend/shortfall incidents | −15–25% | −25–40% |
| Complaint/override rate | < 2–3% | < 1–2% |
| Cost per served user | −30–50% | −50–70% |
| Trust score (1–5) | +0.4 to +0.7 | +0.8 to +1.0 |

---

## III. Project Scope & Problem Definition

### A. Problem Overview

**In-scope:**
- **Target:** Mass retail users in Vietnam with multi-source income and limited financial literacy.
- **Platform:** Mobile fintech app integrating bank accounts, e-wallets, and (for high-tier users) stock trading platforms.
- **Solution:** Agentic Financial Advisor consolidating cashflows, categorizing transactions, allocating budget jars, monitoring goal drift, and providing early alerts. Features suitability checks, transparent explanations, audit logging, and human-in-the-loop for high-impact cases.

**Out-of-scope:**
- Short-term trading (day-trading, market timing).
- High-risk recommendations exceeding user risk appetite.
- Full integration with all banks (prototype will support select sources or simulated data).
- Direct recommendations for specific securities or funds — Market Agent provides macro context and asset class allocation ratios only, not securities advisory.

### B. Business Impact

- **Cost/scale:** As the number of users increases, platforms have to lower personalized financial service quality due to resource constraints.
  - *KPIs: Cost per served user, time per user, users/advisor ratio.*
- **Customer outcomes & trust:** Generic suggestions look like sale pitches rather than financial support, resulting in lower users' trust and most of them don't follow the advice.
  - *KPIs: Acceptance rate, retention, trust score, complaint rate.*
- **If not solved:** Platforms face rising customer acquisition cost and falling retention, while users experience frequent budget collapse leading to abandoned financial goals. Compounded by weak suitability controls, this increases mis-selling risk and regulatory complaints, ultimately driving churn and declining acceptance rates.

### C. Evidence

- **Advice Gap:** Financial consulting services cost 6+ million VND [1] while the average Vietnamese salary is only 8 million VND [2], making advisory inaccessible to most.
- **Behavioral Barriers:** 47.7% of investors exhibit loss aversion bias [3], while 51% make emotionally-driven decisions and 48% lack sufficient financial knowledge [5]. UOB (2025) reports rising anxiety over long-term finances [4].
- **Consequences:** 74% report income insufficient to cover basic needs [6], 47% of youth have zero emergency savings, and 3 in 10 rely on debt for crises [7].

---

## IV. Target Users & Stakeholders

### A. Primary User

**Jobs-To-Be-Done:**
> "When I receive my salary (and other income) and make purchases across multiple channels (including cash), I want an app that automatically allocates my money into appropriate budget jars based on my goals and risk tolerance, so I can stay on track, avoid shortfalls, and feel confident about my long-term financial future without feeling 'sold to'."

**Top Pain Points:**
- Missing or unsynced data (especially cash micro-transactions) reduces plan accuracy and user trust.
- Product-centric interfaces rarely explain trade-offs, creating a perceived sales push rather than goal alignment.
- Users are risk-averse toward investing yet worry that holding cash erodes value under inflation.
- Manual logging friction causes low adherence, breaking budgeting continuity.

### B. Secondary Stakeholders

| Stakeholder | Pain Point |
|---|---|
| Financial institution / platform | High support/advisor workload increases operating cost. |
| Compliance/Advisor | Limited auditability and difficulty verifying recommendation rationale. |
| Regulator | Risk of mis-selling and insufficient transparency for retail protection. |
| Data partners | Access control constraints and the need for secure, stable API integration (SLA). |

### C. Customer Journey Map (As-Is) and Opportunities

| Stage | Current Pain | Opportunity |
|---|---|---|
| Onboarding | Fragmented data | Connect sources, Money Inbox, auto-categorization |
| Planning | Unclear jar allocation | Goal/risk-aware presets |
| Monitoring | Weak goal visibility | Progress + monthly contribution targets |
| Disruptions | Expense spikes/shortfalls | Anomaly detection, alerts, rebalancing |
| Decisions | Trade-off ambiguity | 3 options with explanations, suitability checks, confirmations |

---

## V. Project Requirements & Data Strategy

### A. Functional Requirements (Must-Have)

- **Dynamic Onboarding & Risk Profiling:** Builds risk profiles via conversational AI, recalibrating parameters continuously based on real-time transaction behavior.
- **Multi-scenario Planning:** Generates Conservative, Balanced, and Growth trajectories with defined caps and trade-off analyses to visualize opportunity costs.
- **Suitability & Red-flag Triggers:** Monitors anomalies via a "Best-interest" engine, triggering alerts when spending decouples from strategic objectives.
- **Traceable Audit Logging:** Assigns a `trace_id` to every request, logging all AI telemetry to CloudWatch for accountability and forensic analysis.
- **Macro-Aware Portfolio Nudging:** Market Agent monitors public economic indicators (VN-Index, CPI, SBV interest rates) and uses Efficient Frontier modeling to suggest asset class allocation ratios (cash / fixed income / equity). When macro conditions shift beyond defined thresholds, Planner Agent sends a contextual recommendation requiring explicit user confirmation before any jar reallocation is applied.
- **Proactive Jar Execution:** A user-driven UI mechanism enabling users to manually select pre-allocated budget jars to directly initiate payments or transfers. This guarantees real-time budget deduction and immediate tracking.

### B. Non-Functional Requirements

| Category | Requirement |
|---|---|
| **Latency** | TTFB < 3s; Completes complex financial blocks in < 20s, strictly sequestering outputs until they pass Amazon Cedar policy enforcement for accuracy |
| **Security** | PII redaction via Bedrock Guardrails; JWT auth; PBAC via Amazon Cedar for zero-trust access control |
| **Reliability** | Graceful degradation to SQL fallback; Data grounding eliminates numerical hallucinations |

### C. Data Strategy

- **Sources & Storage:** Manages banking, profile, and market data using PostgreSQL for structured records and S3 for unstructured knowledge assets.
- **Pipeline:** Leverages EventBridge for real-time processing and daily aggregations to support 30/60/90-day trend analysis.
- **Quality Gate & Data Integrity:** Enforces SQL-only numerical fetching and a Reliability Score (threshold 0.75) that forces the AI to "Clarify" if data is insufficient, preventing misaligned advice.
- **Manual Execution Bypass:** Outgoing transactions proactively initiated by the user from a specific jar via the UI bypass the categorization pipeline entirely. These are logged directly to the Database via SQL, ensuring zero processing latency and zero LLM API overhead.

**Jar Categorization Pipeline:**

| Step | Mechanism |
|---|---|
| **Deterministic Lookup** | Deterministic SQL > LLM: Instant classification with zero API overhead or processing delays. |
| **AI Inference Fallback** | Cross-references metadata with Knowledge Base to provide category suggestions and confidence levels. |
| **Human-in-the-loop & Persist** | User feedback instantly creates new SQL rules; subsequent identical transactions are handled at Step 1, eliminating future LLM dependency. |

### D. Suitability / Best-Interest Constraints

- **Input Prerequisites:** Advisory is locked until 6 factors (Risk, Horizon, Liquidity, Experience, Objectives, Constraints) are fully profiled.
- **Hard Constraints:** Blocks any product exceeding risk thresholds, caps high-volatility assets, and mandates total fee transparency.
- **Mandatory Output:** Every response must include Rationale, Alternatives, Suitability Check, and a `trace_id`.

---

## VI. Solution Design (Agentic AI)

### A. Solution Overview

The Agentic AI system replaces static advisory models with a goal-oriented multi-agent architecture, integrating dynamic risk assessment via tool-use (SQL/Knowledge Base) and self-auditing through compliance constraints.

### B. Agent Roles & Responsibilities

#### 1. Multi-Agent System (Reasoning Layer)

- **Orchestrator Agent:** Coordinates intent routing and maintains the conversational ReAct loop state utilizing LangGraph and Aurora PostgreSQL (State Store).
- **Planner Agent:** Analyzes risk profiles and cash flows to deterministically generate optimized financial scenarios via Aurora PG (SQL) and a custom Financial Math Engine.
- **Market Agent:** Aggregates public market data (VN-Index, CPI/interest rate signals) and applies Efficient Frontier modeling to suggest asset class allocation ratios based on user risk profile — passed to Planner Agent as enrichment context, not as securities recommendations.
  > *Example: Rising CPI triggers Emergency Jar increase from 10% to 15%. Financial research capabilities are augmented using Dexter [8], an open-source autonomous agent for deep financial research, adapted for Vietnamese market data ingestion.*

#### 2. AgentCore Services (Control & Governance Plane)

- **AgentCore Memory:** Injects cross-session context to ensure seamless continuity, eliminating redundant user re-profiling via AgentCore Store and User Profile Schema.
- **AgentCore Identity:** Enforces zero-trust validation for individual agent credentials using AWS IAM and Cognito JWT Validator, strictly preventing lateral privilege escalation.
- **AgentCore Observability:** Traces every AI decision and tool call via `trace_id` to maintain an immutable forensic audit trail on CloudWatch and S3 Glacier.

#### 3. Output Processing Pipeline

- **Bedrock LLM Response:** Outputs structured JSON based on strict schemas, appending concrete citations sourced from the Knowledge Base (RAG) and generating a Confidence Score for each financial recommendation.
- **Orchestrator Post-processing:** Renders the structured JSON into Natural Language, automatically injecting mandatory legal disclaimers (Tier-2 rules), and formatting the final payload for UI rendering (Markdown/Plain text).

### C. Human-in-the-Loop Boundaries

HITL oversight is enforced at three levels:

**(1) User confirmation required for:**
- High-risk investment actions.
- Low-confidence cases with missing or contradictory data.
- Policy-threshold breaches (e.g., expenditures exceeding 90% of income).

**(2) Auto-escalation to human advisors triggers for:**
- Vague or repetitive user intent exceeding safety parameters.
- Edge-case scenarios outside AI logic (e.g., bankruptcy, inheritance).

**(3) Policy fail-safe hands control to compliance experts if:**
- Amazon Cedar consistently blocks AI-generated responses.

---

## VII. System Architecture & Workflow (AWS + Agent Runtime)

### A. System Architecture

> **[Figure 1 — System Architecture Diagram]**
>
> The architecture is a **two-tier hybrid system**:
>
> ```
> ┌─────────────────────────────────────────────────────────────┐
> │  TIER 1 — Proactive Notifications (Zero LLM Overhead)       │
> │                                                             │
> │  New Transaction                                            │
> │       │                                                     │
> │       ▼                                                     │
> │  Event Trigger → Buffer/Queue → Workers/Processor           │
> │       │                                                     │
> │       ▼                                                     │
> │  Aurora State Store → Anomaly Detection → Alert Push/Email  │
> │       │                                                     │
> │       ▼                                                     │
> │  User                                                       │
> └─────────────────────────────────────────────────────────────┘
>
> ┌─────────────────────────────────────────────────────────────┐
> │  TIER 2 — Deep Advisory (Activated on User Engagement)      │
> │                                                             │
> │  API Gateway                                                │
> │       │                                                     │
> │  Bedrock Guardrails (PII mask, prompt injection block)      │
> │       │                                                     │
> │  LangGraph Orchestrator + AgentCore Memory                  │
> │       │                                                     │
> │  Planner Agent ←→ Market Agent                              │
> │       │                                                     │
> │  MCP Gateway (Amazon Cedar PBAC check)                      │
> │       │                                                     │
> │  Aurora SQL / RAG Knowledge Base                            │
> │       │                                                     │
> │  Structured JSON Response → UI                              │
> └─────────────────────────────────────────────────────────────┘
> ```
>
> **Core principle:** Direct LLM data access is strictly prohibited.

**4-Layer Control Mechanism (Tier 2):**

1. **Ingestion & Edge Safety:** Requests authenticated via Amazon Cognito (JWT) at API Gateway. Bedrock Guardrails block prompt injections and mask PII before reaching the LLM.
2. **Orchestration & State Management:** LangGraph manages system state and orchestrates the ReAct loop between the Planner Agent and Market Agent.
3. **Zero-Trust Boundary (Compliance Core):** All tool invocations (Aurora SQL / Bedrock RAG) route through the MCP Gateway using short-lived AgentCore identities. Amazon Cedar SDK evaluates PBAC policies (e.g., `user.riskScore ≥ product.riskLevel`); on DENY, the Orchestrator autonomously recalibrates. A Python rule-based validator serves as fallback during Cedar disruptions.
4. **Immutable Audit & Data Integrity:** Aurora PostgreSQL enforces ACID compliance for all financial balances. Every tool invocation, `trace_id`, and Allow/Deny rationale is permanently persisted to S3 Glacier for forensic audits.

### B. Technical Dependencies

| Library | Tier | Purpose |
|---|---|---|
| **Kats (CUSUM)** | Tier 1 | Runtime anomaly detection using `CUSUMDetectorModel` with sliding `scan_window` and `historical_window` to identify abnormal mean shifts without labeled datasets. |
| **Ruptures (PELT)** | Tier 2 / Agent Tools | Offline change-point detection within spending structures for historical analysis by the Planner Agent. Prioritized over Kats at this tier for deterministic accuracy. |
| **River (ADWIN) & PyOD (ECOD)** | — | Real-time signal processing; River for concept drift detection in data distributions, PyOD for statistical outlier identification within transactions. |
| **Statsmodels & Darts** | — | Combines ARIMA/ETS for transparent statistical baselines with automated backtesting and probabilistic forecasting of confidence intervals. |
| **PyPortfolioOpt** | Tier 2 / Agent Tools | Efficient Frontier optimization to generate asset class allocation ratios. Market data sourced via VNDirect or Fireant public API with TTL validation. |

---

## VIII. Project Plan + Evaluation / KPIs

### A. Timeline

> **[Figure 2 — Gantt Chart]**
>
> The project follows a **Phased-Gate Rollout Strategy** across January–March:
>
> | Phase | Milestone | Weeks |
> |---|---|---|
> | **Phase 1** | MVP scope definition & system design | Jan, Week 1–2 |
> | **Phase 2** | AWS backend provisioning (Aurora PG, SQS, AgentCore skeleton) | Jan–Feb |
> | **Phase 3** | LangGraph integration with Zero-Trust boundary (Amazon Cedar, MCP Gateway) | Feb–Mar |
> | **Phase 4** | E2E validation, HITL testing & UI finalization | Mar |
>
> Sub-tasks include: Discovery & System Design, Data & Backend setup, Agents & Controls, Testing & Hackathon demo.

### B. Stakeholder Benefits & Measurable KPIs

| Stakeholder | Core Benefit | KPI |
|---|---|---|
| **End-Users** | Hyper-personalized planning | Personalization Lift +40%, Funnel completion > 85% |
| **Advisors & Ops** | Reduced manual workload | Advisor time reduction −70% |
| **Risk & Compliance** | Automated regulatory adherence | Suitability Violation Rate 0% |

---

## IX. Feasibility Analysis, System Evaluation & Risk Governance

### A. Evaluation Pipeline

To validate operational SLA and exactitude, the system is tested via a dual-phase pipeline:

- **Offline:** RAGAS (Faithfulness ≥ 0.85, Relevancy ≥ 0.80) + Locust latency checks. Error taxonomy guides prompt tuning.
- **Online A/B (1-Week):** Agentic vs. rule-based control. KPIs: Retention, NPS.

### B. Risk Matrix

| Risk Factor | Technical Mitigation Strategy |
|---|---|
| **Cold Start** | 3-Phase Progressive Gating: P1 (D1–7): Static 6-Jar Rules via Onboarding Quiz (0 AI). P2 (D8–30): Hybrid (Rules + AI Categorization). P3 (D30+): Full Agentic Orchestration. Threshold: `CS = min(tx_count/100, 1.0)`. |
| **Tool Integrity** | Evidence Pack: Responses must include a `trace_id` and citations from actual transaction data (Evidence-based). |
| **PII Leakage** | Bedrock Guardrails: Masks PII before Memory Layer persistence. Compliant with Vietnam's Decree No. 13/2023 (PDPD). |
| **API Latency** | Asynchronous Fallback: Implements Timeouts and a Queue mechanism to prevent Agent hanging or session stalls. |
| **Stale Market Data** | TTL Verification: Validates Timestamps. If Data Age > Threshold → Triggers an "Outdated" warning and initiates a Re-fetch. |
| **LLM Hallucination / Advisory Inaccuracy** | RAG outputs evaluated offline with RAGAS (Faithfulness ≥ 0.85, Relevancy ≥ 0.80). At runtime, all numbers come strictly from SQL Views — no autonomous AI calculations, preventing arithmetic hallucinations. |

---

## X. Conclusion

This proposal presents an Agentic AI-driven financial advisory system that combines multi-agent orchestration, real-time risk profiling, and policy-based compliance enforcement to deliver personalized, auditable financial recommendations. By integrating Amazon Bedrock, LangGraph, and Amazon Cedar with a governed tool ecosystem, the system ensures suitability, transparency, and regulatory adherence while maintaining sub-3-second response latency.

---

## References

[1] FIDT, "Financial consulting services," n.d. [Online]. Available: https://fidt.vn/

[2] Trading Economics, "Vietnam wages," 2025. [Online]. Available: https://tradingeconomics.com/vietnam/wages

[3] Q. H. Vuong and N. T. Phuc, "The disposition effect in the Vietnamese stock market," *J. Sci. & Technol. Dev.*, vol. 15, no. Q1, 2012.

[4] UOB, "ASEAN Consumer Spending Sentiment Survey 2025 – Vietnam Report," 2025. [Online]. Available: https://www.uob.com.sg/assets/webresources/asean-insights/pdf/acss-2025-vietnam-report.pdf

[5] "Phat trien 3 ben cung thang cho nganh tu van tai chinh," *Proc. 5th Annual Personal Financial Planning Forum*, Ho Chi Minh City, Vietnam, 2024.

[6] "Khao sat 65,000 nguoi di lam: 74% noi thu nhap hien tai khong du chi tieu," *Tuoi Tre*, Dec. 2024. [Online]. Available: https://tuoitre.vn/...

[7] "47% nguoi Viet tre chua co khoan tiet kiem khan cap," *Gia Dinh Online*, 2024.

[8] V. Tran, "Dexter: An autonomous agent for deep financial research," GitHub, 2026. [Online]. Available: https://github.com/virattt/dexter

[9] X. Jiang et al., "Kats," version 0.2.0, Facebook Research, Mar. 2022. [Online]. Available: https://github.com/facebookresearch/Kats

[10] C. Truong, L. Oudre, and N. Vayatis, "ruptures: change point detection in Python," *arXiv preprint arXiv:1801.00826*, Jan. 2018.

[11] J. Montiel et al., "River: machine learning for streaming data in Python," *J. Mach. Learn. Res.*, vol. 22, no. 110, pp. 1–8, 2021.

[12] A. Bifet and R. Gavalda, "Learning from time-changing data with adaptive windowing," *Proc. 2007 SIAM Int. Conf. Data Mining*, 2007, pp. 443–448.

[13] Z. Li et al., "ECOD: Unsupervised outlier detection using empirical cumulative distribution functions," *IEEE Trans. Knowl. Data Eng.*, vol. 35, no. 12, pp. 12181–12193, 2023.

[14] S. Seabold and J. Perktold, "Statsmodels: Econometric and statistical modeling with Python," *Proc. 9th Python in Science Conf.*, Austin, TX, USA, 2010, pp. 57–61.

[15] J. Herzen et al., "Darts: User-Friendly Modern Machine Learning for Time Series," *J. Mach. Learn. Res.*, vol. 23, no. 124, pp. 1–6, 2022.

[16] R. A. Martin, "PyPortfolioOpt: portfolio optimization in Python," *J. Open Source Softw.*, vol. 6, no. 61, p. 3066, May 2021.
