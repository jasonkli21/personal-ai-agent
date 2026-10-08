# Phase 18 implementation guide — Endpoint registry and strict-free admission

Phase 18 adds an internal, versioned endpoint catalog and a deterministic
strict-free admission guard. The [implementation evidence](phase-18-implementation-evidence.md)
records the checks and the provider, account, quota, database, and workflow
gates that remain open. Application workflows still use the existing Gemini
composition; this phase does not select or dispatch a different provider.

## Profile and quota facts

- [`routing/contracts.py`](../../backend/src/personal_ai/routing/contracts.py)
  defines immutable `EndpointProfile`, `CounterCompatibility`, `DataUsePolicy`,
  `QuotaBucket`, candidate requirements, and registry snapshot contracts. A
  profile keeps provider, model, endpoint/deployment, symbolic credential
  reference/scope, account/project/tier, execution mode, cost/billing owner,
  capabilities, context/output limits, privacy ceiling, serializer/runtime,
  counter provenance/confidence/schema coverage, and quota authority separate.
  Strict-free, tier, and verified quota assertions carry bounded evidence
  references scoped to the endpoint/account/credential facts. The schema has no
  credential-value field and forbids unrecognized fields.
- Quota buckets identify their authority scope, operation coverage, unit,
  window, optional reset/observation/freshness and optional current limit or
  remaining amount. A verified exhausted bucket blocks until its reset; when a
  freshness deadline is also present, expired observations are treated as
  unknown. No provider quota number is an application constant.
  Profiles may reference the same bucket after the registry verifies that the
  account, cost mode, and authority facts agree. A shared bucket cannot join
  independent account scopes or execution modes. Credential rotation under
  one verified account can retain the same bucket identity.
- Counter admission binds the counter to the exact profile ID, endpoint,
  deployment, account/credential scope, provider, model, and serializer. A task
  supplies its minimum count confidence and optional schema ID; both the
  endpoint capability and approved counter mapping must cover a required
  structured schema.

## Seeded profiles and configuration

- [`routing/configured.py`](../../backend/src/personal_ai/routing/configured.py)
  seeds the configured Gemini generation endpoint and a separate, unverified
  Gemini embedding endpoint. It adds Groq or Cloudflare Workers AI profiles
  only when their models are configured. Groq and Cloudflare profiles declare
  generation capabilities (plus explicitly verified structured output); they
  do not declare token counting.
- The environment settings in
  [`backend/.env.example`](../../backend/.env.example) default free-tier,
  privacy, counter, and quota membership attestations off. The profile builder
  checks whether a credential exists but records only a symbolic environment
  variable reference. Free/tier verification, provider data-use approval,
  count compatibility, and quota bucket relationships need separate operator
  evidence for the exact account and endpoint. Per-model context/output limits
  are separate optional settings; an unknown required limit excludes the
  endpoint instead of inheriting the application's global context budget.
- `INFERENCE_ADDITIONAL_ENDPOINT_PROFILES` accepts bounded JSON profile facts
  for synthetic or future endpoints. They pass through the same strict schema
  and admission guard; provider names are not an allowlist. Credentials remain
  symbolic references and secret fields are rejected.

## Admission and lifecycle

- [`routing/registry.py`](../../backend/src/personal_ai/routing/registry.py)
  applies deterministic hard filters before strategy selection. Strict-free
  candidates require enabled credentials, verified zero-cost/tier/account
  facts, permitted data use for the request sensitivity, required operations,
  context/output fit, operation-scoped verified quota membership, and any
  required approved exact counter mapping. Fresh known exhaustion rejects the
  affected operation. Unknown or ambiguous bucket membership is not treated as
  a new independent quota pool.
- `EndpointCandidateRequirements` distinguishes a known zero bound from a
  missing bound. Generation needs explicit input/output limits, token counting
  needs a `CountRequirement`, embeddings need dimensions, and search needs both
  query and result limits. Candidate sets retain the exact immutable
  requirements used for assessment.
- `EndpointRegistry.candidates()` returns a complete assessment for every
  configured profile: endpoint facts plus stable rejection codes, with no score
  or provider preference. Registry construction rejects more than 32 profiles
  rather than truncating them. The assessment order follows the configured
  profile order; registry version hashing is order-independent.
- `upsert()` and `remove()` advance the registry snapshot. Repository-backed
  candidate generation and dispatch revalidation reload durable state, so
  changes from another process invalidate stale candidates. Revalidation uses
  the candidate set's original requirements, rejects a changed requirement or
  originally rejected profile, and reruns time-sensitive quota admission.
- Supplying profiles to `EndpointRegistry` or calling `reconcile()` treats
  operator configuration as the desired profile set. Changed facts advance
  versions automatically; omitted profiles are removed. Built-in profile IDs
  stay stable as model/account/credential settings change. A separate Postgres
  high-water table retains profile versions after deletion, and conflicting
  concurrent reconciliation returns a registry conflict for retry.
- [`PostgresEndpointRegistryRepository`](../../backend/src/personal_ai/persistence/postgres_routing.py)
  persists one bounded system-owned snapshot with compare-and-swap revision
  checks and initializes the singleton row atomically. Canonical JSON is
  limited to 128 KiB before persistence, below migration 016's 256 KiB JSONB
  bound. Migration
  [`016_endpoint_registry.sql`](../../backend/src/personal_ai/persistence/migrations/016_endpoint_registry.sql)
  places durable registry facts under Phase 10 Postgres ownership. The
  migration must be applied before using this repository; no local/cloud
  database migration was run for this phase.

## Current boundary

The new candidate API is not connected to chat, research, memory, or other
request workflows. Phase 21 owns the semantic routing strategy and execution
plan. Current traffic remains Gemini-only, Groq/Cloudflare remain unavailable
for count-required tasks, and no account/tier/privacy/quota or live-provider
verification was performed. The root README was updated to describe the
internal registry and package layout; its statement that application workflows
remain Gemini-only is unchanged.
