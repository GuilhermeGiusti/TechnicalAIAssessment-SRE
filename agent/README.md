# Cost Analyst Agent

A read-only AWS **cost optimization agent** built on [agno](https://www.agno.com/)
with an OpenAI model. It ingests an AWS cost CSV export, inspects it (and,
optionally, the live AWS account, a Kubernetes cluster, and Prometheus), and
produces a prioritized, **evidence-backed** report of cost-reduction
recommendations.

> **Read-only by design.** Every tool the agent can call performs read/describe/
> list operations only. It never creates, modifies, deletes, stops, or starts
> anything — it recommends; a human acts.

Spec, plan, and contracts: [`../specs/001-cost-analyst-agent/`](../specs/001-cost-analyst-agent/).

## Install

```bash
cd agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Configure secrets (`.env`)

Secrets are read from a `.env` file — **never** passed as CLI flags (so they
can't leak into your shell history or the process list).

```bash
cp .env.example .env
# edit .env:
#   OPENAI_API_KEY=sk-...                      # required
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY  # optional (live AWS verification)
#   AWS_REGION=us-east-1
```

`.env` is git-ignored.

## Run

```bash
# MVP — CSV only (no cloud access needed):
python agent.py --CSV_PATH ./examples/example_costs.csv

# + live read-only AWS verification (AWS creds in .env):
python agent.py --CSV_PATH ./examples/example_costs.csv

# + Kubernetes (gated on the flag/env being set and reachable):
python agent.py --CSV_PATH ./examples/example_costs.csv \
  --KUBE_CONFIG_PATH ~/.kube/config

# + Prometheus (needs both URL and metric list; lookback capped at 31 days):
python agent.py --CSV_PATH ./examples/example_costs.csv \
  --PROMETHEUS_PATH http://localhost:9090 \
  --PROMETHEUS_METRICS node_cpu_seconds_total,container_memory_usage_bytes \
  --PROMETHEUS_LOOKBACK_DAYS 14

# write the report to a file instead of stdout:
python agent.py --CSV_PATH ./examples/example_costs.csv --OUTPUT report.md
```

Run `python agent.py --help` for all flags. Precedence for every non-secret
option is **CLI flag > environment variable > default**.

| Flag | Required | Gates | Default |
|---|---|---|---|
| `--CSV_PATH` | yes | — | — |
| `--MODEL` | no | — | `gpt-4o` |
| `--PERIOD` | no | — | derived from CSV |
| `--KUBE_CONFIG_PATH` | no | Kubernetes | unset |
| `--PROMETHEUS_PATH` + `--PROMETHEUS_METRICS` | no | Prometheus | unset |
| `--PROMETHEUS_LOOKBACK_DAYS` | no | — | 7 (max 31) |
| `--OUTPUT` | no | — | stdout |
| `--DEBUG` | no | — | off |

Exit codes: `0` ok · `2` missing/invalid `--CSV_PATH` · `3` missing
`OPENAI_API_KEY` · `1` runtime error.

## Required IAM / RBAC (read-only, provisioned out of band)

The agent assumes — but does not create — least-privilege read-only access:

- **AWS**: a read-only IAM principal. Attaching the AWS managed policies
  `ReadOnlyAccess` and `AWSBillingReadOnlyAccess` is sufficient (Cost Explorer
  requires IAM access to Billing to be activated on the account). Minimum
  actions: `ce:GetCostAndUsage`, `ce:GetCostForecast`, `ec2:Describe*`,
  `s3:ListAllMyBuckets`, `rds:Describe*`.
- **Kubernetes**: a ServiceAccount bound to a (Cluster)Role whose rules use only
  `verbs: ["get", "list", "watch"]`.
- **Prometheus**: only the HTTP query API is used (`GET /api/v1/query_range`).

These external controls are defense-in-depth on top of the code being read-only.

## Architecture

```
agent.py                     CLI entry: load .env → parse flags → build agent → run
cost_analyst/
  config.py                  flag/env resolution, gating, the 31-day clamp
  agent_factory.py           builds the agno Agent + conditional read-only tool list
  persona.py                 system instructions (per active capability)
  models.py                  Pydantic CostReport output schema (enforces evidence)
  tools/
    aws_cost_tools.py        read-only Cost Explorer + describe/list (boto3)
    kubernetes_read_tools.py read-only cluster inspection (kubernetes client)
    prometheus_tools.py      read-only query_range, metric allow-list, 31-day cap
examples/example_costs.csv   fictitious sample cost export
tests/                       pytest suite (config/gating, clamp, read-only guarantee)
```

Reused agno toolkits: `CsvTools`, `PandasTools`. Custom read-only toolkits:
`AwsCostTools`, `KubernetesReadTools`, `PrometheusTools`. The generic
`ShellTools`/`PythonTools` are deliberately **not** registered.

## Tests

```bash
pytest          # from the agent/ directory
```

Covers CLI>env precedence and required input, capability gating, the Prometheus
31-day clamp and metric allow-list, read-only tool shapes, and a **read-only
guarantee** test asserting no mutating tool is ever registered.
