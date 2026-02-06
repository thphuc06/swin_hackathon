from __future__ import annotations

from typing import Any, Dict, List, Protocol


class ExternalCashflowProvider(Protocol):
    name: str

    def fetch_transactions(self, user_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        ...


class MockExternalCashflowProvider:
    """
    Phase-B provider interface placeholder.
    Keep this stable so real connectors (Plaid/Teller/Finicity, etc.)
    can be plugged in without changing tool contracts.
    """

    name = "mock_external_cashflow_provider"

    def fetch_transactions(self, user_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        return [
            {
                "user_id": user_id,
                "date": start_date,
                "amount": 0.0,
                "currency": "VND",
                "direction": "credit",
                "counterparty": "EXTERNAL_PROVIDER_PLACEHOLDER",
                "source": self.name,
            }
        ]
