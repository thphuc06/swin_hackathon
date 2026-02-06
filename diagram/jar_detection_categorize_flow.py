import base64
import re
from pathlib import Path

from diagrams import Diagram, Cluster, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.database import Aurora
from diagrams.aws.general import General, MobileClient, User
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import APIGateway
from diagrams.aws.security import IAMPermissions


output_base = Path(__file__).resolve().parent / "jar-detection-categorize-flow"


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
    svg_path.write_text(content, encoding="utf-8")

# Run: python diagram/jar_detection_categorize_flow.py
# Output: diagram/jar-detection-categorize-flow.svg
with Diagram(
    "External Transaction -> Jar Detection + Attach Flow",
    filename=str(output_base),
    outformat="svg",
    show=False,
    direction="LR",
    graph_attr={"fontsize": "20", "pad": "0.8", "nodesep": "0.8", "ranksep": "0.9"},
    node_attr={"fontsize": "16"},
    edge_attr={"fontsize": "14"},
):
    user = User("Customer")
    external = General("External/Recurring\nCharge Event")

    with Cluster("Client"):
        ui = MobileClient("Web/Mobile UI")
        review = General("Review Queue\n(when low confidence)")

    with Cluster("Backend"):
        api = APIGateway("Ingestion API")
        bff = Lambda("Ingestion/BFF")

    with Cluster("Tool Plane"):
        gateway = General("AgentCore Gateway")
        policy = IAMPermissions("Policy\n(Cedar)")
        categorizer = Bedrock("llm_categorize_tx\n(read description)")

    with Cluster("System of Record"):
        db = Aurora("Postgres\nTransactions + Jars")

    # External transaction is categorized from description and attached to a Jar.
    external >> Edge(label="charge event") >> api >> gateway >> policy >> categorizer
    categorizer >> Edge(label="jar_id + category + confidence") >> bff
    bff >> Edge(label="high confidence: attach Jar + store") >> db
    bff >> Edge(label="low confidence: send to review") >> review
    user >> ui >> Edge(label="review + confirm Jar") >> api >> Edge(label="update txn") >> db


inline_svg_images(output_base.with_suffix(".svg"))
