"""Output schema of the responder role — the final agent response."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DEFAULT_DISCLAIMER = (
    "※ 본 답변은 일반적인 법률 정보 제공 목적이며, "
    "구체적 사안에 대해서는 법률 전문가 상담을 권장합니다."
)


class LegalBasisItem(BaseModel):
    """One piece of legal grounding — a law, precedent, or interpretation."""

    type: Literal["law", "precedent", "interpretation"]
    reference: str = Field(description="Citation string, e.g. '공동주택관리법 제20조'.")
    summary: str = Field(description="Short Korean summary of the relevant content.")


class AgentResponse(BaseModel):
    """What the responder role returns — the final user-facing answer.

    The ``disclaimer`` default is mandatory per the product spec. The
    responder prompt is instructed to keep the default unless the user
    explicitly asks for clarification on liability.
    """

    answer: str = Field(
        description="Primary answer to the user's question, written in Korean."
    )
    legal_basis: list[LegalBasisItem] = Field(
        default_factory=list,
        description="Every legal source cited in the answer.",
    )
    next_steps: list[str] = Field(
        default_factory=list,
        description="Actionable follow-up suggestions for the user.",
    )
    disclaimer: str = Field(default=DEFAULT_DISCLAIMER)
