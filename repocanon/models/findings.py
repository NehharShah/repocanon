"""Confidence and Finding primitives shared across analyzers."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    """Coarse confidence levels for inferences.

    Kept intentionally small. Generators surface ``low`` items as uncertainty
    notes rather than presenting them as facts.
    """

    high = "high"
    medium = "medium"
    low = "low"

    @property
    def score(self) -> float:
        return {"high": 1.0, "medium": 0.6, "low": 0.3}[self.value]


class Finding(BaseModel):
    """A single piece of evidence used to support an inference.

    Findings are surfaced verbatim by the ``audit`` command so users can see
    exactly what RepoCanon saw and why it concluded what it did.
    """

    kind: str = Field(description="Category, e.g. 'framework', 'command', 'topology'.")
    subject: str = Field(description="What the finding is about, e.g. 'fastapi'.")
    rationale: str = Field(description="Plain-English reason this was inferred.")
    evidence: list[str] = Field(
        default_factory=list,
        description="Concrete file paths or snippets supporting the rationale.",
    )
    confidence: Confidence = Confidence.medium
