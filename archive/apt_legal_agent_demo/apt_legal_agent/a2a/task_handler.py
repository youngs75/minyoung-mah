"""A2A task handler — JSON-RPC entry point that drives the orchestrator.

Responsibilities:

- Parse the A2A ``tasks/send`` / ``tasks/sendSubscribe`` JSON-RPC envelope.
- Build an :class:`Orchestrator` wired with :class:`A2AHITLChannel` and
  :class:`SseObserver` so streaming clients receive orchestrator events.
- Run the static pipeline, catch failures, and serialise the final
  :class:`AgentResponse` into an A2A artifact.
- Track per-task state in a simple in-memory ``TASKS`` dict (sufficient
  for a single-replica deployment; multi-replica would swap this for
  Redis or similar).

An ``orchestrator_factory`` injection point keeps tests cheap — they can
hand in a factory closing over FakeChatModel and FakeMCPClient without
touching process-level state.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from minyoung_mah import NullObserver, Observer, Orchestrator

from ..bootstrap import build_orchestrator as _default_build_orchestrator
from ..models.response import AgentResponse
from ..pipeline import build_pipeline
from .hitl_channel import A2AHITLChannel
from .sse_handler import SseEmitter, SseObserver


# ---------------------------------------------------------------------------
# Task state registry
# ---------------------------------------------------------------------------


@dataclass
class TaskState:
    id: str
    state: str  # "submitted" | "working" | "completed" | "failed"
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    emitter: SseEmitter | None = None


TASKS: dict[str, TaskState] = {}


# ---------------------------------------------------------------------------
# Orchestrator factory protocol
# ---------------------------------------------------------------------------


OrchestratorFactory = Callable[[A2AHITLChannel, Observer], Orchestrator]


def _default_factory(hitl: A2AHITLChannel, observer: Observer) -> Orchestrator:
    return _default_build_orchestrator(hitl=hitl, observer=observer)


# ---------------------------------------------------------------------------
# A2A message parsing / rendering
# ---------------------------------------------------------------------------


def _extract_user_text(message: dict[str, Any] | None) -> str:
    """Pull the first text part out of an A2A ``message`` object.

    A2A messages carry a ``parts`` list where each part has a ``type``
    and a payload. We only understand ``text`` parts; anything else is
    ignored.
    """
    if not message:
        return ""
    parts = message.get("parts") or []
    for part in parts:
        if part.get("type") == "text" and isinstance(part.get("text"), str):
            return part["text"]
    return ""


def _render_response_text(response: AgentResponse) -> str:
    lines: list[str] = [response.answer, ""]
    if response.legal_basis:
        lines.append("[법적 근거]")
        for item in response.legal_basis:
            lines.append(f"- ({item.type}) {item.reference}: {item.summary}")
        lines.append("")
    if response.next_steps:
        lines.append("[권장 조치]")
        for step in response.next_steps:
            lines.append(f"- {step}")
        lines.append("")
    lines.append(response.disclaimer)
    return "\n".join(lines).rstrip()


def _response_to_artifact(response: AgentResponse) -> dict[str, Any]:
    return {
        "parts": [
            {"type": "text", "text": _render_response_text(response)},
            {
                "type": "data",
                "data": response.model_dump(mode="json"),
            },
        ],
    }


# ---------------------------------------------------------------------------
# Core execution
# ---------------------------------------------------------------------------


async def run_task(
    task_id: str,
    user_text: str,
    *,
    emitter: SseEmitter | None = None,
    orchestrator_factory: OrchestratorFactory | None = None,
) -> TaskState:
    """Run the pipeline for ``user_text`` and update ``TASKS[task_id]``.

    If an ``emitter`` is supplied, orchestrator events are streamed
    through it and it is closed when the task finishes.
    """
    task = TASKS.setdefault(task_id, TaskState(id=task_id, state="submitted"))
    task.state = "working"
    task.emitter = emitter

    hitl = A2AHITLChannel(task_id, sse_emitter=emitter)
    observer: Observer = SseObserver(emitter) if emitter is not None else NullObserver()

    factory = orchestrator_factory or _default_factory
    orch = factory(hitl, observer)

    try:
        result = await orch.run_pipeline(build_pipeline(), user_request=user_text)
        if not result.completed:
            task.state = "failed"
            task.error = result.error or f"pipeline aborted at {result.aborted_at}"
        else:
            responder_step = result.state.get("responder")
            if responder_step is None or responder_step.output is None:
                task.state = "failed"
                task.error = "responder did not produce an output"
            else:
                response = responder_step.output.output
                if not isinstance(response, AgentResponse):
                    task.state = "failed"
                    task.error = (
                        f"responder returned unexpected type: {type(response).__name__}"
                    )
                else:
                    task.artifacts = [_response_to_artifact(response)]
                    task.state = "completed"
    except Exception as exc:  # noqa: BLE001
        task.state = "failed"
        task.error = f"{type(exc).__name__}: {exc}"

    if emitter is not None:
        await emitter.send(
            {
                "event": "task.complete",
                "task_id": task_id,
                "state": task.state,
                "artifacts": task.artifacts,
                "error": task.error,
            }
        )
        await emitter.close()

    return task


#---------------------------------------------------------------------------
# JSON-RPC entry points
# ---------------------------------------------------------------------------


def _jsonrpc_result(request_id: Any, task: TaskState) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "id": task.id,
            "status": {"state": task.state},
            "artifacts": task.artifacts,
            **({"error": task.error} if task.error else {}),
        },
    }


def _extract_task_id(params: dict[str, Any]) -> str:
    explicit = params.get("id")
    if isinstance(explicit, str) and explicit:
        return explicit
    return str(uuid.uuid4())


async def handle_tasks_send(
    request: dict[str, Any],
    *,
    orchestrator_factory: OrchestratorFactory | None = None,
) -> dict[str, Any]:
    """Synchronous ``tasks/send`` — run the pipeline, return the artifact.

    Streaming clients should call the SSE endpoint instead.
    """
    params = request.get("params") or {}
    task_id = _extract_task_id(params)
    user_text = _extract_user_text(params.get("message"))

    task = await run_task(
        task_id,
        user_text,
        emitter=None,
        orchestrator_factory=orchestrator_factory,
    )
    return _jsonrpc_result(request.get("id"), task)


async def start_streaming_task(
    request: dict[str, Any],
    *,
    orchestrator_factory: OrchestratorFactory | None = None,
) -> tuple[TaskState, asyncio.Task[TaskState]]:
    """Start ``tasks/sendSubscribe`` — returns the task + a background
    asyncio task draining the pipeline into a fresh :class:`SseEmitter`.

    The caller (the FastAPI streaming route) then iterates the emitter
    to produce SSE frames.
    """
    params = request.get("params") or {}
    task_id = _extract_task_id(params)
    user_text = _extract_user_text(params.get("message"))

    emitter = SseEmitter()
    task = TaskState(id=task_id, state="submitted", emitter=emitter)
    TASKS[task_id] = task

    async def _runner() -> TaskState:
        return await run_task(
            task_id,
            user_text,
            emitter=emitter,
            orchestrator_factory=orchestrator_factory,
        )

    bg = asyncio.create_task(_runner())
    return task, bg


__all__ = [
    "OrchestratorFactory",
    "TASKS",
    "TaskState",
    "handle_tasks_send",
    "run_task",
    "start_streaming_task",
]
