# ADR 0008 — Read-only development context inspection

Status: Accepted (2026-10-01)

## Decision

`CONTEXT_INSPECTION_ENABLED=false` is the default in both applications. The
backend endpoint and frontend route independently reject disabled access with
404. Deployment explicitly sets the flag to false in both services.

When enabled locally, `/development/context` displays the planning estimate for
a conversation's latest completed user turn through the existing Next.js API
proxy and owner-scoped backend endpoint. Its existing assistant is excluded as
`after_latest_user`: the view reconstructs that turn's possible input rather than
pretending an unsent new prompt exists. No provider counting/generation call,
summary refresh, storage mutation, or timestamp update is permitted.

Reports contain budget/reserve/margin totals, labelled counter kind, IDs, roles,
timestamps, character counts, excluded reasons, safe diagnostics, overflow, and
summary coverage/fingerprint/count provenance. They do not duplicate raw prompts,
summary content, credentials, or provider objects. A planning estimate may select
differently than production's provider-authoritative counts.

## Consequences

This is a development aid, not a production admin console or authentication
boundary. It remains disabled on the public bootstrap. Enabling the route does
not make storing sensitive personal data safe.
