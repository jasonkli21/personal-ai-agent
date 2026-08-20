# Phase 9 implementation plan

This plan hardens the personal system for intentional private use and ongoing experiments. It follows—not replaces—the project brief’s warning that the current public Cloud Run bootstrap is not suitable for personal data without authentication, authorization, and a deliberate provider-data policy.

## Scope boundary

Phase 9 adds personal-use authentication, authorization, secrets, observability, cost/rate protections, deployment hardening, scheduled maintenance, backup/export/deletion controls, and evaluation-regression tracking. It does not broaden to multi-tenant collaboration, billing, public access, transaction execution, or a claim of regulatory compliance.

## Delivery conventions and release gates

- Create separate local, test, staging, and production configurations with
  explicit allowlists. Production must start deny-by-default and cannot fall
  back to the Phase 1 `local` owner or development auth bypass.
- Treat authentication and owner authorization as an application-wide policy,
  not route middleware alone: repositories, asynchronous jobs, SSE reconnects,
  exports, backups, deletion jobs, and administrative operations all receive a
  verified principal and enforce it.
- Keep infrastructure declarative/reviewable where practical. Document every
  service account, secret binding, IAM role, ingress rule, database/queue
  permission, scheduled trigger, network egress requirement, and rollback
  command. Do not grant broad project-owner/editor roles for convenience.
- Define production telemetry schemas and redaction tests before instrumenting
  a path. Default logs, traces, alerts, and analytics contain correlation IDs,
  status, bounded counts/durations, policy versions, and error classes—not
  prompts, messages, evidence text, tokens, URLs containing sensitive values,
  provider payloads, or credentials.
- Treat backups, export, and deletion as one documented lifecycle. State which
  data is in each backup, encryption/access controls, retention, restore owner,
  deletion propagation, provider limitations, and audit records. Never claim
  immediate deletion from immutable backups unless it is true.
- Require a staging rehearsal with synthetic data, documented rollback, and
  operator approval before production access. Any failed security, recovery,
  budget, or evaluation gate blocks deployment rather than being waived by a
  feature flag.

## Required verification matrix

Run unit/integration tests for auth token/session validation, owner matrix for
every collection/route/event/job, secret/config validation/redaction, limit and
kill-switch behavior, worker push verification, IaC policy assertions,
maintenance idempotency, backup restore, export fidelity, deletion propagation,
and evaluation release gates. Run a separate staged synthetic-data drill for
login, ordinary chat, research, worker processing, provider outage, alerting,
rollback, export, restore, and deletion. Record results and approvals without
including real personal data.

## Required implementation artifacts

P9.0–P9.2 must produce the accepted threat model, owner/authorization matrix,
environment configuration schema, data-flow and provider-policy register,
IaC plan, runbook skeleton, synthetic drill fixtures, and release-gate
checklist before production traffic is considered. Every route, repository,
worker, scheduled job, and operator action must name a principal, an owner or
administrative authority, an audit event, and a safe failure behavior.

**Required control records:**

| Record | Required fields |
| --- | --- |
| Principal/owner mapping | `subject`, `owner_id`, `issuer`, `created_at`, `status`, `migration_version` |
| Audit event | `id`, `actor_subject`, `owner_id` (nullable), `action`, `target_type`, `target_id` (nullable), `result`, `correlation_id`, `occurred_at` |
| Usage budget | `id`, `scope`, `period_start`, `period_end`, `limit`, `reserved`, `settled`, `state`, `policy_version` |
| Maintenance job | `id`, `job_type`, `owner_scope`, `idempotency_key`, `lease_expires_at`, `status`, `attempt_count`, `created_at`, `updated_at` |
| Lifecycle request | `id`, `owner_id`, `request_type`, `state`, `idempotency_key`, `confirmed_at`, `irreversible_at` (nullable), `completed_at` (nullable), `audit_event_ids` |
| Evaluation release record | `id`, `build_id`, `fixture_version`, `configuration_version`, `environment`, `gate_results`, `approved_by`, `created_at` |

**Required configuration:**

| Setting | Purpose |
| --- | --- |
| `APP_ENVIRONMENT` / `AUTH_MODE` / `ALLOWED_ORIGINS` | Explicit environment and deny-by-default access behavior |
| `AUTH_ISSUER`, `AUTH_AUDIENCE`, `AUTH_REQUIRED` | Token/session validation and no-production-bypass guard |
| `*_KILL_SWITCH_ENABLED` | Independently disable chat, research, workers, and external providers |
| `RATE_LIMIT_*`, `BUDGET_*`, `MAX_CONCURRENCY_*` | Enforced identity/provider cost and abuse bounds |
| `OBSERVABILITY_REDACTION_VERSION` | Versioned telemetry allowlist/redaction policy |
| `MAINTENANCE_ENABLED`, `BACKUP_ENABLED`, `EXPORT_ENABLED`, `DELETION_ENABLED` | Explicit lifecycle-operation gates |

## Dependency map

```text
P9.0 Threat model/baseline ─> P9.1 Identity/authz ─> P9.3 API/UI enforcement ─> P9.6 Deploy hardening ─> P9.9 Operational verification
                       ├────> P9.2 Secrets/config ────────────────────────────────────────────────┤
                       ├────> P9.4 Observability/limits ─> P9.5 Cost safeguards ───────────────────┤
                       └────> P9.7 Maintenance ─> P9.8 Backup/export/deletion ─────────────────────┘
```

---

## Phase 9 — Harden and deploy

### P9.0 — Establish the personal-use threat model and operational baseline

**Dependencies:** Phase 8 completion review

**Goal:** decide what must be protected before exposing real data.

**Work:** document assets/data classes, trust boundaries, authorized identities, provider-data flow, retention, abuse/failure cases, recovery objectives, and residual risks. Inventory all routes, stores, workers, secrets, logs, queues, and external adapters; create synthetic security/operations fixtures and a pre-hardening baseline.

**Requirements:** name an owner for each risk and operating control, state the
assumed deployment/account boundary, and distinguish controls implemented in
application code, cloud configuration, provider contract, and manual process;
revisit the model after every material provider or data-flow change.

**Acceptance criteria:** the model identifies public access, cross-owner access, secret leakage, destructive jobs, runaway costs, stale evidence, and backup/delete risks with accountable mitigations; no production credentials or private data appear in documentation/tests.

### P9.1 — Select and implement personal authentication and authorization

**Dependencies:** P9.0  
**Decision required:** yes

**Goal:** replace the Phase 1 `local` identity safely.

**Work:** select a personal-use identity provider/session model; verify issuer/audience/signature/expiry; map stable subject to owner ID; enforce authorization in API, repositories, SSE reconnects, workers, exports, and UI. Plan a deliberate migration for existing `local` records, with rollback and no accidental sharing.

**Requirements:** define account bootstrap/recovery and lost-device/session
revocation procedures; require reauthentication for export/deletion or another
documented equivalent control; migration is dry-run capable, idempotent, and
keeps an auditable mapping without exposing an old identifier to other users;
deny by default; never accept owner ID from client input; use short-lived
secure sessions and CSRF protection where applicable; protect health/admin
endpoints appropriately.

**Acceptance criteria:** tests prove unauthenticated denial, cross-owner denial for every resource type, token/session failures, stream authorization, and safe local-development identity handling.

### P9.2 — Manage secrets, configuration, and provider-data policy

**Dependencies:** P9.0

**Goal:** make credential and data handling deliberate across environments.

**Work:** move secrets to Secret Manager, use workload identity/service accounts with least privilege, validate configuration at startup, rotate/test credentials, and document provider retention/training/data-residency choices. Maintain sanitized examples only in source control.

**Requirements:** differentiate mandatory versus optional provider settings;
rotation must permit a staged cutover and a failed rotation must not expose a
previous secret in logs or diagnostics; revoke obsolete development access.

**Acceptance criteria:** secret scanning and configuration tests find no committed secret; services have only required secret/database/queue permissions; logs and error paths redact credentials and sensitive payloads.

### P9.3 — Apply authorization, validation, and abuse protections end-to-end

**Dependencies:** P9.1, P9.2

**Goal:** make every externally reachable operation safe for one personal account.

**Work:** review routes/SSE/CORS/headers/input limits/upload/fetch policies, worker push authentication, replay/idempotency controls, and secure defaults for dev versus deployed environments. Restrict research adapters to approved destinations and preserve content-size/time limits.

**Requirements:** maintain an authorization matrix covering method/resource/
owner/admin action; use consistent safe 401/403/404 behavior that does not
confirm another owner’s data; security headers and CORS origins are explicit
per environment, never wildcarded in production.

**Acceptance criteria:** automated tests cover authorization matrix, malformed/oversized input, SSRF-like source handling, forged worker delivery, replay, and safe error responses.

### P9.4 — Add privacy-aware observability and rate limits

**Dependencies:** P9.0, P9.3

**Goal:** diagnose reliability without collecting chat/evidence content by default.

**Work:** define structured metrics, traces, audit events, alerts, retention, and access policy using IDs/counts/durations/error classes only; add per-identity and per-adapter rate/concurrency limits with user-safe retry feedback.

**Requirements:** audit events record actor, action, target class/ID, result,
and correlation ID; observability access is itself restricted and audited;
alerts have named severity, owner, threshold, and response playbook.

**Acceptance criteria:** operational dashboards identify API/worker/provider failures and queue backlog without raw prompt/output logging; tests prove limits, redaction, and auditability of privileged operations.

### P9.5 — Implement cost safeguards and kill switches

**Dependencies:** P9.2, P9.4

**Goal:** cap surprise LLM, search, storage, and worker spend.

**Work:** enforce request/identity/day budgets, model token limits, research iteration/provider quotas, concurrency caps, provider timeouts, budget alerts, and independently configurable feature/provider kill switches. Make denial state explicit and non-destructive.

**Requirements:** define how budgets are reserved, reconciled, reset, and
manually overridden; store only safe usage aggregates; an alert is not a limit,
so enforce a hard cap before a provider call and make emergency disablement
effective without a redeploy where infrastructure permits.

**Acceptance criteria:** synthetic usage proves every cap/alert path, fails closed on unknown cost state where configured, and preserves ordinary local/offline testing.

### P9.6 — Deploy hardened API, UI, workers, and data services

**Dependencies:** P9.1–P9.5

**Goal:** deploy the intended simple serverless topology with secure defaults.

**Work:** update infrastructure-as-code/scripts for separate service accounts, private/authenticated API access, verified worker push, Firestore/Pub/Sub indexes/configuration, minimum necessary egress, secret bindings, staged environments, and rollback. Run a pre-production checklist with synthetic data.

**Requirements:** pin/deploy immutable build artifacts, validate configuration
and migrations before traffic shift, set resource/time/concurrency limits, and
make rollback preserve compatible data schemas; production apply commands
require an explicit target environment and reviewable change set.

**Acceptance criteria:** deployment is repeatable, health checks work, unauthorized public access is rejected, rollback is documented/tested, and production configuration is not committed.

### P9.7 — Schedule safe maintenance for memory and evidence

**Dependencies:** P9.3, P9.6

**Goal:** run lifecycle work reliably without altering user data unexpectedly.

**Work:** configure authenticated scheduled triggers for Phase 4 consolidation/expiry and evidence TTL processing, lease/idempotency/dead-letter handling, bounded batches, monitoring, dry-run mode, and operator pause controls. Revalidate authorization/retention before each destructive-eligibility transition.

**Requirements:** schedules use a dedicated least-privilege identity and
non-overlapping execution/lease policy; dead-letter handling requires an
operator decision before replay; no maintenance job physically deletes data
outside the explicit P9.8 lifecycle.

**Acceptance criteria:** duplicate, delayed, failed, and paused jobs do not corrupt state; expiry affects eligibility as designed; maintenance is observable and can be stopped safely.

### P9.8 — Deliver backups, export, and deletion controls

**Dependencies:** P9.1, P9.2, P9.6, P9.7

**Goal:** give the owner control of durable personal data.

**Work:** define encrypted backup scope/retention/restore drills; implement authenticated owner export with a documented portable schema and audit event; implement explicit deletion requests for conversations, memories, research/evidence, derived records, and appropriate backup/provider limitations. Use confirmation, job tracking, and deletion certificates/status—not silent irreversible actions.

**Requirements:** export files use time-limited delivery/storage and are
encrypted at rest/in transit; deletion requests are authenticated,
idempotent, cancellable only before the irreversible stage, and visible only
to the requesting owner; restore procedures cannot reintroduce data that has
passed its documented deletion/backup-retention window. Deletion semantics
distinguish tombstone, immediate access removal, scheduled physical deletion,
and backup expiry; Phase 4 forgetting remains separate from deletion.

**Acceptance criteria:** synthetic restore and export tests work; deletion tests prove owner scoping, derived-data cleanup, retry safety, audit trail, and accurate limitation reporting.

### P9.9 — Track evaluations, regressions, and release readiness

**Dependencies:** P9.0–P9.8

**Goal:** keep experiments safe after deployment.

**Work:** version fixture suites and policy/model/provider configuration; run offline evaluations in CI, retain sanitized result summaries, define regression thresholds and promotion/rollback gates, and execute an end-to-end production-readiness rehearsal with synthetic data.

**Requirements:** a result artifact identifies code/build, configuration,
fixture version, environment class, and pass/fail threshold; baseline updates
require review with the reason for changed expected behavior; failed gates block
automatic promotion and have a named remediation/rollback owner.

**Acceptance criteria:** a release cannot silently change a measured memory/research/ranking behavior without a comparison record; security, backup/restore, export/deletion, budget, and deployment checklists are complete; documentation states residual risks and operating procedures.

**Release handoff:** publish an operator runbook covering incident response,
service/provider outage, rate/cost emergency, key rotation, rollback, worker
pause/replay, backup restore, export/deletion support, and evaluation
regression. Link it from deployment documentation and review it on each
material architecture or provider change.

## Phase 9 completion review

Before declaring Phase 9 done, verify all task acceptance criteria and answer:

1. Is every API, stream, worker, datastore, export, and deletion request authenticated and owner-authorized?
2. Are secrets, logs, provider data handling, costs, and deployment identities reviewed and least-privilege?
3. Can the owner recover data, export it, request deletion, and understand retention limitations?
4. Are scheduled lifecycle jobs bounded, authenticated, observable, and idempotent?
5. Do release gates compare evaluations and support a safe rollback?
6. Is the system honestly documented as a private personal deployment—not a public or compliance-certified service?

Only after all answers are yes is the planned personal AI system ready for intentional private use and continued experiments.
