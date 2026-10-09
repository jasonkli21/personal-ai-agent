# Phase 19 implementation guide — Provider usage accounting and quota ledger

Phase 19 records what the configured provider path actually sends and observes,
with separate logical invocation and physical attempt identities. The
[implementation evidence](phase-19-implementation-evidence.md) records the
local checks and the database/provider gates that remain open. This phase does
not select or route to a different model provider.

## Invocation and attempt lifecycle

- [`usage/contracts.py`](../../backend/src/personal_ai/usage/contracts.py)
  defines safe endpoint, invocation, attempt, usage, quota, and accounting
  contracts. Attributions keep provider/model, endpoint/profile version,
  account/project/tier, credential scope/class, execution/cost mode,
  application/workspace/task, request/run, and routing lineage separate.
- [`usage/context.py`](../../backend/src/personal_ai/usage/context.py) carries
  the validated owner/application/workspace/request context and bounded task/run
  labels across nested service work. Unscoped development calls receive unique
  request identities.
- [`usage/accounting.py`](../../backend/src/personal_ai/usage/accounting.py)
  constructs logical invocation identities and conservative unit reservations.
  [`usage/async_call.py`](../../backend/src/personal_ai/usage/async_call.py)
  gives directly implemented HTTP adapters the same reserve-before-send and
  settle-after-response lifecycle used by the LiteLLM gateway.
- [`llm/litellm_gateway.py`](../../backend/src/personal_ai/llm/litellm_gateway.py)
  reserves each intercepted physical transport request before handing it to
  HTTPX. Hidden SDK retries are disabled and a second send is rejected unless
  it has an explicit new attempt. Search and lookup providers use the shared
  async accounting bridge.

An admitted attempt is a physical send, not a retry estimate. A denied
pre-dispatch reservation creates no attempt row and does not inflate send or
retry counts. Timeouts and interrupted sends remain unknown/uncertain under the
original identity and reservation; unresolved outcomes fence replay. A later
explicit attempt needs a new ID and its own admission.

## Admission and quota state

- [`routing/contracts.py`](../../backend/src/personal_ai/routing/contracts.py)
  supplies quota bucket authority, unit, window/reset, source, confidence, and
  freshness facts. Bucket IDs represent shared provider/account capacity;
  endpoint and credential attribution remain on their individual attempts.
- [`persistence/postgres_usage.py`](../../backend/src/personal_ai/persistence/postgres_usage.py)
  locks request budgets, endpoint cooldowns, and every applicable quota bucket
  in one Postgres transaction. Attempt/token ceilings and known exhausted
  buckets deny before dispatch. All required bucket reservations commit
  together. Unknown capacity is retained as unknown and tracked with local
  reserved/consumed units; it is not replaced with a guessed limit.
- Provider rate-limit headers are reduced to bounded numeric limit, remaining,
  reset, and retry-after facts. Freshness and confidence are stored separately;
  provider-reported quota is never equated with a Personal AI billing or
  remaining-capacity guarantee.
- Endpoint health stores outcome, latency, failure streak, and cooldown by
  profile version. Cooldown prevents another send until its deadline.

`STRICT_FREE`, `EXPLICIT_BYOK`, and opaque subscription/cost classes remain
separate attribution. Phase 19 does not add billing aggregation, spending
budgets, scarcity scoring, or provider selection.

## Persistence, export, and retention

- Migration
  [`017_provider_usage_accounting.sql`](../../backend/src/personal_ai/persistence/migrations/017_provider_usage_accounting.sql)
  creates canonical Postgres invocation, attempt, quota reservation/window,
  endpoint health, and owner-attributed daily aggregate records. Postgres is the
  admission and settlement authority.
- [`persistence/dynamodb_usage.py`](../../backend/src/personal_ai/persistence/dynamodb_usage.py)
  stores bounded, owner/app/workspace-scoped operational attempt events and
  minimal expiry locators. Event publication can be reconciled from Postgres by
  invocation/attempt IDs; DynamoDB does not duplicate the canonical ledger.
- Account export/deletion inventory includes the owner-attributed Postgres
  records and DynamoDB events. Shared quota-window snapshots and endpoint
  health are operational account/profile state, not owner export rows.
- Retention uses bounded explicit Postgres and DynamoDB deletes. DynamoDB TTL
  is only a secondary expiry marker, not the cleanup mechanism. Stale pending
  attempts are marked unknown and keep their quota reservations.

## Developer summary and provider safeguards

`GET /v1/developer/provider-usage?days=30` returns a bounded summary for the
validated owner/application/workspace. `PROVIDER_USAGE_INSPECTION_ENABLED`
defaults off. The response contains compact counts, latency, usage-confidence,
quota observation, and endpoint-health facts; it excludes prompts, responses,
secrets, raw headers, and reasoning. Missing quota evidence is shown as
unknown.

Brave search remains separately gated. Startup configuration requires explicit
prepaid account, no automatic reload, no paid balance, and source-rights
attestations. There is no postpaid overflow path. Public Nominatim/OpenFoodFacts
quota capacity stays unknown unless authoritative observations are available.

## Configuration and verification boundary

Usage limits, retention, stale-attempt age, cooldown, provider-header freshness,
and inspection are bounded settings documented in
[`backend/.env.example`](../../backend/.env.example). The developer summary is
not a substitute for deployment auth or a provider account review. Apply
migration 017 before persistent accounting is enabled in a database-backed
environment. Deterministic fake tests do not establish Postgres transaction
behavior, DynamoDB Local behavior, IAM, provider usage semantics, account tier,
source rights, or cloud retention. Those checks remain external acceptance
gates recorded in the evidence.
