import base64
import re
from pathlib import Path

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Aurora
from diagrams.aws.general import General, MobileClient, User
from diagrams.aws.integration import (
    Eventbridge,
    SimpleNotificationServiceSns,
    SimpleQueueServiceSqs,
)
from diagrams.aws.ml import Bedrock, Forecast
from diagrams.aws.network import APIGateway
from diagrams.aws.security import IAMPermissions


output_base = Path(__file__).resolve().parent / "agent-advisory-tier-flow"
FONT_NAME = "Arial"
FONT_SIZE = "20"
TITLE_SIZE = "22"
EDGE_FONT_SIZE = "18"


def inline_svg_images(svg_path: Path) -> None:
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
    # Graphviz 14 can emit an oversized canvas in SVG (viewBox/width/height),
    # which leaves a large blank area around the actual diagram.
    # Normalize the canvas to the transformed graph background polygon.
    transform_match = re.search(r'<g id="graph0"[^>]*transform="[^"]*translate\(([-\d.]+) ([-\d.]+)\)"', content)
    polygon_match = re.search(r'<polygon fill="white"[^>]*points="([^"]+)"', content)
    if transform_match and polygon_match:
        tx = float(transform_match.group(1))
        ty = float(transform_match.group(2))
        points = polygon_match.group(1).split()
        xs = []
        ys = []
        for p in points:
            x_str, y_str = p.split(",")
            xs.append(float(x_str))
            ys.append(float(y_str))
        min_x = min(xs) + tx
        max_x = max(xs) + tx
        min_y = min(ys) + ty
        max_y = max(ys) + ty
        width = max_x - min_x
        height = max_y - min_y
        content = re.sub(
            r"<svg[^>]*>",
            (
                f'<svg width="{width:.0f}pt" height="{height:.0f}pt" '
                f'viewBox="{min_x:.2f} {min_y:.2f} {width:.2f} {height:.2f}" '
                'xmlns="http://www.w3.org/2000/svg" '
                'xmlns:xlink="http://www.w3.org/1999/xlink">'
            ),
            content,
            count=1,
            flags=re.DOTALL,
        )
    svg_path.write_text(content, encoding="utf-8")


def edge(label: str, **kwargs: str) -> Edge:
    return Edge(label=label, fontsize=EDGE_FONT_SIZE, fontname=FONT_NAME, **kwargs)

# Run: python diagram/agent_advisory_tier_flow.py
# Output: diagram/agent-advisory-tier-flow.svg
with Diagram(
    "Agent Advisory: Tier1 + Tier2 Flow (Bedrock, AWS)",
    filename=str(output_base),
    outformat="svg",
    show=False,
    direction="LR",
    graph_attr={
        "pad": "0.55",
        "nodesep": "0.75",
        "ranksep": "0.78",
        "fontsize": TITLE_SIZE,
        "fontname": FONT_NAME,
        "margin": "6",
        "splines": "ortho",
        "forcelabels": "true",
        "compound": "true",
    },
    node_attr={
        "fontsize": FONT_SIZE,
        "fontname": FONT_NAME,
        "labelloc": "b",
        "imagepos": "tc",
        "margin": "0.2,0.18",
    },
    edge_attr={
        "fontsize": EDGE_FONT_SIZE,
        "fontname": FONT_NAME,
        "labeldistance": "1.2",
        "labelfloat": "false",
    },
):
    user = User("Customer")
    ui = MobileClient("Web/Mobile UI")
    txn_event = Eventbridge("Transaction Event")

    with Cluster(
        "Tier1 (Proactive Notifications)",
        graph_attr={
            "rankdir": "LR",
            "pad": "0.5",
            "margin": "22",
            "labeljust": "l",
            "labelloc": "t",
            "fontsize": FONT_SIZE,
            "fontname": FONT_NAME,
        },
    ):
        t1_queue = SimpleQueueServiceSqs("SQS Buffer")
        t1_worker = Lambda("Tier1 Workers\nSignals + Forecast")
        t1_sql = Aurora("SQL Views\n(System of Record)")
        t1_notify = SimpleNotificationServiceSns("Notification\nInbox/Push")

        # Event-driven insights
        txn_event >> edge(label="TransactionCreated") >> t1_queue
        t1_queue >> edge(label="aggregate + detect") >> t1_worker
        t1_worker >> edge(label="read/write") >> t1_sql
        t1_worker >> edge(label="insight + CTA") >> t1_notify

    with Cluster(
        "Tier2 (Deep Advisory Only)",
        graph_attr={
            "rankdir": "LR",
            "pad": "0.35",
            "margin": "10",
            "labeljust": "l",
            "labelloc": "t",
            "fontsize": FONT_SIZE,
            "fontname": FONT_NAME,
        },
    ):
        t2_api = APIGateway("Chat API\n(BFF)")
        # Leading newline adds extra vertical gap so long labels do not overlap the icon.
        t2_runtime = Lambda("\nAgentCore Runtime\n(LangGraph)")
        t2_gateway = General("AgentCore Gateway\n(MCP)")
        t2_policy = IAMPermissions("Policy\n(Cedar)")
        t2_sql = Aurora("SQL Read")
        t2_forecast = Forecast("Forecast Tool")
        t2_kb = Bedrock("KB Retrieve\n(Citations)")
        mem = General("AgentCore Memory\n(prefs/goals summaries)")

        user >> edge(label="prompt", tailport="e", headport="w") >> t2_api
        t2_api >> edge(label="stream", tailport="e", headport="w") >> t2_runtime
        t2_runtime >> edge(
            label="read/write summaries",
            tailport="e",
            headport="w",
            minlen="1",
        ) >> mem
        t2_runtime >> edge(
            label="tool calls",
            tailport="ne",
            headport="sw",
            minlen="1",
        ) >> t2_gateway
        # Single edge from Gateway -> Policy to avoid duplicate arrows
        t2_gateway >> edge(label="policy check") >> t2_policy
        t2_policy >> edge(label="") >> t2_sql
        t2_policy >> edge(label="") >> t2_forecast
        t2_policy >> edge(label="") >> t2_kb
        # Balance UI vertical placement between tiers (slightly lower than before).
        t2_runtime >> Edge(style="invis", minlen="1", weight="4") >> ui
        t2_runtime >> edge(
            label="response + trace_id",
            tailport="se",
            headport="nw",
            minlen="2",
            labeldistance="0.8",
            labelangle="0",
        ) >> ui

    t1_notify >> Edge(style="invis", minlen="1", weight="8") >> ui
    t1_notify >> edge(
        label="proactive alert",
        tailport="e",
        headport="sw",
        minlen="1",
        labeldistance="0.8",
        labelangle="0",
    ) >> ui
    t1_notify >> edge(
        label="Explain",
        style="dashed",
        tailport="nw",
        headport="s",
        labeldistance="0.5",
        labelangle="0",
        constraint="false",
    ) >> t2_api


inline_svg_images(output_base.with_suffix(".svg"))
