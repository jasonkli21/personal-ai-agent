# Migrating legacy `local` owner records

The Phase 1–8 repositories wrote personal records under the fixed owner ID
`local`. Phase 9 does not silently grant the new Google account access to those
records. Run the migration only after an authenticated request has created the
new active `identity_mappings` record.

1. Pause API traffic and the maintenance schedule. Take a Firestore backup and
   verify that its restore point is usable before proceeding.
2. Read the active `owner_id` from the identity mapping for the intended Google
   account. It is an opaque `usr_` identifier, not an email address.
3. Run the default inventory and review only the collection counts:

   ```sh
   cd backend
   uv run python scripts/migrate_local_owner.py \
     --project YOUR_STAGING_PROJECT \
     --owner-id usr_REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS
   ```

4. Apply is supported only for a database whose legacy records are limited to
   conversations, messages, and working summaries. Any later-phase legacy data
   causes apply to stop before writes. For a chat-only database, review the
   counts and repeat the exact owner ID:

   ```sh
   uv run python scripts/migrate_local_owner.py \
     --project YOUR_STAGING_PROJECT \
     --owner-id usr_REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS \
     --apply \
     --confirm-owner-id usr_REPLACE_WITH_32_LOWERCASE_HEX_CHARACTERS
   ```

The command never prints document IDs or content. It inventories all enumerated
owner collections, then refuses apply if any unsupported collection still has
`local` records. Supported chat-only apply changes just `owner_id` in batches
of at most 200, using Firestore last-update preconditions and a separate audit
event committed with each batch. Strict application schemas remain unchanged.
Re-running after interruption skips records already moved. Pause writes because
a racing application write intentionally fails the precondition. Migration is
not atomic across the database; restore a tested backup if post-migration checks
identify an incorrect mapping.

Full Phase 3–8 migration is **not implemented**. It must rewrite embedded owner
fields, remap owner-derived memory/source identities and lifecycle projections,
rebuild idempotency keys, preserve all references, and validate records through
the actual repository readers. A top-level owner rewrite cannot do this safely.
Do not remove records merely to get past the apply guard.

Inventory covers conversations, messages, summaries, research sessions/keys,
iterative runs/keys, original and derived memory/lifecycle records, canonical
entities/aliases/claims, decisions/evidence/evaluations, domain records/keys, and
audit events. Shared `*` records, identity mappings, rate counters and daily
budget summaries are not reassigned.

Offline tests verify chat schema preservation, audit separation, idempotent
replay and refusal before writes for unsupported aggregates. No Firestore
project, emulator, backup or real migration was accessed. See the
[repository review](repository-review-2026-10-03.md) for the original defects
and remaining migration acceptance work.
