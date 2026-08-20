# ADR 0004: Preserve append-only branchable message history

- Status: accepted
- Date: 2026-08-19

## Context

Phase 1 supports regenerate and edit-and-retry flows. Replacing an earlier message in place would discard the audit trail and make it impossible to represent alternate continuations of one conversation.

## Decision

Store messages append-only with parent and supersession relationships. Select the active branch by the latest non-superseded path; retain older messages for auditability.

## Consequences

- Regeneration and edit-and-retry create new records rather than mutating message content or deleting prior output.
- APIs and UI can show the active path without requiring a Phase 1 branch browser.
- Repository and service logic must validate parent/supersession relationships and consistently derive the active path.
