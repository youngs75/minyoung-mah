"""Design-doc 03 §7 scenarios 2 and 3.

Scenario 1 (simple NOISE law check) is already covered by
``test_pipeline_e2e.py``. This module adds the remaining two:

- **Scenario 2**: 복합 분쟁 대응 — 4 parallel MCP calls across two
  priority groups, all tool results roll into the responder.
- **Scenario 3**: 재건축 절차 안내 — RECON dispute type routed through
  ``search_law`` + ``get_law_article`` with a depends-on chain.
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


# ---------------------------------------------------------------------------
# Scenario 2 — complex dispute response with four MCP tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_2_complex_dispute_four_tool_fan_out() -> None:
    user_request = "윗집 층간소음이 너무 심한데 법적으로 어떻게 대응할 수 있나요?"

    classification = DisputeClassification(
        dispute_type=DisputeType.NOISE,
        keywords=["층간소음", "법적 대응", "손해배상"],
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
                rationale="판례 검색.",
            ),
            ToolCallStep(
                index=2,
                tool_name="search_interpretation",
                arguments={"query": "층간소음 관리규약"},
                priority=2,
                rationale="행정해석 확인.",
            ),
            ToolCallStep(
                index=3,
                tool_name="get_precedent_detail",
                arguments={"case_number": "2020다12345"},
                priority=2,
                depends_on=[1],
                rationale="대표 판례 상세.",
            ),
        ]
    )
    response = AgentResponse(
        answer=(
            "층간소음 분쟁은 공동주택관리법과 관련 판례에 근거하여 "
            "관리주체 협의 → 환경분쟁조정 → 민사소송 순으로 단계별 대응이 가능합니다."
        ),
        legal_basis=[
            LegalBasisItem(
                type="law",
                reference="공동주택관리법 제20조",
                summary="층간소음 방지 의무.",
            ),
            LegalBasisItem(
                type="precedent",
                reference="대법원 2020다12345",
                summary="수인한도 초과 시 손해배상 인정.",
            ),
            LegalBasisItem(
                type="interpretation",
                reference="국토부 행정해석 2021-01",
                summary="관리규약 위반 시 관리주체의 조치 권한.",
            ),
        ],
        next_steps=[
            "관리사무소에 민원 제기",
            "환경분쟁조정위원회 신청",
            "필요 시 변호사 상담",
        ],
    )

    fake_model = FakeChatModel(
        structured_responses=[classification, plan, response]
    )
    fake_mcp = FakeMCPClient(
        responses={
            "search_law": {"results": [{"article": "제20조"}]},
            "search_precedent": {"results": [{"case_number": "2020다12345"}]},
            "search_interpretation": {"results": [{"id": "2021-01"}]},
            "get_precedent_detail": {"case_number": "2020다12345", "text": "..."},
        }
    )

    orch = build_orchestrator(
        model=fake_model,
        mcp_client=fake_mcp,
        config=AptLegalConfig(llm_api_key="test"),
    )
    result = await orch.run_pipeline(build_pipeline(), user_request=user_request)

    assert result.completed

    # All four MCP tools were called.
    called = [name for name, _ in fake_mcp.calls]
    assert set(called) == {
        "search_law",
        "search_precedent",
        "search_interpretation",
        "get_precedent_detail",
    }
    assert len(fake_mcp.calls) == 4

    # Priority 1 group runs before priority 2 group.
    p1_names = {"search_law", "search_precedent"}
    p2_names = {"search_interpretation", "get_precedent_detail"}
    last_p1_idx = max(i for i, (n, _) in enumerate(fake_mcp.calls) if n in p1_names)
    first_p2_idx = min(i for i, (n, _) in enumerate(fake_mcp.calls) if n in p2_names)
    assert last_p1_idx < first_p2_idx

    tool_results = result.state["retrieval_executor"].tool_results
    assert len(tool_results) == 4
    assert all(r.ok for r in tool_results)

    responder_out = result.state["responder"].output.output
    assert isinstance(responder_out, AgentResponse)
    assert len(responder_out.legal_basis) == 3
    assert "환경분쟁조정" in responder_out.next_steps[1]


# ---------------------------------------------------------------------------
# Scenario 3 — 재건축 동의율
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_3_recon_consent_rate() -> None:
    user_request = "재건축 추진하려면 동의율이 얼마나 필요해?"

    classification = DisputeClassification(
        dispute_type=DisputeType.RECON,
        keywords=["재건축", "동의율"],
        intent=QueryIntent.LAW_CHECK,
        confidence=0.98,
    )
    plan = ExecutionPlan(
        steps=[
            ToolCallStep(
                index=0,
                tool_name="search_law",
                arguments={
                    "query": "재건축 동의율",
                    "law_name": "도시 및 주거환경정비법",
                },
                priority=1,
                rationale="재건축 조항 검색.",
            ),
            ToolCallStep(
                index=1,
                tool_name="get_law_article",
                arguments={
                    "law_name": "도시 및 주거환경정비법",
                    "article_number": "제35조",
                },
                priority=2,
                depends_on=[0],
                rationale="제35조 전문 인용.",
            ),
        ]
    )
    response = AgentResponse(
        answer=(
            "도시 및 주거환경정비법 제35조에 따르면 재건축조합 설립에는 "
            "각 동별 구분소유자 과반수 및 전체 구분소유자 3/4 이상의 동의가 필요합니다."
        ),
        legal_basis=[
            LegalBasisItem(
                type="law",
                reference="도시 및 주거환경정비법 제35조",
                summary="재건축조합 설립 동의 요건.",
            )
        ],
        next_steps=["추진위원회 구성 후 정비구역 지정 신청"],
    )

    fake_model = FakeChatModel(
        structured_responses=[classification, plan, response]
    )
    fake_mcp = FakeMCPClient(
        responses={
            "search_law": {
                "results": [
                    {
                        "law_name": "도시 및 주거환경정비법",
                        "article": "제35조",
                    }
                ]
            },
            "get_law_article": {
                "law_name": "도시 및 주거환경정비법",
                "article_number": "제35조",
                "text": "조합설립 인가를 받으려면 ... 3/4 이상의 동의를 받아야 한다.",
            },
        }
    )

    orch = build_orchestrator(
        model=fake_model,
        mcp_client=fake_mcp,
        config=AptLegalConfig(llm_api_key="test"),
    )
    result = await orch.run_pipeline(build_pipeline(), user_request=user_request)

    assert result.completed

    classifier_out = result.state["classifier"].output.output
    assert classifier_out.dispute_type is DisputeType.RECON

    # Two tools called, priority ordering preserved.
    assert [name for name, _ in fake_mcp.calls] == ["search_law", "get_law_article"]

    responder_out = result.state["responder"].output.output
    assert isinstance(responder_out, AgentResponse)
    assert "3/4" in responder_out.answer
    assert (
        responder_out.legal_basis[0].reference
        == "도시 및 주거환경정비법 제35조"
    )
