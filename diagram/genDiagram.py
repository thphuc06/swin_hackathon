"""
=============================================================================
Fintech Agentic AI Platform – AWS Architecture Diagram  (SVG output)
=============================================================================
Author  : AWS Cloud Architect & Python Engineer
Purpose : Generate a scalable-vector (SVG) architecture diagram for an
          Agentic AI Financial Advisory Platform.
          SVG là định dạng vector nên zoom không vỡ, dễ chỉnh sửa bằng
          Inkscape / Illustrator, và có thể nhúng thẳng vào HTML / LaTeX.

Dependencies:
    pip install diagrams

Run:
    python fintech_agentic_ai_svg.py

Output:
    fintech_agentic_ai.svg  (trong thư mục hiện tại)
=============================================================================
"""

import base64
import re
from pathlib import Path

from diagrams import Diagram, Cluster, Edge

# ── AWS Icons ─────────────────────────────────────────────────────────────────
from diagrams.aws.general import User          # Entry-point: end user
from diagrams.aws.ml import Bedrock            # AI Agents + LLM Engine
from diagrams.aws.network import APIGateway    # MCP Gateway
from diagrams.aws.database import Aurora       # Aurora PostgreSQL
from diagrams.aws.storage import S3            # Knowledge Base

# ─────────────────────────────────────────────────────────────────────────────
# Function to embed images into SVG - fix for image display issues
# ─────────────────────────────────────────────────────────────────────────────
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
# Graph Attributes  — kiểm soát layout và chữ toàn biểu đồ
# ─────────────────────────────────────────────────────────────────────────────
GRAPH_ATTR = {
    "rankdir":  "LR",       # Hướng: Left → Right
    "pad":      "0.80",     # Padding quanh canvas
    "nodesep":  "0.60",     # Khoảng cách ngang giữa các node
    "ranksep":  "1.30",     # Khoảng cách giữa các cột (rank)
    "fontname": "Helvetica",
    "fontsize": "13",
    "bgcolor":  "#FAFAFA",  # Màu nền nhẹ, trông chuyên nghiệp
}

NODE_ATTR = {
    "fontname": "Helvetica",
    "fontsize": "11",
}

EDGE_ATTR = {
    "fontname": "Helvetica",
    "fontsize": "9",
    "color":    "#555555",
    "penwidth": "1.6",
}

# ─────────────────────────────────────────────────────────────────────────────
# Output file path
# ─────────────────────────────────────────────────────────────────────────────
output_base = Path(__file__).resolve().parent / "fintech_agentic_ai"

# ─────────────────────────────────────────────────────────────────────────────
# Diagram — outformat="svg" để xuất file vector
# ─────────────────────────────────────────────────────────────────────────────
with Diagram(
    name      = "Fintech Agentic AI Platform – AWS Reference Architecture",
    filename  = str(output_base),           # → fintech_agentic_ai.svg
    outformat = "svg",                      # ← SVG output
    direction = "LR",
    show      = False,                  # Không tự mở file sau khi tạo
    graph_attr = GRAPH_ATTR,
    node_attr  = NODE_ATTR,
    edge_attr  = EDGE_ATTR,
):

    # ── 0. Entry-point ──────────────────────────────────────────────────────
    user = User("User\n(Mobile / Web)")

    # ── 1. Cluster: Tier 2 – AgentCore Runtime ──────────────────────────────
    with Cluster(
        "Tier 2 – AgentCore Runtime",
        graph_attr={
            "style":     "dashed",
            "bgcolor":   "#EAF4FB",
            "fontcolor": "#1A5276",
            "fontsize":  "12",
            "pencolor":  "#2E86C1",
        },
    ):
        # Node điều phối trung tâm
        orchestrator = Bedrock("Orchestrator Agent\n(Routing & State)")

        # Sub-cluster: 4 Sub-agents chuyên biệt
        with Cluster(
            "Specialised Sub-Agents",
            graph_attr={
                "style":     "dotted",
                "bgcolor":   "#D6EAF8",
                "fontcolor": "#1A5276",
                "fontsize":  "11",
                "pencolor":  "#5DADE2",
            },
        ):
            profiling_agent  = Bedrock("Profiling Agent")
            planner_agent    = Bedrock("Planner Agent")
            compliance_agent = Bedrock("Compliance Agent")
            explainer_agent  = Bedrock("Explainer Agent")

        sub_agents = [profiling_agent, planner_agent, compliance_agent, explainer_agent]

    # ── 2. Cluster: Governed Tool Plane ─────────────────────────────────────
    with Cluster(
        "Governed Tool Plane",
        graph_attr={
            "style":     "dashed",
            "bgcolor":   "#FDFEFE",
            "fontcolor": "#6E2F8C",
            "fontsize":  "12",
            "pencolor":  "#9B59B6",
        },
    ):
        mcp_gateway = APIGateway("AgentCore Gateway\n(MCP Server)")

    # ── 3. Cluster: System of Record & Tools ────────────────────────────────
    with Cluster(
        "System of Record & Tools",
        graph_attr={
            "style":     "dashed",
            "bgcolor":   "#EAFAF1",
            "fontcolor": "#1E8449",
            "fontsize":  "12",
            "pencolor":  "#27AE60",
        },
    ):
        aurora  = Aurora("Aurora PostgreSQL\n(SQL DB)")
        s3_kb   = S3("Amazon S3\n(Knowledge Base Docs)")
        bedrock_llm = Bedrock("Amazon Bedrock\n(LLM Engine)")

    # ── Edges / Kết nối ──────────────────────────────────────────────────────

    # [A] User → Orchestrator (yêu cầu đầu vào)
    user >> Edge(label="Request", color="#2E86C1", style="bold") >> orchestrator

    # [B] Orchestrator → từng Sub-agent (fan-out điều phối)
    for agent in sub_agents:
        orchestrator >> Edge(label="Dispatch", color="#5DADE2") >> agent

    # [C] Mọi Sub-agent → MCP Gateway (bắt buộc đi qua cổng tập trung)
    for agent in sub_agents:
        agent >> Edge(label="Tool Call (MCP)", color="#9B59B6") >> mcp_gateway

    # [D] MCP Gateway → các tài nguyên backend
    mcp_gateway >> Edge(label="Query / Write",  color="#27AE60") >> aurora
    mcp_gateway >> Edge(label="Retrieve Docs",  color="#27AE60") >> s3_kb
    mcp_gateway >> Edge(label="LLM Inference",  color="#27AE60") >> bedrock_llm

# ─────────────────────────────────────────────────────────────────────────────
# Embed images into the SVG file
# ─────────────────────────────────────────────────────────────────────────────
svg_path = output_base.with_suffix(".svg")
inline_svg_images(svg_path)

print("✅  SVG diagram generated → fintech_agentic_ai.svg")
print("✅  Images embedded successfully")