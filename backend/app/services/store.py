from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List


@dataclass
class InMemoryStore:
    transactions: List[Dict[str, Any]] = field(default_factory=list)
    notifications: List[Dict[str, Any]] = field(default_factory=list)
    goals: Dict[str, Any] = field(default_factory=dict)
    risk_profiles: List[Dict[str, Any]] = field(default_factory=list)
    audit_events: List[Dict[str, Any]] = field(default_factory=list)
    statement_imports: List[Dict[str, Any]] = field(default_factory=list)
    tool_events: List[Dict[str, Any]] = field(default_factory=list)

    def add_transaction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            **payload,
            "id": f"txn_{len(self.transactions)+1}",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self.transactions.append(record)
        return record

    def add_notification(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            **payload,
            "id": f"note_{len(self.notifications)+1}",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self.notifications.append(record)
        return record

    def add_audit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            **payload,
            "id": f"audit_{len(self.audit_events)+1}",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self.audit_events.append(record)
        return record

    def add_statement_import(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            **payload,
            "id": f"stmt_{len(self.statement_imports)+1}",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self.statement_imports.append(record)
        return record

    def add_tool_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            **payload,
            "id": f"tool_{len(self.tool_events)+1}",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self.tool_events.append(record)
        return record


store = InMemoryStore()
