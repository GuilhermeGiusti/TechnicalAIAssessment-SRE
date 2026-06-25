# Architecture & Operations Proposal

Technical AI Assessment — Senior Site Reliability Engineer, MetaCTO.

---

## 1. Context and Assumptions

### Product
The SaaS being modeled is a **video-on-demand (VOD) streaming platform** in the style of Netflix or Prime Video. VOD only — no live streaming. Single-tenant, B2C, global scale.

### Clients
- **Primary:** mobile and Smart TV applications.
- **Secondary:** web application.

This ordering matters for later decisions: client-side telemetry, CDN strategy, and release cadence are biased toward the mobile and TV experience.

### Region strategy — single-region in `us-east-1`
The platform runs in a **single AWS region (`us-east-1`) by deliberate choice**. A multi-region posture — Aurora Global Database, replicated Cognito user pools, DynamoDB Global Tables, cross-region S3 replication — would clearly be more robust, but the operational and financial cost does not pay back at the current stage.

This is stated explicitly as a trade-off: **unavailability during a full regional outage is the accepted price** of running single-region. Mitigations (CDN-served catalog and playback assets, graceful client-side degradation) are discussed in later sections; an actual regional failover is out of scope.

### Cloud and vendor lock-in principle
Everything runs on **AWS**, and **AWS lock-in is accepted as the default**. The guiding principle is cost, not portability: **open-source software is self-hosted only where it is cheaper than the managed AWS equivalent at this scale** — most visibly the observability stack (§3). Everywhere else, managed AWS services (SQS/SNS, SES, Cognito, Secrets Manager) are preferred, because self-managing a commodity layer adds operational burden without differentiating the product.

The **data layer** follows the same honest line: Aurora (PostgreSQL-compatible) and ElastiCache (Redis-compatible) keep portable semantics, and catalog search uses PostgreSQL `tsvector` (§2.8) rather than a separate engine — but **DynamoDB and Aurora Serverless v2 are deliberate, accepted lock-in**, chosen for AP-scale and managed operations, not portability.

### Cluster-wide HA pattern (stated once)
A single high-availability pattern applies to **every control-plane component running in the EKS cluster** and is not repeated in subsequent sections:

> Each control-plane component runs with **extra replicas** and pod `antiAffinity` rules that spread replicas **across nodes and Availability Zones**.

Where a later section discusses a component without restating this, the pattern is implied.

### Scope
This document covers **exactly the five deliverables required by the assessment PDF**:

1. Assumed AWS architecture (§2).
2. Monitoring and observability strategy (§3).
3. Alerting and escalation strategy (§4).
4. Cost optimization (§5).
5. Consolidated tradeoffs and assumptions (§6).

---

## 2. Assumed AWS Architecture

### 2.1 Networking and routing

**VPC layout**

A single VPC in `us-east-1`, CIDR `10.0.0.0/16`, distributed across three Availability Zones. Three subnet tiers per AZ:

- **Public subnet** — hosts only the NAT Gateway. No workloads.
- **Workload private subnet** (`/20`) — EKS nodes, ElastiCache, and the internal NLB.
- **Database isolated subnet** — Aurora subnet group and the ENIs for VPC Interface Endpoints.

**NAT Gateway — one per Availability Zone**

A NAT Gateway is provisioned **per AZ** (one in each AZ's public subnet), so losing any single AZ does not take platform egress with it — this is what makes the cross-AZ HA pattern from §1 real rather than nominal. Two points keep the decision honest:

- **Egress through the NAT is small to begin with.** Client-facing traffic — video, manifests, API responses — leaves via CloudFront/S3 and API Gateway, *not* the NAT. The NAT carries only outbound-to-internet from private subnets (third-party APIs, package pulls, webhooks), and the VPC Endpoints adopted here — **Gateway endpoints for S3 and DynamoDB**, **Interface endpoints for SQS, SNS, KMS, ECR and STS** — keep traffic to AWS services off it entirely.
- **Per-AZ NATs are typically cost-neutral or cheaper.** Each NAT adds a fixed hourly charge, but a single shared NAT forces the other AZs' egress across an AZ boundary at $0.01/GB; keeping egress in-AZ removes that cross-AZ tax, so the redundancy is effectively free at any real volume.

**Request path — no ALB exposed**

There is no public ALB anywhere in the architecture. Two paths exist, both fronted by CloudFront:

```
Client -> CloudFront -> ( /*    ) -> S3 (static frontend)
Client -> CloudFront -> ( /api/*) -> API Gateway -> VPC Link -> internal NLB (private subnet) -> nginx ingress -> EKS services
```

The frontend is **purely static in S3**, with no compute at the edge. The backend is only reachable through API Gateway, which enters the VPC via a VPC Link terminating on an **internal** NLB. That NLB never has a public IP.

**CloudFront**

Path-based behaviors in priority order:

1. `/api/*` → API Gateway.
2. `/*`    → S3 frontend bucket.

CloudFront was chosen over Cloudflare for practicality and acceptable cost. A side benefit: the web app and the API live under the same domain, so **CORS stops being a problem**.

**API Gateway**

AWS API Gateway is used directly. The features that matter here:

- Per-API-key rate limiting.
- Integrated authorizers.
- CloudWatch access logs.
- Native versioning and deploy history.

### 2.2 Cluster

**Two EKS clusters, both in `us-east-1`: a `prod` cluster for the workloads and a dedicated `ops` cluster.** ECS was evaluated and dropped: cheaper, but constrained on autoscaling, event-driven patterns and observability. EKS is accepted as **soft lock-in** — paid back through managed upgrades, AWS-validated add-ons, and the Kubernetes ecosystem on top, which is portable.

The **`ops` cluster** hosts everything that must *not* sit inside the blast radius of the workloads it serves: the observability stack (§3), the synthetic probes (§3.6), **ArgoCD** (GitOps for both clusters), and the self-hosted GitHub Actions runners. It runs in a **separate AWS account** for IAM, quota and billing isolation, connected to `prod` over PrivateLink. This is the structural form of the rule stated in §4.2 — *the tool that tells you the house is on fire cannot live inside the house* — applied not only to paging but to the eyes (observability), the hands (ArgoCD) and the smoke detectors (probes).

Because the `ops` cluster is now high-value infrastructure, it carries the same §1 HA pattern (multi-AZ) and one signal that depends on neither cluster: a **dead-man's-switch heartbeat to PagerDuty** — if the heartbeat stops, PagerDuty pages, which is how an `ops`-cluster failure surfaces when nothing inside it can report. Its GitHub Actions runners scale to zero on Spot so an idle fleet never bleeds cost (§5).

**Nodegroups (`prod`)** — segregated by workload profile, using taints/tolerations and `nodeSelector`s:

- `system` — kube-system, ingress, the forwarding OTel collector.
- `app-stateless` — APIs and workers. **Spot + Graviton.**
- `app-stateful` — bridges and sidecars that need stability.

The `ops` cluster runs its own nodegroups — `platform` (high-memory observability) and `ci` (Spot, scale-to-zero runners).

**Single-cluster failure boundary — mitigations as part of the decision.** A single cluster is a single failure boundary. These mitigations are declared up front, not in an appendix:

1. `ResourceQuota` and `LimitRange` per namespace.
2. `NetworkPolicy` **default-deny** with explicit allow rules.
3. Namespace-scoped RBAC with dedicated `ServiceAccount` + **IRSA**.
4. `PodDisruptionBudget`s on Istio, KEDA, External Secrets Operator and the OTel collector.
5. A **staging mirror cluster** at reduced scale, used to validate every platform change before prod.
6. An add-on **admission process** — no random Helm chart installs.
7. **etcd hygiene** — Job TTL, active GC, alert on usage > 70%.
8. **Cluster Autoscaler** tuning the nodegroups.

On the last point: **Karpenter** was evaluated for better bin packing and mixed instance type support, but is **not adopted, due to the team's lack of operational experience with it**. The intent is not to recommend a component the team has never operated in production.

### 2.3 Service mesh

**Istio in ambient mode** (GA since 2024).

Justification — lower overhead: no sidecar per pod, native L4 mTLS via **ztunnel**, and L7 features (granular authorization, plugins) available through a **Waypoint Proxy** enabled per workload as needed.

**Trade-off (declared):** ambient is newer than sidecar and the troubleshooting stack has nuances. **Plan B is within the same product** — the same Istio install supports sidecar mode in selected namespaces via label, so the escape, if needed, does not require swapping vendors.

### 2.4 Ingress

**nginx ingress** inside the cluster, behind the VPC Link's internal NLB. Access logs are emitted in **JSON** (no regex parsing downstream) and shipped **directly to the OpenTelemetry Collector**. No broker in the middle, no custom metrics application.

### 2.5 Autoscaling

**KEDA** for scaling on SQS queue depth, custom metrics, and DB queries. HA per the cluster-wide pattern stated in §1.

### 2.6 Auth

**Cognito** with federated login (Meta, Google, Apple). Cognito groups mapped to IAM policies. Lock-in is accepted here: identity is a commodity layer, migration cost is high anywhere, and Cognito + federated IdPs still preserves the escape via OIDC/SAML.

### 2.7 Secrets and config

AWS-native stack:

- **Secrets Manager** — sensitive credentials, with **native rotation for RDS**.
- **SSM Parameter Store SecureString** — sensitive config without auto-rotation.
- **ConfigMaps via GitOps** — non-sensitive config.
- **IRSA** — pod → AWS authentication without persisted credentials.
- **External Secrets Operator** — syncs Secrets Manager into native Kubernetes Secrets.

**Consul and Vault** were considered as alternatives to reduce lock-in, but dropped: the operational cost — Raft quorum, consistent backup, custom rotation, internal certs — does not pay back when the rest of the stack already accepts AWS lock-in at several points.

### 2.8 Data layer

**Different data classes have different CAP profiles, and the platform uses different stores for different classes** — picked by the need of each. The trap to avoid is declaring "A+P" at the top of the section and then contradicting it in the store actually chosen.

**CP — Aurora Serverless v2.** Data that does not tolerate split-brain:

- Billing, subscriptions, payments.
- Identity / auth state (also touches Cognito).
- Canonical catalog — the editorial source of truth, and the source of events for read models.

**AP — DynamoDB.** Data that needs availability and partition tolerance:

- Read catalog.
- Watch history and progress — **last-write-wins by client timestamp**, the streaming standard.
- Recommendations.
- View events — append-only, eventual loss is acceptable.
- Session state.

**Hot cache and ephemeral session — ElastiCache Redis (cluster mode).** Manifests, active profiles, short-lived session state.

**Media — S3 + CloudFront.** Segments, manifests, thumbnails. **Immutable after publish.**

**Catalog search — Aurora full-text search via `tsvector`.** No OpenSearch: it does not justify the cost or operational overhead at current scale.

Read models are fed via **SNS + SQS**, which decouples read load from the transactional writer.

**Trade-off (declared):** polyglot persistence costs operational complexity and team skill, but the alternative — forcing everything into one store — either under-scales or over-consistencies. The cost is worth it.

### 2.9 Messaging, events and email

**SNS + SQS as the only messaging backbone.** RabbitMQ, MSK and Kafka were evaluated and not adopted: they add operational burden without proportional gain at current scale.

**Outbox pattern in every service publishing events.** Implementation via a **polling worker, not CDC**. The flow is drawn explicitly:

```
1. Service writes in an atomic transaction:
   INSERT into the business aggregate
   INSERT into outbox (event_type, payload, published_at=NULL)
   COMMIT

2. Service-owned worker (same deployment or sidecar) loops:
   SELECT * FROM outbox WHERE published_at IS NULL
     LIMIT 100 FOR UPDATE SKIP LOCKED
   → publishes each to the matching SNS topic
   → UPDATE outbox SET published_at = NOW() WHERE id IN (...)
   → sleep 1-2s

3. Consumers via SQS subscribed to the SNS topic.
```

Idempotency lives in the consumer (SNS is at-least-once by default). `FOR UPDATE SKIP LOCKED` enables parallelism across worker replicas.

**Benefits worth registering:**

- Transactional consistency without the dual-write problem.
- The `outbox` table becomes a **native audit trail** — queryable by SQL ("was this event emitted?" answered with a `SELECT`).
- **Manual replay** by resetting `published_at`.
- Traceability becomes trivial.

**Trade-off vs CDC (Debezium + Kafka + MSK):**

- 1–2 s commit → SNS latency is acceptable for all current events.
- Infrastructure cost is ~$0 incremental.
- Operation is a simple worker with SQL-based debug.
- Manual replay is acceptable.

**Revision criteria — when CDC gets reconsidered:**

- The outbox `SELECT` shows up in Aurora's slow queries.
- 1–2 s commit → publish latency becomes a product requirement.
- Sustained volume crosses **~5k events/sec**.

These criteria are listed because the decision is conscious and has a clear exit.

**Transactional email — SES.** Default path. Delivery events (sent, bounce, complaint, open) are published to SNS topics → SQS → handler that updates the bounce list, fires reputation alerts, and updates user state. **Configuration sets per domain.** Reputation monitoring via SES dashboards.

### 2.10 Media delivery

Videos are hosted in **S3** and delivered via **CloudFront with per-session signed cookies**. The web app (static in S3 + CloudFront, plus API Gateway for metadata and auth) covers catalog, player and the authorization flow.

**The media production pipeline — ingest, transcoding, packaging, DRM — is the product/content team's responsibility and out of scope for this proposal.** This document is about SRE operations, not media engineering.

### 2.11 Perimeter security

Three layers:

**AWS WAF v2** attached to CloudFront — edge blocking, before API Gateway:

- AWS Managed Rule Groups: **Core/OWASP top 10**, **Known Bad Inputs**, **Amazon IP Reputation**.
- Custom rule for **rate limiting at 2000 req / 5 min per IP**.

**AWS Shield Standard** is auto-included at no cost — basic volumetric DDoS coverage. **Shield Advanced is not adopted**: ~$3k/month plus extras does not justify without a history of large-scale attacks.

**GuardDuty** enabled account-wide. Findings are published to SNS → SQS → a handler that classifies severity and triggers the alerting pipeline at the right severity — credential exposure, crypto mining, DNS exfiltration, anomalous RDS access. Cost is reasonable and it catches incident classes that application monitoring would never see.

### 2.12 DNS

**Route 53** as hosted zone manager. **Alias records** pointing to the CloudFront distribution. TLS certificates via **ACM in `us-east-1`** (CloudFront requirement), auto-renewed.

**Route 53 health checks and latency-based routing are not used** — they do not apply to the single-region profile. Stated explicitly to make clear the decision not to use them is conscious, not an omission.

### 2.13 Backup and recovery

Strategy per component, no invented complexity:

- **Aurora Serverless v2** — continuous PITR (point-in-time recovery) + daily snapshots, **30-day retention**.
- **DynamoDB** — PITR enabled on every table (**35 days**).
- **Critical S3 buckets** (configs, audit, packaged media) — versioning + lifecycle policies driven by a retention tag.
- **Secrets Manager** — native version rollback (30 days).
- **EKS resources** — stateless, rebuilt from Terraform + GitOps (**ArgoCD**, running in the `ops` cluster — §2.2).

**Quarterly restore drill for Aurora in staging.** This is not "having backups" — it is **proving the restore works**, with the time measured and the runbook followed line by line. A failed drill produces a runbook fix and a re-drill. Without that loop, "backup" is an assumption, not a capability.

**Trade-off (declared):** no cross-region replication, consistent with the single-region choice from §1. The RPO/RTO above are valid for **local failures** — logical corruption, accidental deletes, AZ failure — **not** for a full regional outage.

### 2.14 Infrastructure as Code

Everything is provisioned via **Terraform**, chosen over AWS CDK for lower vendor lock-in and a broader module ecosystem.

**State management** — dedicated S3 bucket per environment, with versioning; encryption-at-rest via per-environment KMS CMK; DynamoDB-based lock to prevent concurrent applies.

**Organization** — mono-repo `infra/`:

- `platform/` — cluster, observability, network.
- `services/<name>/` — resources specific to each service.
- Per-environment directories (`prod/`, `staging/`, `dev/`) using the same modules with different variables.
- Shared modules: `modules/eks-cluster`, `modules/observability-stack`, `modules/service-base` (encapsulating Deployment + ServiceAccount + IRSA + Secret consumption).

**PR workflow:**

1. PR on GitHub.
2. **Atlantis** runs `terraform plan`, `fmt` and `tflint`.
3. **Infracost** estimates the plan's cost variation and comments on the PR.
4. Peer review covers both the technical change **and the cost impact** (visible before merge).
5. `atlantis apply` to staging via approval comment.
6. Prod requires a separate approval (second reviewer).

**The Infracost step is the direct hand-off to §5 (Cost Optimization):** every platform change carries the estimated price of the change **in the PR itself**. The engineer sees the cost before merging, the team discusses cost in review, no one is surprised by the monthly bill. Cost stops being a post-hoc finding and becomes part of code review.

**Tagging policy** — the module wrapper enforces mandatory tags on every resource creation: `Environment`, `Service`, `Owner`, `CostCenter`, `ManagedBy=terraform`, `Lifecycle`. A resource without tags **fails the plan**.

**Drift detection** — weekly scheduled `terraform plan` in GitHub Actions; any detected drift opens an issue with the diff.

---

## 3. Monitoring and Observability Strategy

A distinction adopted up front: **monitoring is knowing about what we already know; observability is discovering what we don't yet know.** Both legs live in the same stack, but their goals differ. Stating it here avoids the trap of buying tools without criteria.

### 3.1 Stack — self-hosted, unified on S3

Three pillars, one storage foundation, all running in the dedicated **`ops` cluster** (§2.2) — never in `prod`:

- **Metrics** — **VictoriaMetrics** in cluster mode. Hot EBS for recent data, long-term in **S3 via `vmstorage`**.
- **Traces** — **Grafana Tempo**, S3 backend.
- **Logs** — **Grafana Loki**, S3 backend.
- **Visualization** — **Grafana OSS**, running in the `ops` cluster.
- **Ingestion** — a per-cluster **OpenTelemetry Collector**; `prod`'s collector forwards to the backends in `ops` over PrivateLink, so a `prod` outage never takes the telemetry path down with it.

**Grafana Cloud is not adopted.** Combining a self-hosted Grafana stack with a paid Grafana Cloud subscription would mean paying twice for the same service. Stated explicitly because it is a common anti-pattern.

**Trade-off (declared) on Tempo:** exploratory free-form trace search is more limited than alternatives. Accepted, because the real debugging workflow arrives via **log → `trace_id`**, rarely via free-form search.

### 3.2 Ingestion pipeline

OpenTelemetry Collector as the single entrypoint, with:

- `filelog` receiver reading the nginx access log (JSON, no regex parsing).
- `transform` processor extracting `status`, `request_time`, `path`, `method`.
- `logstometrics` connector converting log events into metrics (status code counter, latency histogram).
- **Parallel exporters** — Loki (raw logs), VictoriaMetrics (derived metrics via `remote_write`), Tempo (traces via OTLP).

**Trace sampling — tail sampling at the OTel collector:**

- 100% of error traces.
- 100% of traces above the journey SLO's p99 latency.
- 100% of synthetic probe traces (defined in §4).
- **1% sample of normal traffic.**

### 3.3 Grafana governance

- **SSO via OIDC** (Cognito or corporate IdP).
- **RBAC per folder / organization.**
- **Dashboards versioned as YAML** via the Grafana Operator — **no free editing in prod**.
- **Integrated alerting**, rules versioned in the same repository.

### 3.4 Declared lock-in

Grafana Labs remains the tooling provider (open source), **without subscription**. The whole observability stack is portable off AWS, with the single exception of **S3** — which is commodity object storage, replaceable by another object store with a configuration change.

### 3.5 SLOs and error budget

> *Honest note recorded here for transparency: calibrating SLOs and burn-rate thresholds for a VOD workload required going back to the **Site Reliability Engineering** book (O'Reilly / Google) and researching streaming-specific metrics. Deciding what to measure in VOD is not trivial if the only mental reference is a traditional web app.*

**Alerting without SLOs degenerates into noise.** Without SLOs, every red chart triggers the same debate — *"is this actually a problem?"* — and in three months oncall stops looking. That is precisely the assignment's point when it says **"alerting is inconsistent"**.

The ruler: **7 SLOs centered on user journeys, not infrastructure.** No one buys streaming for EKS uptime; they buy because the video plays. **28-day window:**

| # | Journey              | SLO                                                       |
|---|----------------------|-----------------------------------------------------------|
| 1 | Login                | 99.9% 2xx on `/auth/login` under 500 ms                   |
| 2 | Playback start       | 99.5% 2xx on manifest fetch under 2 s                     |
| 3 | Continuous playback  | 99.9% 2xx on video segment under 1 s                      |
| 4 | Playback quality     | 99.5% time without rebuffering (client-reported)          |
| 5 | Checkout / billing   | 99.95% transactions without technical error               |
| 6 | Catalog search       | 99.5% 2xx on `/search` under 500 ms                       |
| 7 | Transactional email  | 99.5% delivery under 5 min without bounce                 |

Each SLO defines an **error budget** = (1 − SLO).

**Regional outages are out of budget (force majeure).** These SLOs are *conditional on the region being available* — they measure whether journeys work **when `us-east-1` is up**, the quality the platform actually controls. A full-regional outage is the accepted single-region risk from §1, not an SLO miss: it sits in a separate, lower **infrastructure-availability** tier and its downtime is excluded from the journey error budgets. Burn-rate alerts (below) **still fire** during such an event — you always want to know — but a declared regional outage does not consume the budget that gates deploys and freezes. This keeps the targets honest and meetable without pretending single-region buys regional four-nines.

**Multi-window burn rate alerts** (Google SRE standard):

| Window | Burn rate | Severity | Action              |
|--------|-----------|----------|---------------------|
| 1 h    | 14.4×     | P0 / P1  | Immediate page      |
| 6 h    | 6×        | P1       | Page                |
| 24 h   | 3×        | P2       | Notify, don't wake  |
| 3 d    | 1×        | P3       | Backlog             |

This table gives **objective criteria for severity** — without it, P0 becomes "oncall hunch".

**Error budget policy:**

- **Above 50%** — normal deploy.
- **10–50%** — deploy with extra review.
- **Below 10%** — feature freeze.
- **Exhausted** — full halt and mandatory postmortem.
- Quarterly review.

**Trade-off (declared):** the 28-day window is slower to forgive transient spikes — accepted because shorter windows generate noise.

### 3.6 Synthetic probes

**Synthetic probes are the direct answer to the assignment's pain** — *"the team often discovers issues from customers before internal monitoring detects them."* Without probes, detection depends on traffic: at 3 AM with no traffic, a deploy that breaks login goes unnoticed until 8 AM.

OSS stack, consistent with the self-hosted observability choice:

**Prometheus Blackbox Exporter — single-step probes:**

- TLS certificate expiration.
- Health endpoints.
- Manifest fetch with cached token.
- CloudFront edge HEAD.
- DNS.
- Search endpoint with a known query.

**Canary jobs (Python / Node) — multi-step probes, run as Kubernetes CronJobs / KEDA cron-scaled pods in the `ops` cluster (no Lambda, no EventBridge):**

- **Full login.**
- **Playback start** — login → manifest → signed cookie → first segment.
- **Continuous playback** — 3 sequential segments with byte validation.
- **Sandbox checkout** — PSP in test mode.
- **Transactional email** — reset → IMAP polling → validate under 5 min.

**Single-region vantage (accepted trade-off).** Probes run only from the `ops` region and write directly to the `ops`-cluster collector, persisted in VictoriaMetrics. This consciously drops the multi-region geographic signal — *"is playback slow in São Paulo?"* — consistent with the single-region posture in §1; that signal, if needed later, belongs to real-user telemetry, not synthetic probes.

**Failure-pattern escalation (anti false-positive).** With a single vantage, cross-region agreement no longer suppresses false positives — consecutive runs and corroboration with the real-traffic SLI do that instead:

| Pattern | Action |
|---|---|
| 1 failed run | Blip — discard |
| 2 consecutive failed runs, one journey | P3 |
| 3 consecutive, **or** 2+ journeys failing together | P1, page |
| Core journey (login / playback / checkout) down **and** corroborated by the real-traffic SLI | P0 |

**Dual SLI.** The official SLO uses **real traffic as canonical source**; synthetic probes act as the **always-available early warning**. A divergence (probe ok, real bad) means the probe doesn't cover the real customer path — that is itself a valuable learning artefact from the practice.

**Probe isolation:**

- Minimal IAM in Secrets Manager, **monthly rotation**.
- Probe user IDs `probe-<journey>`, filtered out of business metrics.
- Checkout: PSP test mode hardcoded.
- Email: dedicated mailbox.

---

## 4. Alerting and Escalation Strategy

This section directly answers the assignment's pain — *"alerting is inconsistent and lacks clear escalation paths"*. Severity is not a feeling; it is a function of impact and budget consumption, connected back to the burn-rate windows in §3.5.

### 4.1 Severity matrix

| Severity | Definition                                                       | Response                                                                 | Examples                                                          |
|----------|------------------------------------------------------------------|--------------------------------------------------------------------------|-------------------------------------------------------------------|
| **P0**   | Platform unavailable or revenue stopping.                        | Oncall + **incident commander**, 24/7, **immediate page**, **war room**. | Global playback broken; auth down; checkout down.                 |
| **P1**   | Critical functionality degraded, SLO at risk.                    | Oncall **24/7**, page.                                                   | Regional playback below 95%; latency above 2 s p95; email bounce rate above 5%. |
| **P2**   | Significant degradation with workaround, **or** early P1 warning.| Oncall notified, response within **1 business day**.                     | Cache hit dropping; 5xx below 1%; transcoding time rising.        |
| **P3**   | Trend warning.                                                   | **No page** — backlog, async.                                            | Disk slowly rising; cost out of expected band.                    |

### 4.2 Tool — PagerDuty

**PagerDuty is adopted as the paging and escalation service.**

Stated honestly up front: this is a **recommendation based on market research and technical criteria**, not on prior production operation by the author. The justification is recorded explicitly because two obvious alternatives were evaluated and rejected for reasons that matter:

- **AWS Systems Manager Incident Manager** — evaluated as an AWS-native, lower-cost alternative. Not adopted: weaker mobile UX, less mature post-incident review tooling, and less established as an industry standard (which matters for hiring).
- **Grafana OnCall** — evaluated and discarded for an important reason: running the alerting tool **inside the same cluster as the platform** creates a SPOF. If the cluster degrades, alerting degrades with it, precisely when it needs to work most. **The tool that tells you the house is on fire cannot live inside the house.**

**Trade-off (declared):** license cost and additional vendor lock-in. Accepted because the paging tool's reliability is the primary requirement.

### 4.3 Oncall — weekly rotation

- **Cadence** — weekly, **Monday 9 AM handover**.
- **Coverage** — 24/7 primary + 24/7 secondary.
- **Minimum 4 people on the rotation** — each engineer oncall every 4 weeks. Fewer becomes burnout.
- **15-minute ritualized handover** — SLO state, alerts from the past 48 h, deploys in flight.
- **Compensation** — monthly oncall stipend + comp day per off-hours page.

**Separate security path.** A dedicated PagerDuty schedule for security incidents (critical GuardDuty findings, exposures detected via WAF). Pages the **security engineer** with fallback on the engineering manager. **Independent of the operational rotation.**

### 4.4 Escalation by severity

| Severity | Primary        | Ack    | Escalation path                                                                                                                              |
|----------|----------------|--------|----------------------------------------------------------------------------------------------------------------------------------------------|
| **P0**   | 24/7           | 5 min  | No ack → **secondary (10 min)** → engineering manager (20 min) → director / CTO (40 min). **War room** opened via PagerDuty + Slack integration. |
| **P1**   | 24/7           | 10 min | No ack → secondary (15 min) → manager (30 min).                                                                                              |
| **P2**   | Business hours | 1 hour | —                                                                                                                                            |
| **P3**   | —              | —      | No page; **Jira ticket** opened via webhook.                                                                                                 |

**Parallel security track.** A security **P0 escalates simultaneously** to the security engineer, **legal / comms**, and the **CTO**. Notification and disclosure decisions do not go through engineering alone — this is recorded explicitly.

### 4.5 Runbook standard

**Every alert carries an attached runbook**, linked via the `runbook_url` field in the PagerDuty payload. Runbooks live in the platform repository, versioned, **reviewed in PR as code**.

**Minimal template:**

- **Symptom** — what the alert indicates.
- **Possible causes** — top 3–5 hypotheses ordered by **historical frequency**.
- **Diagnosis** — copy-paste functional commands (`kubectl`, AWS CLI, Grafana / Loki / Tempo queries).
- **Remediation** — actions in increasing risk order, marking what **requires approval**.
- **Escalation criteria** — when to bump severity or call the lead.
- **Post-incident** — link to the postmortem template if P0 / P1.

**Three rules, recorded in the document:**

1. **An alert without a runbook does not go to production.**
2. Every incident-time execution generates a **runbook review as a postmortem action item**.
3. An **outdated runbook is treated as an operations bug**, not a documentation problem.

Without those rules, runbooks rot and become traps.

### 4.6 Postmortem and blameless culture

**Every P0 and P1 incident produces a postmortem.** Template in Git:

- **Timeline** with timestamps.
- **Measured impact** — users affected, SLO error budget consumed, estimated revenue when applicable.
- **Root cause.**
- **Contributing factors.**
- **What went well.**
- **What didn't.**
- **Action items** — Jira-ticketed with **owner and deadline**, linked back to the postmortem.

**Deadline:** draft within **5 business days**, finalized within **10**.

**Blameless culture.** Focus stays on **systemic causes** — design, observability, process — and never on individuals. A system without a guardrail is the real responsible party; the engineer who made the error is the **primary source of learning, not a target**.

**Review.** A **bi-weekly platform meeting** reads recent postmortems together. Action items without implementation in **60 days** escalate to the engineering manager.

---

## 5. Cost Optimization

The assignment's opening line — *"infrastructure costs have steadily increased without clear visibility into optimization opportunities"* — actually contains **two distinct problems**: **visibility** and **optimization**. They are addressed in that order. Optimization without data is guesswork, so visibility comes first.

### 5.1 Visibility

**Mandatory tagging** is enforced via the Terraform module wrapper introduced in §2.14. Every resource creation requires `Environment`, `Service`, `Owner`, `CostCenter`, `ManagedBy` and `Lifecycle`. **A resource without tags fails the plan.** Without tags, there is no breakdown — and without a breakdown, no real optimization.

**Visibility stack:**

- **AWS Cost Explorer** — interactive analysis and custom reports by tag.
- **AWS Cost and Usage Report (CUR) in S3** — queryable via Athena for ad-hoc analyses the UI does not support.
- **AWS Budgets** — per-service / per-tag alerts.
- **AWS Cost Anomaly Detection** (ML) — emits to SNS → Slack.
- **Cost dashboards in Grafana OSS** — side-by-side with technical metrics, so engineers see **CPU and cost in the same view**, not in silos.

**Visual diagnostic — [Cloudcraft](https://www.cloudcraft.co/).** Cloudcraft syncs with the live AWS account, generates up-to-date isometric diagrams of the infrastructure, and **overlays per-component cost on the diagram itself**. Useful for quarterly architectural reviews and onboarding ("here is what exists and what it costs", visually, not on a spreadsheet). It complements Cost Explorer / CUR / Anomaly Detection — it does not replace them.

### 5.2 Optimization — in order of typical impact

#### Compute (40–60% of cost)

- **Cluster Autoscaler** tuning nodegroups — adopted because the team has operational experience with it.
- **Spot Instances on stateless nodegroups** — `app-stateless` and polling workers. Cluster Spot Interruption Handler manages graceful drain.
- **Graviton (ARM64)** wherever the stack supports — Python, Node, Go, modern Java. Requires a multi-arch build pipeline.
- **Right-sizing via VPA in recommender mode** — recommendations only, **no auto-apply**. The engineer reviews and lands it in a PR.
- **Scheduled scaling in non-prod** — staging and dev shut down nights and weekends. ≈ −60% in non-prod with no impact on the dev flow.

**Karpenter — reinforced here in cost context:** evaluated for better bin packing, **not adopted, due to the team's lack of operational experience with it**. The marginal efficiency gain does not justify the operational risk.

#### Storage (10–15% of cost)

- **S3 Intelligent-Tiering** on media buckets (catalog, originals).
- **S3 Lifecycle** for logs, backups and audit: Standard → IA at 30 d → Glacier at 90 d → Deep Archive at 365 d.
- **EBS `gp3` replacing `gp2`** — no-downtime migration, cheaper and equal-or-better.
- **Monthly Lambda** sweeping orphan EBS snapshots over 90 d without a retention tag.
- **Mandatory CloudWatch Logs retention** — 30 d prod, 7 d staging, 3 d dev. The default is "Never Expire", which silently explodes.

#### Orphan resources — the silent bleed

One case bleeds silently and deserves to be called out: **orphan Load Balancers** — ALB / NLB with no active target group, or pointing to a deleted service. Each idle LB costs ≈ **$16–22/month fixed + LCU**, and disappears from radar because no one watches.

**Weekly Lambda sweep:** list all LBs, cross-reference with healthy targets, flag the **zero-target ones for review**.

The same principle applies to **unassociated Elastic IPs**, **NAT Gateways without an active route**, and **stopped-but-not-deleted RDS instances**.

#### Data transfer (5–15% — frequently underestimated)

An observation worth opening with: by default, **every pod-in-private-subnet → AWS-service request goes through the NAT Gateway, charged at $0.045 per GB processed** — even when the destination is another AWS service in the same region. **That is the silent killer of the data-transfer line item.**

Tactics:

- **VPC Gateway Endpoints for S3 and DynamoDB** — zero extra cost, eliminates the NAT pass-through. Enabling is a route-table configuration.
- **VPC Interface Endpoints (PrivateLink) for SQS, SNS, KMS, ECR and STS** — ≈ $0.01/hour per AZ + $0.01/GB processed. Pays in volume.
- **Topology-aware routing in Istio** — reduces unnecessary cross-AZ traffic, charged at $0.01/GB.

#### Database

- **Aurora Serverless v2** — ACU range tuned by real usage, reviewed weekly.
- **RDS Proxy** — connection pool and transparent failover.
- **DynamoDB on-demand vs provisioned** — analyzed per table, by load pattern.
- **DynamoDB TTL** on ephemeral data — session, probe watch progress.

#### Reserved capacity — applied last

**Savings Plans are applied only after right-sizing, Spot and Graviton are in production and stabilized.** Committing to the wrong baseline locks the platform into the very inefficiency it is trying to remove.

- **Quarterly review cadence.**
- Target coverage: **70–80% on Compute Savings Plans**, **20–30% on-demand** for elasticity.

The "last" is emphasized because many teams burn themselves by committing before optimizing.

### 5.3 Continuous operation

| Cadence    | Action                                                                                              |
|------------|-----------------------------------------------------------------------------------------------------|
| **Daily**     | Cost Anomaly Detection → Slack.                                                                  |
| **Weekly**    | Automated report — top 10 by cost, top 5 changes, top 3 pending recommendations.                 |
| **Monthly**   | Orphan cleanup; Savings Plan coverage adjustment.                                                |
| **Quarterly** | Architectural review — any layer disproportionately rising?                                      |

**Consolidated trade-offs:**

- Spot requires interruption-tolerant code — already the principle for stateless workloads in §2.2.
- Aggressive lifecycle increases restore time when an old object is needed.
- Savings Plans tie up capital for 1–3 years.
- VPC Endpoints add Terraform items and a small amount of operational surface.

---

## 6. Consolidated Tradeoffs and Assumptions

This section is the index to every conscious decision in the document. Nothing here is accidental: each trade-off was declared at the point of decision, with a stated *why* and — where it mattered — an explicit exit criterion. The tables below re-collect them in one place so a reviewer (or a future on-call engineer) can read the whole risk surface at a glance, instead of reconstructing it from fifteen subsections.

The reading order is deliberate: **foundational assumptions first** (§6.1) — the four choices from §1 that everything else inherits — then the **layer-by-layer trade-off matrix** (§6.2), then the **headline accepted risks** (§6.3) — the structural single points of failure, called out on their own because they are the decisions a reviewer should challenge first.

### 6.1 Foundational assumptions (set in §1, inherited everywhere)

These four are not local trade-offs; they shape every decision downstream. If any one of them is wrong for the business, large parts of the architecture change.

| # | Assumption | Why it holds at this stage | Consequence accepted |
|---|------------|----------------------------|----------------------|
| 1 | **VOD-only, single-tenant B2C, global**; mobile/TV primary, web secondary. No live streaming. | Matches the modeled product (Netflix/Prime-style catalog). | Client telemetry, CDN strategy and release cadence are biased toward mobile/TV; live-streaming infra is absent by design. |
| 2 | **Single region `us-east-1`.** | Multi-region cost/complexity does not pay back at current scale. | A full regional outage is **downtime** — accepted. Actual failover is out of scope. |
| 3 | **AWS lock-in accepted by default**; open-source self-hosted **only where cheaper** than the managed AWS equivalent (e.g. observability). | Self-managing a commodity layer adds burden without differentiating the product. | Data is deliberate lock-in (DynamoDB, Aurora Serverless v2); Aurora/ElastiCache/`tsvector` keep portable semantics. |
| 4 | **Cluster-wide HA pattern** — extra replicas + pod `antiAffinity` across nodes and AZs — applies to **every** control-plane component. | One pattern stated once avoids repetition and drift. | Where a later section omits it, the pattern is implied, not absent. |

### 6.2 Trade-offs and assumptions by architecture layer

One row per decision, ordered by the section it comes from. A blank cell means that dimension does not apply to the decision.

| Layer (§) | Decision / stance | Key assumption behind it | Trade-off accepted | Mitigation / revisit trigger |
|-----------|-------------------|--------------------------|--------------------|------------------------------|
| **Networking** (§2.1) | **One NAT Gateway per AZ** | Client egress leaves via CloudFront/S3/API GW, not the NAT; NAT carries only private-subnet outbound-to-internet | Fixed hourly charge per NAT (×3) | Per-AZ NATs make AZ failure survivable **and** remove the cross-AZ $0.01/GB tax (≈ cost-neutral); VPC endpoints keep AWS-service traffic off the NAT |
| **Networking** (§2.1) | No public ALB — CloudFront → API Gateway → VPC Link → internal NLB | Frontend is **purely static in S3** | All ingress funnels through CloudFront/API Gateway | Internal NLB never gets a public IP; web + API share one domain so **CORS disappears** |
| **Networking** (§2.1) | CloudFront over Cloudflare | Cost acceptable; practicality | Edge vendor tied to AWS | Same-domain web + API benefit |
| **Cluster** (§2.2) | EKS, **two clusters (`prod` + `ops`)**, over ECS | k8s ecosystem worth the cost; ops workloads must not share prod's blast radius | **EKS soft lock-in**; `prod` is a single workload failure boundary | Prod boundary covered by 8 guardrails (quotas, default-deny `NetworkPolicy`, RBAC+IRSA, PDBs, staging mirror, add-on admission, etcd hygiene, Cluster Autoscaler); `ops` in a separate account with a PagerDuty heartbeat |
| **Cluster** (§2.2) | Cluster Autoscaler, **not Karpenter** | Team has no Karpenter production experience | Forgo Karpenter bin-packing / mixed-instance gains | **Revisit** once the team builds operational experience with it |
| **Cluster** (§2.2) | Spot + Graviton on `app-stateless` | Stateless workloads tolerate interruption | Spot interruptions; needs multi-arch build pipeline | Spot Interruption Handler does graceful drain |
| **Service mesh** (§2.3) | Istio in **ambient mode** | Ambient GA since 2024; lower overhead (no per-pod sidecar, ztunnel L4 mTLS) | Ambient is newer; troubleshooting has nuances | **Plan B within the same product** — sidecar mode in selected namespaces via label, no vendor swap |
| **Ingress** (§2.4) | nginx ingress, JSON access logs straight to the OTel Collector | JSON avoids downstream regex parsing | — | No broker and no custom metrics app in the path |
| **Autoscaling** (§2.5) | KEDA on queue depth / custom metrics / DB queries | Event-driven scaling fits the workload | — | HA per the cluster-wide pattern |
| **Auth** (§2.6) | Cognito + federated login (Meta/Google/Apple) | Identity is a commodity layer; migration is costly **anywhere** | Lock-in accepted | OIDC/SAML preserves the escape path |
| **Secrets** (§2.7) | AWS-native (Secrets Manager, SSM, IRSA, External Secrets Operator); **Vault/Consul dropped** | Rest of the stack already accepts AWS lock-in at several points | Forgo Vault/Consul portability | Vault/Consul ops cost (Raft quorum, consistent backup, custom rotation, internal certs) doesn't pay back; native RDS rotation used |
| **Data** (§2.8) | Polyglot persistence — Aurora (CP) / DynamoDB (AP) / Redis / S3 / tsvector | Different data classes genuinely have different CAP profiles | Operational complexity + team skill | Worth it vs. a single store that either under-scales or over-consistencies |
| **Data** (§2.8) | Watch history / progress = **last-write-wins by client timestamp** | The streaming standard; conflicts are rare and low-stakes | Concurrent writes may be lost | Accepted as industry norm |
| **Data** (§2.8) | View events append-only | Eventual loss is acceptable for this class | Some analytics events may be lost | Accepted by data class |
| **Data** (§2.8) | Aurora full-text search (`tsvector`), **no OpenSearch** | Current scale doesn't justify OpenSearch cost/overhead | Search features more limited than a dedicated engine | **Revisit** at scale; read models fed via SNS + SQS |
| **Messaging** (§2.9) | SNS + SQS as the only backbone | Current scale needs no Kafka-class system | Forgo Kafka throughput/replay semantics | RabbitMQ/MSK/Kafka add ops burden without proportional gain now |
| **Messaging** (§2.9) | Outbox via **polling worker, not CDC** | 1–2 s commit→publish latency, manual replay, ~$0 incremental are all acceptable | Polling latency; replay is manual | **Revisit triggers:** outbox `SELECT` appears in Aurora slow queries; latency becomes a product requirement; sustained **>~5k events/sec** |
| **Messaging** (§2.9) | Idempotency lives in the consumer | SNS is at-least-once by default | Consumers must dedupe | `FOR UPDATE SKIP LOCKED` enables parallel workers |
| **Email** (§2.9) | SES for transactional email | Commodity layer | Lock-in accepted | Delivery events → SNS → SQS → handler updates bounce list / reputation alerts |
| **Media** (§2.10) | S3 + CloudFront with per-session signed cookies | Immutable-after-publish assets | — | — |
| **Media** (§2.10) | Media production pipeline (ingest/transcode/packaging/DRM) **out of scope** | Owned by the product/content team | This proposal is scoped to SRE operations | — |
| **Perimeter** (§2.11) | WAF v2 + Shield Standard + GuardDuty; **Shield Advanced not adopted** | Shield Standard volumetric coverage is enough without an attack history | No advanced DDoS / cost protection | ~$3k/month + extras unjustified today; **revisit** after a real large-scale attack |
| **Perimeter** (§2.11) | Rate limit 2000 req / 5 min per IP | A reasonable abuse threshold | May clip very aggressive legitimate clients | Tune on observed data |
| **DNS** (§2.12) | Route 53 alias + ACM in `us-east-1`; **no health checks / latency routing** | Single-region profile has nowhere to fail over to | Those features unused | Stated explicitly as a **conscious omission**, not an oversight |
| **Backup** (§2.13) | Per-component PITR / snapshots / versioning + **quarterly restore drill** | Local failures (corruption, deletes, AZ loss) are the realistic risk | **No cross-region replication** | RPO/RTO valid for **local** failures only, **not** a full regional outage — consistent with §1 |
| **IaC** (§2.14) | Terraform over AWS CDK | Broader module ecosystem, lower lock-in | — | State in S3 + per-env KMS + DynamoDB lock; Atlantis + Infracost + weekly drift detection |
| **IaC** (§2.14) | Mandatory tagging enforced in the module wrapper | Cost breakdown is impossible without it | — | A resource without tags **fails the plan** |
| **Observability** (§3) | Self-hosted stack (VictoriaMetrics, Tempo, Loki, Grafana OSS, OTel) on S3; **no Grafana Cloud** | Self-hosting avoids paying twice for the same service | Operational burden of running the stack | Runs in the dedicated **`ops` cluster** (§2.2), outside prod's blast radius; only **S3** is locked-in — swappable by config |
| **Observability** (§3) | Grafana **Tempo** for traces | The real debugging path is **log → `trace_id`** | Free-form exploratory trace search is limited | Accepted |
| **Observability** (§3) | Tail sampling — 1% of normal traffic | Normal-path traces are mostly uninteresting | Rare normal-path traces dropped | 100% of error / over-SLO / synthetic traces retained |
| **Observability** (§3) | 7 journey SLOs, **28-day window**, **conditional on region-up** | Users buy working playback; single-region is an accepted §1 risk | 28-day window slower to forgive spikes; regional outages excluded from the budget | Force-majeure carve-out (§3.5): alerts still fire on a regional event, but it does not burn the journey error budget |
| **Observability** (§3) | Dual SLI — real traffic canonical, synthetic = early warning | Synthetic probes detect breakage even with no traffic | A probe may not cover the real customer path | A real-vs-probe divergence is itself a **learning artefact** |
| **Alerting** (§4) | **PagerDuty** for paging/escalation | Paging reliability is the primary requirement | License cost + added vendor lock-in; this is a **researched recommendation**, not prior production operation | **Grafana OnCall rejected** (in-cluster SPOF — "the tool that tells you the house is on fire cannot live inside the house"); **SSM Incident Manager rejected** (weaker mobile UX, less mature) |
| **Alerting** (§4) | Weekly rotation, **minimum 4 people** | Fewer than 4 leads to burnout | Staffing cost | Monthly stipend + comp day per off-hours page |
| **Cost** (§5) | **Visibility before optimization** | Optimization without data is guesswork | — | Tagging + Cost Explorer + CUR/Athena + Budgets + Anomaly Detection + Cloudcraft |
| **Cost** (§5) | VPA in **recommender mode only** (no auto-apply) | Humans should land sizing changes | A manual step remains | Engineer reviews and lands it in a PR |
| **Cost** (§5) | Aggressive S3 lifecycle (IA → Glacier → Deep Archive) | Old objects are rarely needed fast | Higher restore latency for archived data | Accepted |
| **Cost** (§5) | **Savings Plans applied last** | Committing before optimizing locks in the inefficiency | Capital tied up 1–3 years | Only after right-sizing + Spot + Graviton stabilize; 70–80% coverage target, quarterly review |
| **Cost** (§5) | VPC Endpoints (Gateway + Interface) | Eliminate the $0.045/GB NAT pass-through | Added Terraform items + small ops surface | Pays back in volume |

### 6.3 The headline accepted risks

Two structural single points of failure run through the architecture — a third, the single NAT Gateway, was removed in §2.1 by going per-AZ. Each remaining one is **deliberate** — a bet that the cost/complexity of removing it outweighs a failure that is either low-probability or otherwise mitigated. They are the decisions a reviewer should challenge first.

| Accepted risk | Blast radius | Why it is acceptable now | What would change the decision |
|---------------|--------------|--------------------------|--------------------------------|
| **Single region** (`us-east-1`) | Full platform outage during a regional failure | Multi-region cost doesn't pay back at current scale; CDN-served catalog/playback assets + graceful client degradation soften user impact; journey SLOs are scoped to exclude it (§3.5) | A regional SLA requirement, regulatory data-residency needs, or a regional outage that materially hurts revenue |
| **Single `prod` workload cluster** | A `prod`-cluster degradation affects all production workloads | Eight guardrails + a staging mirror contain blast radius; observability, ArgoCD, probes and CI live in a separate `ops` account, so they survive a prod-cluster failure | A blast-radius incident the guardrails don't contain, or a tenant/compliance need for hard isolation |

**The common thread:** every accepted risk is paired with either a mitigation that shrinks its probability/impact or an explicit trigger that would reopen the decision. That is the difference between an *accepted* trade-off and an *unexamined* one — and it is the posture this entire proposal is built to demonstrate.
