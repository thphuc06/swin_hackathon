from __future__ import annotations

from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

from app.routes import (
    aggregates,
    audit,
    chat,
    decision,
    forecast,
    goals,
    mcp,
    notifications,
    risk_profile,
    transactions,
)

load_dotenv()

app = FastAPI(title="Jars Fintech API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions.router)
app.include_router(aggregates.router)
app.include_router(notifications.router)
app.include_router(goals.router)
app.include_router(risk_profile.router)
app.include_router(forecast.router)
app.include_router(decision.router)
app.include_router(chat.router)
app.include_router(audit.router)
app.include_router(mcp.router)


@app.get("/health")
def health():
    return {"status": "ok"}
