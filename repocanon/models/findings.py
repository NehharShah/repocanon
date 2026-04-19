"""Confidence and Finding primitives shared across analyzers."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Confidence(StrEnum):
    """Coarse confidence labels for inferences.

    The label drives how a finding is *displayed* (color in the audit table,
    whether it shows up in "Uncertainty"). The numeric weight that feeds into
    ``ProjectModel.overall_confidence`` is computed from the label *plus* the
    amount of corroborating evidence each Finding carries — see
    ``Finding.weighted_score``. Treat the enum as a presentation choice and
    the score as the actual signal.
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

    @property
    def weighted_score(self) -> float:
        """Confidence score multiplied by an evidence-count saturation curve.

        A "high" finding with one piece of evidence is roughly equivalent to a
        "medium" finding with three. Findings with zero evidence count for the
        listed confidence at half weight, since we have nothing to point at.
        """
        if not self.evidence:
            return self.confidence.score * 0.5
        # Saturating: 1 piece -> 0.7, 2 -> 0.85, 3+ -> 1.0
        n = len(self.evidence)
        evidence_factor = min(1.0, 0.55 + 0.15 * n)
        return self.confidence.score * evidence_factor
