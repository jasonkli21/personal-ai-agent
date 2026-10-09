# Storage boundary

`repositories.py` defines backend-neutral contracts for owner-scoped conversations and append-only branchable messages. `fake.py` supplies deterministic in-memory implementations for offline tests. Provider-specific persistence implementations and composition live in the sibling `personal_ai.persistence` package.

## Current implementation

The active factory composes Postgres/pgvector repositories with DynamoDB timeline and runtime repositories. Local/test use explicit local Postgres and DynamoDB Local endpoints; deployed settings target Neon and federated AWS DynamoDB. Firestore adapters and migration tooling have been removed from runtime. The original decision is retained in [ADR 0002](../../../../docs/decisions/0002-firestore-native-persistence.md), superseded for current architecture by [ADR 0021](../../../../docs/decisions/0021-polyglot-persistence-foundation.md).

## Correctness concerns

- Services depend on repository protocols, not SQL, DynamoDB clients, or concrete persistence adapters.
- Preserve owner/application/workspace scope and immediate list behavior where required by existing contracts.
- Conversation turn preparation must preserve active-branch selection, parent/supersedes provenance, and atomic conflict handling. Superseded messages remain stored.
- Cross-store changes must preserve the bounded guards, receipts, and recovery rules in ADR 0021. Do not split a transactional correctness boundary merely to align broad data labels.
- Local DynamoDB does not establish real AWS capacity, IAM, index propagation, or strict-$0 behavior.

## Entry points and references

Start with `repositories.py`, `fake.py`, and `personal_ai.persistence.factory`. Relevant checks include `backend/tests/test_storage_repositories.py` and `backend/tests/persistence/`; use `make persistence-test` for the isolated local-engine integration suite when Docker is available. See the [Phase 10 storage ownership contract](../../../../docs/personal-ai-chapter-2/phase-10-storage-ownership-and-access-patterns.md), [cutover/verification plan](../../../../docs/personal-ai-chapter-2/phase-10-migration-cutover-and-verification-plan.md), and [P10.6 evidence](../../../../docs/personal-ai-chapter-2/phase-10-p10.6-implementation-evidence.md).


## Private artifact bodies

Phase 20 adds `personal_ai.artifacts` with scoped immutable references, gzip JSON/JSONL, local fake and private GCS body adapters. Migration 019 keeps compact metadata, storage budgets and deletion fences in Postgres. No artifact bodies or metadata mirror are added to DynamoDB; memory vectors keep pgvector. The tier defaults off. See the [Phase 20 guide](../../../../docs/personal-ai-chapter-2/phase-20-implementation-guide.md) and [evidence](../../../../docs/personal-ai-chapter-2/phase-20-implementation-evidence.md) for lifecycle recovery, consumer gates, configuration and unverified target-store/cloud acceptance.
