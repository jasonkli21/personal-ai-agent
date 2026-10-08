# Phase 14 implementation guide — Provenance and context inspection

Phase 14 extends the gated development inspector with a retained actual-build
chat trace and request correlation. The inspector still shows the estimated
current view separately and never claims to reconstruct a past build from
current state. See the [implementation evidence](phase-14-implementation-evidence.md)
for the tested source tree, checks, and remaining external gates.

## Runtime contracts

- [`context/traces.py`](../../backend/src/personal_ai/context/traces.py)
  defines the versioned `ContextTraceManifest`, bounded source/planning
  decisions, source budgets and provider failures, and the repository contract.
  `context-trace-v1` records request/conversation/turn IDs, schema/policy/planner
  and source-version labels, requested operations, selected and omitted items,
  authority, sensitivity, counts, counter kind, and safe reasons. It contains no
  prompt text, provider payload, credentials, or hidden reasoning. Provider
  source and item IDs are stored as domain-separated SHA-256 fingerprints;
  source versions remain the bounded version labels provided by current source
  adapters. Planning and build decisions are independently bounded and expose
  truncation counts.
- [`persistence/dynamodb.py`](../../backend/src/personal_ai/persistence/dynamodb.py)
  implements `DynamoDBContextTraceRepository` in the existing owner/app/
  workspace-scoped conversation partition. `CTX_STATE` uses a conditional
  sequence update so concurrent appends retain exactly the latest 32 trace
  records; trace payloads are capped at 48 KiB. The trace is written during
  chat preparation before the assistant placeholder and model stream are
  created. A trace write failure stops preparation before a model call.
- [`persistence/factory.py`](../../backend/src/personal_ai/persistence/factory.py)
  exposes the repository through the existing persistence factory. The portable
  account export includes scoped trace records and verifies that the trace set
  did not change during export. The operational sequence marker is not exported
  as user content.
- [`services/chat_turns.py`](../../backend/src/personal_ai/services/chat_turns.py)
  captures the Phase 12 actual-build manifest with the request ID and the user
  and assistant message IDs. Planner selections and decisions come from the
  Phase 13 `ContextPlan`; item decisions, token counts, sensitivity, authority,
  and provider failures come from the existing build manifest.
- [`api/routes.py`](../../backend/src/personal_ai/api/routes.py) reads the
  trace for the latest completed user message under the authenticated owner,
  application, and workspace scope. The development-only route remains gated by
  `CONTEXT_INSPECTION_ENABLED`. It returns the current estimate as
  `estimated_current_view`, plus a separate `actual_build` trace when a retained
  match exists. Otherwise it reports `manifest_missing` with
  `no_retained_manifest_for_latest_user_turn`. Inspection does not write, prune,
  invoke context providers, or call a model. Foreign resources continue to use
  not-found behavior.
- [`frontend/src/lib/conversation-proxy.ts`](../../frontend/src/lib/conversation-proxy.ts)
  forwards allowlisted `X-Request-ID` and preserves the API correlation header.
  The development inspector sends an inspection request ID and displays it
  separately from the generation request ID in an actual trace.

## Storage, privacy, and scope

Traces are compact operational metadata in DynamoDB; bulky trace artifacts remain
Phase 20 scope. The record carries the current code-defined policy and planner
version labels plus source-version labels supplied by existing providers; it
does not snapshot policy/source bodies. No client-supplied owner label grants
access. The repository derives the partition from the server owner and validated
application/workspace scope, verifies conversation metadata before writes, and
checks each trace envelope before reads or export. Read-only inspection never
changes the 32-record retention window.

The root README was reviewed. No README edit was required: this phase adds a
development-gated diagnostic detail that the root README does not currently
describe, and does not change setup, providers, deployment, or user-facing chat
behavior.

## Scope limits

- A missing or expired trace degrades to the explicitly labeled estimated view;
  it does not infer a previous build from current records.
- This repository persists conversation chat-build traces. Standalone research,
  proposal, and booking preparations continue to use their existing Phase 12
  manifests but are outside this conversation-turn trace store.
- The tests use deterministic fakes for the repository boundary. They do not
  establish DynamoDB Local, cloud IAM, deployed retention, external provider,
  or production-security behavior. The fixed `local` owner remains a
  development identity.
