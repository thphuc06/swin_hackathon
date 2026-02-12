from __future__ import annotations

from fastapi import FastAPI
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

# Always load backend/.env regardless of current working directory.
# main.py is at backend/app/main.py -> backend/.env is parents[1]/.env
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
# Read .env as UTF-8 with BOM support to avoid malformed first key (e.g. AWS_REGION).
load_dotenv(ENV_PATH, override=True, encoding="utf-8-sig")

from app.routes import (  # noqa: E402
    audit,
    chat,
    goals,
    notifications,
    risk_profile,
)

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
