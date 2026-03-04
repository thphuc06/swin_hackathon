from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

from core.settings import CLOUDWATCH_LOG_GROUP, CLOUDWATCH_LOG_STREAM, CLOUDWATCH_REGION

logger = logging.getLogger(__name__)


class CloudWatchExporter:
    """CloudWatch Logs exporter hook (optional, config-gated)."""

    def __init__(
        self,
        *,
        log_group: str | None = None,
        log_stream: str | None = None,
        region: str | None = None,
    ) -> None:
        self._log_group = str(log_group or CLOUDWATCH_LOG_GROUP).strip()
        self._log_stream = str(log_stream or CLOUDWATCH_LOG_STREAM).strip()
        self._region = str(region or CLOUDWATCH_REGION).strip()
        self._sequence_token = None
        self._client = None
        self._ready = False
        self._init_client()

    def _init_client(self) -> None:
        if not self._log_group or not self._log_stream:
            logger.warning("cloudwatch_exporter_not_configured")
            return
        try:
            import boto3
        except Exception:
            logger.warning("cloudwatch_exporter_missing_boto3")
            return
        kwargs: Dict[str, Any] = {}
        if self._region:
            kwargs["region_name"] = self._region
        self._client = boto3.client("logs", **kwargs)
        self._ready = True

    def _ensure_group_and_stream(self) -> None:
        if not self._ready or self._client is None:
            return
        try:
            self._client.create_log_group(logGroupName=self._log_group)
        except self._client.exceptions.ResourceAlreadyExistsException:  # type: ignore[attr-defined]
            pass
        except Exception:
            pass
        try:
            self._client.create_log_stream(logGroupName=self._log_group, logStreamName=self._log_stream)
        except self._client.exceptions.ResourceAlreadyExistsException:  # type: ignore[attr-defined]
            pass
        except Exception:
            pass

    def export_trace(self, envelope: Dict[str, Any]) -> None:
        if not self._ready or self._client is None:
            return
        self._ensure_group_and_stream()
        message = json.dumps(envelope, ensure_ascii=True, default=str)
        event = {"timestamp": int(time.time() * 1000), "message": message}
        kwargs: Dict[str, Any] = {
            "logGroupName": self._log_group,
            "logStreamName": self._log_stream,
            "logEvents": [event],
        }
        if self._sequence_token:
            kwargs["sequenceToken"] = self._sequence_token
        try:
            response = self._client.put_log_events(**kwargs)
            token = response.get("nextSequenceToken")
            if token:
                self._sequence_token = token
        except Exception as exc:  # noqa: BLE001
            logger.warning("cloudwatch_export_failed error=%s", exc)

