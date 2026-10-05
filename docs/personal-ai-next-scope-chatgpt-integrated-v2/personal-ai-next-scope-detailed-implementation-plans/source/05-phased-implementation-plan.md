# Phased Implementation Plan

Status: integrated next-scope plan  
Date: 2026-10-05

## Overview

This plan combines:

- domain-context federation for Travel, Shopping, Finance, and Health;
- strict-free hosted inference routing;
- explicit Gemini + Groq + Cloudflare provider support;
- Firestore + Cloud Storage storage tiering.

This update adds a fourth, purely additive workstream:

- **ChatGPT-plan integration through Sign in with ChatGPT**, implemented as an explicit user-selected provider lane plus a reusable AI sidecar. It does not replace, weaken, or automatically participate in Gemini/Groq/Cloudflare strict-free routing.


The repository should not be reset or rewritten.

The phases are intentionally narrow. Provider integration, accounting, object storage, routing, evaluation, and quota optimization are separate phases.

ChatGPT account integration is intentionally grouped into one Phase 17 block with four subphases because it is one additive user-facing capability built on top of that completed substrate.

Numbering is local to this handoff. Phase 0 must reconcile it with the actual repository roadmap first.

---

# Phase 0 — Reconcile with current repository and roadmap

## Goal

Map this handoff onto actual code before changing behavior.

## Tasks

- Review current docs, ADRs, implementation/release records, verification gaps.
- Map:
  - LLM/provider access,
  - structured generation,
  - embeddings,
  - Firestore repositories,
  - context,
  - memory,
  - research/search,
  - domains,
  - auth/policy,
  - tracing/evaluation.
- Confirm current Gemini generation/embedding paths.
- Confirm Firestore vector/index dependencies.
- Produce reuse/refactor/missing/defer map.
- Update authoritative roadmap/docs.

## Acceptance criteria

- No major refactor starts from hypothetical module assumptions.
- Existing regression surface is identified.
- Phase numbering is reconciled with the repository.

---

# Phase 1 — Application and workspace identity

## Goal

Make every request explicitly application-aware.

## Tasks

- Add/verify `application_id`.
- Add optional `workspace_id`.
- Thread through API, conversation, memory scope, tracing, tools.
- Define canonical app IDs.
- Preserve standalone use.

## Acceptance criteria

- App namespaces cannot leak.
- Existing chat works.
- Traces identify app/workspace.

---

# Phase 2 — Application registry and manifest model

## Goal

Move app capabilities/policy into registration.

## Tasks

- Define `ApplicationDefinition`.
- Add registry.
- Register providers/tools/memory/sensitivity/cross-app metadata.
- Add initial app definitions/stubs.

## Acceptance criteria

- Adding an app does not require core branching.
- Invalid definitions fail clearly.

---

# Phase 3 — Context source and provider abstraction

## Goal

Normalize structured domain-context access.

## Tasks

- Define context source classes.
- Define provider capabilities/interfaces.
- Normalize context item/provider response.
- Carry provenance, authority, sensitivity, timestamps, refs.
- Wrap existing memory where appropriate.
- Add fixtures.

## Acceptance criteria

- Core orchestration does not query domain databases.
- Context retains source identity.

---

# Phase 4 — Context builder refactor

## Goal

Make context assembly explicit, budgeted, and sensitivity-aware.

## Tasks

- Extend/refactor current context assembly.
- Combine conversation, memory, domain, research, tools.
- Add global/per-source budgets/priorities.
- Preserve provenance/authority.
- Compute effective sensitivity.
- Add structured debug output.

## Acceptance criteria

- Final context can be reconstructed.
- Budgets are enforced.
- Effective sensitivity is deterministic.

---

## Checkpoint A — Domain-context foundation

Review Phases 1–4.

---

# Phase 5 — Deterministic context planner

## Goal

Retrieve only relevant bounded context.

## Tasks

- Define planner.
- Implement deterministic categories/rules.
- Select provider/fields/history window/result limit/budget.
- Define unavailable-provider fallback.
- Avoid an LLM planner initially.

## Acceptance criteria

- Representative requests fetch narrow relevant slices.
- Unrelated sensitive fields are not requested.

---

# Phase 6 — Provenance and context inspection

## Goal

Make effective model context auditable.

## Tasks

- Trace planning/provider/policy/exclusion/token decisions.
- Correlate request IDs.
- Add development inspection.
- Redact sensitive values.

## Acceptance criteria

Developer can explain source selection, exclusion, authority, and token use.

---

# Phase 7 — Permissions and sensitivity policy

## Goal

Prevent inappropriate context/model-provider access.

## Tasks

- Define sensitivity.
- Define app/provider/field policy.
- Enforce pre-retrieval authorization.
- Add deny-by-default cross-app rules.
- Pass trustworthy effective sensitivity to inference runtime.

## Acceptance criteria

- Sensitive Health context is deny-by-default outside Health.
- Unauthorized data is not fetched first and filtered later.

---

## Checkpoint B — Policy gate

Review Phases 5–7.

---

# Phase 8 — Provider-neutral inference and embedding contracts

## Goal

Create neutral seams without intelligent routing.

## Tasks

- Reconcile stream-only chat contract with structured generation.
- Add minimal neutral generation operations.
- Add explicit embedding boundary with model/dimension metadata.
- Add fake backend.
- Migrate representative existing Gemini call paths incrementally.

## Acceptance criteria

- Higher-level migrated paths need no provider SDK import.
- Current chat streaming remains functional.
- Vector compatibility is preserved.

---

# Phase 9 — Concrete provider adapters: Gemini, Groq, Cloudflare

## Goal

Prove the provider boundary against the three explicitly planned providers without adding routing policy.

## Tasks

### Gemini
- migrate existing generation behind neutral backend;
- migrate structured memory extraction behind neutral backend;
- preserve existing Gemini embeddings initially.

### Groq
- add provider/backend integration;
- support the minimal generation operations needed by actual tasks;
- add fake/contract tests;
- capture rate-limit/usage headers where available;
- verify strict-free configuration against configured Groq Free-plan models.

### Cloudflare Workers AI
- add provider/backend integration;
- support the minimal generation operations needed by actual tasks;
- add fake/contract tests;
- verify strict-free configuration only against Workers Free-eligible models.

### Shared
- use LiteLLM internally where it reduces duplication, or native adapter where cleaner;
- keep all provider-specific details below the boundary;
- do not add benchmarking, quota-aware selection, cascades, or generalized provider discovery in this phase.

## Acceptance criteria

- Gemini, Groq, and Cloudflare can satisfy neutral contracts in opt-in compatibility checks.
- Strict-free tests never require paid provider paths.
- No provider-specific types leak into context/domain logic.

---

# Phase 10 — Provider/model registry and strict-free eligibility

## Goal

Describe endpoint capability/privacy/free eligibility independently of routing.

## Tasks

- Model profile schema.
- Enabled/strict-free flags.
- Capabilities and context/output limits.
- Provider data-policy metadata.
- Quota/reset metadata.
- Initial profiles for:
  - Gemini configured free-tier models,
  - Groq configured Free-plan models,
  - Cloudflare configured Workers Free models.
- Strict-free admission guard.

## Acceptance criteria

- Paid/ineligible endpoints cannot enter strict-free candidate sets.
- Unknown data policy can conservatively exclude sensitive use.
- Current quota numbers are not application constants.

---

# Phase 11 — Provider usage accounting and quota ledger

## Goal

Measure capacity before optimizing it.

## Tasks

- Record provider/model/task per invocation.
- Capture token usage where available.
- Record latency/success/429/5xx/retries.
- Add health/cooldown.
- Add quota/reset state with confidence/source.
- Expose compact developer summaries.

## Acceptance criteria

- Every normalized invocation is attributable.
- Unknown quota state remains unknown.

---

# Phase 12 — Cloud Storage artifact tier and retention

## Goal

Keep bulky immutable observability/evaluation/export artifacts out of Firestore.

## Tasks

- Define `ArtifactStore` and `ArtifactRef`.
- Add fake/in-memory implementation.
- Add private GCS implementation.
- Add compressed JSON/JSONL support.
- Persist compact artifact metadata/reference in Firestore.
- Initial use:
  - detailed routing/context traces,
  - raw evaluation output,
  - account export bundles,
  - debug/replay artifacts.
- Add retention classes and deletion behavior.
- Add storage-usage observability for Firestore and GCS.
- Keep memory vectors and operational records in Firestore.
- Define conservative artifact-write guardrails so optional traces/evals can stop before known free GCS operation/storage ceilings.

## Acceptance criteria

- Raw evals/traces can avoid Firestore storage.
- Firestore still holds queryable summaries/references.
- No public artifact access.
- Optional artifact failure does not fail successful inference.
- Export artifact failure is explicit.
- No DynamoDB dependency.

---

## Checkpoint C — Inference and storage substrate

Review Phases 8–12.

Do not proceed to smart routing if:

- provider-specific API details still leak upward,
- strict-free cannot be enforced,
- usage cannot be measured,
- verbose telemetry still requires Firestore,
- vector compatibility is unclear.

---

# Phase 13 — Deterministic task-aware routing

## Goal

Select eligible free models using transparent task rules.

## Tasks

- Define small task taxonomy.
- Add routing requirements: capability, sensitivity, context size, quality floor, escalation.
- Hard eligibility filtering.
- Fixed task-specific priorities.
- Trace rejection/selection.
- Route chat plus at least two non-chat subtasks.

## Acceptance criteria

- No round-robin.
- Privacy/capability precede scoring.
- Known task type does not require an LLM classifier.

---

# Phase 14 — Cross-provider task evaluation matrix

## Goal

Measure actual task quality.

## Tasks

- Reuse/extend existing fixtures.
- Compare enabled strict-free models:
  - Gemini,
  - Groq models,
  - Cloudflare models.
- Store raw outputs in GCS, summaries in Firestore.
- Version quality profiles.
- Define task quality floors.

## Acceptance criteria

- Router quality assumptions have project-specific evidence.
- Evaluations are bounded/reproducible.
- Strict-free eval mode cannot call paid endpoints.

---

# Phase 15 — Quota-aware routing

## Goal

Treat free quota as scarce, expiring compute.

## Tasks

- Deterministic scarcity policy.
- Consider known/estimated remaining capacity and time-to-reset.
- Preserve scarce stronger free routes when substitutes meet quality floors.
- Reduce scarcity penalty near reset.
- Incorporate cooldown/reliability.
- Trace route reasons.

## Acceptance criteria

- Hard eligibility is never violated to save quota.
- Unknown quota does not create fake precision.
- Quota conservation is measurable.

---

# Phase 16 — Bounded cascades and deterministic validation

## Goal

Use abundant weaker models where safe and escalate only when useful.

## Tasks

- Cascade contract with max depth.
- Deterministic validators for selected tasks:
  - schema,
  - provenance,
  - hard constraints,
  - required fields/citations.
- Escalate to stronger eligible free model.
- Evaluate cascade vs direct stronger-model use.

## Acceptance criteria

- Cascades are bounded.
- Sensitivity cannot widen.
- Adopted cascades improve quality or quota efficiency.

---

## Checkpoint D — Free-runtime gate

Confirm:

- strict-free enforcement,
- Gemini + Groq + Cloudflare integration,
- task routing,
- eval profiles,
- quota accounting,
- GCS artifact behavior,
- bounded cascades.

---

# Phase 17 — ChatGPT account integration and AI sidecar

## Goal

Add ChatGPT-plan access as one coherent, explicitly user-selected capability after the generic Personal AI inference substrate is complete and before domain applications integrate with it.

This phase is **purely additive**. It does not replace, remove, weaken, or reorder the substantive scope of Phases 0–16. Gemini/Groq/Cloudflare remain the automatic strict-free runtime; ChatGPT remains a separate user-entitled lane.

## Phase 17.1 — Authentication and local bridge

### Goal

Add the user-controlled execution boundary required for ChatGPT-plan usage without storing ChatGPT credentials in the managed Personal AI cloud backend.

### Tasks

- Re-verify current Sign in with ChatGPT open-source/local-runtime requirements before implementation.
- Define `ChatGPTPlanBridge` / local-client contract using normalized Personal AI request/output types where practical.
- Implement supported OAuth/OIDC/PKCE registration/sign-in flow.
- Persist stable host/client registration metadata and credentials only in protected local/user-controlled storage.
- Validate ID token identity and required ChatGPT-plan usage scope.
- Implement token refresh, sign-out/disconnect, and revocation/recovery behavior.
- Implement account-specific model discovery.
- Implement direct Responses API streaming behind the bridge using current required request semantics.
- Normalize completed/incomplete/auth/eligibility/usage-limit errors.
- Add fake bridge and contract tests.
- Ensure the bridge never returns reusable OAuth tokens to browser/cloud callers.
- For hosted web integration, define a loopback/local-IPC transport with origin allowlisting and anti-CSRF/request authorization.
- Treat native-mobile support as capability to verify against the supported SIWC flow rather than assuming desktop loopback mechanics apply unchanged.

### Acceptance criteria

- Eligible signed-in user can complete a streamed ChatGPT-plan request through the local/user-controlled runtime.
- No persistent ChatGPT credential appears in Firestore, GCS, Secret Manager, browser storage, logs, traces, analytics, or exports.
- Managed Cloud Run services can operate with zero knowledge of ChatGPT access/refresh tokens.
- Account model list is discovered rather than hard-coded.
- Existing Gemini behavior and Phase 8 neutral contracts remain functional.

---

## Phase 17.2 — Provider/runtime integration, policy, and usage handling

### Goal

Represent ChatGPT-plan usage inside Personal AI's provider/runtime model while keeping it outside automatic strict-free routing, and make connection/usage failures diagnosable without treating opaque ChatGPT-plan allowance as ordinary free-provider quota.

### Tasks

- Add/verify provider metadata fields for:
  - `auth_mode`,
  - `selection_mode`,
  - credential runtime,
  - account-specific model discovery,
  - automation eligibility,
  - provider-hosted conversation-state availability.
- Define `openai_chatgpt_plan` as `explicit_user` and `automatic_candidate=false`.
- Add request envelope fields for explicit provider/model choice.
- Add policy check that explicit provider selection does not bypass context/sensitivity authorization.
- Persist only safe provider/model attribution on completed Personal AI turns.
- Add test proving ChatGPT models can never enter a strict-free automatic candidate set.
- Track safe connection state: connected/disconnected/reauth-required/unavailable.
- Track normalized usage state: available/limit-reached/unavailable/unknown.
- Record per-turn provider/model/latency/status/error metadata.
- Add Manage usage / reconnect / switch-account hooks for UI clients.
- Never infer a reset timestamp from a generic plan/app usage-limit error.
- Add redaction tests for auth headers/tokens/authorization URLs/account metadata.

### Acceptance criteria

- Automatic strict-free routing remains Gemini/Groq/Cloudflare only.
- ChatGPT requests require explicit user/session/request selection.
- No silent fallback occurs in either direction.
- Provider/model attribution is preserved on conversation turns.
- ChatGPT failures produce actionable normalized states.
- The strict-free quota ledger remains semantically separate.
- No auth secret is emitted into tracing/evaluation artifacts.

## Phase 17.3 — Shared AI sidecar UI

### Goal

Provide the shared in-application UX that lets domain apps use Personal AI automatic routing or the user's connected ChatGPT plan without duplicating provider/auth logic.

### Tasks

- Build reusable AI sidecar/drawer shell for desktop/web.
- Define bottom-sheet/full-screen adaptation for mobile-capable clients.
- Add provider selector:
  - Personal AI automatic strict-free routing,
  - ChatGPT plan when connected.
- Add ChatGPT account/model controls and visible `Using ChatGPT plan` status.
- Add bounded context summary/inspector/selector.
- Add Personal AI `ContextPackage` endpoint/model that reuses existing planner/provider/policy/builder semantics.
- Add browser/native bridge client that sends the authorized context package to the local/user-controlled ChatGPT runtime.
- Stream normalized ChatGPT output into the same conversation view used by other providers.
- Add **Copy** action universally.
- Add **Insert** only for explicitly non-authoritative draft/edit surfaces.
- Defer authoritative **Apply** to Phase 23 mutation proposals.
- Persist completed turns in Personal AI with provider/model attribution.
- Keep incomplete/interrupted streamed output transient unless explicitly saved as a draft.
- Add tests for bridge absence, revoked auth, model disappearance, usage-limit errors, and explicit switch back to automatic routing.

### Acceptance criteria

- One sidecar component works with both automatic Personal AI routing and explicit ChatGPT plan mode.
- ChatGPT mode does not resemble or claim to be the user's chatgpt.com session/history.
- Context sent to ChatGPT is inspectable and bounded.
- Copy works without domain mutations.
- No ChatGPT credential crosses into managed cloud persistence.

---

## Phase 17.4 — Domain integration contract

### Goal

Define the reusable contract that Travel, Shopping, Finance, and Health consume in their existing integration phases so ChatGPT-specific UI/auth/provider logic is not duplicated across applications.

### Tasks

- Standardize sidecar launch context around `application_id`, optional `workspace_id`, active entity/view scope, conversation scope, and bounded client context.
- Reuse the existing planner/provider/policy/builder pipeline to produce an inspectable `ContextPackage`; do not create a parallel ChatGPT-only context system.
- Preserve domain ownership: Personal AI may read/reason/propose, while authoritative state and mutation validation remain in the domain application.
- Standardize provider/model attribution and completed-turn persistence for sidecar conversations.
- Standardize action boundaries across domains:
  - **Copy** is universally safe,
  - **Insert** is limited to explicitly non-authoritative draft/edit surfaces,
  - **Apply** is unavailable until the typed mutation-proposal framework exists.
- Define sensitivity-aware domain hooks so lower-sensitivity apps can expose broader context while Finance/Health can require narrower explicit context selection.
- Keep domain-specific sidecar behavior in the existing Travel, Shopping, Finance, and Health phases rather than branching core logic by app name.

### Acceptance criteria

- Domain apps integrate through one shared sidecar/context contract.
- No domain app needs to implement its own ChatGPT authentication or token handling.
- Domain-specific context remains bounded, authorized, attributable, and sensitivity-aware.
- The shared contract does not move authoritative domain state into Personal AI.
- Existing domain-phase scope remains intact; ChatGPT tasks are additive to it.

---

# Phase 18 — Travel integration

## Goal

Validate the complete context + routing architecture on a lower-sensitivity app.

## Tasks

- Implement Travel context providers.
- Exercise profile/current state/research/conversation/memory.
- Route through inference runtime.
- End-to-end tests/traces.

### Additive ChatGPT sidecar tasks

- Integrate the shared sidecar into trip/day/place views.
- Pre-scope context to the active trip/day/entity plus relevant preferences/research.
- Make included trip context visible.
- Support Copy and safe draft insertion where appropriate.
- Keep itinerary writes out of the generic response path until Phase 23.


## Acceptance criteria

- Travel stays authoritative.
- Core has no Travel branching.
- Provider route is inspectable.

---

# Phase 19 — Shopping integration

## Goal

Validate project state, external evidence, constraints, and routing.

## Tasks

- Implement Shopping providers.
- Feed structured requirements to product research.
- Preserve hard/soft constraints.
- Use saved/rejected products.
- Evaluate routing for extraction/rewrite/synthesis.

### Additive ChatGPT sidecar tasks

- Integrate sidecar into project/search/comparison/product views.
- Allow explicitly selected products and active requirements to populate the bounded context package.
- Show the selected product/context set before sending to ChatGPT.
- Support Copy and non-authoritative draft insertion.
- Keep shortlist/requirement mutations behind Phase 23.


## Acceptance criteria

- Recommendations reflect project state.
- Deterministic constraints remain authoritative.
- Personal AI does not own Shopping state.

---

## Checkpoint E — Lower-sensitivity domains

Review Travel + Shopping.

---

# Phase 20 — Finance integration

## Goal

Validate high-value structured state with stricter privacy/provider policy.

## Tasks

- Read-only Finance providers first.
- Distinguish observed/calculated/assumed/AI-interpreted.
- Stricter provenance.
- Finance-specific provider eligibility.
- No implicit mutation.

### Additive ChatGPT sidecar tasks

- Integrate read-only sidecar into portfolio/security/research views.
- Default to the narrow selected security/account/research context needed for the prompt.
- Present broader portfolio/account context as an explicit visible inclusion choice.
- Preserve observed/calculated/assumed/AI-interpreted labels in the context package.
- Support Copy/save-as-draft/research-note flows only where domain policy permits.
- Do not execute trades or financial transactions from generic sidecar output.


## Acceptance criteria

- Finance remains authoritative.
- Ineligible free providers never receive sensitive Finance context.

---

# Phase 21 — Health integration

## Goal

Integrate the most sensitive/flexible domain.

## Tasks

- Read-only Health providers first.
- Flexible structured profile and bounded time queries.
- Field sensitivity.
- Strict provider eligibility.
- Minimal context.
- Mutation proposals only with domain rules.

### Additive ChatGPT sidecar tasks

- Integrate read-only sidecar with strict default context minimization.
- Expose human-readable sensitive context categories (for example current state, sleep/activity window, medications, conditions, diet/restrictions, labs where available) and allow narrowing before send where practical.
- Require existing Health authorization before a category can even be offered.
- Keep generic sidecar output from directly editing medications, conditions, measurements, or clinical records.
- Verify native-mobile SIWC support before embedding credential logic in the mobile client; preserve the existing Health implementation plan regardless of ChatGPT mobile availability.


## Acceptance criteria

- Health is not flattened into memory.
- Cross-app Health access is deny-by-default.
- Routing cannot weaken Health sensitivity.
- Verbose artifacts default to minimal/no retention for sensitive traces.

---

# Phase 22 — Cross-app context federation

## Goal

Enable safe cross-domain intelligence.

## Initial cases

- Health dietary restrictions -> Travel.
- Health ergonomic constraints -> Shopping.
- Travel trip -> Shopping.
- Finance discretionary budget -> Shopping.

### Additive ChatGPT sidecar tasks

- Make cross-app context categories visible when a ChatGPT sidecar request includes them.
- Preserve the most restrictive effective sensitivity in the `ContextPackage`.
- Require explicit user/context-policy permission exactly as for automatic inference.


## Acceptance criteria

- Narrow, auditable access.
- Revocation blocks future retrieval.
- Router reflects the most restrictive context sensitivity.

---

# Phase 23 — Mutation proposal framework

## Goal

Standardize AI-assisted edits without making Personal AI authoritative.

## Tasks

- Define mutation proposal.
- Target app/entity/patch/rationale/source/validation/confirmation/idempotency.
- Domain validation callback.
- User confirmation.
- Return authoritative post-state.

### Additive sidecar Apply path

- Allow a sidecar response to expose **Apply** only when it has been converted into a typed mutation proposal.
- Reuse target app/entity/patch/rationale/source/validation/confirmation/idempotency semantics.
- Treat the producing provider (including ChatGPT) as provenance, never as write authority.


## Acceptance criteria

- No arbitrary direct writes.
- Domain validation mandatory.
- Trace is auditable.

---

# Phase 24 — Smarter context planning

## Goal

Improve selection after deterministic planning has failure data.

## Tasks

- Evaluate misses/over-fetch.
- Add LLM-assisted planning only where justified.
- Route planner calls through strict-free runtime.
- Keep permission constraints outside model.
- Compare quality/token/latency.

## Acceptance criteria

- Measurable improvement.
- Deterministic fallback remains.

---

# Phase 25 — Search and evidence retrieval optimization

## Goal

Give weaker models better evidence.

## Tasks

- Query rewrite experiments.
- Hybrid/source-specialized retrieval.
- Dedup/freshness/reranking.
- Evidence compression/packing.
- Search quota hooks when justified.
- Store bulky experiment artifacts in GCS.

## Acceptance criteria

- Measured end-answer/evidence improvement.
- Provenance preserved.

---

# Phase 26 — Memory retrieval optimization

## Goal

Improve durable personal context without weakening attribution.

## Tasks

- Benchmark current vs hybrid/entity-aware retrieval.
- Task-conditioned memory selection/budgets.
- Packing/compression experiments.
- Measure irrelevant/missed/stale context.

## Acceptance criteria

- Relevance improves without attribution/authority regression.

---

# Phase 27 — Adaptive routing experiments

## Goal

Explore learned routing only after deterministic baselines.

## Tasks

- Complexity classifiers / RouteLLM-style concepts / contextual bandits.
- Shadow/offline first.
- Hard strict-free/privacy/capability filters remain outside learning.
- Compare quality/quota use.

## Acceptance criteria

- No deployment without measurable benefit.
- Deterministic rollback remains.

---

# Phase 28 — Integrated evaluation and hardening

## Goal

Validate the complete multi-app, multi-provider, two-tier-storage platform.

## Evaluate

- app/workspace isolation,
- context relevance/omission,
- provenance,
- authority confusion,
- mutation safety,
- strict-free enforcement,
- Gemini/Cloudflare failure handling,
- quota exhaustion,
- cascade correctness,
- sensitive routing,
- Firestore growth,
- GCS growth/retention,
- artifact authorization,
- deletion/export propagation,
- provider removal/change.

### Additive ChatGPT hardening

- Verify no reusable ChatGPT credential is present in Firestore/GCS/Secret Manager/browser storage/logs/traces/exports.
- Test local bridge origin/client authorization and CSRF/request-nonce protections.
- Test revoked/expired credentials, account switching, model disappearance, consent decline, user/workspace ineligibility, usage-limit reached/unavailable, and interrupted streams.
- Test that ChatGPT never enters automatic strict-free routing.
- Test that switching from ChatGPT to automatic free routing is explicit.
- Test domain sidecar context minimization and Finance/Health sensitive-category controls.
- Test provider/model attribution for persisted turns.
- Test Copy/Insert/Apply action boundaries.


## Acceptance criteria

- No known cross-app isolation failure.
- No known paid-overflow path.
- No sensitivity-unsafe fallback.
- No public/unauthorized artifact path.
- Firestore does not retain avoidable bulky raw evaluation/trace data.
- Provider failures degrade explicitly.
- Regression suites cover quality and resource behavior.

---

## Checkpoint F — ChatGPT-plan integration gate

Confirm during/after integrated hardening:

- managed cloud services never persist ChatGPT reusable credentials;
- local/user-controlled bridge auth and token refresh are robust;
- account model discovery works without hard-coded model IDs;
- ChatGPT remains explicit-only and outside strict-free automatic routing;
- sidecar context is bounded/inspectable;
- Finance/Health context controls are stricter than lower-sensitivity domains;
- ChatGPT failures do not silently change providers or billing paths;
- authoritative mutations still flow only through domain validation + confirmation.

---


# Provider extension policy

The main plan intentionally stops at:

- Gemini,
- Groq,
- Cloudflare Workers AI.

Additional providers such as Cerebras, Mistral, OpenRouter, GitHub Models, and Hugging Face should be added only after a concrete capacity/quality/capability need and through the existing adapter/registry/evaluation path.

They should not require redesigning routing, context, or domain layers.

The ChatGPT-plan integration is a special **user-entitled provider lane**, not one of these optional API-provider extensions. It is implemented as the coherent Phase 17 block and through additive tasks in the downstream domain/hardening phases.


---

# DynamoDB policy

DynamoDB is not part of the current implementation plan.

Revisit only if measured structured/queryable Firestore state approaches the free storage budget **after**:

- bulky artifacts are moved to GCS,
- retention is bounded,
- indexes/vector growth is understood,
- avoidable duplication is removed.

---

# Dependency order

```text
reconcile
 -> app identity
 -> app registry
 -> context providers
 -> context builder
 -> context planner
 -> provenance
 -> permissions
 -> neutral inference contracts
 -> Gemini / Groq / Cloudflare adapters
 -> model registry / strict-free guard
 -> usage + quota ledger
 -> Cloud Storage artifact tier
 -> deterministic routing
 -> cross-provider evaluation
 -> quota-aware routing
 -> bounded cascades
 -> ChatGPT account integration + AI sidecar
 -> Travel
 -> Shopping
 -> Finance
 -> Health
 -> cross-app federation
 -> mutation framework
 -> smarter context planning
 -> search optimization
 -> memory optimization
 -> adaptive routing experiments
 -> integrated hardening
```

Additive dependency block for ChatGPT integration:

```text
existing platform foundation (Phases 0-16)
  -> Phase 17 ChatGPT account integration and AI sidecar
       17.1 authentication and local bridge
       17.2 provider/runtime policy and usage handling
       17.3 shared AI sidecar UI
       17.4 domain integration contract
  -> Travel / Shopping / Finance / Health integrations (Phases 18-21, additive sidecar tasks)
  -> cross-app federation (22)
  -> mutation framework + sidecar Apply (23)
  -> existing optimization/adaptive-routing/hardening (24-28)
```

The original substantive dependency order remains intact. Original Phases 17-27 are renumbered to 18-28 solely to insert the additive ChatGPT Phase 17 block; their scope and ordering are unchanged.


---

# Codex guidance

- Begin with Phase 0 against actual code.
- Preserve working APIs where reasonable.
- Keep phases independently reviewable/testable.
- Update ADRs/docs with accepted boundaries.
- Prefer deterministic offline/fake tests.
- Never hard-code volatile free-tier quota facts into business logic.
- Do not enable Cloudflare models requiring Workers Paid in strict-free mode.
- Keep provider-specific SDK types below the provider boundary.
- Keep vectors/queryable state in Firestore.
- Keep bulky raw artifacts in GCS when retained.
- Do not introduce DynamoDB speculatively.
- Treat Artifact Registry image retention and GCP infrastructure ceilings as part of strict-$0 hardening.
- Do not begin learned routing until deterministic baselines are mature.


- Treat ChatGPT-plan integration as explicit user-entitled inference, not as a strict-free automatic provider.
- Keep SIWC credentials entirely outside managed cloud persistence and browser storage.
- Never scrape/automate/iframe chatgpt.com as an integration substitute.
- Preserve Personal AI conversation/context ownership for ChatGPT turns.
- Do not hard-code ChatGPT account model availability or plan reset times.
- Keep ChatGPT-specific Responses/SIWC limitations inside the bridge boundary.
- Prefer Copy first; enable Insert only for non-authoritative drafts and Apply only through Phase 23 mutation proposals.
