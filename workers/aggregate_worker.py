import json
import os
from datetime import datetime

# Placeholder worker: would run in Lambda or ECS Fargate
# Reads TransactionCreated event from EventBridge / SQS


def handler(event, context=None):
    print("Aggregation worker invoked")
    print(json.dumps(event))
    return {
        "status": "ok",
        "processed_at": datetime.utcnow().isoformat() + "Z",
    }


if __name__ == "__main__":
    sample = {"detail-type": "TransactionCreated", "detail": {"amount": 100000}}
    handler(sample)
