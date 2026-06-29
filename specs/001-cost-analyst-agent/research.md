# Phase 0 Research: Cost Analyst Agent

All Technical Context unknowns are resolved here. Each decision lists rationale and
the alternatives considered. Sources were verified against official docs (agno,
boto3, kubernetes-client, Prometheus, python-dotenv) in June 2026.

## 1. Agent framework & model

**Decision**: Build on **agno v2.x** using `from agno.agent import Agent` and
`from agno.models.openai import OpenAIChat`. Construct with
`Agent(model=OpenAIChat(id=...), tools=[...], instructions=..., markdown=True,
output_schema=CostReport)`.

**Rationale**: Mandated by Constitution Principle IV (agno + OpenAI). agno
natively supports a model object, a list of tools/toolkits, system instructions,
markdown output, and Pydantic structured output — exactly what this agent needs.

**Alternatives considered**: LangChain/LlamaIndex (not mandated, heavier);
hand-rolled OpenAI tool-calling loop (re-implements what agno provides); MCP
servers for the integrations (explicitly out of scope per spec §8 — native agno
tools at this stage).

## 2. OpenAI model id & API key

**Decision**: Default model id `gpt-4o`, overridable via the `--MODEL` CLI flag.
The OpenAI API key is read from `OPENAI_API_KEY` in the environment (populated by
the `.env` file); `OpenAIChat` reads it automatically.

**Rationale**: `gpt-4o` is a current, widely available, tool-calling- and
structured-output-capable model documented in agno's examples — a safe default
for a 2–3h assessment. Making it a flag lets a reviewer pick a cheaper id
(`gpt-4o-mini`) or a newer one without code changes. Keeping the key in the
environment honors FR-024 (no secrets on the CLI).

**Alternatives considered**: Hard-coding a model (less flexible); a specific
`gpt-5.x` flagship id — left to the operator because exact current ids should be
confirmed against OpenAI's live model list, and `gpt-4o` is a dependable default.
`OpenAIResponses` (Responses API) — `OpenAIChat` (chat-completions) is the simpler
fit.

## 3. Custom toolkit authoring

**Decision**: Implement each integration as a subclass of
`from agno.tools import Toolkit`, registering only read methods via the
constructor `tools=[...]` argument. One toolkit per integration:
`AwsCostTools`, `KubernetesReadTools`, `PrometheusTools`.

**Rationale**: A `Toolkit` subclass groups cohesive functions that share config
(a boto3 client, a kube client, a Prometheus base URL) and state — the right
shape for these wrappers. Registering only read methods means the mutating
surface literally does not exist on the object (FR-016).

**Alternatives considered**: Standalone `@tool`-decorated functions (fine for
one-offs, but these functions share clients/config, so a class is cleaner);
agno's built-in `aws-lambda`/`aws-ses` toolkits (cover neither cost nor resource
inspection).

## 4. Reused built-in toolkits

**Decision**: Reuse `from agno.tools.csv_toolkit import CsvTools`
(`CsvTools(csvs=[csv_path])`) for reading/inspecting the cost CSV and
`from agno.tools.pandas import PandasTools` for aggregation. Register only the
read/list/query functions; use `exclude_tools=[...]` to drop anything not needed.

**Rationale**: Don't rebuild CSV/dataframe tooling agno already ships (Principle
VI, YAGNI). DuckDB-backed CSV querying and pandas aggregation are read-only
against the source file.

**Alternatives considered**: Reading the CSV manually with pandas only (loses the
agent's ability to inspect columns/rows as tools); custom CSV toolkit (redundant).

## 5. Conditional / gated tool registration

**Decision**: Resolve configuration first (CLI flag → env fallback), then build
the `tools=[...]` list in plain Python: always include `CsvTools` + `PandasTools`
(+ `AwsCostTools` when AWS creds resolve); append `KubernetesReadTools` only when
the kubeconfig path resolves and the cluster is reachable; append
`PrometheusTools` only when both Prometheus settings resolve and the endpoint is
reachable. A disabled capability's toolkit is never instantiated/registered.

**Rationale**: agno's canonical pattern for runtime capability selection is to
assemble the tool list before constructing the `Agent`. This makes gating
deterministic (FR-020) and keeps the active tool surface minimal (FR-019).

**Alternatives considered**: `agent.add_tool(...)` after construction (no
per-run scoping; unnecessary here); always registering all toolkits and failing
inside them when unconfigured (violates "tools not registered" in FR-010/012 and
wastes tokens); `include_tools`/`exclude_tools` only trims within a toolkit, not
whole-capability gating.

## 6. Structured, evidence-bound output

**Decision**: Define Pydantic models (`WasteFinding`, `Recommendation`,
`CostReport`) and pass `output_schema=CostReport` to the Agent. Each
`Recommendation` carries required `evidence` and `category` fields and a
`confidence`/`needs_data` flag.

**Rationale**: Enforces Principle V / FR-005/006 structurally — the model cannot
return a recommendation without an evidence field, and "insufficient data" is a
first-class state rather than an invitation to hallucinate. `output_schema` is the
current v2 arg; `use_json_mode=True` is the fallback if a chosen model lacks
native structured outputs.

**Alternatives considered**: Free-text report (unverifiable, fails Principle V);
the older `response_model` arg name (use `output_schema` in v2).

## 7. Read-only enforcement & safety

**Decision**: Defense in depth — (a) custom toolkits expose read methods only;
(b) `ShellTools`/`PythonTools` are never imported or registered; (c) the persona
instructs refusal of any mutating request; (d) operators run with read-only IAM
and a read-only K8s ServiceAccount. A `test_readonly_guarantee.py` asserts the
registered tool set contains no mutating method names and no Shell/Python toolkit.

**Rationale**: Principle III + FR-015–018. The strongest guarantee is that no
write code path exists; the external IAM/RBAC layer backstops it.

**Alternatives considered**: agno HITL `requires_confirmation=True` for risky
tools — unnecessary because there are no risky (mutating) tools at all; relying on
IAM alone (weaker — defense in depth preferred).

## 8. AWS read-only access (boto3)

**Decision**: `boto3.client("ce", region_name="us-east-1").get_cost_and_usage(
TimePeriod={...}, Granularity=..., Metrics=[...], GroupBy=[...])` for cost data,
plus `describe_*`/`list_*` (EC2/S3/RDS) for live resource verification. boto3
reads credentials from the standard chain (env vars populated by `.env`, shared
config, or role). Operator attaches `ReadOnlyAccess` and/or
`AWSBillingReadOnlyAccess`.

**Rationale**: `get_cost_and_usage` is the canonical read API for spend; Cost
Explorer is global and addressed via `us-east-1`. The standard credential chain
keeps secrets out of code/CLI.

**Alternatives considered**: Cost & Usage Report (CUR) in S3 (richer but needs
setup/athena — heavier than the assessment needs; CSV import covers the offline
path); AWS Cost Explorer console export only (no programmatic verification).

## 9. Kubernetes read-only access

**Decision**: Official `kubernetes` client. `config.load_kube_config(
config_file=KUBE_CONFIG_PATH)`, then read verbs only —
`CoreV1Api().list_*/read_*` (pods, nodes, services) and
`AppsV1Api().list_*/read_*` (deployments, replicasets). Flag missing
requests/limits, over-provisioning, and obvious misconfigurations.

**Rationale**: Matches FR-010/011; least-privilege RBAC (`verbs: get/list/watch`)
backs it. Reachability is checked at gating time so an unreachable cluster
disables the capability cleanly.

**Alternatives considered**: `kubectl` shell-out (needs a shell tool — forbidden);
metrics-server `top` only (useful but `requests/limits` vs. usage requires the API
objects too).

## 10. Prometheus read-only access

**Decision**: Raw `requests.get(f"{base}/api/v1/query_range", params={query,
start, end, step})` over the predefined comma-separated `PROMETHEUS_METRICS`. The
toolkit clamps any requested window to ≤31 days before issuing the query.

**Rationale**: `query_range` is read-only and dependency-light; raw `requests`
avoids adding `prometheus-api-client` (Principle VI). The 31-day clamp is enforced
in code (FR-014) so it cannot be bypassed by a prompt.

**Alternatives considered**: `prometheus-api-client` (convenient pandas output but
an extra dependency); instant `query` only (loses the time-series needed for
utilization trends).

## 11. Secrets & configuration loading

**Decision**: `from dotenv import load_dotenv; load_dotenv()` at startup (before
building the model/clients) to populate the environment from `.env`. Non-secret
parameters come from `argparse` flags with env fallback (CLI wins). `.env` is
git-ignored; a committed `.env.example` documents the keys with placeholder
values.

**Rationale**: Standard, well-understood pattern; satisfies FR-023/024 and the
public-repo hygiene constraint. python-dotenv does not override already-set env
vars by default, which keeps real shell/role credentials authoritative.

**Alternatives considered**: Secrets as CLI flags (rejected in clarify — exposed
in process list/history); a bespoke config file format (reinventing dotenv).

## Resolved unknowns summary

| Unknown | Resolution |
|---|---|
| Agent framework / model | agno v2 `Agent` + `OpenAIChat(id="gpt-4o")`, `--MODEL` override |
| How to gate capabilities | Build `tools=[...]` conditionally after CLI>env resolution |
| Evidence enforcement | Pydantic `output_schema=CostReport` with required evidence |
| Prometheus client | raw `requests` to `/api/v1/query_range`, ≤31-day clamp |
| AWS auth | boto3 standard credential chain via `.env`/env |
| Secret handling | `python-dotenv` `load_dotenv()`; `.env` git-ignored |
| Read-only proof | read-only toolkits + no Shell/Python + guarantee test |
