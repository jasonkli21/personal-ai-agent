# Phase 6 implementation plan

This plan turns Phase 5 research evidence into structured decision support. Phase 5 remains authoritative for research provenance, evidence freshness, attribution, and sourced synthesis.

## Scope boundary

Phase 6 adds canonical entities, conservative entity resolution, deterministic hard constraints, explainable soft ranking, and evaluations for decisions based on fresh evidence. It does not add travel/shopping-specific adapters or schemas, iterative research, learned ranking, authentication, or autonomous purchase/booking actions.

## Delivery conventions and cross-cutting requirements

- Keep a canonical entity separate from each evidence-backed assertion about
  it. Entity identity can persist; mutable claims such as price, inventory,
  opening hours, or availability retain their source, observation time, and
  expiry eligibility.
- Model every decision as a reproducible snapshot: request constraints,
  candidate/entity IDs, claim/evidence IDs, policy and feature versions,
  constraint outcome, score components, rank/tie-break result, and generation
  time. Never mutate this record to make a later result appear historical.
- Normalize money, units, time zones, locale, and geographic distance at typed
  boundaries. Preserve the original value/unit/currency and conversion source
  where conversion matters. An unavailable exchange rate or ambiguous unit is
  `unknown`, not a guessed conversion.
- A hard constraint has an explicit missing-data policy. The default for a
  required attribute is fail closed; product/domain modules may only relax this
  by declaring the field optional in their typed contract.
- Define policy changes as configuration versions with approval/release notes.
  Do not edit weights, match thresholds, or normalization semantics in place
  without a comparison against fixtures.
- Add a development-only decision inspection payload/UI with selected and
  excluded candidates, attributes, constraints, score components, policy IDs,
  and source links. It must not disclose raw private memory or hidden model
  reasoning.

## Required verification matrix

Use fakes for retrieval/search/clocks and cover identity extraction, exact and
ambiguous matches, reconciliation after a source update, expiry/conflicts,
unit/time/currency boundary cases, every constraint operator, score arithmetic,
tie-breaking, empty eligible set, ranking failure fallback, and API/UI display
of uncertainty. Regression output should name fixture, evidence snapshot,
entity/resolution policy, constraint policy, ranking policy, and result.

## Required implementation artifacts

P6.1 must create accepted ADRs, versioned neutral schemas, policy validators,
repository interfaces, deterministic fakes, migrations/index definitions, and
fixture-result schemas before entity or ranking writes begin. All UI/synthesis
work consumes a persisted decision snapshot; it does not reconstruct or alter
eligibility from display text. Record every policy version in the snapshot so
Phase 7 can extend fields without changing prior decision meaning.

**Required persisted records:**

| Record | Required fields |
| --- | --- |
| Canonical entity | `id`, `entity_type`, `canonical_name`, `owner_scope`, `identity_version`, `created_at`, `updated_at`, `status` |
| Entity claim | `id`, `entity_id`, `attribute`, `typed_value`, `original_value`, `unit` (nullable), `currency` (nullable), `evidence_ids`, `observed_at`, `expires_at`, `claim_status`, `schema_version` |
| Entity match | `id`, `subject_id`, `candidate_entity_ids`, `selected_entity_id` (nullable), `outcome`, `confidence`, `feature_values`, `policy_version`, `evidence_ids`, `created_at` |
| Decision snapshot | `id`, `owner_id`, `research_session_id`, `constraint_set`, `candidate_ids`, `evidence_snapshot_id`, `policy_versions`, `state`, `created_at` |
| Candidate evaluation | `id`, `decision_id`, `entity_id`, `claim_ids`, `eligibility`, `constraint_outcomes`, `feature_values`, `score` (nullable), `rank` (nullable), `exclusion_reasons` |

**Required configuration:**

| Setting | Purpose |
| --- | --- |
| `ENTITY_RESOLUTION_POLICY_VERSION` / `ENTITY_MATCH_THRESHOLD` | Versioned deterministic resolution behavior |
| `DECISION_CONSTRAINT_POLICY_VERSION` | Missing/conflict/freshness semantics |
| `DECISION_RANKING_POLICY_VERSION` / `DECISION_FEATURE_*_WEIGHT` | Versioned deterministic scoring |
| `DECISION_MAX_CANDIDATES` / `DECISION_MAX_COMPARISON_ROWS` | Bounded evaluation and rendering |
| `DECISION_INSPECTION_ENABLED` | Read-only development-only inspection gate |

## Dependency map

```text
P6.0 Fixtures ─> P6.1 Contracts ─┬─> P6.2 Entity storage ─> P6.3 Resolution ─┐
                                 └─> P6.4 Freshness/conflict policy ───────────┼─> P6.5 Constraints ─> P6.6 Ranking ─> P6.7 Decision synthesis ─> P6.8 Verify
P5 sessions/evidence/selection ────────────────────────────────────────────────┘
```

---

## Phase 6 — Entities, constraints, and ranking

### P6.0 — Establish decision fixtures and Phase 5 baseline

**Dependencies:** Phase 5 completion review

**Goal:** make recommendations falsifiable before canonicalization or scoring exists.

**Work:** add deterministic synthetic cases for duplicate entities, ambiguous matches, stale offer data, conflicting facts, missing required attributes, budget/date/location/dimension/availability constraints, equal candidates, and preference conflict. Define expected canonical entities, no-match/review outcomes, eligible/ineligible candidates, score explanations, and cited evidence IDs.

**Requirements:** use invented products/places and fake clocks/adapters; the baseline is Phase 5 sourced summary with no canonical recommendation.

**Acceptance criteria:** fixtures distinguish a hard-constraint failure from a low rank and require safe abstention when identity or required facts are uncertain.

### P6.1 — Record decisions and define decision-support contracts

**Dependencies:** P6.0  
**Decision required:** yes

**Goal:** define stable shared semantics before domains depend on them.

**Work:** document contracts for `CanonicalEntity`, `EntityClaim`, `EntityMatch`, `Constraint`, `Candidate`, `Feature`, `RankingPolicy`, and `Recommendation`; define identity confidence thresholds, merge/review/no-match states, typed units/currency/time/location handling, missing-value semantics, and a policy-versioned hard-then-soft pipeline.

**Requirements:** a model may propose structured candidates but application code validates identity and enforces constraints; current request constraints outrank memory-derived preferences; recommendations retain links to source evidence and policy version.

**Acceptance criteria:** contracts disallow a recommendation without candidate/entity/evidence provenance and make unknown data ineligible whenever it is necessary to prove a hard constraint.

**Out of scope:** domain vocabulary, learned weights, user-adjustable scoring,
multi-tenant identity policy, or adapter-specific data types in core contracts.

### P6.2 — Implement canonical entity and claim persistence

**Dependencies:** P6.1

**Goal:** model shared real-world candidates without overwriting observations.

**Work:** add owner-safe/shared-read policy, canonical entity records, immutable evidence-backed claims, aliases, candidate references, resolution events, and derived state. Keep observed facts attributed and timestamped; entity metadata must not turn an expiring price/availability claim into permanent entity truth.

**Requirements:** all merges are reversible/auditable; entity IDs are not exposed as source citations; indexes support evidence-to-entity lookup and duplicate detection.

**Acceptance criteria:** tests prove provenance, idempotency, non-destructive merges, owner boundaries where applicable, and expiry of entity claims.

**Out of scope:** destructive entity merge, migration of arbitrary old
evidence, or a claim made durable simply because an entity is durable.

### P6.3 — Implement conservative entity resolution

**Dependencies:** P6.1, P6.2

**Goal:** resolve only matches with sufficient explainable support.

**Work:** normalize names, identifiers, URLs, merchant/provider IDs, locations, and key attributes; apply deterministic exact identifiers first, then bounded scored candidate matching; persist features and decision reasons. Route ambiguous/low-confidence matches to separate candidates/no-match rather than silently merging.

**Requirements:** never use title similarity alone for an automatic merge; resolution uses only eligible evidence and remains repeatable under the same policy version.

**Acceptance criteria:** fixtures prove exact match, duplicate aliases, near-name non-match, ambiguity abstention, stale-claim exclusion, and audit reconstruction.

**Out of scope:** LLM-only identity decisions, cross-owner matching, global
person profiles, or automatic merge based on title/name similarity alone.

### P6.4 — Define freshness, conflict, and candidate completeness policy

**Dependencies:** P6.1, P5 evidence policy

**Goal:** prevent a clean ranking from disguising stale or contradictory inputs.

**Work:** calculate candidate attribute status (`verified`, `conflicting`, `stale`, `missing`); specify which attributes require fresh evidence by decision type; retain conflicts with citations and prevent automatic selection when a required attribute conflicts.

**Requirements:** evaluate status from an evidence snapshot and injected clock,
not display text; retain competing values and their scopes rather than picking
the newest one by default; a conflict may be resolved only by a documented
deterministic rule with a retained audit explanation.

**Acceptance criteria:** stale/missing/conflicting required facts cause ineligibility or an explicit research-needed result; optional unknown facts are labelled, never fabricated.

**Out of scope:** re-fetching evidence, iterative conflict resolution, or a
new truth arbitration model.

### P6.5 — Implement deterministic hard-constraint filtering

**Dependencies:** P6.2, P6.4

**Goal:** guarantee requirements are met before preference ranking.

**Work:** build typed validators for exact/maximum/minimum/range/set/geospatial/date-window/availability constraints, unit conversion, currency/time normalization, and explicit constraint-source provenance. Return an exclusion record for every rejected candidate.

**Requirements:** no LLM decides pass/fail; missing/ambiguous required evidence fails safely; policy defaults never relax an explicit user constraint.

**Acceptance criteria:** tests cover boundary values, units, time zones, currency dates, unknown values, and deterministic explanations.

**Out of scope:** a model deciding pass/fail, silent constraint relaxation, or
domain-specific constraint logic outside an extension contract.

### P6.6 — Implement explainable soft ranking

**Dependencies:** P6.5

**Goal:** order eligible candidates transparently after filtering.

**Work:** define versioned feature calculators and weighted policy with normalization, tie-breaking, optional memory preference features, diversity limits, and an explanation containing feature values, weights, evidence IDs, and missing-data treatment. Begin with deterministic, hand-authored weights.

**Requirements:** preferences cannot resurrect an ineligible candidate; scoring must expose rather than conceal conflict/staleness; no learned model or opaque provider ranking is introduced.

**Acceptance criteria:** fixture comparisons prove hard constraints precede ranking, score arithmetic and ties are reproducible, preferences apply only to eligible candidates, and failure falls back to an unranked eligible set.

**Out of scope:** learned/opaque ranking, online tuning, or a score presented
as a factual confidence level.

### P6.7 — Present a source-grounded decision result

**Dependencies:** P6.3–P6.6

**Goal:** give users useful recommendations with their limitations visible.

**Work:** synthesize/format candidate comparisons, requirement status, ranking rationale, evidence links, uncertainties, and excluded candidates where helpful. The LLM receives structured, validated results and cannot invent candidates, prices, or passes; validate any referenced IDs before display.

**Requirements:** a response must distinguish `recommended`, `eligible but
unranked`, `research needed`, and `no verified match`; comparison values must
show their observation/freshness status; no response may imply a purchase,
reservation, or guaranteed availability.

**Acceptance criteria:** recommendations cite their supporting claims, disclose material conflict/staleness, and respond `no verified match` when appropriate.

**Out of scope:** transactional calls to action, guaranteed availability, or
candidate facts inferred solely from model prose.

### P6.8 — Evaluate, document, and verify Phase 6

**Dependencies:** P6.0–P6.7

**Goal:** establish that decisions are traceable and constraint-safe.

**Work:** run deterministic evaluations and document schemas, indexes, policy versions, review/abstention behavior, and inspection output. Add integration tests from evidence through decision response.

**Requirements:** result records preserve the exact fixture clock and policy
versions; approval thresholds must be declared before inspecting the comparison;
credentialed/provider checks are opt-in and cannot replace deterministic CI.

**Acceptance criteria:** clean offline CI proves no invalid recommendation, duplicate auto-merge, stale required claim, cross-owner leak, or preference-over-constraint result; Phase 5 research-only mode remains available; no Phase 7 domain adapter or Phase 8 iteration work exists.

**Implementation handoff:** publish the stable neutral entity/claim,
constraint, decision-result, and inspection schemas plus policy configuration
and fixture commands. Phase 7 may extend typed attributes, but may not bypass
the hard-filter and evidence-provenance path.

## Phase 6 completion review

Before declaring Phase 6 done, verify all task acceptance criteria and answer:

1. Can every recommendation be reconstructed from canonical identity, eligible evidence, constraint results, and a policy version?
2. Do hard constraints always run before preference ranking, including missing and stale-data cases?
3. Does ambiguity yield abstention or separate candidates rather than false entity merges?
4. Are conflict and uncertainty visible to users and evaluations?
5. Has the shared platform stayed domain-neutral and deterministic?

Only after all answers are yes should work advance to Phase 7.
