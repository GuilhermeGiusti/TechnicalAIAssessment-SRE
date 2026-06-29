# Contract: CLI Interface (`agent.py`)

The agent's external contract for users. Invoked as a single command. All
non-secret parameters are flags; secrets come from `.env` / the environment.

## Invocation

```bash
python agent.py --CSV_PATH ./example.csv [options]
```

(Run from the `agent/` directory, or `python agent/agent.py --CSV_PATH ...` from
the repo root.)

## Flags (non-secret parameters)

| Flag | Required | Env fallback | Default | Purpose |
|---|---|---|---|---|
| `--CSV_PATH` | **Yes** | `CSV_PATH` | — | Path to the AWS cost export CSV (primary input). |
| `--MODEL` | No | `MODEL` | `gpt-4o` | OpenAI model id passed to `OpenAIChat`. |
| `--PERIOD` | No | `PERIOD` | derived from CSV | Analysis window, e.g. `2026-05-01:2026-05-31`. |
| `--KUBE_CONFIG_PATH` | No | `KUBE_CONFIG_PATH` | unset | **Gates** the Kubernetes capability; path to a kubeconfig. |
| `--PROMETHEUS_PATH` | No | `PROMETHEUS_PATH` | unset | **Gates** the Prometheus capability (with metrics); endpoint URL. |
| `--PROMETHEUS_METRICS` | No | `PROMETHEUS_METRICS` | unset | **Gates** the Prometheus capability; comma-separated metric list. |
| `--PROMETHEUS_LOOKBACK_DAYS` | No | `PROMETHEUS_LOOKBACK_DAYS` | `7` | Lookback window; **hard-capped at 31** regardless of value. |
| `--OUTPUT` | No | `OUTPUT` | stdout | Optional path to write the Markdown report to a file. |
| `--DEBUG` | No | `DEBUG` | off | Verbose agno/tool logging. |

**Precedence**: CLI flag > environment variable > default (FR-023).

## Secrets (NEVER flags — `.env` / environment only)

| Variable | Required for | Source |
|---|---|---|
| `OPENAI_API_KEY` | all runs (the model) | `.env` / env |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION` (or a shared profile / role) | live AWS verification | standard boto3 chain via `.env` / env |

Providing **no** AWS credentials is valid — the agent runs CSV-only (FR-009).

## Capability gating (deterministic — FR-020)

| Capability | Active when |
|---|---|
| Cost Analysis (CSV) | always (requires `--CSV_PATH`) |
| Live AWS verification | AWS credentials resolve from the standard chain |
| Kubernetes | `KUBE_CONFIG_PATH` resolves **and** cluster is reachable |
| Prometheus | `PROMETHEUS_PATH` **and** `PROMETHEUS_METRICS` resolve **and** endpoint reachable |

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Report produced successfully. |
| `2` | Usage error — `--CSV_PATH` missing or file not found (FR-022). |
| `3` | `OPENAI_API_KEY` missing (cannot construct the model). |
| `1` | Unexpected runtime error (reported clearly). |

A requested optional capability whose secret/endpoint is unavailable does **not**
fail the run — it degrades gracefully and is noted in the report (spec Edge Cases;
SC-005).

## Behavioral contract

1. `load_dotenv()` runs before anything else.
2. Missing `--CSV_PATH` → exit `2` with a clear message; no analysis starts.
3. Optional capabilities are gated per the table above; disabled ones are not
   registered as tools.
4. Output is the Markdown rendering of a `CostReport` (see `data-model.md`),
   written to stdout or `--OUTPUT`.
5. The agent performs zero mutating operations on any system (SC-003).
