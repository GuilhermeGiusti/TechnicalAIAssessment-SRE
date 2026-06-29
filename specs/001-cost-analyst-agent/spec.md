# Feature Specification: Cost Analyst Agent

**Feature Branch**: `001-cost-analyst-agent`

**Created**: 2026-06-28

**Status**: Draft

**Input**: User description: "Cost Analyst Agent — an AWS cost-analysis agent (agno + OpenAI) that ingests an AWS cost CSV export and uses read-only tools to inspect AWS resources, Kubernetes resources, and Prometheus metrics, then produces prioritized, evidence-backed cost-reduction recommendations. Read-only by design; runnable as a CLI (`agent.py`) with all non-secret parameters as flags; Kubernetes and Prometheus capabilities are activated only when their CLI flags (or matching environment variables) are present."

## Clarifications

### Session 2026-06-28

- Q: With all parameters now passed as CLI flags, how should the optional Kubernetes and Prometheus capabilities be gated? → A: A capability activates when its CLI flag is provided OR its matching environment variable is set (CLI flag wins); it stays disabled when neither is present.
- Q: How should secrets (AWS credentials, OpenAI API key) be supplied, given that raw secrets on a command line are exposed in the process list? → A: Via a `.env` file loaded into the environment at startup — never as CLI flags; all non-secret parameters are CLI flags.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Analyze a cost export and get prioritized recommendations (Priority: P1)

An SRE exports their AWS costs to a CSV and hands the file to the agent. The agent
inspects every line item, identifies the largest cost drivers and likely sources
of waste, and returns a prioritized report of practical recommendations to reduce
spend — each one tied to the specific cost data it came from.

**Why this priority**: This is the core promise of the deliverable and the
minimum viable product. It delivers value with nothing more than a CSV file — no
live cloud access required — so it can be demonstrated by any reviewer.

**Independent Test**: Provide a representative AWS cost CSV with no AWS/Kubernetes/
Prometheus access configured. Confirm the agent returns a prioritized
recommendation report where every recommendation references a line item from the
CSV, and that it completes without error.

**Acceptance Scenarios**:

1. **Given** a valid AWS cost CSV, **When** the agent runs, **Then** it returns a
   prioritized list of cost-reduction recommendations ordered by estimated
   savings weighed against effort/risk.
2. **Given** a valid AWS cost CSV, **When** the agent produces a recommendation,
   **Then** that recommendation cites the specific line item(s) it is derived
   from.
3. **Given** a cost driver the data is insufficient to act on, **When** the agent
   reports it, **Then** it states the assumption made or flags it as needing more
   data instead of inventing a figure.

---

### User Story 2 - Verify findings against the live AWS account (Priority: P2)

With read-only AWS credentials available, the agent confirms its CSV-derived
findings against the live account — checking that flagged resources still exist,
whether they appear idle/obsolete, and how service-level cost trends are moving —
so recommendations reflect current reality rather than a stale export.

**Why this priority**: Live verification raises recommendation confidence and
catches resources that were deleted or changed since the export, but the agent is
still useful without it (US1). It builds directly on US1.

**Independent Test**: Run the agent with a CSV plus read-only AWS credentials.
Confirm at least one CSV finding is enriched or confirmed/refuted using live
account data, and that the run performs no mutating operations.

**Acceptance Scenarios**:

1. **Given** read-only AWS credentials, **When** the agent verifies a flagged
   resource, **Then** it reports whether the resource still exists and its
   current state using read-only calls only.
2. **Given** no AWS credentials are configured, **When** the agent runs, **Then**
   it degrades gracefully to CSV-only analysis without failing.
3. **Given** any input or instruction, **When** the agent operates on AWS,
   **Then** it performs only read/describe/list operations and never a mutating
   one.

---

### User Story 3 - Detect Kubernetes resource waste (Priority: P3, conditional)

When a reachable cluster configuration is provided, the agent inspects the
cluster's resources read-only and flags misconfigurations and workloads
requesting or consuming excessive resources, adding workload-level waste to the
cost picture.

**Why this priority**: Valuable for teams running on Kubernetes, but optional and
fully gated — many environments won't supply cluster access, and the agent must
remain useful without it.

**Independent Test**: With the Kubernetes capability's environment variable set to
a reachable cluster, confirm the agent inspects cluster resources read-only and
reports at least one misconfiguration or over-provisioning finding. With the
variable unset, confirm the capability is not offered at all.

**Acceptance Scenarios**:

1. **Given** the Kubernetes gating variable is set and the cluster is reachable,
   **When** the agent starts, **Then** the Kubernetes capability is available.
2. **Given** the Kubernetes gating variable is not set, **When** the agent
   starts, **Then** the Kubernetes capability is unavailable and its tools are
   not registered.
3. **Given** the capability is active, **When** the agent inspects the cluster,
   **Then** it uses read-only access and flags misconfigurations or excessive
   resource requests/usage.

---

### User Story 4 - Correlate cost with Prometheus utilization (Priority: P3, conditional)

When a reachable Prometheus endpoint and a predefined metric list are provided,
the agent collects those metrics over an agent-chosen time window (never more
than 31 days) and uses real utilization evidence to strengthen rightsizing and
idle-resource recommendations.

**Why this priority**: Utilization data makes rightsizing recommendations far more
credible, but it is optional, gated, and bounded to control token/query cost.

**Independent Test**: With the Prometheus endpoint and metric-list variables set,
confirm the agent collects only the named metrics over a window of at most 31
days. With either variable unset, confirm the capability is not offered.

**Acceptance Scenarios**:

1. **Given** both Prometheus gating variables are set and the endpoint is
   reachable, **When** the agent starts, **Then** the Prometheus capability is
   available.
2. **Given** either Prometheus gating variable is missing, **When** the agent
   starts, **Then** the Prometheus capability is unavailable and its tools are
   not registered.
3. **Given** the capability is active, **When** the agent queries metrics,
   **Then** it requests only the predefined metrics and never a window longer
   than 31 days.

---

### Edge Cases

- **Empty or malformed CSV**: the agent reports the problem clearly and does not
  fabricate findings.
- **Unexpected CSV schema** (missing or differently named columns): the agent
  adapts to common variations or states which expected fields are missing.
- **AWS credentials present but lacking read permission, or API throttling**: the
  agent reports the limitation and falls back to CSV-only findings for affected
  checks.
- **Cluster config set but unreachable**: the Kubernetes capability reports it
  cannot connect rather than crashing the run.
- **Prometheus reachable but a metric name is invalid or returns no data**: the
  agent records "no data" for that metric and continues.
- **Requested lookback exceeds 31 days**: the request is clamped to 31 days (or
  refused) — never exceeded.
- **User asks the agent to stop/terminate/delete/modify a resource**: the agent
  refuses and explains it is read-only, regardless of who asks.
- **Conflicting evidence** (CSV shows spend on a resource the live account says no
  longer exists): the agent surfaces the conflict instead of silently picking one
  side.
- **Very large CSV**: the agent summarizes/aggregates rather than attempting to
  reason over every raw row, and notes if any data was sampled or truncated.
- **Required input missing**: if `--CSV_PATH` is not supplied, the agent exits
  immediately with a clear error and does not start an analysis.
- **Secret missing for an active capability**: if a capability is requested but
  its required secret is absent from the `.env`/environment (e.g. AWS credentials
  for live verification), the agent reports the missing secret and degrades that
  capability gracefully rather than crashing.

## Requirements *(mandatory)*

### Functional Requirements

**Core cost analysis (US1)**

- **FR-001**: The agent MUST accept an AWS cost export CSV as its primary input
  and inspect every line item in it.
- **FR-002**: The agent MUST aggregate and summarize the cost data (e.g. by
  service, resource, usage type, and period) to surface the largest cost drivers.
- **FR-003**: The agent MUST identify likely waste, covering at least:
  rightsizing/over-provisioning, unused or obsolete resources, scaling-policy
  inefficiency, storage optimization, and reserved/committed-capacity
  opportunities, as well as anomalous service-level cost trends.
- **FR-004**: The agent MUST output a prioritized list of practical
  recommendations, ranked by estimated savings weighed against implementation
  effort and risk.
- **FR-005**: Every recommendation MUST cite the specific evidence (cost line
  item(s) and/or verified resource state) it is derived from.
- **FR-006**: When data is insufficient to support a conclusion, the agent MUST
  state the assumption it made or flag the item as needing more data, and MUST
  NOT fabricate resources, prices, or savings figures.
- **FR-007**: The agent MUST clearly label estimated savings as estimates.

**Live AWS verification (US2)**

- **FR-008**: When read-only AWS access is available, the agent MUST be able to
  verify candidate findings against the live account (resource existence, current
  state, idle indicators, and service-level cost trends).
- **FR-009**: When AWS access is not configured, the agent MUST degrade
  gracefully to CSV-only analysis without failing.

**Conditional Kubernetes capability (US3)**

- **FR-010**: The agent MUST enable the Kubernetes capability only when its
  cluster-config path is provided — via the `--KUBE_CONFIG_PATH` CLI flag or the
  `KUBE_CONFIG_PATH` environment variable (CLI flag takes precedence) — and the
  cluster is reachable; otherwise the capability's tools MUST NOT be registered.
- **FR-011**: When active, the Kubernetes capability MUST inspect cluster
  resources read-only and flag misconfigurations and workloads requesting or
  consuming excessive resources.

**Conditional Prometheus capability (US4)**

- **FR-012**: The agent MUST enable the Prometheus capability only when both an
  endpoint and a predefined metric list are provided — via the `--PROMETHEUS_PATH`
  and `--PROMETHEUS_METRICS` CLI flags or the matching `PROMETHEUS_PATH` and
  `PROMETHEUS_METRICS` environment variables (CLI flags take precedence) — and the
  endpoint is reachable; otherwise the capability's tools MUST NOT be registered.
- **FR-013**: When active, the Prometheus capability MUST collect only the
  predefined metrics it was given (supplied as a comma-separated list) over a
  time window chosen by the agent.
- **FR-014**: The Prometheus lookback window MUST never exceed 31 days; any
  longer request MUST be clamped or refused.

**Safety & read-only guarantee (cross-cutting)**

- **FR-015**: The agent MUST NEVER perform any write/create/update/delete or
  otherwise state-changing operation on any system, regardless of who requests it
  or how the request is phrased.
- **FR-016**: Every tool available to the agent MUST expose read-only operations
  only; no mutating capability may exist in the tool surface.
- **FR-017**: The agent MUST NOT be granted arbitrary command or code execution
  capabilities (no general-purpose shell/script execution).
- **FR-018**: The read-only guarantee MUST be enforced in depth — by external
  controls (read-only cloud permissions and read-only cluster access) in addition
  to the tool surface being read-only.

**Operational behavior (cross-cutting)**

- **FR-019**: Capabilities MUST be loaded on demand (only when needed) rather
  than all upfront, to conserve tokens and keep the active tool surface minimal.
- **FR-020**: The agent MUST behave deterministically with respect to gating: the
  same configuration MUST always yield the same set of available capabilities.

**Invocation & configuration (CLI)**

- **FR-021**: The agent MUST be runnable as a command-line program with the entry
  point `agent.py`, started by a single command (e.g.
  `python agent.py --CSV_PATH ./example.csv`).
- **FR-022**: All non-secret parameters MUST be configurable as CLI flags. The
  cost-CSV path (`--CSV_PATH`) MUST be required; if it is absent the agent MUST
  exit with a clear error message rather than proceeding.
- **FR-023**: For any parameter exposed both as a CLI flag and an environment
  variable, the CLI flag MUST take precedence and the environment variable MUST
  act as a fallback; this same precedence governs capability gating (FR-010,
  FR-012).
- **FR-024**: Secrets — AWS credentials and the OpenAI API key — MUST be supplied
  through a `.env` file / the environment and MUST NOT be accepted as CLI flags,
  so they are never exposed in the process list or shell history.

### Key Entities *(include if feature involves data)*

- **AWS Cost Export**: the input CSV of cost line items; each item carries at
  least a service, an associated resource/usage descriptor, a cost amount, and a
  time period.
- **Waste Finding**: a detected inefficiency — its category (rightsizing, unused/
  obsolete, scaling, storage, reserved-capacity, trend), the affected
  resource/service, the supporting evidence, an estimated savings, and a
  confidence level.
- **Recommendation**: an actionable proposal derived from one or more findings —
  the suggested action, its rationale, estimated savings, effort, risk, and
  resulting priority.
- **Capability (Skill)**: a gated, on-demand bundle of read-only tools (Cost
  Analysis, Kubernetes, Prometheus) with explicit activation conditions.
- **Cost Report**: the final, prioritized, evidence-backed output presented to the
  operator.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Given a representative AWS cost CSV, the agent produces a
  prioritized recommendation report in a single run with no manual intervention.
- **SC-002**: 100% of recommendations reference at least one concrete piece of
  evidence from the inputs; there are zero unsourced claims.
- **SC-003**: Across all runs and all instructions, the agent performs zero
  mutating operations on any system — the read-only guarantee holds 100% of the
  time.
- **SC-004**: A reviewer can identify the top three savings opportunities from the
  report in under one minute, because recommendations are ordered by
  savings-vs-effort.
- **SC-005**: With AWS credentials, cluster config, and Prometheus config all
  absent, the agent still completes CSV-only analysis without error, and no
  inactive capability is offered.
- **SC-006**: The Prometheus capability never requests more than 31 days of data
  in any query.
- **SC-007**: For every waste category present in the input among rightsizing,
  unused/obsolete resources, scaling policies, storage optimization, and
  reserved-capacity opportunities, the report surfaces at least one corresponding
  finding when one exists.
- **SC-008**: When asked to perform a destructive or state-changing action, the
  agent refuses 100% of the time and explains its read-only constraint.
- **SC-009**: The agent can be launched for any combination of capabilities using
  a single command line for all non-secret options, with secrets read from a
  `.env` file; launching with only `--CSV_PATH` succeeds and runs CSV-only
  analysis.

## Assumptions

- The AWS cost CSV follows a standard AWS export shape (Cost Explorer / Cost &
  Usage Report style) containing at least service, cost, usage, and period
  fields; the agent adapts to common column variations.
- The output is a human-readable, structured report (e.g. Markdown) with a
  prioritized recommendations table, consumed by an SRE/engineer.
- The analysis time period is derived from the CSV's date range or specified by
  the operator at run time.
- Estimated savings are approximate, derived from observed spend and standard
  pricing heuristics, and are always labeled as estimates.
- Read-only cloud permissions (a read-only IAM policy) and read-only cluster
  access (a read-only ServiceAccount/RBAC) are provisioned out-of-band by the
  operator; the agent assumes but does not create them.
- Scope is a single AWS account for the initial version; multi-account analysis is
  only considered insofar as it appears in the provided CSV.
- **Implementation constraints (pre-decided by the project constitution, recorded
  here for traceability)**: the agent is built on the agno framework using an
  OpenAI model; it uses native agno tools rather than MCP servers at this stage;
  existing agno CSV/data tools are reused for ingestion while read-only AWS,
  Kubernetes, and Prometheus toolkits are purpose-built; general-purpose shell/
  script execution tools are deliberately excluded. These bind the planning phase,
  not the behavior described above.
- **Invocation**: the agent ships as a CLI entry point `agent.py`; non-secret
  parameters are CLI flags (with environment-variable fallback) and secrets are
  loaded from a `.env` file. The report is written to standard output by default.

## Out of Scope

- Any write, create, update, or delete operation on any system.
- MCP-based integrations (native agno tools are used at this stage).
- Automated remediation: the agent recommends, a human acts.
- Provisioning the read-only permissions/RBAC the agent relies on.
