# Phase 9 personal-use threat model and operational baseline

**Status:** initial baseline, 2026-10-03

**Revision assessed:** `f0d3d9e` (`origin/main`)
**Scope:** one privately operated personal account, synthetic-data staging, and
the current Cloud Run / Firestore / Pub/Sub topology. This is an engineering
baseline, not a penetration test or a compliance assessment.

## Protected assets and data classes

| Asset / data class | Sensitivity | Expected handling |
| --- | --- | --- |
| Conversations, messages, summaries | Private user content | Owner scoped; never in default logs or telemetry |
| Memories and lifecycle records | Private, durable user knowledge | Provenance checked; separate from external evidence; explicit lifecycle gates |
| Research questions, evidence, claims, decisions, domain comparisons | Private query history plus time-sensitive public-source observations | Owner scoped; provider/storage policy and expiry retained; no prompt or passage logs |
| Provider, OAuth, and signing credentials | Secret | Secret Manager in deployed environments; untracked environment files locally |
| Identity-to-owner mapping and audit events | Restricted operational metadata | Least-privilege access, bounded fields, no profile payloads |
| Evaluation fixtures and result summaries | Public/synthetic only | No real prompts, evidence, credentials, or user records |
| Backups and exports | Private copies of all data included in the export | Encrypted, access restricted, retained/deleted by an explicit schedule |

## Trust boundaries and data flows

1. **Owner browser → Next.js web service.** The browser receives Google Identity
   Services (GIS) credentials for the configured web client. Authentication is
   sent only to same-origin application routes over HTTPS. Do not persist ID
   tokens in browser storage or include them in URLs, logs, analytics, or error
   reports.
2. **Next.js → FastAPI.** The web runtime calls a private Cloud Run API using
   its dedicated service identity. It forwards the end-user Google ID token in
   a separate identity header. The API validates the service boundary at Cloud
   Run and validates the signed user token, issuer, audience, lifetime, and
   account allowlist before resolving an owner.
3. **API → Firestore / Pub/Sub / Secret Manager.** Each service identity gets
   only the permissions needed for its role. Repository contracts remain the
   authorization boundary for owner-scoped data. Pub/Sub messages contain
   opaque job IDs, never user content.
4. **API → model/search providers.** A request sends only the content needed by
   the selected feature. Provider rights, retention, training, and residency
   are tracked per adapter; existing Brave, Nominatim, Open Food Facts, and
   Gemini policy gates remain independent and disabled until separately
   approved.
5. **API / worker → telemetry.** Structured operational records contain a
   request/correlation ID, route template, status, duration, bounded counts,
   policy version, and error class. They exclude prompts, message/evidence
   content, tokens, provider payloads, credentials, and sensitive URL query
   values.
6. **Lifecycle operator → export, restore, deletion, and maintenance.** These
   actions are identity-bound, auditable, idempotent, bounded, and fail closed.
   Backups have an explicit retention and deletion-propagation statement.

## Risk register

| Threat | Risk / initial exposure | Required control and control owner |
| --- | --- | --- |
| Public access | Current bootstrap exposes both web and API publicly | API denies unauthenticated requests; web can expose only the sign-in shell; API Cloud Run IAM admits only the web runtime identity. Operator owns load-balancer, domain, and IAM configuration. |
| Cross-owner access | All current services resolve to the fixed `local` owner | Resolve owner only from a verified principal; never accept owner IDs from request bodies; preserve owner filters in every repository and job. Application owner is the API service. |
| Forged identity / token confusion | A client can choose request headers | Verify signed Google ID tokens and exact audience/issuer/expiry; use Google `sub`, not a supplied user ID; protect private API invocation with Cloud Run IAM. |
| Secret leakage | Provider credentials are present in process settings | Secret Manager bindings, typed secret values, allowlisted configuration, redaction tests, rotation procedure. Operator owns IAM and rotation. |
| Destructive or replayed jobs | Maintenance and lifecycle work can be retried | Idempotency keys, fenced leases, bounded batches, authenticated invoker, dry-run, audit trail, and operator review before physical deletion. |
| Runaway provider/storage costs | Existing request bounds do not create a total account spend cap | Per-identity and per-adapter limits, durable request/token budgets before side effects, kill switches, alerts, and a manual provider emergency-stop procedure. |
| Stale or misleading evidence | External records may expire or conflict | Retain source, observation, and expiry; recheck freshness at use; never treat expiry as physical deletion or an external claim as verified truth. |
| Backup/export exposure | A second copy can outlive primary data | Encrypt and scope backups, restrict restore principals, use time-limited encrypted exports, record retention and deletion limitations, test synthetic restore. |
| Telemetry content capture | Framework/provider logs may include sensitive values | Explicit structured allowlist, logging redaction tests, no request bodies/headers, disable HTTP debug traces, inspect Cloud Run logging configuration. |
| Evaluation drift | Experiment changes can silently regress safety or quality | Version fixtures/configuration, retain sanitized results, compare to reviewed baselines, block promotion on failed security/recovery/budget gates. |

## Environment allowlist

| Environment | Identity | Data / provider policy | Deployment and operations |
| --- | --- | --- | --- |
| `local` | Explicit development-only identity; no production fallback | Synthetic or developer-owned data only; all experimental/provider gates off unless deliberately enabled | Local secrets remain untracked; emulator and provider calls are opt-in |
| `test` | Test principal injected by fakes | Synthetic fixtures only; no external network or credentials | Tests fail if they attempt real providers or cloud resources |
| `staging` | Same signed OIDC policy and owner authorization as production | Synthetic, namespaced data only; approved test-provider settings | Separate project, service accounts, secrets, database, and queue; reviewed deployment plan and rollback rehearsal |
| `production` | Deny by default; Google OIDC required; exactly allowlisted personal account; no `local` owner or development bypass | No real personal data until provider policy, backup, export/deletion, alert, restore, and staged-drill gates are approved | Separate project/configuration; explicit target and reviewed immutable release; named operator approves apply |

## Baseline at Phase 9 start

At revision `f0d3d9e`, the API uses an unauthenticated fixed `local` owner;
the deployment script allows unauthenticated web and API access. The API key
uses Secret Manager, and the memory worker is a private Cloud Run service with
Pub/Sub push authentication, but chat/research do not have an application
identity. Feature/provider gates default off. Existing Phase 4 jobs are bounded
and fenced; there is no general scheduler, lifecycle export/deletion, account
backup/restore drill, identity budget, or release-result gate. Offline tests use
fakes and synthetic data. Real Firestore, provider, IAM, staged deployment,
backup, restore, and deletion behavior has not been verified.

## Accepted residual risks and release blockers

- This single-user design is not a general multi-tenant access model and does
  not provide workspace administration, invitations, or account linking.
- A Google ID token is a short-lived bearer credential. Removing the configured
  account allowlist blocks new requests after configuration reload/deploy; an
  already-issued token may remain usable until its expiry unless the owner also
  disables/revokes the Google account or client. Require recent reauthentication
  for export and deletion.
- Google sign-in and Cloud Run IAM prove identity/invocation, not provider data
  rights, semantic correctness, or private-data-safe configuration.
- Production remains blocked until a synthetic staging rehearsal, rollback,
  restore/export/deletion exercise, security and cost gate, and operator approval
  are recorded. No production deploy is authorized by this implementation task.
- The fixed `local` data migration is opt-in, dry-run-first, and must be backed
  up. Existing local records remain inaccessible to the authenticated owner
  until an operator deliberately maps them.

## Review and update triggers

Review after adding an identity provider, provider/data class, route, repository,
worker action, backup/export destination, or deployment boundary; after a
material security incident; and before every production release. Record the
revision, date, results, owner, and remaining gaps in the Phase 9 release record.
