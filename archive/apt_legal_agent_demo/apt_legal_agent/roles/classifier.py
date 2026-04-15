"""Classifier role — single structured-output LLM call, no tools."""

from __future__ import annotations

from types import SimpleNamespace

from minyoung_mah import InvocationContext

from ..models.classification import DisputeClassification
from ..prompts.classifier import CLASSIFIER_SYSTEM_PROMPT


def _build_user_message(ctx: InvocationContext) -> str:
    return f"사용자 질문:\n{ctx.user_request}\n\n위 질문을 분류해 주세요."


CLASSIFIER_ROLE = SimpleNamespace(
    name="classifier",
    system_prompt=CLASSIFIER_SYSTEM_PROMPT,
    tool_allowlist=[],
    model_tier="default",
    output_schema=DisputeClassification,
    max_iterations=1,  # fast path
    build_user_message=_build_user_message,
)
