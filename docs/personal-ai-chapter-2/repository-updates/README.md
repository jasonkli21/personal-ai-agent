# Repository updates when installing this chapter

The review found that deleting the old planning package while leaving inbound links/status text unchanged created broken/stale documentation. These changes are part of applying the regenerated package.

## Living docs

Update these living/current documents to point at `docs/personal-ai-chapter-2/` and reflect that next-scope Phases 0–2 are complete and Phase 10 is next:

- `docs/project-brief.md`
- `docs/architecture.md`
- `docs/implementation-plan.md`
- `docs/gcp-deployment.md`

Translate old future-phase references where they describe the current roadmap (for example former 8→16, 9→17, 11→19, 12→20, 28→36). Phase 10 now owns the storage/TTL/cutover prerequisite before Phase 11+.

## Historical records

Do not rewrite historical facts in:

- `docs/phase-9-implementation-evidence.md`
- `docs/decisions/0006-context-token-budget.md`

Instead add a dated supersession/current-plan note that points to the new chapter and maps the old next-scope phase references to their current numbers. This retains the original evidence/decision chronology while avoiding dead links or misleading current handoff instructions.

## Root README

Do **not** rewrite the root README to the Postgres/DynamoDB architecture merely when installing planning docs. Phase 10 has a mandatory README closeout requirement and must update architecture/tech-stack/local-setup/cloud-deployment facts once the migration is actually implemented.

Every later phase likewise reviews README accuracy at phase close.

## Helper

`apply_documentation_updates.py` applies the path/status/supersession edits to a working tree. Review its diff before committing.
