# Quickstart & Validation: Cost Analyst Agent

A run/validation guide proving the feature works end to end. Implementation
details live in `tasks.md` and the code; this is how to exercise it.

## Prerequisites

- Python 3.11+
- An OpenAI API key
- (Optional) read-only AWS credentials, a kubeconfig, and/or a Prometheus endpoint

## Setup

```bash
cd agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set at least:
#   OPENAI_API_KEY=sk-...
# optionally (for live AWS verification):
#   AWS_ACCESS_KEY_ID=...    AWS_SECRET_ACCESS_KEY=...    AWS_REGION=us-east-1
```

`.env` is git-ignored — never commit real secrets.

## Scenario 1 — CSV-only analysis (User Story 1, P1 · MVP)

The minimum demonstrable path; needs only a CSV and `OPENAI_API_KEY`.

```bash
python agent.py --CSV_PATH ./examples/example_costs.csv
```

**Expected**: a Markdown `CostReport` printed to stdout — a spend summary plus a
list of recommendations ordered by priority, **each citing evidence** from the
CSV. `capabilities_used` shows `["csv"]`. (Validates SC-001, SC-002, SC-004,
SC-007.)

## Scenario 2 — Live AWS verification (User Story 2, P2)

Add read-only AWS credentials to `.env`, then re-run the same command.

```bash
python agent.py --CSV_PATH ./examples/example_costs.csv
```

**Expected**: at least one finding is confirmed/enriched against the live account
(resource existence/state, idle indicators, or CE trend); `capabilities_used`
includes `aws_live`. No mutating calls are made. With AWS creds removed, the run
still completes CSV-only (validates SC-005, FR-009).

## Scenario 3 — Kubernetes analysis (User Story 3, P3 · gated)

```bash
python agent.py --CSV_PATH ./examples/example_costs.csv \
  --KUBE_CONFIG_PATH ~/.kube/config
```

**Expected**: when the cluster is reachable, the report adds workload findings
(missing/oversized requests/limits, over-provisioning); `capabilities_used`
includes `kubernetes`. Omit the flag → the capability is absent and no Kubernetes
tools are registered (validates FR-010).

## Scenario 4 — Prometheus correlation (User Story 4, P3 · gated)

```bash
python agent.py --CSV_PATH ./examples/example_costs.csv \
  --PROMETHEUS_PATH http://localhost:9090 \
  --PROMETHEUS_METRICS node_cpu_seconds_total,container_memory_usage_bytes \
  --PROMETHEUS_LOOKBACK_DAYS 14
```

**Expected**: rightsizing/idle findings are supported by utilization data;
`capabilities_used` includes `prometheus`. Only the listed metrics are queried.
Setting `--PROMETHEUS_LOOKBACK_DAYS 90` still queries **at most 31 days**
(validates SC-006, FR-014). Missing either Prometheus flag → capability absent
(FR-012).

## Scenario 5 — Read-only guarantee (cross-cutting)

```bash
# In an agent session, instruct it to delete/stop/modify a resource.
python agent.py --CSV_PATH ./examples/example_costs.csv
# then prompt: "terminate the idle EC2 instance"
```

**Expected**: the agent refuses and explains it is read-only (validates SC-003,
SC-008). Automated proof:

```bash
pytest tests/test_readonly_guarantee.py -q
```

## Scenario 6 — Required-input guard

```bash
python agent.py            # no --CSV_PATH
```

**Expected**: exits with code `2` and a clear error; no analysis runs (validates
FR-022).

## Test suite

```bash
pytest -q
```

Covers config/gating precedence (`test_config.py`), the 31-day clamp
(`test_prometheus_tools.py`), read-only tool shapes
(`test_aws_cost_tools.py`, `test_kubernetes_read_tools.py`), and the read-only
guarantee (`test_readonly_guarantee.py`).

## Traceability

| Scenario | User story | Success criteria |
|---|---|---|
| 1 | US1 (P1) | SC-001, SC-002, SC-004, SC-007 |
| 2 | US2 (P2) | SC-005, FR-009 |
| 3 | US3 (P3) | FR-010, FR-011 |
| 4 | US4 (P3) | SC-006, FR-012, FR-014 |
| 5 | cross-cutting | SC-003, SC-008 |
| 6 | cross-cutting | FR-022 |
