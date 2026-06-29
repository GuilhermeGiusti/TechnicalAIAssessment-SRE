---
description: "Task list for Cost Analyst Agent implementation"
---

# Tasks: Cost Analyst Agent

**Input**: Design documents from `/specs/001-cost-analyst-agent/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: INCLUDED — the plan and contracts explicitly require a pytest suite
(config/gating, 31-day clamp, read-only tool shapes, and the read-only guarantee).

**Organization**: Tasks are grouped by user story so each story can be implemented
and tested independently. All paths are relative to the repo root.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: US1–US4 (user-story phases only); Setup/Foundational/Polish carry no story label
- Exact file paths are included in every task

## Path Conventions

Single-project CLI under `agent/` (see plan.md → Project Structure). Package code
in `agent/cost_analyst/`, entry point `agent/agent.py`, tests in `agent/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project skeleton and tooling.

- [X] T001 Create the `agent/` project tree per plan.md (`agent/cost_analyst/`, `agent/cost_analyst/tools/`, `agent/examples/`, `agent/tests/`) with `__init__.py` in each package dir
- [X] T002 Create `agent/requirements.txt` pinning: `agno`, `openai`, `boto3`, `kubernetes`, `requests`, `pandas`, `python-dotenv`, `pydantic`, `pytest`
- [X] T003 [P] Create `agent/.env.example` with placeholder keys (`OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`) and append `.env` to the repo `.gitignore`
- [X] T004 [P] Create `agent/examples/example_costs.csv` — a small, fictitious AWS cost export (service, usage_type, cost, period) containing seeded waste (idle EC2, unattached EBS, over-provisioned RDS, old-storage-class S3)
- [X] T005 [P] Add pytest config in `agent/pyproject.toml` (or `agent/pytest.ini`) and `agent/tests/conftest.py` with fixtures for a sample CSV path and mocked clients

**Checkpoint**: Project installs (`pip install -r agent/requirements.txt`) and `pytest` collects.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared spine every user story plugs into — config/gating, the
output schema, the persona, the agent factory, and the CLI entry point.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 [P] Implement the Pydantic output schema (`Category`, `Source`, `Level`, `Recommendation`, `CostReport`) in `agent/cost_analyst/models.py` per data-model.md, enforcing required `evidence` and the `estimated_monthly_savings is None ⇒ needs_data` rule
- [X] T007 [P] Implement the agent persona/system instructions (cost-optimization expert; refuse mutating requests; cite evidence; flag `NEEDS DATA`) in `agent/cost_analyst/persona.py`
- [X] T008 Implement configuration in `agent/cost_analyst/config.py`: `load_dotenv()`, argparse flags (`--CSV_PATH` required, `--MODEL`, `--PERIOD`, `--KUBE_CONFIG_PATH`, `--PROMETHEUS_PATH`, `--PROMETHEUS_METRICS`, `--PROMETHEUS_LOOKBACK_DAYS`, `--OUTPUT`, `--DEBUG`), CLI>env fallback precedence, and a `resolve_capabilities()` that returns which capabilities are active (deterministic gating)
- [X] T009 Implement the agent factory in `agent/cost_analyst/agent_factory.py`: build `OpenAIChat(id=model)` (default `gpt-4o`), assemble the `tools=[...]` list conditionally from resolved capabilities, and return `Agent(model=..., tools=..., instructions=persona, markdown=True, output_schema=CostReport)` (depends on T006, T007, T008)
- [X] T010 Implement the CLI entry point `agent/agent.py`: parse config → build agent → run → render `CostReport` to Markdown on stdout or `--OUTPUT`, with exit codes (0 ok, 2 missing/!found `--CSV_PATH`, 3 missing `OPENAI_API_KEY`, 1 runtime) (depends on T009)
- [X] T011 [P] Write `agent/tests/test_config.py`: missing `--CSV_PATH` exits 2; CLI flag overrides env var; capability gating turns on/off based on resolved config (depends on T008)

**Checkpoint**: `python agent/agent.py` (no args) exits 2 cleanly; the agent builds with only `OPENAI_API_KEY` + `--CSV_PATH`.

---

## Phase 3: User Story 1 — CSV cost analysis & prioritized recommendations (Priority: P1) 🎯 MVP

**Goal**: Given a cost CSV (no cloud access), produce a prioritized, evidence-backed recommendation report.

**Independent Test**: `python agent/agent.py --CSV_PATH agent/examples/example_costs.csv` with only `OPENAI_API_KEY` set returns a prioritized report where every recommendation cites CSV evidence; `capabilities_used == ["csv"]`.

- [X] T012 [US1] Register `CsvTools(csvs=[csv_path])` (read/list/query only; drop any write fn via `exclude_tools`) in the base tool set in `agent/cost_analyst/agent_factory.py`
- [X] T013 [US1] Register `PandasTools()` for cost aggregation (by service/usage_type/period) in `agent/cost_analyst/agent_factory.py`
- [X] T014 [US1] Extend `agent/cost_analyst/persona.py` with the CSV-analysis playbook: detect top cost drivers, classify waste into the six categories, rank by savings vs. effort/risk, and populate `CostReport.summary`/`analysis_period`/`assumptions`
- [X] T015 [P] [US1] Write `agent/tests/test_csv_analysis.py`: with a mocked/stubbed model returning a `CostReport`, assert the CSV-only path registers exactly CSV+pandas tools and that recommendations are sorted by `priority` and each has non-empty `evidence`

**Checkpoint**: MVP works end-to-end on the sample CSV and is demoable.

---

## Phase 4: User Story 2 — Live read-only AWS verification (Priority: P2)

**Goal**: When AWS credentials are present, confirm/enrich findings against the live account read-only.

**Independent Test**: With read-only AWS creds in `.env`, a finding is confirmed/enriched via live data and `capabilities_used` includes `aws_live`; with creds absent the run still completes CSV-only.

- [X] T016 [US2] Implement `AwsCostTools(Toolkit)` (read-only) in `agent/cost_analyst/tools/aws_cost_tools.py`: `get_cost_and_usage`, `get_cost_forecast` (CE client in `us-east-1`), `list_ec2_instances`, `list_ebs_volumes`, `list_s3_buckets`, `list_rds_instances` — describe/list only, no mutating methods
- [X] T017 [US2] Add AWS-credential resolution (standard boto3 chain) and conditional registration of `AwsCostTools` in `agent/cost_analyst/config.py` + `agent/cost_analyst/agent_factory.py`; degrade gracefully (warn, continue CSV-only) when creds/permissions are absent
- [X] T018 [US2] Extend `agent/cost_analyst/persona.py` to use live AWS evidence (resource existence/state, idle indicators, CE trends) and set `source=aws_live` on verified findings
- [X] T019 [P] [US2] Write `agent/tests/test_aws_cost_tools.py` with mocked boto3 (e.g. `botocore.stub`/`unittest.mock`): correct CE params, no mutating methods exist on the toolkit, graceful behavior when credentials are missing

**Checkpoint**: US1 still works; US2 adds live verification without any mutation.

---

## Phase 5: User Story 3 — Kubernetes resource waste (Priority: P3, gated)

**Goal**: When a reachable kubeconfig is provided, flag misconfigurations and over-provisioned workloads read-only.

**Independent Test**: With `--KUBE_CONFIG_PATH` to a reachable cluster, the report adds workload findings and `capabilities_used` includes `kubernetes`; without the flag, no Kubernetes tools are registered.

- [X] T020 [US3] Implement `KubernetesReadTools(Toolkit)` (read-only) in `agent/cost_analyst/tools/kubernetes_read_tools.py`: `config.load_kube_config(config_file=...)`, `list_nodes`, `list_pods`, `list_deployments`, `get_workload_resources` (requests/limits gaps, missing limits) — `list_*`/`read_*` only
- [X] T021 [US3] Add `KUBE_CONFIG_PATH` gating + cluster-reachability check + conditional registration in `agent/cost_analyst/config.py` + `agent/cost_analyst/agent_factory.py` (unreachable ⇒ capability disabled, reported)
- [X] T022 [US3] Extend `agent/cost_analyst/persona.py` to convert K8s findings into `Recommendation`s (`source=kubernetes`, categories rightsizing/scaling_policy)
- [X] T023 [P] [US3] Write `agent/tests/test_kubernetes_read_tools.py` with a mocked kubernetes client: read verbs only, no mutating methods, capability absent when the flag/env is unset

**Checkpoint**: US1/US2 unaffected; Kubernetes capability is cleanly gated.

---

## Phase 6: User Story 4 — Prometheus utilization correlation (Priority: P3, gated)

**Goal**: When a reachable Prometheus endpoint + metric list are provided, strengthen rightsizing/idle findings with utilization data, capped at 31 days.

**Independent Test**: With `--PROMETHEUS_PATH` + `--PROMETHEUS_METRICS`, only the listed metrics are queried over ≤31 days and `capabilities_used` includes `prometheus`; missing either flag disables the capability.

- [X] T024 [US4] Implement `PrometheusTools(Toolkit)` (read-only) in `agent/cost_analyst/tools/prometheus_tools.py`: `query_range` via `requests.get("{base}/api/v1/query_range", params=...)` and `list_configured_metrics`; clamp `lookback_days` to ≤31 before any request; restrict queries to configured metrics
- [X] T025 [US4] Add `PROMETHEUS_PATH`+`PROMETHEUS_METRICS` gating (+ `--PROMETHEUS_LOOKBACK_DAYS`, default 7) + endpoint-reachability check + conditional registration in `agent/cost_analyst/config.py` + `agent/cost_analyst/agent_factory.py`
- [X] T026 [US4] Extend `agent/cost_analyst/persona.py` to fold utilization evidence into rightsizing/idle `Recommendation`s (`source=prometheus`)
- [X] T027 [P] [US4] Write `agent/tests/test_prometheus_tools.py`: a 90-day request is clamped to 31; only configured metrics are queryable; HTTP GET only (mocked `requests`)

**Checkpoint**: All four capabilities work independently and compose.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: The read-only guarantee, observability, docs, and end-to-end validation.

- [X] T028 [P] Write `agent/tests/test_readonly_guarantee.py`: against the fully-assembled agent, assert no registered tool name matches `create|delete|modify|put|update|patch|replace|run|exec|terminate|stop|start|write`, and that `ShellTools`/`PythonTools` are absent; assert CSV-only build registers only CSV+pandas tools
- [X] T029 Add structured run logging (capabilities used, tool calls, timings) gated by `--DEBUG` in `agent/cost_analyst/agent_factory.py` and `agent/agent.py` (Constitution Principle I — observability)
- [X] T030 [P] Write `agent/README.md`: install, `.env` setup, and the run commands for all six quickstart scenarios
- [X] T031 [P] Add a `.gitignore` check / confirm no secrets, account IDs, or real ARNs are committed (public-repo hygiene; Constitution §2)
- [X] T032 Validate all six scenarios in `quickstart.md` end-to-end and fix any gaps
- [X] T033 Final Constitution review: confirm read-only guarantee, evidence-bound output, deterministic gating, and prompt-log update before sign-off

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (P1)**: no dependencies.
- **Foundational (P2)**: depends on Setup — **blocks all user stories**.
- **User stories (P3–P6)**: all depend on Foundational. US1 is the MVP; US2/US3/US4 are independent of each other and can proceed in any order or in parallel once Foundational is done.
- **Polish (P7)**: depends on the user stories it validates (T028 and T032 want all capabilities present).

### Story dependencies

- **US1 (P1)**: needs only Foundational. No dependency on other stories.
- **US2 (P2)**: needs Foundational. Independent of US3/US4.
- **US3 (P3)**: needs Foundational. Independent of US2/US4.
- **US4 (P3)**: needs Foundational. Independent of US2/US3.

### Within each story

- Tool implementation → gating/registration wiring → persona integration → tests.
- T009 (factory) depends on T006/T007/T008; T010 depends on T009.

---

## Parallel Opportunities

- **Setup**: T003, T004, T005 in parallel.
- **Foundational**: T006 and T007 in parallel (different files); T008→T009→T010 are sequential (shared files); T011 in parallel after T008.
- **Across stories**: once Foundational completes, US2, US3, and US4 can be built in parallel by different developers — each touches its own `tools/<x>.py` and test file (the only shared files are `config.py`/`agent_factory.py`/`persona.py`, so coordinate edits there).
- **Per-story tests** (T015, T019, T023, T027) and the polish docs (T030, T031) are `[P]`.

### Parallel example — after Foundational

```bash
# Three developers, three independent capabilities:
Dev A: T016–T019  (US2 — AWS)
Dev B: T020–T023  (US3 — Kubernetes)
Dev C: T024–T027  (US4 — Prometheus)
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1.
4. **STOP and validate**: run quickstart Scenario 1; confirm a prioritized,
   evidence-bound report from the sample CSV. This alone is a demoable deliverable
   (and needs no AWS/K8s/Prometheus access — ideal for the assessment reviewer).

### Incremental delivery

Foundational → US1 (MVP, demo) → US2 (live AWS) → US3 (Kubernetes) → US4
(Prometheus) → Polish. Each story is an independently testable increment that adds
value without breaking earlier ones.

---

## Notes

- `[P]` = different files, no dependency on incomplete tasks.
- Every user-story task carries its `[US#]` label; Setup/Foundational/Polish do not.
- Read-only is non-negotiable: no task introduces a mutating method, and
  `ShellTools`/`PythonTools` are never registered (FR-015–018; T028 enforces it).
- Keep `prompts.txt` updated per CLAUDE.md as implementation proceeds.
- Commit after each task or logical group; stop at any checkpoint to validate.

## Implementation status (2026-06-28)

All 33 tasks implemented. **27/27 unit tests pass.** Validated without external
credentials: package builds, the agno `Agent` assembles with `OpenAIChat` +
`output_schema=CostReport` and the correctly-gated read-only tool list, `--help`
works, exit codes 2 (missing `--CSV_PATH`) and 3 (missing `OPENAI_API_KEY`) are
correct, the Prometheus 31-day clamp and metric allow-list hold, and the
read-only-guarantee test passes (no mutating tool ever registered; no Shell/Python
toolkits).

**Not exercised against live services (require the operator's credentials):** the
actual OpenAI call that produces a populated report, and live AWS / Kubernetes /
Prometheus queries. These are covered structurally (mocked) in the test suite and
are run via the commands in `quickstart.md` once `OPENAI_API_KEY` (and any
optional read-only backends) are configured in `.env`.
