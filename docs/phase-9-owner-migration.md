# Migrating legacy `local` owner records

The Phase 1–8 repositories wrote personal records under the fixed owner ID
`local`. Phase 9 does not silently grant the new Google account access to those
records. Run the migration only after an authenticated request has created the
new active `identity_mappings` record.

1. Pause API traffic and the maintenance schedule. Take a Firestore backup and
   verify that its restore point is usable before proceeding.
2. Read the active `owner_id` from the identity mapping for the intended Google
   account. It is an opaque `usr_` identifier, not an email address.
3. Run the default dry-run and review only the collection counts:

   ```sh
   cd backend
   uv run python scripts/migrate_local_owner.py \
     --project YOUR_STAGING_PROJECT \
     --owner-id usr_REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS
   ```

4. Review the counts and apply in the intended environment by repeating the
   exact owner ID:

   ```sh
   uv run python scripts/migrate_local_owner.py \
     --project YOUR_STAGING_PROJECT \
     --owner-id usr_REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS \
     --apply \
     --confirm-owner-id usr_REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS
   ```

The command never prints document IDs or content. It updates only records whose
top-level `owner_id` is exactly `local`, in batches of at most 200 with a
Firestore last-update precondition. Re-running after an interrupted migration
is safe: records already moved no longer match the query. Pause writes because
an application write racing the migration intentionally causes the
precondition to fail. The operator must restore from the backup if a verified
post-migration owner-count review identifies a bad mapping; do not run a
reverse owner rewrite against live data without a reviewed recovery plan.

Collections covered: conversations, messages, conversation summaries,
research sessions and request keys, iterative research runs and keys, memories
and derived/lifecycle records, decision snapshots/evidence/claims/matches,
owner-specific canonical entity aliases, and domain registrations/claims/
observations/comparisons/lookup idempotency records. Shared `*` catalog rows,
identity mappings, audit events, rate counters, and daily budget summaries are
not reassigned.

The tool itself was verified offline for syntax and safety review only. No
Firestore project, emulator, backup, or migration was accessed during Phase 9
implementation.
