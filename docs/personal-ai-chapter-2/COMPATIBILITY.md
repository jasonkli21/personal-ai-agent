# Compatibility and supersession notes

## Planning package

Current planning package path when installed in the repository:

`docs/personal-ai-chapter-2/`

It supersedes `docs/personal-ai-next-scope-chatgpt-integrated-v2/` for future planning.

## Historical records

Do not rewrite historical ADRs/evidence to imply DynamoDB/Postgres existed in earlier revisions. Preserve the former Firestore implementation as historical code context without implying a deployed Firestore dataset existed. Historical references may retain explanatory text but should include a resolvable pointer to the current chapter when the old package is removed.

## Completed next-scope phases

Phases 0–2 stay at their original next-scope numbers. Existing Phase 1/2 implementation evidence remains evidence of the implementation at that time, including Firestore-specific details retired by Phase 10.

## Future phases

Former Phases 3–28 are renumbered per `NUMBERING-MAP.md`. Their substantive scope is preserved. A phase implementation should cite both its new number and former number in migration/review evidence when that helps trace old discussions.

## Root README

The root README describes **implemented current state**. Phase 10 P10.6 updated it after changing the active runtime wiring; no data migration is claimed because the user reports that no Firestore source was deployed.
