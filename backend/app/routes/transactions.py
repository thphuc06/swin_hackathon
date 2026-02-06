from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.services.auth import current_user
from app.services.financial_tools import ingest_statement_vn, normalize_and_categorize_txn
from app.services.store import store

router = APIRouter(prefix="/transactions", tags=["transactions"])


class TransferRequest(BaseModel):
    jar_id: str
    category_id: str
    amount: float = Field(gt=0)
    counterparty: str


class CounterpartyRule(BaseModel):
    counterparty_norm: str
    jar_id: str
    category_id: str


class StatementImportRequest(BaseModel):
    file_ref: str
    bank_hint: str | None = None
    currency: str = "VND"
    rules_counterparty_map: list[CounterpartyRule] = []


@router.post("/transfer")
def transfer(payload: TransferRequest, user=Depends(current_user)):
    record = store.add_transaction({
        **payload.model_dump(),
        "user_id": user.get("sub"),
        "type": "transfer",
    })
    return {"status": "ok", "transaction": record}


@router.get("")
def list_transactions(range: str = "30d", user=Depends(current_user)):
    return {
        "range": range,
        "items": [t for t in store.transactions if t.get("user_id") == user.get("sub")],
    }


@router.post("/import/statement")
def import_statement(payload: StatementImportRequest, user=Depends(current_user)):
    ingest_result = ingest_statement_vn(
        file_ref=payload.file_ref,
        bank_hint=payload.bank_hint,
        currency=payload.currency,
    )
    normalize_result = normalize_and_categorize_txn(
        transactions=ingest_result.get("transactions", []),
        rules_counterparty_map=[rule.model_dump() for rule in payload.rules_counterparty_map],
        trace_id=ingest_result.get("trace_id"),
    )

    imported_count = 0
    for tx in normalize_result.get("normalized_txn", []):
        store.add_transaction({
            **tx,
            "user_id": user.get("sub"),
            "type": "statement_import",
        })
        imported_count += 1

    store.add_statement_import({
        "user_id": user.get("sub"),
        "file_ref": payload.file_ref,
        "bank_hint": payload.bank_hint,
        "currency": payload.currency,
        "trace_id": ingest_result.get("trace_id"),
        "quality_score": ingest_result.get("quality_score", 0),
        "parse_warnings": ingest_result.get("parse_warnings", []),
        "imported_count": imported_count,
    })
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": ingest_result.get("trace_id"),
        "tool_name": "ingest_statement_vn",
        "payload": ingest_result.get("audit", {}),
    })
    store.add_tool_event({
        "user_id": user.get("sub"),
        "trace_id": normalize_result.get("trace_id"),
        "tool_name": "normalize_and_categorize_txn",
        "payload": normalize_result.get("audit", {}),
    })
    return {
        "status": "ok",
        "trace_id": ingest_result.get("trace_id"),
        "ingest": {
            "quality_score": ingest_result.get("quality_score", 0),
            "parse_warnings": ingest_result.get("parse_warnings", []),
        },
        "normalize": {
            "confidence": normalize_result.get("confidence", 0),
            "needs_review": normalize_result.get("needs_review", []),
        },
        "imported_count": imported_count,
    }
