# Contract: Agent Tools (read-only)

Every tool the agent can call is read-only. Reused agno toolkits are registered
with only their read functions; the three custom toolkits expose read methods
only. The generic `ShellTools` / `PythonTools` toolkits are deliberately **not**
registered.

## Reused agno toolkits

### `CsvTools` — `agno.tools.csv_toolkit`
- Constructed as `CsvTools(csvs=[csv_path])`.
- Registered functions (read-only): list CSV files, read a CSV, read column names,
  query a CSV (DuckDB `SELECT` over the file).
- Any non-read function is dropped via `exclude_tools=[...]`.

### `PandasTools` — `agno.tools.pandas`
- Constructed as `PandasTools()`.
- Used for aggregation/summarization of the cost data (group-by service, usage
  type, period). Operates on dataframes created from the read-only CSV.

## Custom read-only toolkits (to build)

Each subclasses `agno.tools.Toolkit` and registers only the methods below.

### `AwsCostTools` (gated: AWS credentials present)
| Method | Inputs | Returns | Underlying read-only call |
|---|---|---|---|
| `get_cost_and_usage` | `start: str, end: str, granularity: str, metrics: list[str], group_by: list \| None` | cost rows | `ce.get_cost_and_usage(...)` |
| `get_cost_forecast` | `start: str, end: str, granularity: str, metric: str` | forecast | `ce.get_cost_forecast(...)` |
| `list_ec2_instances` | `region: str \| None` | instance summaries | `ec2.describe_instances(...)` |
| `list_ebs_volumes` | `region: str \| None` | volume summaries (find unattached) | `ec2.describe_volumes(...)` |
| `list_s3_buckets` | — | bucket + storage-class summary | `s3.list_buckets`, `s3.get_bucket_*` |
| `list_rds_instances` | `region: str \| None` | RDS summaries | `rds.describe_db_instances(...)` |

- boto3 clients use the standard credential chain; CE client pinned to `us-east-1`.
- **No** `create_*`/`delete_*`/`modify_*`/`put_*`/`run_*` methods exist.

### `KubernetesReadTools` (gated: kubeconfig present + cluster reachable)
| Method | Inputs | Returns | Underlying read-only call |
|---|---|---|---|
| `list_nodes` | — | node capacity/allocatable | `CoreV1Api().list_node()` |
| `list_pods` | `namespace: str \| None` | pods + requests/limits | `list_namespaced_pod` / `list_pod_for_all_namespaces` |
| `list_deployments` | `namespace: str \| None` | replicas, resources | `AppsV1Api().list_namespaced_deployment` |
| `get_workload_resources` | `namespace: str \| None` | requests vs. limits gaps, missing limits | composed from the reads above |

- Loaded via `config.load_kube_config(config_file=KUBE_CONFIG_PATH)`.
- Read verbs only (`list_*`, `read_*`); backed by a read-only RBAC ServiceAccount
  (`verbs: get/list/watch`). No `create/patch/delete/replace`.

### `PrometheusTools` (gated: endpoint + metric list present + reachable)
| Method | Inputs | Returns | Underlying read-only call |
|---|---|---|---|
| `query_range` | `metric: str, lookback_days: int, step: str` | time series | `GET {base}/api/v1/query_range` |
| `list_configured_metrics` | — | the predefined `PROMETHEUS_METRICS` | local |

- Only metrics in `PROMETHEUS_METRICS` may be queried.
- `lookback_days` is clamped to **≤ 31** before any request (FR-014; SC-006).
- HTTP `GET` only — no writes; the Prometheus admin/TSDB-mutating endpoints are
  never called.

## Read-only guarantee (test contract)

`tests/test_readonly_guarantee.py` asserts, against the fully-assembled agent:
- No registered tool name matches a mutating verb
  (`create|delete|modify|put|update|patch|replace|run|exec|terminate|stop|start|write`).
- `ShellTools` and `PythonTools` are not present in the tool set.
- Building the agent with only `--CSV_PATH` registers exactly the CSV/pandas tools
  (no AWS/K8s/Prometheus), proving gating (SC-005).
