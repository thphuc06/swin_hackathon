import json
import os
import logging
from datetime import datetime, timezone
import psycopg2
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# cusum_engine and cusum_state_manager must be bundled in the Lambda deployment zip
from cusum_state_manager import CUSUMStateManager
from cusum_engine import CUSUMTimeSeriesDetector
from income_engine import analyze_income_vs_spend

sns_client = boto3.client('sns')


class PostgresDBWrapper:
    """Wrap raw psycopg2 connection for CUSUMStateManager compatibility."""
    def __init__(self, conn):
        self.conn = conn

    def query(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                return cur.fetchall()
            return []

    def execute(self, sql, params=()):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            self.conn.commit()
            return cur


def get_db_connection():
    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        logger.error("SUPABASE_DB_URL missing from environment variables")
        return None
    return psycopg2.connect(db_url)


# =============================================================================
# Lambda Handler – Supports BOTH Supabase Webhook AND SQS payloads
# =============================================================================

def lambda_handler(event, context):
    """
    AWS Lambda entry point.

    Supported triggers:
      1. Supabase Database Webhook (via Lambda Function URL / API Gateway)
         Payload: { "type": "INSERT", "table": "transactions", "record": { ... } }
      2. AWS SQS (legacy EventBridge path)
         Payload: { "Records": [{ "body": "..." }] }
    """
    logger.info(f"Received event: {json.dumps(event)}")

    conn = get_db_connection()
    if not conn:
        return {"statusCode": 500, "body": "Database connection failed"}

    try:
        db = PostgresDBWrapper(conn)
        manager = CUSUMStateManager(db)

        # ── Detect payload format ──────────────────────────────────────────
        # Path A: Supabase Webhook (HTTP POST via Function URL / API Gateway)
        if "body" in event and isinstance(event["body"], str):
            payload = json.loads(event["body"])
            
            # --- START: Handle explicit direct SNS alerts (e.g. Budget) ---
            if payload.get("type") == "BUDGET_ALERT":
                _handle_sns_only(payload)
                return {"statusCode": 200, "body": "OK - SNS Alert processed"}
            # --- END ---
            
            record = payload.get("record", payload)
            _process_record(manager, db, record)

        elif "record" in event:
            # Direct invocation with Supabase-style JSON
            _process_record(manager, db, event["record"])

        # Path B: SQS Records (legacy EventBridge → SQS path)
        elif "Records" in event:
            for sqs_record in event["Records"]:
                body = json.loads(sqs_record.get("body", "{}"))
                detail = body.get("detail", body)
                _process_record(manager, db, detail)

        else:
            logger.warning("Unknown event format, attempting direct parse")
            _process_record(manager, db, event)

        return {"statusCode": 200, "body": "OK"}

    except Exception as e:
        logger.error(f"Lambda execution error: {e}")
        return {"statusCode": 500, "body": str(e)}
    finally:
        conn.close()


# =============================================================================
# Core Processing (shared by all trigger paths)
# =============================================================================

def _process_record(manager, db, record: dict):
    """Route record to income flow (credit) or CUSUM flow (debit)."""
    user_id = record.get("user_id")
    jar_id  = record.get("jar_id")
    amount  = record.get("amount")
    direction = record.get("direction", "debit")

    if not all([user_id, jar_id, amount]):
        logger.warning(f"Skipping record – missing fields: {record}")
        return

    amount = float(amount)

    # ── INCOME FLOW (credit) ──────────────────────────────────────────────
    if direction == "credit":
        _process_income(manager, db, user_id, jar_id, amount)
        return

    # ── CUSUM FLOW (debit) — giữ nguyên ────────────────────────────
    state_dict = manager.load_state(user_id, jar_id)

    # 2. Compute baseline statistics
    baseline = manager.get_baseline_stats(user_id, jar_id, lookback_days=30)
    weekly_mean = baseline["mean"] * 7 if baseline["mean"] > 0 else 10_000_000
    sigma = baseline["sigma"] * 2.6 if baseline["sigma"] > 0 else 1_500_000

    # 3. Initialize detector with persisted state
    detector = CUSUMTimeSeriesDetector(
        reference_mean=weekly_mean,
        sigma=sigma,
        k_factor=0.5,
        h_factor=5.0,
        z_score_threshold=4.0,
    )
    detector.cumsum_pos = state_dict["cumsum_pos"]
    detector.cumsum_neg = state_dict["cumsum_neg"]
    detector.transaction_count = state_dict["transaction_count"]

    # 4. Run CUSUM update
    timestamp = datetime.now(timezone.utc).isoformat()
    new_state, drift_detected, anomaly_info = detector.update_series(amount, timestamp)

    # 5. Persist updated state
    manager.save_state(
        user_id, jar_id,
        cumsum_pos=new_state.cumsum_pos,
        cumsum_neg=new_state.cumsum_neg,
        reference_mean=weekly_mean,
        reference_sigma=sigma,
        drift_detected=drift_detected,
        transaction_count=new_state.transaction_count,
    )

    logger.info(
        f"CUSUM OK – user={user_id} jar={jar_id} "
        f"S+={new_state.cumsum_pos:.0f} drift={drift_detected}"
    )

    # 6. Alert pathway
    if drift_detected or anomaly_info.get("type") == "sudden_spike":
        _handle_alert(db, user_id, jar_id, anomaly_info)


# =============================================================================
# Alert: DB notification + AWS SNS
# =============================================================================

def _handle_alert(db, user_id, jar_id, anomaly_info):
    _anomaly = anomaly_info.get("type", "other")
    if "up" in _anomaly or "spike" in _anomaly:
        mapped_type = "upward_drift"
    elif "down" in _anomaly:
        mapped_type = "downward_drift"
    else:
        mapped_type = "other"

    trace_id = f"auto_drift_{int(datetime.now().timestamp())}"

    # ── Insert into tier1_notifications ─────────────────────────────────
    try:
        db.execute(
            """
            INSERT INTO tier1_notifications
                (user_id, jar_id, anomaly_type, title, detail, severity, trace_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id, jar_id, mapped_type,
                "Cảnh báo CUSUM: Bất thường chi tiêu!",
                anomaly_info.get("recommendation", "Kiểm tra lại giao dịch."),
                anomaly_info.get("severity", "medium"),
                trace_id,
            ),
        )
        logger.info(f"🚨 Notification saved for {user_id}")
    except Exception as e:
        logger.error(f"Failed to save notification: {e}")

    # ── Publish to AWS SNS ──────────────────────────────────────────────
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if sns_topic_arn:
        try:
            sns_client.publish(
                TopicArn=sns_topic_arn,
                Subject="Fintech Tier 1 Alert",
                Message=f"🚨 Cảnh báo CUSUM: {anomaly_info.get('recommendation')}",
            )
            logger.info("📡 Published to SNS")
        except Exception as e:
            logger.error(f"SNS publish failed: {e}")

def _handle_sns_only(payload):
    """Directly push pre-formatted messages to SNS without DB logic."""
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if sns_topic_arn:
        try:
            sns_client.publish(
                TopicArn=sns_topic_arn,
                Subject="Fintech Budget Alert",
                Message=f"{payload.get('title', 'Cảnh báo')}\n\n{payload.get('detail', '')}",
            )
            logger.info("📡 Budget Alert published to SNS")
        except Exception as e:
            logger.error(f"SNS publish failed (Budget Alert): {e}")


# =============================================================================
# Income Detection Flow (direction == 'credit')
# =============================================================================

def _process_income(manager, db, user_id: str, jar_id: str, income: float):
    """
    Kiểm tra income vừa vào so với chi tiêu 30 ngày và gợi ý tiết kiệm.
    Chỉ gửi thông báo khi thặng dư ≥ 10% income.
    """
    monthly_spend = manager.get_monthly_spend(user_id, lookback_days=30)
    suggestion = analyze_income_vs_spend(income, monthly_spend)

    logger.info(
        f"INCOME – user={user_id} income={income:,.0f} "
        f"spend30d={monthly_spend:,.0f} surplus_pct={suggestion.surplus_pct}% "
        f"suggest={suggestion.should_suggest}"
    )

    if not suggestion.should_suggest:
        return

    trace_id = f"income_{int(datetime.now().timestamp())}"

    # ── Ghi vào tier1_notifications ────────────────────────────────────
    try:
        db.execute(
            """
            INSERT INTO tier1_notifications
                (user_id, jar_id, anomaly_type, title, detail, severity, trace_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id, jar_id, "other",
                suggestion.title,
                suggestion.detail,
                suggestion.severity,
                trace_id,
            ),
        )
        logger.info(f"💡 Saving suggestion saved for {user_id}")
    except Exception as e:
        logger.error(f"Failed to save income notification: {e}")

    # ── Publish to AWS SNS ─────────────────────────────────────────
    sns_topic_arn = os.environ.get("SNS_TOPIC_ARN")
    if sns_topic_arn:
        try:
            sns_client.publish(
                TopicArn=sns_topic_arn,
                Subject="💡 Gợi ý tiết kiệm — Thu nhập vừa vào!",
                Message=(
                    f"{suggestion.title}\n\n"
                    f"{suggestion.detail}\n\n"
                    f"Số tiết kiệm gợi ý: {suggestion.suggested_saving_amount:,.0f} VND"
                ),
            )
            logger.info("📡 Income suggestion published to SNS")
        except Exception as e:
            logger.error(f"SNS publish failed (Income): {e}")
