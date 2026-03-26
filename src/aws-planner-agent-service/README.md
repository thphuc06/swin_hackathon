# Planner Agent Service (Deprecated Compatibility)

This service remains only as a deprecated compatibility shim during rollout.
The default architecture now runs planner in-process inside `src/aws-specialist-agent-mcp-server/`.

## Endpoints

- GET /health
- POST /v1/planner/run

## Local run

```powershell
cd src/aws-planner-agent-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PLANNER_STUB_MODE="true"
uvicorn app.main:app --host 0.0.0.0 --port 8090
```

## Environment variables

See .env.example for the full list.

## Integration

If you still need the temporary compatibility path, point the specialist MCP server at this service:

```
PLANNER_AGENT_EXTERNAL_ENABLED=true
PLANNER_AGENT_URL=http://localhost:8090/v1/planner/run
```

## Notes

- This service is not part of the steady-state default runtime path.
- The default planner path no longer requires a separate planner HTTP deployment.
- The default planner path no longer requires finance MCP as a dependency.
- Do not enable this path for normal staging/prod deploys unless you are deliberately reviving the compatibility contract.
