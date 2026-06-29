# Implementation Plan: Cost Analyst Agent

**Branch**: `001-cost-analyst-agent` | **Date**: 2026-06-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-cost-analyst-agent/spec.md`

## Summary

A read-only, command-line AWS cost-analysis agent. It ingests an AWS cost CSV
export, summarizes the spend, and produces a prioritized, evidence-backed report
of cost-reduction recommendations. It is built on the **agno** framework with an
**OpenAI** model. Beyond the always-on CSV analysis, it gains optional, gated
capabilities — live read-only AWS verification (when AWS credentials are present),
Kubernetes resource inspection (when a kubeconfig is provided), and Prometheus
utilization correlation (when an endpoint + metric list are provided, capped at a
31-day lookback). Every tool the agent can call is read-only by construction; the
agent never mutates any system. The entry point is `agent.py`, all non-secret
parameters are CLI flags (with environment-variable fallback), and secrets are
loaded from a `.env` file.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `agno` (v2.x agent framework) · `openai` (model
backend via `agno.models.openai.OpenAIChat`) · `boto3` (read-only AWS: Cost
Explorer + describe/list) · `kubernetes` (official read-only client) · `requests`
(Prometheus `query_range`) · `pandas` (cost aggregation, via agno `PandasTools`) ·
`python-dotenv` (load `.env` secrets) · `pydantic` (structured output models) ·
`argparse` (stdlib, CLI). Reused agno toolkits: `CsvTools`, `PandasTools`.

**Storage**: N/A — stateless. Inputs are a CSV file plus live read-only API
queries; output is a Markdown report written to stdout (optionally a file).

**Testing**: `pytest` (unit tests for config/gating resolution, tool input
validation, the 31-day clamp, and a read-only-guarantee test that asserts no
mutating tool/method is registered).

**Target Platform**: Linux/macOS CLI (Python 3.11+).

**Project Type**: Single project — a CLI tool. Lives under `agent/` per the repo
README.

**Performance Goals**: Interactive single-run usage (one report per invocation).
Cost CSVs of up to tens of thousands of rows are handled by aggregating in pandas
rather than reasoning row-by-row. Prometheus queries are bounded to ≤31 days to
control token/query cost. No high-throughput/concurrency target.

**Constraints**: Read-only everywhere (FR-015–018) — every tool exposes only
read operations; the generic `ShellTools`/`PythonTools` agno toolkits are NOT
registered. Secrets only via `.env`/environment, never CLI flags (FR-024). CLI
flag takes precedence over env var; capability gating is deterministic
(FR-010/012/020/023). Public repo: no real secrets, account IDs, or sensitive
ARNs committed; sample data is fictitious.

**Scale/Scope**: Single AWS account; one cost CSV per run; optionally one
Kubernetes cluster and one Prometheus endpoint. Multi-account only insofar as it
appears in the provided CSV.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Constitution v1.0.0 — evaluation of this plan against each principle:

| Principle | Verdict | How this plan satisfies it |
|---|---|---|
| **I. Operational Excellence by Design (SRE-First)** | ✅ PASS | The agent directly attacks the named "cost visibility" gap. The agent itself emits structured run logging so its own behavior is observable. |
| **II. Cost Optimization as a First-Class Signal** | ✅ PASS | Output is categorized (rightsizing, unused/obsolete, scaling, storage, reserved-capacity, trend) and prioritized by savings vs. effort/risk (FR-003/004). |
| **III. AI-Leveraged, Human-Accountable** | ✅ PASS | Agent is advisory only — read-only tools, no auto-mutation (FR-015). Prompt logging to `prompts.txt` continues. |
| **IV. The Cost Agent Runs on Agno + OpenAI** | ✅ PASS | Built on `agno.agent.Agent` + `agno.models.openai.OpenAIChat`; capabilities are explicit, single-responsibility, typed, read-only Toolkits; native agno tools, no MCP. |
| **V. Evidence-Based, Reproducible Outputs** | ✅ PASS | Structured Pydantic output requires every recommendation to cite evidence; missing data → assumption/`NEEDS DATA` (FR-005/006); deterministic gating (FR-020). |
| **VI. Pragmatism with Documented Tradeoffs** | ✅ PASS | `research.md` records each decision + alternatives. Scope fits the assessment; raw `requests` chosen over an extra Prometheus lib to minimize deps. |

**Technology & Security Constraints** (constitution §2): ✅ read-only IAM/RBAC
assumed and documented; no `Shell`/`Python` toolkits; secrets via `.env` (git-
ignored); fictitious example values only.

**Result: PASS — no violations. Complexity Tracking is empty.**

## Project Structure

### Documentation (this feature)

```text
specs/001-cost-analyst-agent/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output — decisions, rationale, alternatives
├── data-model.md        # Phase 1 output — entities + structured-output schema
├── quickstart.md        # Phase 1 output — run/validation guide
├── contracts/           # Phase 1 output
│   ├── cli-interface.md #   CLI flags, env fallback, exit codes
│   └── tools.md         #   read-only tool (function) contracts
├── checklists/
│   └── requirements.md  # spec quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
agent/
├── agent.py                      # CLI entry point: load_dotenv() → parse args → build agent → run
├── requirements.txt
├── .env.example                  # template only — no real secrets (OPENAI_API_KEY, AWS_* )
├── README.md                     # how to install & run
├── cost_analyst/
│   ├── __init__.py
│   ├── config.py                 # argparse + env fallback + gating resolution (CLI > env)
│   ├── agent_factory.py          # builds the agno Agent: model, persona, conditional toolkits
│   ├── persona.py                # system instructions (the persona from spec §2)
│   ├── models.py                 # Pydantic: WasteFinding, Recommendation, CostReport (output_schema)
│   └── tools/
│       ├── __init__.py
│       ├── aws_cost_tools.py     # AwsCostTools(Toolkit): read-only ce:GetCostAndUsage + describe_*/list_*
│       ├── kubernetes_read_tools.py  # KubernetesReadTools(Toolkit): list_*/read_* only
│       └── prometheus_tools.py   # PrometheusTools(Toolkit): query_range, ≤31-day clamp
├── examples/
│   └── example_costs.csv         # fictitious AWS cost export for demos/tests
└── tests/
    ├── test_config.py            # required --CSV_PATH; CLI>env precedence; gating on/off
    ├── test_prometheus_tools.py  # 31-day lookback clamp
    ├── test_aws_cost_tools.py    # read-only shape (mocked boto3)
    ├── test_kubernetes_read_tools.py  # read verbs only (mocked client)
    └── test_readonly_guarantee.py     # no mutating method names; Shell/Python toolkits absent
```

**Structure Decision**: Single-project CLI under `agent/` (matches the repo
README, which reserves `agent/` for the Cost Optimization Agent). `agent.py` is
the thin entry point the user specified; all logic lives in the importable
`cost_analyst/` package so it is unit-testable without invoking the LLM. The three
custom read-only integrations are isolated as separate Toolkits under
`cost_analyst/tools/` so each can be gated, tested, and reasoned about
independently.

## Complexity Tracking

> No constitution violations. No entries required.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |

## Phase 0 — Outline & Research

See [research.md](./research.md). All Technical Context items are resolved (no
`NEEDS CLARIFICATION` remain). Key decisions: agno v2 `Agent` + `OpenAIChat`;
custom `Toolkit` subclasses for AWS/K8s/Prometheus (agno ships none of these);
conditional `tools=[...]` assembly in Python for gating; `output_schema` Pydantic
model for evidence-bound recommendations; raw `requests` for Prometheus; standard
boto3 credential chain + `python-dotenv` for secrets.

## Phase 1 — Design & Contracts

- [data-model.md](./data-model.md) — entities (AWS Cost Export, Waste Finding,
  Recommendation, Capability, Cost Report) and the Pydantic structured-output
  schema.
- [contracts/cli-interface.md](./contracts/cli-interface.md) — the CLI command
  contract: flags, required/optional, env fallback, exit codes.
- [contracts/tools.md](./contracts/tools.md) — the read-only tool/function
  contracts for the reused (`CsvTools`, `PandasTools`) and custom
  (`AwsCostTools`, `KubernetesReadTools`, `PrometheusTools`) toolkits.
- [quickstart.md](./quickstart.md) — install, configure `.env`, and run each user
  story scenario with expected outcomes.
- Agent context: the `<!-- SPECKIT START -->…<!-- SPECKIT END -->` block in
  `CLAUDE.md` is updated to point at this plan.

**Post-design Constitution re-check: PASS** — the design introduces no mutating
surface, keeps secrets out of the CLI, and preserves deterministic gating and
evidence-bound output. No new violations.
