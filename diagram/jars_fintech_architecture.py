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
from diagrams.aws.management import Cloudwatch
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import APIGateway
from diagrams.aws.security import Cognito, IAMPermissions
from diagrams.aws.storage import S3
from diagrams.aws.analytics import AmazonOpensearchService


output_base = Path(__file__).resolve().parent / "jars-fintech-architecture"


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


# Run: python diagram/jars_fintech_architecture.py
# Output: diagram/jars-fintech-architecture.svg
with Diagram(
    "Jars Fintech Architecture (AWS)",
    filename=str(output_base),
    outformat="svg",
    show=False,
    direction="LR",
    graph_attr={"pad": "0.75", "nodesep": "0.85", "ranksep": "0.95", "fontsize": "20"},
    node_attr={"fontsize": "16"},
    edge_attr={"fontsize": "14"},
):
    user = User("Customer")

    with Cluster("Client"):
        ui = MobileClient("Web / Mobile UI\nNext.js")

    with Cluster("Auth"):
        cognito = Cognito("Cognito\nUser Pool")

    with Cluster("API + BFF"):
        apigw = APIGateway("API Gateway")
        bff = Lambda("BFF (FastAPI)\nLambda/ECS/App Runner")

    with Cluster("Tool Plane (Governed)"):
        gateway = General("AgentCore Gateway\n(MCP)")
        policy = IAMPermissions("Policy\n(Cedar)")
        llm = Bedrock("Bedrock LLM\n(llm_categorize_tx, advice)")
        kb = Bedrock("Bedrock KB\n(citations)")
        os = AmazonOpensearchService("OpenSearch Serverless\n(Vector store)")

    with Cluster("Data of Record"):
        aurora = Aurora("Postgres\nSupabase -> Aurora PG")

    with Cluster("Event-Driven Tier1"):
        eb = Eventbridge("EventBridge")
        sqs = SimpleQueueServiceSqs("SQS Buffer")
        agg_worker = Lambda("Aggregation Worker")
        trig_worker = Lambda("Triggers/Notifications")
        notify = SimpleNotificationServiceSns("SNS/Pinpoint")

    with Cluster("Observability"):
        cw = Cloudwatch("CloudWatch + OTel")

    with Cluster("RAG Corpus"):
        s3 = S3("S3 Policies/Templates/Services")

    # Client -> Auth -> API
    user >> ui >> Edge(label="JWT flow") >> cognito
    cognito >> apigw >> bff

    # BFF -> Tool plane -> governed resources
    bff >> gateway >> policy
    policy >> Edge(label="allow read") >> aurora
    policy >> Edge(label="allow LLM") >> llm
    policy >> Edge(label="allow KB") >> kb
    kb >> os

    # Event-driven Tier1
    bff >> Edge(label="TransactionCreated") >> eb >> sqs >> agg_worker >> aurora
    agg_worker >> trig_worker >> notify >> ui

    # External/recurring feed could enter via API Gateway as well
    apigw >> Edge(label="external feed\n(recurring charges)") >> gateway >> policy >> llm

    # Observability
    bff >> cw
    gateway >> cw
    policy >> cw
    agg_worker >> cw
    trig_worker >> cw


inline_svg_images(output_base.with_suffix(".svg"))
