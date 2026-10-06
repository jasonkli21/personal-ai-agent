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
