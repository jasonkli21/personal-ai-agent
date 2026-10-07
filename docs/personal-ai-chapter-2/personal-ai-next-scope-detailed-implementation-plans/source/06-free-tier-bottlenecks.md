# Free-tier bottlenecks and resource guardrails

## Expected bottleneck order

The exact order changes with provider offerings and user behavior, but for this personal system the likely progression is:

1. hosted model request/token limits;
2. external search quota;
3. provider privacy/eligibility constraints;
4. accidental cloud billing or missing strict-$0 hard gates;
5. Neon compute/storage/vector-index/connection growth and cross-cloud network use;
6. GCS operation counts/artifact retention once Phase 20 is active;
7. DynamoDB capacity/hot-key/network behavior (raw storage is expected to have more headroom for one user);
8. Cloud Run/Artifact Registry/Secret Manager and other supporting infrastructure ceilings.

Model/search quotas are resettable flow limits. Durable databases/object storage are cumulative and need long-horizon monitoring even when models limit daily/monthly write generation.

## Resource ledger

Track each resource independently with source/confidence and refresh date rather than hard-coding volatile allowances:

- provider/model request/token/usage buckets;
- search requests;
- Cloud Run CPU/memory/network;
- Neon database bytes, vector/index bytes, compute time, connections;
- DynamoDB table/index bytes, read/write capacity mode/consumption, throttles/hot keys;
- GCS bytes, object operations, retention/lifecycle behavior;
- cross-cloud egress/network costs;
- Artifact Registry image storage;
- secrets/other managed-service usage.

## Strict-$0 guardrails

Admission must fail before a known billable path where practical. Unknown provider billing/free eligibility cannot be treated as free. Optional traces/evals may stop before artifact/resource ceilings; core correctness and required export failures remain explicit.

Phase 10 deployment validation includes Neon + DynamoDB + network use. Later phases extend the same ledger rather than creating separate billing logic.

## Capacity design implications

Do not choose DynamoDB solely because its current free storage allowance is larger, and do not choose Postgres solely for consistency with other projects. Phase 10 uses both because their access patterns differ. The inference bottleneck reduces the value of extreme request capacity, but long-term event/history accumulation still benefits from operational storage headroom.

Phase 10 reviews actual account/region allocations for fixed provisioned Standard DynamoDB capacity, including its publication GSI and transactional directory amplification. Neon table/TOAST/index bytes, cast/query compute, pooled connections and migration/recovery network work all count toward the budget. The lossless-array baseline avoids duplicate vector storage but spends query CPU; neither storage arithmetic nor alerts establish a hard free limit. Detailed activation gates belong in the [Phase 10 verification plan](../../phase-10-migration-cutover-and-verification-plan.md).

## Embeddings

Memory embedding migration is never implicit. Phase 10 carries current vectors into Postgres/pgvector with provider/model/dimension/task-space metadata. Phase 34 may optimize retrieval but cannot silently change vector space; a provider/model migration requires explicit re-embedding/reindex planning and resource checks.
