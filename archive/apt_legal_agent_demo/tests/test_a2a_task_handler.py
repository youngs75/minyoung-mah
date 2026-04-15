"""A2A task handler tests — JSON-RPC entry + FastAPI TestClient.

These verify that the HTTP surface built on top of the orchestrator
plumbs the pipeline output through to A2A artifacts without losing the
AgentResponse schema fields, and that the streaming endpoint drains
orchestrator events plus a terminal ``task.complete`` frame.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apt_legal_agent.a2a.hitl_channel import A2AHITLChannel
from apt_legal_agent.a2a.task_handler import TASKS, handle_tasks_send, run_task
from apt_legal_agent.app import create_app
from apt_legal_agent.bootstrap import build_orchestrator
from apt_legal_agent.config import AptLegalConfig
from apt_legal_agent.models.classification import DisputeClassification
from apt_legal_agent.models.dispute import DisputeType, QueryIntent
from apt_legal_agent.models.plan import ExecutionPlan, ToolCallStep
from apt_legal_agent.models.response import AgentResponse, LegalBasisItem

from .conftest import FakeChatModel, FakeMCPClient


# ---------------------------------------------------------------------------
# Shared fixture: canned NOISE scenario (reused across tests)
# ---------------------------------------------------------------------------


def _noise_fixture() -> tuple[FakeChatModel, FakeMCPClient]:
    classification = DisputeClassification(
        dispute_type=DisputeType.NOISE,
        keywords=["층간소음", "기준", "데시벨"],
        intent=QueryIntent.LAW_CHECK,
        confidence=0.95,
    )
    plan = ExecutionPlan(
        steps=[
            ToolCallStep(
                index=0,
                tool_name="search_law",
                arguments={"query": "층간소음 기준"},
                priority=1,
                rationale="기본 법령 조회.",
            ),
        ]
    )
    response = AgentResponse(
        answer="공동주택관리법 제20조에 따르면 주간 43dB, 야간 38dB입니다.",
        legal_basis=[
            LegalBasisItem(
                type="law",
                reference="공동주택관리법 제20조",
                summary="층간소음 기준 조항.",
            )
        ],
        next_steps=["관리사무소에 협의 요청"],
    )
    model = FakeChatModel(structured_responses=[classification, plan, response])
    mcp = FakeMCPClient(
        responses={"search_law": {"results": [{"article": "제20조"}]}}
    )
    return model, mcp


def _factory_from(model: FakeChatModel, mcp: FakeMCPClient):
    def _factory(hitl, observer):
        return build_orchestrator(
            model=model,
            mcp_client=mcp,
            hitl=hitl,
            observer=observer,
            config=AptLegalConfig(llm_api_key="test"),
        )

    return _factory


@pytest.fixture(autouse=True)
def _clear_tasks():
    TASKS.clear()
    yield
    TASKS.clear()


# ---------------------------------------------------------------------------
# 1. handle_tasks_send returns a fully formed JSON-RPC envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_tasks_send_returns_completed_artifact() -> None:
    model, mcp = _noise_fixture()

    request = {
        "jsonrpc": "2.0",
        "id": "req-1",
        "method": "tasks/send",
        "params": {
            "id": "task-noise-1",
            "message": {
                "role": "user",
                "parts": [
                    {"type": "text", "text": "층간소음 기준이 몇 데시벨이야?"}
                ],
            },
        },
    }

    response = await handle_tasks_send(
        request, orchestrator_factory=_factory_from(model, mcp)
    )

    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "req-1"
    result = response["result"]
    assert result["id"] == "task-noise-1"
    assert result["status"]["state"] == "completed"

    artifact = result["artifacts"][0]
    text_part = next(p for p in artifact["parts"] if p["type"] == "text")
    data_part = next(p for p in artifact["parts"] if p["type"] == "data")

    assert "43dB" in text_part["text"]
    assert "※ 본 답변" in text_part["text"]  # disclaimer preserved in rendered text
    assert data_part["data"]["legal_basis"][0]["reference"] == "공동주택관리법 제20조"


# ---------------------------------------------------------------------------
# 2. FastAPI TestClient — /a2a/tasks/send and /healthz and agent card
# ---------------------------------------------------------------------------


def test_fastapi_routes_agent_card_and_healthz() -> None:
    app = create_app()
    client = TestClient(app)

    assert client.get("/healthz").json() == {"status": "ok"}

    card = client.get("/.well-known/agent.json").json()
    assert card["name"] == "apt-legal-agent"
    assert card["capabilities"]["streaming"] is True
    assert any(skill["id"] == "apt-legal-qa" for skill in card["skills"])


def test_fastapi_tasks_send_returns_artifact() -> None:
    model, mcp = _noise_fixture()
    app = create_app(orchestrator_factory=_factory_from(model, mcp))
    client = TestClient(app)

    response = client.post(
        "/a2a/tasks/send",
        json={
            "jsonrpc": "2.0",
            "id": "http-1",
            "method": "tasks/send",
            "params": {
                "id": "task-http-1",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "층간소음 기준?"}],
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["status"]["state"] == "completed"
    assert "43dB" in body["result"]["artifacts"][0]["parts"][0]["text"]


# ---------------------------------------------------------------------------
# 3. SSE streaming — events include orchestrator frames and terminal complete
# ---------------------------------------------------------------------------


def test_fastapi_stream_emits_events_and_completes() -> None:
    model, mcp = _noise_fixture()
    app = create_app(orchestrator_factory=_factory_from(model, mcp))
    client = TestClient(app)

    with client.stream(
        "POST",
        "/a2a/stream",
        json={
            "jsonrpc": "2.0",
            "id": "stream-1",
            "method": "tasks/sendSubscribe",
            "params": {
                "id": "task-stream-1",
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": "층간소음 기준?"}],
                },
            },
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        frames: list[dict] = []
        for raw in response.iter_lines():
            if not raw:
                continue
            line = raw if isinstance(raw, str) else raw.decode("utf-8")
            if not line.startswith("data:"):
                continue
            frames.append(json.loads(line[5:].strip()))

    event_names = [f.get("event") for f in frames]
    assert "orchestrator.run.start" in event_names
    assert "orchestrator.run.end" in event_names
    assert event_names[-1] == "task.complete"
    assert frames[-1]["state"] == "completed"
    assert frames[-1]["artifacts"][0]["parts"][0]["text"].startswith(
        "공동주택관리법 제20조"
    )


# ---------------------------------------------------------------------------
# 4. A2AHITLChannel auto-picks options and forwards notify to emitter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a2a_hitl_ask_auto_picks_first_option() -> None:
    hitl = A2AHITLChannel(task_id="t", sse_emitter=None)
    reply = await hitl.ask("계속할까요?", options=["네", "아니오"])
    assert reply.choice == "네"
    assert reply.metadata == {"auto": True}

    empty = await hitl.ask("자유 입력?", options=None)
    assert empty.choice == ""


# ---------------------------------------------------------------------------
# 5. Pipeline failure surfaces as state="failed" with an error string
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_tasks_send_reports_failure_when_pipeline_raises() -> None:
    model = FakeChatModel(structured_responses=[])  # empty → raises RuntimeError

    def factory(hitl, observer):
        return build_orchestrator(
            model=model,
            mcp_client=FakeMCPClient(),
            hitl=hitl,
            observer=observer,
            config=AptLegalConfig(llm_api_key="test"),
        )

    response = await run_task(
        "task-fail",
        "아무 질문",
        emitter=None,
        orchestrator_factory=factory,
    )

    assert response.state == "failed"
    assert response.error is not None
