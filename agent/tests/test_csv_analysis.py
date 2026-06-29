"""T015 — CSV-only MVP: tool assembly + output-schema invariants."""

import pytest
from pydantic import ValidationError

from cost_analyst.agent_factory import build_tools
from cost_analyst.config import AppConfig
from cost_analyst.models import Category, CostReport, Level, Recommendation, Source
from cost_analyst.persona import Capabilities


def test_csv_only_registers_exactly_csv_and_pandas(example_csv):
    config = AppConfig(csv_path=example_csv)
    caps = Capabilities(csv=True)  # nothing else active
    names = {type(t).__name__ for t in build_tools(config, caps)}
    assert names == {"CsvTools", "PandasTools"}


def test_recommendation_requires_evidence():
    with pytest.raises(ValidationError):
        Recommendation(
            title="x", category=Category.rightsizing, rationale="y",
            evidence="", priority=1,  # empty evidence is rejected
        )


def test_missing_savings_estimate_flags_needs_data():
    rec = Recommendation(
        title="x", category=Category.rightsizing, rationale="y",
        evidence="row 3", estimated_monthly_savings=None, priority=1,
    )
    assert rec.needs_data is True


def test_report_sorts_recommendations_and_renders_evidence():
    report = CostReport(
        summary="EC2 dominates spend.",
        analysis_period="2026-03:2026-05",
        capabilities_used=[Source.csv],
        recommendations=[
            Recommendation(
                title="Low prio", category=Category.cost_trend, rationale="r2",
                evidence="cloudwatch rising", estimated_monthly_savings=50.0,
                effort=Level.low, risk=Level.low, priority=3,
            ),
            Recommendation(
                title="Top prio", category=Category.reserved_capacity, rationale="r1",
                evidence="RDS steady on-demand", estimated_monthly_savings=300.0,
                effort=Level.low, risk=Level.low, priority=1,
            ),
        ],
        total_estimated_monthly_savings=350.0,
    )
    ordered = report.sorted_recommendations()
    assert [r.priority for r in ordered] == [1, 3]

    md = report.render_markdown()
    assert "Top prio" in md and "RDS steady on-demand" in md
    assert "read-only" in md.lower()  # the read-only disclaimer is present
