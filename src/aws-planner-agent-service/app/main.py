from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from jsonschema import Draft202012Validator, ValidationError

from app.agent import run_planner
from app.auth import require_planner_auth
from app.contracts import PlannerRequest

load_dotenv()

app = FastAPI(title="Planner Agent Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
INPUT_SCHEMA = json.loads((SCHEMA_DIR / "run_planner_agent_v1.input.json").read_text(encoding="utf-8"))
INPUT_VALIDATOR = Draft202012Validator(INPUT_SCHEMA)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/planner/run")
def planner_run(
    payload: Dict[str, Any] = Body(...),
    _: None = Depends(require_planner_auth),
) -> Dict[str, Any]:
    try:
        INPUT_VALIDATOR.validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    request = PlannerRequest.model_validate(payload)
    envelope = run_planner(request)
    return envelope.model_dump()
