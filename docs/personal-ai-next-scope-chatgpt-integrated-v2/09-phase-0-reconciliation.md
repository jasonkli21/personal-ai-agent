# Comprehensive Phase 0 reconciliation

**Date:** 2026-10-05. **Code revision:** `ad1dea5912af81eda0c9c5d6a41180ce186a07a5` (`ad1dea5`), plus this documentation working tree. **Scope:** repository, product, architecture and execution planning; no substantive implementation. The expanded user review instructions govern this pass.

This supersedes incomplete execution conclusions in the [earlier Phase 0 review](personal-ai-next-scope-detailed-implementation-plans/phase-0-reconciliation-2026-10-05.md), which is retained as historical evidence. Actual code/tests and accepted ADRs describe the baseline; corrected source designs describe intended scope; detailed plans are execution guidance. No handoff document was treated as immutable.

## Review inventory and evidence

Reviewed all eight source design documents, both README/index documents, the earlier review, manifest, all 32 detailed plans and all source mirrors. Repository review covered the project brief, architecture, implementation roadmap, API contract, existing Phase 1–8 guides/plans/releases, Phase 9 plan/evidence/authorization/release/operations documents, verification-gap and dated repository/architecture reviews, dependency/deployment guidance, and ADRs 0001–0020. Relevant test contracts and fakes were checked against services, not just document titles.

Code inspection covered API schemas/routes/dependency wiring; Google auth/principal directory/middleware/account operations; chat turn and branch transactions; context assembler/counters/summaries/inspection; memory extraction/embedding/retrieval/lifecycle/jobs; search and evidence pipelines; entity/claim/constraint/ranking/decision services; single-pass and iterative research; domain comparison modules/adapters; itinerary proposals and booking extraction; repositories/indexes; frontend proxy/auth/API/SSE/chat/research/domain views; settings, Makefile, packaging, CI, Cloud Run/Pub/Sub/Secret Manager/deployment/emulator patterns. Domain applications outside this checkout were not independently inspected or executed.

The former package source mirrors now retain their existing paths as one-hop links to canonical documents. Top-level design files are authoritative; there is no duplicate body to drift. All original snapshot content was reviewed and preserved in the corrected canonical designs. Detailed plans share the [execution contract](personal-ai-next-scope-detailed-implementation-plans/execution-contract.md) rather than repeating generic implementation tasks.

## Verified repository state and capability classification

Classification describes behavior, not entire numbered phases. **Implemented** means local behavior exists; **reusable as-is** means its existing contract can be retained; **partial / extend / refactor** identifies new scope; **duplicated** identifies planning work already owned elsewhere; **missing** means no implementation; **deferred** means optimization awaits evidence; **external only** means local machinery exists but live acceptance remains unverified.

| Capability | Actual evidence and classification | Reconciliation decision |
| --- | --- | --- |
| API/auth/identity | [Principal](../../backend/src/personal_ai/auth/contracts.py), [middleware](../../backend/src/personal_ai/auth/middleware.py), API dependencies and Google verification implement owner auth, private-service separation, safe foreign IDs and correlation. Client owner is not authority. App/workspace identity is **missing**. | Extend existing API/service/repository scope in 1; preserve fixed `local` for local/test only. Forward correlation through the proxy; keep it distinct from idempotency. |
| Conversation/branch/history | [Chat turns](../../backend/src/personal_ai/services/chat_turns.py), [branches](../../backend/src/personal_ai/storage/branches.py) and conversation repositories implement append-only branch/supersession, transactional preparation and conditional terminal writes: **implemented / reusable as-is**. | Extend scope and producing-model metadata without rewriting branch semantics. New external completion uses the same ownership/fencing patterns. |
| Context and working summaries | [Assembler](../../backend/src/personal_ai/context/assembler.py), contracts/deadline and [Gemini counter](../../backend/src/personal_ai/llm/context.py) implement complete-turn budgeting, mandatory newest input, summary coverage and optional memory; research has separate bounded evidence assembly. **Partial foundation; extend in 3–8**. | Keep one builder, add typed sources/per-source manifests and endpoint-specific final fit. Inspector is estimated reconstruction, not historical exact dispatch evidence. |
| Global/profile/tool/client context | AI-owned small global profile and general domain/current/history/tool-result provider contracts are **missing**; current memory is not a canonical global profile. | Implement bounded AI-owned preferences/profile provider in 3; domain profiles/state via 18–21. Advisory client context never grants permission. Side effects wait for 23. |
| Memory extraction/embedding | [Memory services](../../backend/src/personal_ai/memory/services.py), [Gemini memory adapter](../../backend/src/personal_ai/llm/memory.py) and contracts implement exact user-source validation, gated structured extraction and embeddings. **Implemented / needs neutral extension**. Extraction directly calls Gemini with character/output bounds, bypassing shared assembler preparation. | Phase 8 closes this real preparation gap and extends the existing Embedder protocol, rather than inventing another vector subsystem. No weakening of sensitive extraction policy. |
| Memory persistence/retrieval/lifecycle | [Memory repositories](../../backend/src/personal_ai/memory/repositories.py), lifecycle/policy/jobs and fakes implement owner/status/model/dimension-filtered KNN, source validation, fixed/scored/consolidated retrieval, immutable v1/v2 attribution and fenced jobs. **Implemented / reusable**; scope extension needed. | Preserve 768-dimensional normalized Gemini vector space and matching indexes. Forgetting is eligibility, not physical deletion. Hybrid/task-aware improvements in 26 are **deferred**; incompatible migration is intentionally deferred. |
| Search/research/evidence | [Search policy](../../backend/src/personal_ai/search/policy.py), Brave adapter, [evidence pipeline](../../backend/src/personal_ai/evidence/pipeline.py) and research services implement bounded snippet search, constraint-preserving queries, freshness/dedupe, literal cited synthesis and idempotent/fenced iterative runs. **Implemented / reusable**. | No full-page fetch or general fluent synthesis is implied. Basic quota admission belongs in 11; optimized rewrite/hybrid/packing in 25 requires baseline and explicit ADR amendment for semantic changes. |
| Entities/claims/decisions | Entity, decision and ranking contracts implement immutable observations/claims, conservative identity matching, freshness, hard-before-soft constraints and snapshots. **Implemented / reusable as-is**. | Do not recreate matching/ranking per domain or treat canonical research identity as authoritative application state. |
| Provider generation/stream/errors/fakes | [LLMClient](../../backend/src/personal_ai/llm/client.py) is stream-only; Gemini has concrete optional bounded streaming and SDK-only structured memory generation. Fake clients and safe errors exist. **Partial / extend**. No general neutral terminal/usage/structured/count boundary. | Phase 8 extends current seams; 9 adds Groq/Cloudflare. SDK types remain below `llm`. Neutral attribution starts here, not first in ChatGPT UI. |
| Routing/registry/accounting/evaluation | Single configured Gemini injection, HTTP request estimates, iterative ledgers and lookup throttles are **partial**, not a neutral quota ledger. Existing eight fixture evaluation targets are **reusable**. Multi-provider profiles/router/quality matrix/cascades are **missing**. | Separate endpoint eligibility 10, all-operation accounting 11, fixed baseline routing 13, measured profiles 14, scarcity/cascades 15–16. Adaptive optimization 27 remains **deferred**. |
| Domain comparisons/applications | [DomainModule](../../backend/src/personal_ai/domains/contracts.py) and registry implement thin Travel/Shopping comparisons. Nominatim provides public place identity; OFF provides exact-barcode catalog identity. **Implemented / reusable**, but not rich domain applications. Finance/Health providers are **missing**. | Add a small application registry by composition, not by turning comparison modules into app stores. Authoritative app APIs/revisions/auth require external integration evidence. |
| Proposals/extraction | Itinerary proposals and [booking extraction](../booking-document-extraction-contract.md) implement bounded typed validation, opaque/source handles and owner/key fences. **Partial reusable patterns**, not generic domain mutation execution. Booking extraction is locally accepted; its ADR's pending label was stale. | Reuse in 8/18/23; source review candidates are not confirmed domain state. Domain validate → user confirm → domain execute → authoritative post-state remains explicit. |
| Persistence/export/deletion | Distributed Firestore repository protocols, vector indexes, bounded export and audited deletion requests are implemented. Export is bounded, not a verified consistent cloud snapshot. Account deletion stops at `confirmed_pending_operator`; full migration is unsupported. **Partial / existing Phase 9 gaps**. | Keep repository boundaries. Scope all AI record families; legacy query compatibility must not fetch newly scoped foreign-app records, and existing comparison domain labels are not origin-app identity. Artifact lifecycle adds obligations in 12; account-wide erasure/migration/recovery stays owned by existing Phase 9 and must close for release in 28. |
| Artifacts/GCS | No runtime blob/artifact store or GCS provisioning exists: **missing**. | Add private artifact tier in 12, with Firestore reference lifecycle and non-atomic recovery. No second database/DynamoDB implementation. |
| Frontend | Same-origin Next.js cloud proxy, Google tokens in memory, bounded SSE, chat branch state and research/decision/domain comparison views are implemented: **reusable / extend**. No local bridge, ContextPackage selector or shared domain sidecar. | Extend existing feature/state/API/SSE seams; separate paired local transport deliberately, without forwarding Google/IAM secrets. |
| Infrastructure/CI | Cloud Run private API/worker, public web, Pub/Sub, numeric Secret Manager versions, selected indexes, paused maintenance and optional backup paths exist. **Partial / external only**. `deploy.sh` unconditionally enables paid-excluded Firestore TTL for two operational collections. | No existing strict-$0 or production-readiness claim. First affected preflight/ledger/artifact phase gates new resources; 28 closes integrated cloud acceptance. CI runs seven eval targets, not the separate itinerary-proposal eval. |
| ChatGPT | Local runtime/auth/discovery/explicit policy/sidecar are **missing and additive**. Official public SIWC compatibility documentation was checked; actual distribution/account/transport approval is **external only**. | Keep all 17.1–17.4 scope. Verify distribution classification and plan-only controls; do not equate local custody with hosted eligibility or plan entitlement with no credit overflow. |

## Verification of the earlier Phase 0 review

| Earlier assertion | Verified outcome |
| --- | --- |
| Reviewed `24f75a7`, package untracked | Historical only. Current package is tracked at `ad1dea5`; earlier whitespace/link counts are not current evidence. |
| Owner-only scope, existing branch/context/memory/research seams | Correct foundation; verified independently. Scope propagation must include every persisted/derived record and vector filter, not just request JSON. |
| DomainModule can be extended for an application registry | Reuse registration patterns, but application definitions must compose alongside comparison modules instead of conflating responsibilities. |
| Stream-only LLM boundary needs extension | Correct; incomplete about direct extraction bypass, Gemini-only remote counting, terminal completion and actual attribution. Corrected in 8 and source architecture/inference. |
| All accounting remains open | Correct; request/run estimates are not provider accounting. Search admission moved from optional optimization to foundational 11, preserving optimization in 25. |
| Firestore/vector/GCS boundaries | Correct; incomplete about non-atomic writes, generation/version cleanup, required export readiness and account deletion dependencies. |
| CI covers established evaluations | Seven targets are in CI; itinerary-proposal eval exists but is not run there. Tests cover proposal contracts separately. |
| ADR 0020 awaiting coordinator acceptance | Contradicted by the accepted booking contract and later repository acceptance commit. ADR/status prose now reflect local acceptance, without promoting external gates. The external coordinator's reported suites are historical records, not independently rerun here. |
| Serial Phase 17 gates all later domain work | Overconstrained. Shared sidecar tasks require 17.4; baseline domain/backend work requires the existing substrate. Preserve blocked additive tasks explicitly instead of removing domains. |
| Mandatory authoritative-write confirmation | Correct accepted correction. Propagated remaining source-design wording so provider choice or domain callback cannot bypass confirmation. |
| Next Phase 1 locally implementable; production blocked | Confirmed after comprehensive reconciliation. Phase 1 is offline identity/scope work only; no next-phase code was written. |

## Phase prerequisites and implementation-state allocation

Numbers are **next-scope** numbers. Prerequisites are exact delivered-contract requirements, not an artificial dependency on every preceding number. The manifest records the same graph; it is acyclic. Recommended execution order remains numerical and no phase is renumbered in this pass.

| Phase | Required prerequisites | State and work remaining |
| --- | --- | --- |
| 0 | none | Documentation reconciliation complete after verification below; no implementation. |
| 1 | 0 | Owner auth reusable; app/workspace identity and all-record/vector isolation missing. |
| 2 | 1 | Comparison registration reusable; separate application manifests missing. |
| 3 | 1, 2 | Memory/evidence wrappers reusable; typed source/provider contracts and bounded global profile missing. |
| 4 | 3 | Existing builder needs multi-source budgets, sensitivity and actual-build manifests. |
| 5 | 4 | General deterministic context planner missing; research query planner stays separate. |
| 6 | 5 | Gated inspector reusable; captured provenance and proxy correlation need extension. |
| 7 | 3, 5, 6 | Source isolation enforced earlier; full field/provider/sensitivity and revocation policy missing. |
| 8 | 4, 7 | Neutral generation/count/embedding/completion and extraction preparation need refactor. |
| 9 | 8 | Gemini migration reuses 8; Groq/Cloudflare concrete adapters missing. No routing here. |
| 10 | 7, 9 | Profile registry and strict-free admission missing. |
| 11 | 10 | Full operation/account quota ledger missing; reuse request/run fences; include search. |
| 12 | 1, 6, 11 | GCS/reference/retention/export/deletion and resource guards missing. |
| 13 | 8, 10, 11 | Fixed task-aware routing missing; quality explicitly unmeasured until 14. |
| 14 | 12, 13 | Reuse existing fixtures; cross-provider measured profiles missing. |
| 15 | 14 | Quota scarcity policy deferred until measured baseline. |
| 16 | 15 | Bounded validated cascades deferred until measured baseline. |
| 17.1 | 8, 10 | New local bridge/auth/discovery; external approval/plan-only/transport gates. |
| 17.2 | 11, 13, 17.1 | Explicit lane policy and external-turn lifecycle, with client-report trust. |
| 17.3 | 6, 17.2 | ContextPackage endpoint and reusable UI/client; reuse completion from 17.2. |
| 17.4 | 17.3 | Domain launch/context/action hooks; consume shared auth and persistence. |
| 18 | 7, 13, 16 | Travel authoritative read adapters; comparisons/proposals reusable. |
| 19 | 7, 13, 16 | Shopping authoritative project providers; comparisons/constraints reusable. |
| 20 | 7, 13, 16 | Finance read-only providers and strict semantic/privacy contracts missing. |
| 21 | 7, 13, 16 | Health minimal read providers and field sensitivity missing. |
| 22 | 7, 18–21 | Four narrow explicit grants/broker cases missing; revoke all derived reuse. |
| 23 | 7, 18–21 | Proposal patterns partial; generalized domain validate/confirm/apply/reconcile missing. |
| 24 | 14, 22 | Measured context planning improvement deferred; deterministic fallback remains. |
| 25 | 11, 12, 14 | Retrieval/query/evidence experiments deferred; reuse quota admission and grounding. |
| 26 | 1, 4, 8, 14 | Hybrid/entity/task memory optimization deferred; existing variants are baseline. |
| 27 | 14–16 | Adaptive shadow experiments deferred; no hard-filter learning. |
| 28 | 12, 17.4, 22–27 | Integrated negative/quality/resource matrix and existing Phase 9 release closure. |

**Conditional edges:** all additive domain sidecar tasks in 18–23 require 17.4. They can be implemented/tested against a supported fake contract while live ChatGPT remains unavailable, but a real integration is not complete without its external acceptance. Baseline domain work need not wait for ChatGPT approval. Plans 18–21 do not technically depend on each other; their recommended sequence shares integration lessons. Phase 23 does not require federation as a prerequisite for same-app proposals. Phase 24 consumes implemented cross-app/domain baseline data; 25/26/27 can run independent experiments once their own prerequisites exist.

**Release edges:** existing Phase 9 full owner migration, physical deletion, provider-data/privacy and operational acceptance are additional release dependencies. Offline next-scope work may proceed with synthetic data and disabled live gates. Phase 11 owns new invocation accounting, 12 owns artifact lifecycle, and 28 integrates closure without silently marking the older plan complete. First live enablement must satisfy its applicable security/free-resource gates; safety is not postponed to Phase 28.

## Requirement coverage and deduplication

Every detailed plan retains its original normative commitments, phase acceptance and exclusions, with a local requirement-to-work-package table. There are 199 phase commitments. A baseline-to-revised scope comparison permits only the recorded corrections (captured versus estimated context, incremental neutral migration, required foundational search admission and truthful offline/live adapter acceptance); no commitment or exclusion was dropped. The following map covers the broader source requirements, including source requirements that the generated plans had not assigned concretely. Target interface names are explicitly future; verified file seams are listed in each plan.

| Intended requirement family | Implementation owner(s) and acceptance |
| --- | --- |
| Principal/app/workspace/conversation/request identity, advisory capabilities, standalone compatibility | 1, 2; all-record/vector/replay/export isolation, no client authority. |
| Small AI-owned global profile, distinct domain profiles/state/history, client/tool data | 3–7; bounded profile provider and typed sources; real domain data in 18–21, side effects in 23. |
| Active-branch history, lossy summaries, memory/evidence inclusion and global/per-source budgets | 4, 8; preserve existing assembler behavior and close all future dispatch paths. |
| Deterministic narrow context planning, unavailable-source behavior | 5; named baseline selection/omission fixtures; smarter planning only in 24. |
| Provenance, permissions, sensitivity, safe inspection and correlation | 3, 4, 6, 7; pre-retrieval/pre-disclosure enforcement; audit actual build separately from estimated reconstruction. |
| Memory extraction/embedding/lifecycle/vector compatibility | Reuse existing memory in 3/4; neutral/counted preparation in 8; scope in 1; optimization in 26; physical lifecycle release in existing 9/next 28. |
| Research/search/evidence/entities/claims/constraints/ranking/iterative budgets | Reuse existing layers in 3–8 and 18/19; operation accounting in 11; evaluated retrieval improvements in 25. |
| Minimal provider-neutral operations, SDK confinement, streaming/errors/usage and fakes | 8–9; preserve task validators and endpoint-specific serializer/counter/embedding metadata. |
| Required Gemini/Groq/Cloudflare, strict-free model/account/capability/privacy eligibility | 9–10 and all live gates; paid-only models and unknown-policy sensitive paths excluded. Optional providers remain future extensions, not new required scope. |
| All-operation quotas/accounting, shared account windows/health/reset confidence and safe summaries | 11; reserve/settle unknown work, count search/count/embed/worker operations. Optimization hooks reuse this owner. |
| Firestore operational/vector state and private GCS bulky artifacts, retention/export/deletion/resource constraints | 12; bounded JSON/JSONL, cross-store reference states and orphan recovery; integrated lifecycle and existing Phase 9 closure in 28. |
| Fixed task-aware routing, quality floors, cross-provider evaluation, quota-aware scarcity, bounded cascades | 13 → 14 → 15 → 16; explicit unmeasured baseline before measured profile consumption, no after-delta model concatenation. |
| ChatGPT auth/local custody/refresh/revocation/account discovery/supported Responses and caller security | 17.1; official compatibility snapshot is not live acceptance; mobile/hosted eligibility checked separately. |
| ChatGPT explicit-only policy/coarse usage/no silent fallback/producing-model metadata | 17.2; reuse automatic attribution from 8/13; scoped idempotent external completion is client-reported. |
| ContextPackage, reusable responsive sidecar/context controls, Copy/draft Insert and domain hooks | 17.3–17.4 plus 18–21; one context/auth/persistence contract, Apply waits for 23. |
| Travel trip/day/place/preferences/research, Shopping project/requirements/saved/rejected products | 18–19; authoritative external app reads, existing comparisons reused; no itinerary/shortlist generic writes. |
| Finance observed/calculated/assumed/AI labels and narrow portfolio/account context | 20; read-only, stricter eligibility, no trades/transactions or implicit whole-portfolio disclosure. |
| Health flexible typed profile/time queries/category controls and minimal/no verbose traces | 21; read-only and deny-by-default sharing; no flattening into memory or generic clinical edits. |
| Four explicit narrow cross-app cases, sensitivity, audit/revocation | 22; source grant dependencies also apply to history/summaries/memory/caches/artifacts. |
| Domain-validated, confirmed, idempotent typed mutations and authoritative post-state | 23; reuse itinerary proposal fences, no direct core DB writes or provider authority. |
| Smarter planning/retrieval/memory/learned-routing experiments | 24–27; versioned baselines and paired metrics before promotion, bounded strict-free calls, deterministic fallback. |
| Security/provider churn/cloud/telemetry/recovery/CI/resource/storage/export/deletion hardening | 28 and earliest affected live gates; existing Phase 9 checklist remains required, all providers/lanes/domains included. |

Removed duplication is execution boilerplate, not requirements: generic registry/contract/testing work repeated within every work package, Phase 9 router/scoring bullets, multiple ChatGPT persistence/auth implementations, optional search accounting introduced too late, and implied reimplementation of existing memory/search/constraint modules. Shared acceptance obligations remain in the execution contract. All 32 phase scopes remain represented; no domain, provider, optimization or hardening phase was removed.

## Substantive change record

All rows preserve intended scope. “Behavior” identifies target behavior/architecture clarification, not code implemented during this review.

| ID / issue | Documents changed / correction and rationale | Sequencing and impact |
| --- | --- | --- |
| C01 — Earlier audit treated as complete/current | New comprehensive review, historical-record notice, README/index/manifest and final review record; independently verify assertions at current revision. | No renumbering; Phase 0 evidence correction only. |
| C02 — Identity authority and correlation conflated | Product/architecture, 1/2/6, shared contract: server owner, registered app/membership, explicit null/legacy scope, all record/vector/job/replay boundaries; request correlation is not idempotency. | Identity remains first; target isolation clarification. |
| C03 — Application registry confused with comparisons | Architecture/2/3/18–21: compose a small application definition registry beside DomainModule; core-owned global profile explicitly assigned to 3. | No new database or domain ownership; fills an existing requirement allocation gap. |
| C04 — Context guarantees overstated | Architecture/roadmap/4/6/8 and repository architecture/ADR 0006 extension note: distinguish actual-build manifest from estimated inspection; direct memory extraction still bypasses assembler; endpoint-aware fit/counters. | Shared preparation gap closed in 8 before new adapters; behavior/privacy clarification. |
| C05 — Late policy and derived-context bypass | Product/architecture/shared contract and 3–7/17/22/24–26: isolation/minimal admission exists before provider calls; full field policy in 7; revocation dependencies survive derived reuse. | Early synthetic groundwork cannot fetch first/filter later; no weakening of privacy. |
| C06 — Adapter/routing/accounting duplication | Inference/roadmap/8–11/13/17.2: minimal existing neutral boundary, no mandatory framework, per-operation usage/terminal metadata, automatic attribution starts 8/13. | Adapter 9 no longer implements router; ChatGPT extends rather than recreates attribution. Implementation/architecture clarification. |
| C07 — Quota/strict-free claims exceeded evidence | Inference/operations/11/25/28 and GCP docs: account/window-specific quota, unknown reservations, required search admission in 11; unconditional deployment TTL is a real gap. | Search accounting moves earlier; first affected live gates and final hardening close cost contradictions. Target strict-free behavior preserved. |
| C08 — GCS atomicity/lifecycle underdefined | Storage/architecture/12/28: scoped ready/pending states, generation/hash/bounds, orphan recovery, versions/soft-delete, required export versus advisory traces. | No new store; artifact deletion in 12 and general physical deletion existing 9/28 explicitly owned. Architecture/failure clarification. |
| C09 — Evaluation/routing dependency gap | Inference/architecture/roadmap/13–16/24–27: unmeasured fixed baseline, actual quality profiles before optimization, safe pre-output fallback and buffered cascades. | Baseline-before-optimization enforced; no speculative quality scores. |
| C10 — SIWC assumptions and duplicate completion | ChatGPT design/product/inference/17.1–17.4: verified supported public flow, distribution and plan-only gates, separate caller auth, unsupported-field serializer, package-bound verifiable dispatch authorization and scoped client-reported completion. | 17.2 owns external-turn lifecycle, 17.3 ContextPackage/UI, 17.4 hooks. All additive scope retained with explicit external blockers. |
| C11 — Domains assumed implemented or entirely ChatGPT-dependent | Roadmap/architecture/18–23: distinguish comparisons from authoritative app reads, pin external contracts/revisions, preserve privacy/semantic labels and sidecar work. | Baseline domains depend on 7/13/16; additive sidecars on 17.4. No phase renumbering; scope remains pending where externally blocked. |
| C12 — Mutation and semantic optimization boundaries ambiguous | Product/ChatGPT design/23/25/26: mandatory authoritative-write confirmation, domain reconciliation/post-state, exact compression support and ADR amendment gates. | Existing proposals are patterns, not general Apply. No trade/clinical feature expansion; existing memory/evidence semantics preserved. |
| C13 — Local acceptance and release evidence stale | ADR 0020, booking contract, repository docs and 28: local booking acceptance recognized; live readiness stays closed; CI itinerary-eval omission and existing Phase 9 obligations identified. | Evidence/status and release ownership corrections; no runtime or production promotion. |
| C14 — Plans generic rather than executable | All 32 detailed plans, shared execution contract, manifest and source pointers: real seams, future types, concrete responsibilities/failures, exact prerequisites, targeted tests and requirement mapping. | Repeated execution guidance consolidated; all commitments/acceptance/exclusions retained. |

## Verification performed in this pass

At code revision `ad1dea5` with documentation edits only:

- `make backend-test` using the existing backend venv: **561 passed, 12 skipped**, one upstream Starlette/httpx deprecation warning. A first invocation without the venv failed because shell `python` was unavailable; the configured invocation passed. Skips are opt-in external checks, not successes.
- `make backend-lint`: **passed**.
- Eight offline evaluation targets: context **5**, memory **14**, memory lifecycle **60**, research **13**, decision **15**, domain **10**, iterative research **18 paired**, itinerary proposal **6** fixture/results rows; all runners completed successfully and reported no failing fixtures. Synthetic/fake results establish local contracts, not live quality.
- Documentation/static verification: local links and heading anchors, existing code paths, source-pointer target validity, all 32 plan/manifest entries and byte sizes, exact dependency graph and conditional sidecar edges, scope/requirement mapping, commands and `git diff --check`. Final results are recorded in [the review record](07-final-review-record.md).

Frontend suites/builds were not rerun because this pass changed documentation only. No emulator, provider inference, OAuth flow, logged-in quota dashboard, deployed cloud/browser/native/domain test, backup/restore or private-data check ran. Official provider documentation was read for volatile facts; that is separate external-document evidence. Existing unrelated frontend build-info modification and legacy-package deletions were preserved.

## Risks and next implementation handoff

1. Existing Phase 9 full migration, account physical deletion, export fidelity, recovery, provider accounting/data-use and release gates remain incomplete. Narrow booking candidate deletion is not account erasure. Live private-data/production readiness is not established.
2. Gemini memory/counting and model/vector compatibility, Groq/Cloudflare configured account tiers, Brave rights/zero-overflow settings, GCS region/IAM/retention and supporting GCP resource controls require live/account verification. No code/config change in Phase 0 resolves the unconditional TTL gap.
3. SIWC preview contracts can change. Hosted-distribution approval, plan-only credit controls and browser/native/mobile transport remain explicit enablement gates. Keep the additive lane pending when unavailable; never replace required automatic providers or delete domain scope.
4. Authoritative Travel/Shopping/Finance/Health applications are outside this checkout. Pin their read/apply contracts, authorization and tested revisions before claiming integration. Fakes validate core contracts only.
5. Cross-provider quality and optimization benefits are unmeasured. Existing literal evidence/extractive memory policies remain accepted baselines; richer semantics need evaluated explicit decisions.

**Resulting recommended sequence:** 0 → 1–7 → 8–12 → 13–16 → 17.1–17.4 → 18–21 → 22–23 → 24–27 → 28. The exact graph permits baseline domain work and independent experiments after their real prerequisites, retaining conditional sidecar/release obligations. Checkpoints A–F in the roadmap are review milestones, not new implementations.

**Next genuinely ready phase:** next-scope **Phase 1 — Application and workspace identity**, using synthetic data and existing fakes, with default-off live gates. Read its corrected plan and this record; begin by capturing isolation/legacy behavior, then extend the existing request/service/repository seams. No Phase 1 or later implementation was started in this session.

**Scope assessment:** all intended context, provider/runtime, strict-free, storage, ChatGPT, Travel/Shopping/Finance/Health, cross-app, mutation, retrieval, memory, routing, evaluation, security and operational-hardening scope remains represented. Deduplication consolidates ownership; it does not remove requirements. Domain authority, privacy/sensitivity, strict-free fallback, Firestore/vector and private GCS boundaries remain intact.
