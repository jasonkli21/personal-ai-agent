# Final review record — regenerated renumbered package

Date: 2026-10-06

## Review findings addressed

### P1 — Scope loss during renumbering

**Accepted as a blocker and corrected.** The previous renumbered draft shortened former Phases 3–28 and, in places, changed assumptions (for example treating the global profile as already existing) or dropped acceptance details such as sensitivity/actual-build manifests.

Correction rule: the pre-renumbering detailed plans are authoritative for scope. New Phases 11–24, 25.1–25.4, and 26–36 preserve their former normative commitments/work packages/invariants/acceptance and change only numbering/prerequisites, Phase-10-obsolete storage references, and README maintenance.

Examples explicitly restored:

- Phase 11 creates the bounded global profile with user-set provenance and export/deletion participation rather than merely wrapping an assumed existing profile.
- Phase 12 retains deterministic effective sensitivity and actual-build context-manifest requirements.
- Phase 20 retains the original artifact sensitivity, actual lifecycle, required-vs-optional failure, export, and cost-guard scope while replacing Firestore metadata with Postgres and removing the obsolete “no DynamoDB” constraint.

### P2 — Stale removed-package links and handoff status

**Accepted and corrected by the repository-update bundle.** Living docs are updated to the new `docs/personal-ai-chapter-2` package. The implementation-plan handoff states that next-scope Phases 0–2 are complete and Phase 10 is next. Historical evidence/ADRs keep their historical meaning while receiving an explicit current-plan pointer rather than being rewritten as if the new architecture existed at the time.

### P2 — whitespace/diff check

**Accepted.** Generated Markdown/JSON/text is normalized to remove trailing whitespace. The package validator runs an equivalent whitespace check before ZIP creation.

## Persistence addition review

The Phase 10 addition remains substantively intact because the review found no comparable blocker in it. It includes:

- explicit DynamoDB/Postgres/GCS ownership;
- local Postgres/pgvector + DynamoDB Local;
- access-pattern-first DynamoDB design;
- versioned Postgres migrations/pgvector compatibility;
- idempotent Firestore backfill/reconciliation;
- bounded cutover/rollback and Firestore retirement;
- AWS scope constrained initially to DynamoDB/IAM;
- strict-$0 resource/network verification;
- root README update as a required post-implementation closeout item.

## Numbering

33 detailed plan entries:

- 0, 1, 2;
- 10;
- 11–24;
- 25.1–25.4;
- 26–36.

Phases 3–9 are intentionally unused. See `NUMBERING-MAP.md`.

## README synchronization

Every phase includes a README-maintenance closeout section. The root README remains a high-level current-state document, not a detailed implementation plan. Phase 10 explicitly updates it after migration completion because architecture/tech stack/setup/deployment change materially.

## Validation expectation

Before applying/committing this package:

- manifest contains 33 unique entries and an acyclic prerequisite graph;
- each manifest file exists and byte metadata is current;
- package-local Markdown targets resolve;
- generated files contain no trailing whitespace;
- no active future plan reintroduces Firestore as canonical target storage;
- completed Phase 0–2 history remains represented;
- external living-doc links point at the replacement package.

## P10.0 repository architecture review — 2026-10-06

Reviewed revision: `e17ebd76afd1feb90fe47d959c43ab23eb553499`, with completed
next-scope Phase 1–2 evidence and the existing persistence/export/lifecycle paths.
The earlier package review above remains historical. This later review resolves
implementation details before P10.1+, without weakening existing phase scope.

- [ADR 0021](../decisions/0021-polyglot-persistence-foundation.md) and the
  [storage contract](phase-10-storage-ownership-and-access-patterns.md) assign all
  34 current collections and future families exactly one canonical target.
  Research/replay and knowledge-effect transaction groups stay Postgres-owned;
  execution jobs and branch timelines stay DynamoDB-owned.
- Strong scoped DynamoDB directories preserve immediate listings; one sparse
  publication GSI serves eventual notifications. Detailed keys/size/branch
  mechanics remain in the Phase 10 contract.
- Sanity check limits coordination to existing atomic memory source/job validation,
  reusing conversation/job guards and a Postgres applied/aborted effect receipt.
  There is no general saga/outbox or mirrored job authority. Unknown effects
  remain fenced until serialized receipt recovery determines their outcome.
- Sanity check chooses one lossless embedding array plus a transient exact-search
  pgvector cast, rather than two stored representations. This saves Neon storage
  while preserving original-value reads; numeric boundary parity and query CPU
  require P10.2/local and later Neon verification. No default ANN or re-embedding.
- The [migration/verification plan](phase-10-migration-cutover-and-verification-plan.md)
  fixes logical reconciliation, final update/existence delta, all-writer freeze,
  post-write rollback limits, retirement and local/cloud/strict-$0 gates.
- Downstream Phases 12–16 prerequisite text is corrected to the already-correct
  manifest graph; affected storage dependencies are clarified without removing
  work packages, invariants, acceptance or verification requirements.
- Sanity check keeps detailed keys/recovery/migration mechanics in Phase 10 docs;
  shared architecture/strategy/execution docs contain short rules and links.

P10.0 changes documentation only. Root README runtime claims, application code,
infrastructure, cloud resources, completed evidence and original historical
records remain intact. No P10.1+ implementation or persistence/cloud test is
claimed. Open Phase 9 obligations remain independently open.

### Documentation verification

Validation on 2026-10-06 used reviewed HEAD plus the P10.0 documentation working
tree. `python3 /tmp/validate_p10_docs.py` passed: all 33 manifest entries/files/byte
sizes and the unchanged acyclic prerequisite graph, corrected Phase 11–16
prerequisite text, all 34 literal collection mappings, normalized source-copy
synchronization, Markdown file/anchor links and changed-file whitespace.
`git diff --check` passed. Protected root README, implementation/infrastructure
files, completed evidence and original historical content were unchanged.
No application, local-engine, migration, provider or cloud checks were run.
