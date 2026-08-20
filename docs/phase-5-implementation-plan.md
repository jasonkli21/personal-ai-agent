# Phase 5 implementation plan

This is the execution plan for a reusable, source-grounded research platform. It extends the Phase 1–4 chat, context, and memory work; those plans remain authoritative for ownership, streaming, token budgets, and the memory/evidence lifetime boundary.

Read the [project brief](project-brief.md), [architecture notes](architecture.md), and [research-agent notes](research-agent.md) first. Their constraints override convenience decisions here.

## Scope boundary

Phase 5 adds one bounded research loop: plan one or more queries, search through a replaceable web adapter, turn source observations into expiring evidence, select evidence, and synthesize a cited answer. It adds durable research sessions, queries, sources, evidence, provenance, deduplication, and an inspection/evaluation path.

It does not add entity resolution, recommendations, hard-constraint filtering, learned ranking, travel or shopping modules, iterative investigation, authentication, production crawling, or automatic promotion of evidence into memory. Research is opt-in per request; ordinary chat keeps its Phase 1–4 behavior. Evidence is an observation, never a claim of truth.

## Delivery conventions and cross-cutting requirements

- Keep `agents` responsible for orchestration; adapters fetch or transform data
  but do not choose the answer. Keep provider-specific types and SDK calls out
  of API, storage, context, and domain code.
- Use a versioned, documented request/response schema. A research request must
  include the user question and may include an explicit freshness intent; it
  returns a research session ID. Session detail must expose state, final result
  or safe failure, evidence/citation metadata, and only safe progress data.
- Make request creation idempotent. A client retry must either return the same
  session or a clearly new session—never run duplicate searches invisibly.
- Treat every external value as untrusted input. Bound URL count, redirects,
  response bytes, extracted text, query count, concurrent requests, adapter
  attempts, and total per-session work. Reject unsupported URL schemes and
  private/local network targets before any fetch.
- Preserve a source chain: request → planned query → adapter attempt → source
  observation → extracted passage → normalized evidence → selection → cited
  result. IDs, policy versions, and timestamps make this reconstructable.
- Use UTC instants for observation and expiry, a testable injected clock, and
  explicit TTL rules. Do not silently reuse an expired session result as fresh
  research; surface its stale/incomplete status instead.
- Deliver every feature behind a setting (`research_enabled`, adapter choice,
  planner choice, reranker choice, inspection flag) with safe disabled
  behavior. Local development defaults to fakes; credentialed checks are
  manual opt-in.
- Add migration/index/retention instructions with each persisted collection.
  Repository writes must use owner-scoped lookups even though Phase 5 precedes
  real authentication, so the Phase 9 migration is mechanical.

## Required verification matrix

At minimum, test repository invariants, contract validation, request/SSE event
ordering, adapter error mapping, content safety bounds, extraction and dedupe,
freshness selection, citation validation, provider failure, client disconnect,
and disabled-mode parity. Run unit and route tests entirely offline. A separate
documented smoke procedure may exercise the selected provider with synthetic
queries only; it must check attribution, source links, timeouts, and spend
limits before the adapter is enabled for personal use.

## Required implementation artifacts

P5.1 must produce accepted ADRs, versioned domain/API/SSE contracts, settings
validation, migrations/index definitions, deterministic fakes, and fixture
schemas before P5.2 starts. Every subsequent task changes those artifacts only
through a compatible version or an explicit migration. Name concrete modules,
routes, collections, and settings in the implementation handoff; do not leave
provider behavior embedded in an endpoint or UI component.

**Required persisted records:**

| Record | Required fields |
| --- | --- |
| Research session | `id`, `owner_id`, `request_fingerprint`, `mode`, `state`, `policy_version`, `idempotency_key`, `created_at`, `updated_at`, `expires_at`, `failure_code` (nullable) |
| Search query | `id`, `session_id`, `owner_id`, `normalized_query`, `rationale_code`, `sequence`, `state`, `created_at`, `executed_at` (nullable) |
| Source observation | `id`, `session_id`, `query_id`, `owner_id`, `canonical_url`, `title` (nullable), `provider`, `observed_at`, `content_fingerprint` (nullable), `status`, `attempt_id` |
| Evidence | `id`, `session_id`, `owner_id`, `source_observation_ids`, `passage`, `content_fingerprint`, `observed_at`, `expires_at`, `extraction_version`, `status` |
| Evidence selection | `id`, `session_id`, `owner_id`, `evidence_ids`, `excluded`, `selector_policy_version`, `token_count`, `created_at` |
| Adapter attempt | `id`, `session_id`, `query_id`, `owner_id`, `adapter`, `idempotency_key`, `attempt_number`, `status`, `started_at`, `completed_at`, `error_code` (nullable) |

**Required configuration:**

| Setting | Purpose |
| --- | --- |
| `RESEARCH_ENABLED` | Master opt-in gate; disabled by default |
| `RESEARCH_SEARCH_ADAPTER` / `RESEARCH_PLANNER` / `RESEARCH_RERANKER` | Named replaceable implementations; fakes are local defaults |
| `RESEARCH_MAX_QUERIES`, `RESEARCH_MAX_SOURCES`, `RESEARCH_MAX_RESPONSE_BYTES` | Per-session work and input bounds |
| `RESEARCH_MAX_REDIRECTS`, `RESEARCH_MAX_CONCURRENCY`, `RESEARCH_ATTEMPT_LIMIT` | Fetch and retry bounds |
| `RESEARCH_EVIDENCE_TTL_*` | Explicit source-class expiry policy |
| `RESEARCH_MAX_EVIDENCE_CONTEXT_TOKENS` | Context allocation after Phase 2 mandatory content |
| `RESEARCH_INSPECTION_ENABLED` | Read-only development-only inspection gate |

## Dependency map

```text
P5.0 Fixtures/baseline ─> P5.1 Contracts ─> P5.2 Session/evidence storage ─┬─> P5.4 Search adapter ─> P5.5 Extract/dedupe ─> P5.6 Select/rerank ─> P5.7 Synthesize ─> P5.8 Verify
                                                                            └─> P5.3 Query planner ────────────────────────────────────────────────────────────────────┘
P2 context budgets + P3/P4 memory boundary ────────────────────────────────────────────────────────────────────────────────────────────────────────────────> P5.7
```

Tasks marked **decision required** stop for input only if the stated default is unsuitable. All other work must remain within this phase.

---

## Phase 5 — Reusable search platform

### P5.0 — Establish research fixtures and a no-research baseline

**Dependencies:** Phase 4 completion review

**Goal:** measure research behavior before network access affects an answer.

**Work:** create synthetic fixtures for a direct factual query, conflicting sources, a stale source, duplicate URLs/content, an unsupported source, insufficient evidence, citation placement, and a memory-like but externally sourced claim. Record expected planned queries, source/evidence IDs, excluded evidence, citation links, freshness outcome, and safe failure outcome.

**Requirements:** use deterministic fake search, clock, extractor, reranker, and LLM clients; fixtures contain no personal data or copied paywalled content; the baseline explicitly records the prior chat answer has no fresh evidence.

**Acceptance criteria:** every later component shares named fixtures; tests distinguish no result, adapter failure, extraction failure, and insufficient evidence; no test needs credentials, Firestore, or a real search provider.

### P5.1 — Record decisions and define research contracts

**Dependencies:** P5.0  
**Decision required:** yes

**Goal:** make provider substitution, attribution, and freshness enforceable at boundaries.

**Work:** add ADRs/contracts for: an opt-in research request mode; `ResearchSession`, `SearchQuery`, `SourceObservation`, `Evidence`, and `EvidenceSelection`; owner/session correlation and immutable provenance; source URL canonicalization; source-specific attribution; observation/expiry timestamps; a per-source freshness policy; result and content-size limits; and a provider-neutral `SearchAdapter`, `ContentExtractor`, `QueryPlanner`, and `EvidenceSelector` protocol. Default to one licensed/terms-compliant web-search API and fetch only permitted result content.

**Requirements:** evidence stores source URL, title where available, observed time, extraction method/version, content fingerprint, query/session link, expiry policy, and stable ID; citations expose the original source URL, not an internal ID; provider credentials stay in Secret Manager/configuration.

**Acceptance criteria:** contracts prevent evidence without attribution/freshness, distinguish raw observations from normalized evidence, and permit an adapter fake; no domain schema or entity identity is introduced.

**Out of scope:** entity aliases, recommendation policies, domain-specific
source adapters, iterative query state, authentication, or production crawling.

### P5.2 — Implement owner-scoped research and evidence persistence

**Dependencies:** P5.1

**Goal:** retain reproducible research provenance without treating external data as memory.

**Work:** implement repository interfaces and Firestore indexes for sessions, planned/executed queries, source observations, evidence, selections, and synthesis metadata. Use append-only attempt records and derived session state (`pending`, `running`, `completed`, `insufficient`, `failed`, `expired`). Enforce owner/session isolation and idempotency keys for request and adapter attempts.

**Requirements:** raw fetched content has explicit retention/size controls; normalized evidence carries a content fingerprint and source link; only bounded safe metadata appears in logs; expired evidence remains auditable but is ineligible by default.

**Acceptance criteria:** repository tests prove owner isolation, idempotent writes, query/evidence provenance, expiry eligibility, and no accidental write to memory collections.

**Out of scope:** cross-session deduplication that changes ownership, entity
canonicalization, background TTL deletion, or public inspection endpoints.

### P5.3 — Implement a bounded single-pass query planner

**Dependencies:** P5.1

**Goal:** translate a research request into transparent, limited searches.

**Work:** define a planner input containing user question, explicit constraints, permitted memory hints, and a maximum query budget. Implement deterministic query normalization plus an optional replaceable LLM planner whose structured output is validated, deduplicated, and capped. Persist the rationale class and planned queries before execution.

**Requirements:** planner output cannot override explicit user constraints, request disallowed data, invoke tools, or create follow-up loops; memory may suggest terminology but must be labelled and cannot become evidence.

**Acceptance criteria:** fixtures prove query caps, deterministic fallback, invalid-plan rejection, safe empty planning, and provenance from each executed query to the request.

**Out of scope:** autonomous retries, iterative gap filling, tool execution,
or model output accepted without schema validation.

### P5.4 — Add the basic web-search adapter

**Dependencies:** P5.1, P5.2, P5.3

**Goal:** fetch a bounded set of attributable candidate sources through one replaceable integration.

**Work:** implement request validation, provider timeout/retry classification, result normalization, allow/deny policy hooks, response-size limits, rate/concurrency limits, and persisted attempt records. Supply a fake adapter for tests and configuration gates that leave web research disabled by default until provider/privacy review.

**Requirements:** respect provider terms, robots/content-use constraints, attribution, and user-agent requirements; never log query text or raw results by default; do not scrape around authentication or paywalls.

**Acceptance criteria:** adapter tests cover success, empty results, timeout, malformed result, quota error, duplicate delivery, and disabled configuration without a live provider.

**Out of scope:** general web crawling, browser automation, authenticated
sources, paywall bypass, or provider-specific domain modeling.

### P5.5 — Extract, normalize, deduplicate, and expire evidence

**Dependencies:** P5.2, P5.4

**Goal:** produce a small, attributable evidence set rather than an unbounded page cache.

**Work:** canonicalize URLs, extract bounded relevant passages, preserve source/title/publication date when available, fingerprint normalized content, merge exact and near duplicates conservatively, attach per-source TTLs, and record all merge/exclusion reasons. Never infer a publication date that is absent.

**Requirements:** extraction is fail-closed for unsafe/oversized/unreadable content; deduplication retains all source links; evidence text is clearly separated from extractor/model summary; freshness is checked at selection time.

**Acceptance criteria:** fixtures prove canonical URL dedupe, retained provenance for merged sources, expired exclusion, conflicting-source retention, and no fabricated date or citation.

**Out of scope:** declaring a canonical entity, resolving source conflicts as
truth, or promoting evidence/derived summaries into personal memory.

### P5.6 — Implement explainable evidence selection and reranking

**Dependencies:** P5.1, P5.5

**Goal:** select a budget-fitting, diverse, fresh evidence set before synthesis.

**Work:** implement a deterministic selector using query relevance, source/result quality signals, freshness eligibility, diversity, and token cost. Record component scores, selected/excluded IDs, and exclusion reason. Use an optional provider-neutral reranker only behind a versioned feature gate and preserve deterministic fallback.

**Requirements:** selection must not hide material conflicts merely to make an answer smoother; expired, unattributed, and cross-owner records are ineligible; selected passages must fit the Phase 2 context budget with room for the user question and answer instructions.

**Acceptance criteria:** tests prove deterministic tie-breaking, budget adherence, conflict visibility, fallback after reranker failure, and selection explanations without raw private query text.

**Out of scope:** learned ranking, recommendation scoring, user preference
optimization, or a selection that silently removes material disagreement.

### P5.7 — Synthesize a sourced answer through the context layer

**Dependencies:** P2 context assembler, P5.3, P5.6

**Goal:** answer only to the strength of selected evidence and surface uncertainty.

**Work:** add a research context segment with numbered source IDs/URLs and instructions to cite supported claims, distinguish observed facts from inference, report conflicts and missing information, and avoid uncited factual assertions. Validate returned citations against selected evidence and render valid links; downgrade invalid/missing citation output to a safe insufficient-evidence response or clearly labelled uncited conversational content as configured.

**Requirements:** preserve the newest user message and existing token rules; selected Phase 3/4 memory remains labelled as user context and cannot be cited as external evidence; do not persist the synthesis as memory.

**Acceptance criteria:** fixture tests prove citations resolve only to selected sources, conflicts/uncertainty are present, unsupported claims are rejected or labelled, and LLM/selection failure cannot corrupt chat persistence.

**Out of scope:** entity/candidate creation, purchases or bookings, memory
extraction from research output, and changes to normal-chat SSE semantics.

### P5.8 — Integrate, evaluate, document, and verify Phase 5

**Dependencies:** P5.0–P5.7

**Goal:** ship an opt-in, inspectable vertical slice without weakening normal chat.

**Work:** add a research request/API/UI path and SSE progress limited to stable session/query/source/evidence milestones; add a disabled-by-default inspection report; run fixture comparisons; document provider policy, TTLs, attribution, retention, indexes, and local fake-provider workflow.

**Requirements:** ordinary chat emits the existing Phase 1 event contract unchanged; only safe IDs/counts/statuses appear in default telemetry; CI is fully offline and deterministic.

**Acceptance criteria:** integration tests cover research success, insufficient evidence, source conflict, expiry, cancellation/disconnect, adapter/LLM failures, and disabled parity; a clean checkout passes all checks; no Phase 6 entity/ranking or Phase 8 iteration behavior was added.

**Implementation handoff:** record the final public route/event schemas,
collection/index names, configuration keys/defaults, policy versions, fixture
command, and one synthetic manual verification transcript. This is the input
to Phase 6; Phase 6 must consume evidence through these contracts rather than
re-fetching or re-parsing sources.

## Phase 5 completion review

Before declaring Phase 5 done, verify all task acceptance criteria and answer:

1. Can every evidence-backed claim link to selected, attributable, unexpired evidence?
2. Are evidence, user memory, and model conclusions still separate data classes?
3. Can a provider outage, invalid citation, stale source, or empty result produce a safe response without breaking chat?
4. Are source use, retention, attribution, budgets, and privacy decisions documented and gated?
5. Do fixtures prove no fabricated citations, cross-owner access, silent conflict suppression, or evidence-to-memory promotion?
6. Has work avoided entities, recommendation ranking, domain modules, iterative loops, and authentication?

Only after all answers are yes should work advance to Phase 6.
