# Phase 1 Data Model: Cost Analyst Agent

This agent is stateless — it persists nothing. The "data model" is (a) the shape
of the data it reasons over and (b) the structured output schema it must produce.
The output schema is the most important contract: it is what enforces
evidence-bound, prioritized recommendations (Constitution Principle V; FR-004/005/
006).

## Domain entities

### AWS Cost Export (input)
The CSV the user supplies. Treated as read-only tabular data.

| Field (typical) | Meaning | Notes |
|---|---|---|
| service | AWS service name (e.g. `Amazon EC2`) | primary grouping dimension |
| usage_type / resource | usage type or resource identifier | may vary by export |
| cost (amount) | spend for the row | currency assumed USD unless stated |
| period (start/end or month) | time bucket | drives the analysis window |

Column names vary between Cost Explorer and CUR-style exports; the agent adapts to
common variants and reports which expected fields are missing (spec Edge Cases).

### Waste Finding (derived, internal → surfaced)
A detected inefficiency. One or more findings back a Recommendation.

| Field | Type | Rule |
|---|---|---|
| `category` | enum | one of: `rightsizing`, `unused_or_obsolete`, `scaling_policy`, `storage_optimization`, `reserved_capacity`, `cost_trend` |
| `resource` | string | affected service/resource |
| `evidence` | string | concrete reference to input data and/or verified live state (REQUIRED) |
| `estimated_monthly_savings` | number \| null | null when not estimable; labeled as estimate |
| `confidence` | enum | `high` \| `medium` \| `low` |
| `needs_data` | bool | true when the finding could not be fully substantiated |
| `source` | enum | `csv` \| `aws_live` \| `kubernetes` \| `prometheus` |

### Recommendation (output)
An actionable proposal derived from findings, ranked for the report.

| Field | Type | Rule |
|---|---|---|
| `title` | string | short action (e.g. "Rightsize idle `m5.2xlarge`") |
| `category` | enum | same enum as Waste Finding `category` |
| `rationale` | string | why it saves money |
| `evidence` | string | REQUIRED — what data it is based on (FR-005) |
| `estimated_monthly_savings` | number \| null | labeled estimate; null ⇒ `needs_data` true |
| `effort` | enum | `low` \| `medium` \| `high` |
| `risk` | enum | `low` \| `medium` \| `high` |
| `priority` | int | 1 = highest; derived from savings vs. effort/risk (FR-004) |
| `needs_data` | bool | true ⇒ states the gap instead of a fabricated figure (FR-006) |

### Cost Report (output root) — `output_schema`
The top-level object the agent returns.

| Field | Type | Rule |
|---|---|---|
| `summary` | string | top cost drivers in plain language |
| `analysis_period` | string | the window analyzed (from CSV range or `--PERIOD`) |
| `capabilities_used` | list[enum] | which sources ran: `csv`, `aws_live`, `kubernetes`, `prometheus` |
| `recommendations` | list[Recommendation] | ordered by `priority` ascending |
| `total_estimated_monthly_savings` | number \| null | sum of non-null estimates; labeled estimate |
| `assumptions` | list[string] | assumptions/`NEEDS DATA` notes (FR-006) |

### Capability (configuration, not persisted)
A gated bundle of read-only tools with activation conditions.

| Capability | Activation condition | Tools registered |
|---|---|---|
| Cost Analysis (always on) | `--CSV_PATH` present | `CsvTools`, `PandasTools` (+ `AwsCostTools` if AWS creds resolve) |
| Kubernetes | `--KUBE_CONFIG_PATH`/env set **and** cluster reachable | `KubernetesReadTools` |
| Prometheus | `--PROMETHEUS_PATH` **and** `--PROMETHEUS_METRICS` (or env) set **and** endpoint reachable | `PrometheusTools` |

## Reference Pydantic schema (for implementation)

```python
from enum import Enum
from pydantic import BaseModel, Field

class Category(str, Enum):
    rightsizing = "rightsizing"
    unused_or_obsolete = "unused_or_obsolete"
    scaling_policy = "scaling_policy"
    storage_optimization = "storage_optimization"
    reserved_capacity = "reserved_capacity"
    cost_trend = "cost_trend"

class Source(str, Enum):
    csv = "csv"; aws_live = "aws_live"
    kubernetes = "kubernetes"; prometheus = "prometheus"

class Level(str, Enum):
    low = "low"; medium = "medium"; high = "high"

class Recommendation(BaseModel):
    title: str
    category: Category
    rationale: str
    evidence: str = Field(..., description="Concrete data this is based on; required")
    estimated_monthly_savings: float | None = None
    effort: Level
    risk: Level
    priority: int = Field(..., ge=1)
    needs_data: bool = False

class CostReport(BaseModel):
    summary: str
    analysis_period: str
    capabilities_used: list[Source]
    recommendations: list[Recommendation]
    total_estimated_monthly_savings: float | None = None
    assumptions: list[str] = []
```

## Validation rules (cross-cutting)

- `Recommendation.evidence` is non-empty (structural enforcement of FR-005).
- `estimated_monthly_savings is None` ⇒ `needs_data is True` (FR-006).
- `recommendations` is sorted by `priority` ascending (FR-004; SC-004).
- `capabilities_used` reflects only capabilities that actually ran (FR-020; SC-005).
