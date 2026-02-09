from __future__ import annotations

from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

from app.routes import (
    audit,
    chat,
    goals,
    notifications,
    risk_profile,
)

load_dotenv()

app = FastAPI(title="Jars Fintech API Gateway", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core routes - thin API gateway
app.include_router(chat.router)  # Proxy to AgentCore Runtime
app.include_router(goals.router)  # User goals management
app.include_router(risk_profile.router)  # User risk profile
app.include_router(notifications.router)  # User notifications
app.include_router(audit.router)  # Audit logs


@app.get("/health")
def health():
    return {"status": "ok"}
