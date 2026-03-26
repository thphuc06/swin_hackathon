from __future__ import annotations

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.routing import Route

load_dotenv()

app = FastAPI(title="Specialist Agent MCP Server", version="0.1.0")

from app.mcp import StreamableHTTPASGIApp, create_mcp_session_manager, router as mcp_router

mcp_asgi_app = StreamableHTTPASGIApp(lambda: getattr(app.state, "mcp_session_manager", None))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    session_manager = create_mcp_session_manager()
    _app.state.mcp_session_manager = session_manager
    async with session_manager.run():
        yield
    _app.state.mcp_session_manager = None


app.router.lifespan_context = lifespan

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(mcp_router)
app.router.routes.append(Route("/mcp", endpoint=mcp_asgi_app))
app.router.routes.append(Route("/mcp/", endpoint=mcp_asgi_app))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
