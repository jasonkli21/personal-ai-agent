# Compatibility and supersession notes

## Planning package

Current planning package path when installed in the repository:

`docs/personal-ai-chapter-2/`

It supersedes `docs/personal-ai-next-scope-chatgpt-integrated-v2/` for future planning.

## Historical records

Do not rewrite historical ADRs/evidence to imply DynamoDB/Postgres existed when Firestore was actually used. Historical references may retain explanatory text but should include a resolvable pointer to the current chapter when the old package is removed.

## Completed next-scope phases

Phases 0–2 stay at their original next-scope numbers. Existing Phase 1/2 implementation evidence remains evidence of the implementation at that time, including Firestore-specific details that Phase 10 later migrates.

## Future phases

Former Phases 3–28 are renumbered per `NUMBERING-MAP.md`. Their substantive scope is preserved. A phase implementation should cite both its new number and former number in migration/review evidence when that helps trace old discussions.

## Root README

The root README describes **implemented current state**. Do not update it to the Phase 10 target just because the plan is merged. Phase 10 must update it as part of its implementation closeout once the migration/cutover changes the actual architecture.
