"""FastAPI entry point for apt-legal-agent.

Routes:

- ``GET  /healthz``                  — liveness probe for k8s.
- ``GET  /.well-known/agent.json``   — A2A agent card.
- ``POST /a2a/tasks/send``           — synchronous JSON-RPC task.
- ``POST /a2a/stream``               — JSON-RPC task with SSE streaming.

The app holds no global state beyond the in-memory ``TASKS`` registry
in :mod:`apt_legal_agent.a2a.task_handler`. Everything else is wired
per-request so tests can use :class:`fastapi.testclient.TestClient`
with dependency-injected orchestrators.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .a2a.agent_card import build_agent_card
from .a2a.sse_handler import stream_events
from .a2a.task_handler import (
    OrchestratorFactory,
    handle_tasks_send,
    start_streaming_task,
)


def create_app(
    *,
    base_url: str = "http://localhost:8000",
    orchestrator_factory: OrchestratorFactory | None = None,
) -> FastAPI:
    """Create a FastAPI app. ``orchestrator_factory`` is the DI seam —
    tests inject a factory that closes over FakeChatModel/FakeMCPClient.
    """
    app = FastAPI(title="apt-legal-agent", version="0.0.1")
    agent_card = build_agent_card(base_url=base_url)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/agent.json")
    async def well_known_agent() -> dict[str, Any]:
        return agent_card

    @app.post("/a2a/tasks/send")
    async def tasks_send(request: Request) -> JSONResponse:
        body = await request.json()
        result = await handle_tasks_send(
            body, orchestrator_factory=orchestrator_factory
        )
        return JSONResponse(result)

    @app.post("/a2a/stream")
    async def tasks_stream(request: Request) -> StreamingResponse:
        body = await request.json()
        task, _bg = await start_streaming_task(
            body, orchestrator_factory=orchestrator_factory
        )
        assert task.emitter is not None
        return StreamingResponse(
            stream_events(task.emitter),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
