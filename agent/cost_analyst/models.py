"""Structured output schema for the Cost Analyst Agent.

The agent is constrained to return a ``CostReport`` (passed to the agno Agent as
``output_schema=CostReport``). The schema *structurally* enforces the
constitution's evidence rule (every recommendation must cite evidence) and the
"no fabrication" rule (a missing savings estimate must be flagged as needing
data). See specs/001-cost-analyst-agent/data-model.md.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Category(str, Enum):
    """Waste categories the agent must classify findings into."""

    rightsizing = "rightsizing"
    unused_or_obsolete = "unused_or_obsolete"
    scaling_policy = "scaling_policy"
    storage_optimization = "storage_optimization"
    reserved_capacity = "reserved_capacity"
    cost_trend = "cost_trend"


class Source(str, Enum):
    """Where the evidence for a finding came from."""

    csv = "csv"
    aws_live = "aws_live"
    kubernetes = "kubernetes"
    prometheus = "prometheus"


class Level(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Recommendation(BaseModel):
    """A single actionable, evidence-backed cost-reduction recommendation."""

    title: str = Field(..., description="Short action, e.g. 'Rightsize idle m5.2xlarge'")
    category: Category
    rationale: str = Field(..., description="Why this reduces cost")
    evidence: str = Field(
        ...,
        min_length=1,
        description="Concrete data this is based on (CSV line item and/or verified "
        "live state). REQUIRED — no unsourced recommendations.",
    )
    estimated_monthly_savings: float | None = Field(
        default=None,
        description="Approximate monthly USD saving (an ESTIMATE). Null when it "
        "cannot be estimated from the available data.",
    )
    effort: Level = Level.medium
    risk: Level = Level.low
    priority: int = Field(..., ge=1, description="1 = highest priority")
    source: Source = Source.csv
    needs_data: bool = Field(
        default=False,
        description="True when the finding could not be fully substantiated.",
    )

    @model_validator(mode="after")
    def _missing_estimate_needs_data(self) -> "Recommendation":
        # No fabricated figures: if we cannot estimate savings, we must say so.
        if self.estimated_monthly_savings is None:
            self.needs_data = True
        return self


class CostReport(BaseModel):
    """The top-level structured report the agent returns."""

    summary: str = Field(..., description="Top cost drivers in plain language")
    analysis_period: str = Field(..., description="The window analyzed")
    capabilities_used: list[Source] = Field(
        default_factory=list,
        description="Which data sources actually contributed to this report",
    )
    recommendations: list[Recommendation] = Field(default_factory=list)
    total_estimated_monthly_savings: float | None = Field(
        default=None,
        description="Sum of the non-null savings estimates (an ESTIMATE).",
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Assumptions made and any NEEDS DATA notes.",
    )

    def sorted_recommendations(self) -> list[Recommendation]:
        """Recommendations ordered by priority ascending (1 = highest)."""
        return sorted(self.recommendations, key=lambda r: r.priority)

    def render_markdown(self) -> str:
        """Render the report as a human-readable Markdown document."""
        lines: list[str] = []
        lines.append("# AWS Cost Analysis Report\n")
        lines.append(f"**Analysis period:** {self.analysis_period}")
        used = ", ".join(s.value for s in self.capabilities_used) or "csv"
        lines.append(f"**Data sources used:** {used}")
        if self.total_estimated_monthly_savings is not None:
            lines.append(
                "**Total estimated monthly savings (estimate):** "
                f"${self.total_estimated_monthly_savings:,.2f}"
            )
        lines.append("\n## Summary\n")
        lines.append(self.summary)

        lines.append("\n## Recommendations (highest priority first)\n")
        if not self.recommendations:
            lines.append("_No recommendations produced._")
        else:
            lines.append(
                "| # | Recommendation | Category | Est. monthly savings | "
                "Effort | Risk | Source | Evidence |"
            )
            lines.append("|---|---|---|---|---|---|---|---|")
            for r in self.sorted_recommendations():
                savings = (
                    f"~${r.estimated_monthly_savings:,.2f}"
                    if r.estimated_monthly_savings is not None
                    else "NEEDS DATA"
                )
                evidence = r.evidence.replace("|", "\\|")
                rationale = r.rationale.replace("|", "\\|")
                title = r.title.replace("|", "\\|")
                lines.append(
                    f"| {r.priority} | {title} | {r.category.value} | {savings} "
                    f"| {r.effort.value} | {r.risk.value} | {r.source.value} | {evidence} |"
                )
                lines.append(f"|  | _{rationale}_ |  |  |  |  |  |  |")

        if self.assumptions:
            lines.append("\n## Assumptions & data gaps\n")
            for a in self.assumptions:
                lines.append(f"- {a}")

        lines.append(
            "\n> All savings figures are estimates derived from the supplied data "
            "and standard pricing heuristics. This agent is read-only and makes no "
            "changes to any system."
        )
        return "\n".join(lines)
