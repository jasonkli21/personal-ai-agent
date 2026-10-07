# Storage and artifact strategy

## Decision

Phase 10 intentionally adopts polyglot persistence:

```text
DynamoDB                Neon Postgres + pgvector         GCS (Phase 20+)
--------------------    ---------------------------       --------------------
operational timeline    interpreted/query-rich state     bulky immutable bodies
messages/conversations  global profile/memory            raw evals/traces
summaries/runtime       provenance/lifecycle             exports/replay
checkpoints/idempotency research/decisions/metadata
```

This supersedes the future-facing Firestore/GCS-only target. Firestore remains historical/current implementation until Phase 10 actually migrates it.

## DynamoDB ownership

Use for append/key/range-heavy operational records with named access patterns: conversation metadata, branchable messages, summaries, retained runtime/model/tool events, and selected checkpoint/idempotency/job state. Design keys/indexes from reads/writes rather than translating relational tables. Avoid normal-path scans and unbounded secondary indexes.

Do not store large artifact bodies or semantic vector memory here merely for free-tier storage headroom.

## Postgres ownership

Use Neon Postgres for state that benefits from relationships, constraints, ad-hoc filtering, aggregation, migrations, or vector + metadata queries: bounded global profile, memory/pgvector, provenance/lifecycle, research/evidence/entity/claim state, decisions/proposals, account/control metadata, compact provider/quota/evaluation records, and later artifact refs.

Use typed relational columns for stable semantics and bounded JSONB where evolution is genuinely useful. Preserve embedding model/dimension/normalization/task-space metadata and reject incompatible spaces.

The [Phase 10 storage contract](phase-10-storage-ownership-and-access-patterns.md) is the exhaustive family/access-pattern authority. Research runs/sessions/replay keys and lifecycle events/state/effect receipts stay in Postgres to preserve their transaction boundaries; execution jobs stay in DynamoDB. Embeddings use one lossless array with transient pgvector exact-search casts, avoiding a second stored projection while retaining original-value reads. Numeric parity, CPU and storage fit require implementation verification; detailed tradeoffs remain in that contract.

## Artifact tier

Phase 20 adds `ArtifactStore`/`ArtifactRef` and private GCS for allowed large immutable outputs: detailed traces, raw evaluation results, exports, replay/debug artifacts, and permitted retained research artifacts. Compact queryable references live in Postgres. Optional artifact failure is advisory; required export failure is explicit.

Sensitive Finance/Health verbose artifacts default to minimal/no retention. Source rights/privacy gates apply to retained research material.

## Cross-store consistency

- One canonical store per record class.
- Stable opaque IDs connect stores.
- No distributed transaction assumption.
- Use idempotency and conditional writes; narrowly coordinate memory source/job validation through the Phase 10 guard/receipt contract, rather than a general cross-store workflow platform.
- No permanent Firestore/Postgres/DynamoDB dual-write architecture.
- Account export/deletion inventory spans every canonical store and object tier.

## Local development

Phase 10 provides local Postgres + pgvector and official DynamoDB Local. Normal development should not require Neon/AWS credentials. Fakes remain useful for unit tests, but persistence integration tests should exercise local engines with the actual semantics they represent.

## Firestore migration

Phase 10 owns:

1. source collection/repository inventory and target ownership map;
2. versioned Postgres migrations and DynamoDB schema/bootstrap;
3. dry-run/idempotent/restartable backfill;
4. count/hash/sample reconciliation;
5. short write-freeze/final-delta cutover rather than indefinite dual writes;
6. bounded rollback/verification window;
7. removal of normal runtime Firestore dependencies/indexes after acceptance.

Historical ADRs/evidence remain historical.

## ChatGPT credentials

Reusable ChatGPT credentials must never be stored in Postgres, DynamoDB, GCS, Secret Manager, browser storage, managed logs/traces, analytics, or exports. Only safe connection/attribution state may enter managed storage.
