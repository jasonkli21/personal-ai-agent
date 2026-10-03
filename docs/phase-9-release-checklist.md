# Phase 9 release checklist

Use synthetic records only. Every row requires a named operator, code revision,
date, evidence link, and pass/fail result before production access.

| Gate | Required evidence | Current state |
| --- | --- | --- |
| Identity and owner authorization | Exact Google client audience/account, Gmail or Workspace domain verification, cross-owner matrix, safe 401/403/404, active stream/reconnect checks | Code checks added; real sign-in/staged IAM not run |
| Legacy owner migration | Backup, dry-run counts, reviewed `usr_` target, preconditioned migration, post-migration owner counts | Tool implemented; no project or backup touched |
| Secret and provider policy | Numeric Secret Manager versions, least-privilege bindings, provider retention/training/residency approval, rotation rollback | Script and register added; account/project/provider review open |
| Abuse and cost | Malformed/oversized input, per-owner minute limit, daily provider/token reservation, feature and provider switches, denial retry behavior | Unit-level controls implemented; Cloud Run concurrency/provider meters not verified |
| Telemetry | Redaction tests, log access policy, retention, alerts/dashboard thresholds and owner | Allowlisted request logs implemented; cloud alerts/access policy not provisioned |
| Worker | Pub/Sub service-account token, exact audience, malformed/duplicate/retry behavior, bounded concurrency | Application verifier and IAM script added; no Pub/Sub/Cloud Run rehearsal |
| Maintenance | OIDC scheduler identity, paused-job run, idempotency, expiry eligibility, pause and retry behavior | Handler and paused schedule script added; no schedule run |
| Backup/restore | Encrypted backup scope/retention, restore into isolated project, deletion-aware restore test | Script supports an opt-in daily 30-day Firestore schedule; no schedule was created and no restore or deletion-aware restore test was run |
| Export | All owner collections, portable schema, record/byte limit, audit, authenticated download, no-store behavior | Bounded JSON endpoint and account download UI implemented; Firestore fidelity and browser download not verified |
| Deletion | Confirm/cancel workflow, immediate access removal, all derived data, backup/provider limits, retry-safe physical deletion and certificate | Request/audit state implemented only; physical deletion is not implemented; production blocker |
| Evaluation and rollback | Build/config/fixture versions, sanitized baseline comparison, blocking thresholds, immutable image, traffic rollback rehearsal | Offline suites and immutable image deployment exist; no release-result store, approval workflow, or staging rehearsal |
| Production approval | All prior gates passed by named operator; explicit target and change review | Not granted by this implementation task |

Do not mark Phase 9 complete until every release blocker has evidence. The code
repository cannot attest to provider contracts, cloud IAM state, production
backup integrity, or operator approval.
