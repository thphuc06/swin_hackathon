"""
=============================================================================
Fintech Two-Tier Agentic AI Platform – Improved Architecture Diagram v2
=============================================================================
Cải tiến so với bản cũ:
  - Layout LR (Left→Right) — đọc luồng tự nhiên hơn
  - Tier 1 & Tier 2 xếp song song, kết nối rõ ràng
  - Compliance/Guardrails là middleware layer, KHÔNG phải peer agent
  - splines=ortho → mũi tên vuông, không chồng chéo
  - Visual hierarchy: User → Input Layer → Runtime → Tool Plane
Run:
    pip install diagrams
    python fintech_two_tier_multiagent_architecture.py
Output:
    fintech-two-tier-multiagent-architecture.svg
=============================================================================
"""

import base64
import re
from pathlib import Path

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.general import User, MobileClient
from diagrams.aws.compute import Lambda
from diagrams.aws.network import APIGateway
from diagrams.aws.security import Shield, WAF
from diagrams.aws.database import Aurora, Dynamodb
from diagrams.aws.storage import S3
from diagrams.aws.ml import Sagemaker
from diagrams.aws.integration import Eventbridge, SQS, SNS


def inline_svg_images(svg_path: Path) -> None:
    """Embed external image references as base64 data URIs in the SVG file."""
    content = svg_path.read_text(encoding="utf-8")

    def replace_href(match: re.Match[str]) -> str:
        href = match.group(1)
        if href.startswith("data:"):
            return match.group(0)
        try:
            img_bytes = Path(href).read_bytes()
        except OSError:
            return match.group(0)
        encoded = base64.b64encode(img_bytes).decode("ascii")
        return f'xlink:href="data:image/png;base64,{encoded}"'

    content = re.sub(r'xlink:href="([^"]+)"', replace_href, content)
    svg_path.write_text(content, encoding="utf-8")

# ─────────────────────────────────────────────────────────────────────────────
# Attributes
# ─────────────────────────────────────────────────────────────────────────────
GRAPH_ATTR = {
    "rankdir":  "LR",
    "splines":  "ortho",       # mũi tên vuông, không chồng chéo
    "pad":      "0.80",
    "nodesep":  "0.50",
    "ranksep":  "1.40",
    "fontname": "Helvetica",
    "fontsize": "13",
    "bgcolor":  "#F7F9FC",
    "compound": "true",
}
NODE_ATTR = {"fontname": "Helvetica", "fontsize": "10", "margin": "0.15"}
EDGE_ATTR = {"fontname": "Helvetica", "fontsize": "8", "penwidth": "1.6", "color": "#555F70"}

C_TIER1   = {"style":"dashed","bgcolor":"#F0FFF4","fontcolor":"#1A6B3C","pencolor":"#38A169","fontsize":"11"}
C_TIER2   = {"style":"dashed","bgcolor":"#EBF4FF","fontcolor":"#1A4A8A","pencolor":"#3B82F6","fontsize":"11"}
C_INPUT   = {"style":"dotted","bgcolor":"#EDE9FE","fontcolor":"#5B21B6","pencolor":"#7C3AED","fontsize":"10"}
C_RUNTIME = {"style":"dotted","bgcolor":"#DBEAFE","fontcolor":"#1E40AF","pencolor":"#2563EB","fontsize":"10"}
C_AGENTS  = {"style":"dotted","bgcolor":"#BFDBFE","fontcolor":"#1E3A8A","pencolor":"#1D4ED8","fontsize":"9"}
C_TOOLS   = {"style":"dashed","bgcolor":"#FDF4FF","fontcolor":"#6B21A8","pencolor":"#9333EA","fontsize":"11"}

# ─────────────────────────────────────────────────────────────────────────────
# Diagram
# ─────────────────────────────────────────────────────────────────────────────
output_base = Path(__file__).resolve().parent / "fintech-two-tier-multiagent-architecture"

with Diagram(
    name       = "Fintech Two-Tier Architecture: Orchestrator + MultiAgent System",
    filename   = str(output_base),
    outformat  = "svg",
    direction  = "LR",
    show       = False,
    graph_attr = GRAPH_ATTR,
    node_attr  = NODE_ATTR,
    edge_attr  = EDGE_ATTR,
):

    # ── Actors ────────────────────────────────────────────────────────────────
    customer = User("Customer")
    ui       = MobileClient("UI\n(Mobile / Web)")

    # ── TIER 1: Proactive Notifications ──────────────────────────────────────
    with Cluster("Tier 1 – Proactive Notifications", graph_attr=C_TIER1):
        event   = Eventbridge("Event\n(Trigger)")
        buffer  = SQS("Buffer\n(Queue)")
        workers = Lambda("Workers\n(Processor)")
        pg_t1   = Aurora("PostgreSQL\n(State Store)")
        alerts  = SNS("Alerts\n(Push/Email)")

        event   >> Edge(color="#38A169") >> buffer
        buffer  >> Edge(color="#38A169") >> workers
        workers >> Edge(color="#38A169") >> pg_t1
        workers >> Edge(label="insight", color="#38A169") >> alerts

    # ── TIER 2: Deep Advisory ─────────────────────────────────────────────────
    with Cluster("Tier 2 – Deep Advisory (Orchestrator + MultiAgent)", graph_attr=C_TIER2):

        with Cluster("Input & Safety Layer", graph_attr=C_INPUT):
            chat_api   = APIGateway("Chat API\n(Entry Point)")
            guardrails = Shield("Guardrails\n(PII / Safety)")
            memory     = Dynamodb("AgentCore\nMemory")

        bedrock = Sagemaker("Bedrock\n(LLM Engine)")

        with Cluster("AgentCore Runtime", graph_attr=C_RUNTIME):
            orchestrator = Lambda("Orchestrator\n(Routing + Output)")

            with Cluster("Specialised Agents", graph_attr=C_AGENTS):
                planner  = Lambda("Planner\nAgent")
                profiler = Lambda("Profiling\nAgent")

        # Luồng nội bộ Tier 2
        chat_api     >> Edge(label="input",     color="#7C3AED") >> guardrails
        guardrails   >> Edge(label="validated", color="#7C3AED") >> orchestrator
        orchestrator >> Edge(label="output",    color="#2563EB", style="dashed") >> bedrock
        bedrock      >> Edge(label="reasoning", color="#2563EB", style="dashed") >> orchestrator
        memory       >> Edge(label="context",   color="#6B7280", style="dashed") >> orchestrator
        orchestrator >> Edge(color="#1D4ED8") >> planner
        orchestrator >> Edge(color="#1D4ED8") >> profiler

    # ── Tool Plane ────────────────────────────────────────────────────────────
    with Cluster("Tool Plane", graph_attr=C_TOOLS):
        gateway   = APIGateway("Gateway\n(MCP Server)")
        policy    = WAF("Policy\n(Cedar)")
        kb        = S3("Knowledge Base\n(RAG Docs)")
        fin_tools = Lambda("Financial\nTools")
        pg_tools  = Aurora("PostgreSQL\n(User Data)")

        gateway >> Edge(label="authorize", color="#9333EA") >> policy
        policy >> Edge(color="#9333EA") >> kb
        policy >> Edge(color="#9333EA") >> fin_tools
        policy >> Edge(color="#9333EA") >> pg_tools

    # ── Cross-Cluster Edges ───────────────────────────────────────────────────

    # Customer ↔ UI
    customer >> Edge(label="prompt",      color="#374151", penwidth="2.0") >> ui
    alerts   >> Edge(label="alert",       color="#38A169", style="dashed") >> customer

    # UI → Tier 2
    ui >> Edge(label="API call", color="#7C3AED", penwidth="2.0") >> chat_api

    # Tier 2 response → UI
    orchestrator >> Edge(label="response", color="#7C3AED", style="dashed", penwidth="2.0") >> ui

    # Agents → MCP Gateway (tất cả tool call đều qua gateway)
    planner  >> Edge(label="tool call", color="#9333EA") >> gateway
    profiler >> Edge(label="tool call", color="#9333EA") >> gateway

    # Transaction feedback: DB → Tier 1 event trigger
    pg_tools >> Edge(label="transaction", color="#38A169", style="dashed") >> event

# ─────────────────────────────────────────────────────────────────────────────
# Post-process: Embed images into SVG
# ─────────────────────────────────────────────────────────────────────────────
svg_path = output_base.with_suffix(".svg")
inline_svg_images(svg_path)

print("✅  Diagram generated: fintech-two-tier-multiagent-architecture.svg")
print("✅  Images embedded successfully")
print(f"✅  Location: {svg_path}")