"""End-to-end pipeline test — drives all four steps with fakes.

Scenario reproduced from design doc 03 §7 scenario 1: "공동주택에서 층간소음
기준이 몇 데시벨이야?" The test asserts that:

- classifier → planner → executor → responder all run in order
- executor issues exactly the tool calls the planner requested
- responder output lands as an :class:`AgentResponse` with the expected
  answer and legal_basis cited
"""

from __future__ import annotations

import pytest

from apt_legal_agent.bootstrap import build_orchestrator
from apt_legal_agent.config import AptLegalConfig
from apt_legal_agent.models.classification import DisputeClassification
from apt_legal_agent.models.dispute import DisputeType, QueryIntent
from apt_legal_agent.models.plan import ExecutionPlan, ToolCallStep
from apt_legal_agent.models.response import AgentResponse, LegalBasisItem
from apt_legal_agent.pipeline import build_pipeline

from .conftest import FakeChatModel, FakeMCPClient


@pytest.mark.asyncio
async def test_noise_law_check_scenario_end_to_end() -> None:
    user_request = "공동주택에서 층간소음 기준이 몇 데시벨이야?"

    # ── Queue the three structured responses in pipeline order ──
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
                arguments={"query": "층간소음 기준", "law_name": "공동주택관리법"},
                priority=1,
                depends_on=[],
                rationale="층간소음 기준이 담긴 공동주택관리법 조문을 찾기 위한 기본 검색.",
            ),
            ToolCallStep(
                index=1,
                tool_name="get_law_article",
                arguments={
                    "law_name": "공동주택관리법",
                    "article_number": "제20조",
                },
                priority=2,
                depends_on=[0],
                rationale="제20조 전문을 조회해 정확한 수치를 인용.",
            ),
        ]
    )
    response = AgentResponse(
        answer=(
            "공동주택관리법 제20조에 따르면 주간 43dB, 야간 38dB가 층간소음의 "
            "허용 기준입니다."
        ),
        legal_basis=[
            LegalBasisItem(
                type="law",
                reference="공동주택관리법 제20조",
                summary="공동주택 입주자 등의 층간소음 기준과 관리 의무를 규정.",
            )
        ],
        next_steps=[],
    )

    fake_model = FakeChatModel(
        structured_responses=[classification, plan, response]
    )

    fake_mcp = FakeMCPClient(
        responses={
            "search_law": {
                "results": [
                    {
                        "law_name": "공동주택관리법",
                        "article": "제20조",
                        "snippet": "입주자는 ... 층간소음을 발생시켜서는 아니된다.",
                    }
                ]
            },
            "get_law_article": {
                "law_name": "공동주택관리법",
                "article_number": "제20조",
                "text": "주간 43dB, 야간 38dB 이상의 층간소음은 ...",
            },
        }
    )

    orch = build_orchestrator(
        model=fake_model,
        mcp_client=fake_mcp,
        config=AptLegalConfig(llm_api_key="test"),
    )
    result = await orch.run_pipeline(build_pipeline(), user_request=user_request)

    # ── Pipeline completed cleanly ─────────────────────────────
    assert result.completed
    assert "classifier" in result.state
    assert "retrieval_planner" in result.state
    assert "retrieval_executor" in result.state
    assert "responder" in result.state

    # ── Classifier output roundtripped into the state ──────────
    classifier_out = result.state["classifier"].output.output
    assert isinstance(classifier_out, DisputeClassification)
    assert classifier_out.dispute_type is DisputeType.NOISE

    # ── Executor called both tools in the correct order ────────
    assert [name for name, _ in fake_mcp.calls] == ["search_law", "get_law_article"]
    assert fake_mcp.calls[0][1]["query"] == "층간소음 기준"
    assert fake_mcp.calls[1][1]["article_number"] == "제20조"

    # ── Tool results landed in the executor step ───────────────
    tool_results = result.state["retrieval_executor"].tool_results
    assert len(tool_results) == 2
    assert all(r.ok for r in tool_results)

    # ── Responder produced a fully-shaped AgentResponse ────────
    responder_out = result.state["responder"].output.output
    assert isinstance(responder_out, AgentResponse)
    assert "43dB" in responder_out.answer
    assert responder_out.legal_basis[0].reference == "공동주택관리법 제20조"
    assert responder_out.disclaimer.startswith("※ 본 답변")  # default preserved


@pytest.mark.asyncio
async def test_partial_mcp_failure_still_produces_response() -> None:
    """If one MCP call fails but continue_on_failure=True, the responder
    still runs with the remaining tool results.
    """
    user_request = "윗집 층간소음 법적 대응 방법?"

    classification = DisputeClassification(
        dispute_type=DisputeType.NOISE,
        keywords=["층간소음", "법적 대응"],
        intent=QueryIntent.DISPUTE_RESOLUTION,
        confidence=0.9,
    )
    plan = ExecutionPlan(
        steps=[
            ToolCallStep(
                index=0,
                tool_name="search_law",
                arguments={"query": "층간소음"},
                priority=1,
                rationale="기본 법령 조회.",
            ),
            ToolCallStep(
                index=1,
                tool_name="search_precedent",
                arguments={"query": "층간소음 손해배상"},
                priority=1,
                rationale="판례 인용을 위한 필수 호출.",
            ),
        ]
    )
    response = AgentResponse(
        answer="법령 조회는 성공했으나 판례 검색이 실패했습니다. 변호사 상담을 권장합니다.",
        legal_basis=[
            LegalBasisItem(
                type="law",
                reference="공동주택관리법 제20조",
                summary="층간소음 관련 기본 조항.",
            )
        ],
        next_steps=["변호사 또는 환경분쟁조정위원회 상담"],
    )

    fake_model = FakeChatModel(
        structured_responses=[classification, plan, response]
    )
    fake_mcp = FakeMCPClient(
        responses={"search_law": {"results": [{"article": "제20조"}]}},
        raise_on={"search_precedent"},  # this tool blows up
    )

    orch = build_orchestrator(
        model=fake_model,
        mcp_client=fake_mcp,
        config=AptLegalConfig(llm_api_key="test"),
    )
    result = await orch.run_pipeline(build_pipeline(), user_request=user_request)

    assert result.completed
    tool_results = result.state["retrieval_executor"].tool_results
    assert len(tool_results) == 2
    assert tool_results[0].ok is True
    assert tool_results[1].ok is False
    assert "fail" in (tool_results[1].error or "").lower()

    # Responder still ran and the partial response landed.
    responder_out = result.state["responder"].output.output
    assert isinstance(responder_out, AgentResponse)
    assert "변호사" in responder_out.next_steps[0]
