<!--
SYNC IMPACT REPORT
==================
Version change: (template, unversioned) → 1.0.0
Bump rationale: Initial ratification. The constitution moved from an unfilled
template (all [PLACEHOLDER] tokens) to a concrete, project-specific document.
First adoption ⇒ MAJOR baseline 1.0.0.

Principles defined (6):
  I.   Operational Excellence by Design (SRE-First)
  II.  Cost Optimization as a First-Class Signal
  III. AI-Leveraged, Human-Accountable
  IV.  The Cost Agent Runs on Agno + OpenAI
  V.   Evidence-Based, Reproducible Outputs
  VI.  Pragmatism with Documented Tradeoffs

Sections added:
  - Technology & Security Constraints (Section 2)
  - Development Workflow & Quality Gates (Section 3)
  - Governance

Sections removed: none (template placeholders replaced in place).

Templates / artifacts reviewed for consistency:
  ✅ .specify/templates/plan-template.md — "Constitution Check" gate references the
     constitution dynamically; no change required (aligned).
  ✅ .specify/templates/spec-template.md — mandatory sections compatible with new
     principles; no change required (aligned).
  ✅ .specify/templates/tasks-template.md — task categorization supports
     observability/cost/AI task types; no change required (aligned).
  ✅ README.md — repository structure (docs/, agent/, prompts.txt) consistent with
     Principles III, IV, and the Development Workflow section.
  ⚠ No .specify/templates/commands/*.md directory present — nothing to reconcile.

Follow-up TODOs: none. All placeholders resolved.
-->

# Technical AI Assessment — SRE Constitution

## Core Principles

### I. Operational Excellence by Design (SRE-First)

Reliability, observability, and alerting are designed before functionality is
considered complete — never bolted on afterward. Monitoring MUST cover
business-critical functionality (e.g. checkout, API success rates, job
completion, email delivery), not merely website uptime. Every alert MUST be
actionable and tied to an explicit, documented escalation path; non-actionable
alerts MUST be removed or downgraded. The system MUST aim to detect and surface
incidents before customers report them.

Rationale: The assessment's stated gaps are exactly these — cost/visibility
blind spots, uptime-only monitoring, inconsistent alerting, and customer-first
incident discovery. Solving them is the core of the SRE role being evaluated.

### II. Cost Optimization as a First-Class Signal

Cloud cost is treated as an operational signal with the same rigor as latency or
error rate. Every cost recommendation MUST: (a) trace to concrete input evidence
(a value in the supplied cost data); (b) be classified by waste category —
rightsizing, unused/idle resources, scaling policy, storage class & lifecycle,
reserved/Savings-Plan capacity, or service-level cost trend; and (c) be
prioritized by estimated savings weighed against implementation effort and risk.
Recommendations that cannot be tied to evidence or prioritized MUST NOT ship.

Rationale: Cost waste with no visibility is a named challenge, and an actionable,
prioritized cost analysis is the heart of both deliverables.

### III. AI-Leveraged, Human-Accountable

AI is used throughout the workflow, and that usage MUST remain transparent: every
new instruction or prompt is appended to `prompts.txt` with an ISO 8601 timestamp
and a brief summary of the response. AI-generated output is advisory by default —
it MUST NOT trigger destructive or state-changing AWS operations automatically.
Any remediation that mutates infrastructure requires explicit human approval.

Rationale: The assessment evaluates *how* AI is leveraged, and an SRE tool that
can silently change production is unacceptable; auditability and safety are
non-negotiable.

### IV. The Cost Agent Runs on Agno + OpenAI

The AWS Cost Optimization Agent MUST be implemented with the Agno framework
(agno.com) using an OpenAI model. Agent capabilities MUST be exposed as explicit,
single-responsibility tools with typed inputs and outputs. The agent MUST operate
read-only over the cost inputs it is given and MUST degrade gracefully (state the
gap, do not crash) when expected data is missing or malformed.

Rationale: The technology stack is an explicit project mandate; constraining the
agent to clear, typed, read-only tools keeps its behavior predictable, testable,
and safe.

### V. Evidence-Based, Reproducible Outputs

No invented resources, prices, account identifiers, or savings figures. Every
finding MUST trace to a field in the supplied cost data, and every numeric claim
MUST be reproducible from documented inputs and stated assumptions. When the data
is insufficient to support a conclusion, the output MUST record the assumption
made or flag `NEEDS DATA` — it MUST NOT guess.

Rationale: An SRE recommendation is only as trustworthy as its provenance;
hallucinated savings destroy credibility and can drive harmful changes.

### VI. Pragmatism with Documented Tradeoffs

Favor the simplest solution that satisfies the requirement (YAGNI). Every
significant architectural or implementation decision MUST record its assumptions
and tradeoffs in the relevant deliverable. Scope MUST fit the assessment's intent
— a focused, demonstrable proof of value — and any extension beyond the stated
deliverables MUST be justified by clear added value.

Rationale: The assessment explicitly rewards pragmatic decisions, prioritization,
ownership, and documented tradeoffs over exhaustive completeness.

## Technology & Security Constraints

- **Stack**: The Cost Optimization Agent is Python on Agno + an OpenAI model. The
  Architecture & Operations Proposal is authored in Markdown (with an exported
  PDF) under `docs/`.
- **Secrets**: `OPENAI_API_KEY`, AWS credentials, and any tokens MUST be supplied
  via environment variables / a local `.env` and MUST NEVER be committed.
- **Public-repo hygiene**: The repository is public. No real secrets, AWS account
  IDs, customer data, or sensitive ARNs may appear in any committed artifact;
  examples MUST use clearly fictitious values.
- **Least privilege**: Any AWS access used to gather cost inputs (Cost Explorer,
  CUR, CloudWatch) MUST be read-only and least-privilege.

## Development Workflow & Quality Gates

- **Spec-Driven**: Non-trivial work flows through the Spec Kit lifecycle
  (constitution → specify → plan → tasks → implement). Plans MUST include a
  Constitution Check; violations MUST be recorded with justification in the
  plan's Complexity Tracking table.
- **Prompt-logging gate**: `prompts.txt` MUST be updated for every new
  instruction before that work is considered complete (Principle III).
- **Reproducibility gate**: Each deliverable MUST be runnable / readable from
  documented steps, with no hidden manual setup — sufficient for the required
  Loom walkthrough and a public reviewer.
- **Demonstrability gate**: Every shipped capability MUST be demonstrable end to
  end (agent run on sample cost data; proposal readable standalone) with its key
  tradeoffs documented.

## Governance

This constitution supersedes ad-hoc practices for this repository. When guidance
conflicts, the constitution wins.

- **Amendments**: Changes are made by editing this file, accompanied by a version
  bump and an updated Sync Impact Report (prepended as an HTML comment).
- **Versioning policy** (semantic):
  - **MAJOR** — backward-incompatible governance/principle removals or
    redefinitions.
  - **MINOR** — a new principle/section is added or guidance is materially
    expanded.
  - **PATCH** — clarifications, wording, and non-semantic refinements.
- **Compliance review**: Plans and specs MUST be checked against these principles
  before implementation; any deviation MUST be justified in writing or the work
  MUST be revised to comply. Reviewers (human or AI) MUST verify Principles
  II–V for any cost-analysis output and Principle III for any AI-driven action.

**Version**: 1.0.0 | **Ratified**: 2026-06-28 | **Last Amended**: 2026-06-28
