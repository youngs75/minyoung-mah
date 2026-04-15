"""Output schema of the classifier role."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .dispute import DisputeType, QueryIntent


class DisputeClassification(BaseModel):
    """What the classifier returns for a single user question."""

    dispute_type: DisputeType = Field(
        description="10 supported dispute types. Use GENERAL when uncertain."
    )
    keywords: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Key terms extracted from the question, in Korean.",
    )
    intent: QueryIntent = Field(
        description="What the user wants to know — informational, procedural, etc."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Self-reported confidence in the classification.",
    )
