import json
from datetime import datetime

# Placeholder worker: evaluates triggers & writes notifications


def handler(event, context=None):
    print("Trigger worker invoked")
    print(json.dumps(event))
    return {
        "status": "ok",
        "processed_at": datetime.utcnow().isoformat() + "Z",
        "insight": "Abnormal spend vs rolling avg",
    }


if __name__ == "__main__":
    sample = {"detail-type": "DailyAggregateUpdated", "detail": {"total_spend": 12000000}}
    handler(sample)
