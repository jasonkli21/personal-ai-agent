# Free-Tier and Cloud Portability Plan

Status: reconciled infrastructure direction  
Date: 2026-10-02

## 1. Current GCP baseline

Preserve the repository's current deployed topology:

```text
Next.js web        -> Cloud Run
FastAPI API        -> Cloud Run
private worker     -> Cloud Run
durable data       -> Firestore Native mode
async notification -> Pub/Sub
secrets            -> Secret Manager
generation         -> Gemini API through LLM boundary
embeddings         -> Gemini API through embedding boundary
```

This is already implemented/documented and should not be replaced merely to optimize hypothetical future storage.

## 2. Free-tier posture

Current public pricing verified on 2026-10-02:

- Firestore Standard: one free database per project, 1 GiB stored data, 50,000 reads/day, 20,000 writes/day, 20,000 deletes/day, 10 GiB/month outbound.
- Cloud Storage Always Free: 5 GB-months Standard storage in eligible `us-west1`, `us-central1`, and `us-east1` regions, plus bounded operations/data transfer.
- DynamoDB Always Free: 25 GB storage plus 25 provisioned RCUs and 25 provisioned WCUs.
- Gemini 3.8 Flash Standard currently lists free-tier input/output tokens.
- Gemini Embedding 2 currently lists free-tier multimodal embedding input.

These offerings can change. Keep pricing assumptions in deployment docs/configuration, not in core application behavior.

## 3. Firestore should remain the near-term store

Do not migrate merely because Firestore's free storage is 1 GiB.

Reasons:

- current repository contracts and tests already target Firestore;
- current memory vector retrieval uses Firestore cosine KNN;
- current research design stores bounded evidence rather than full pages;
- personal chat/memory metadata is likely to remain small for a long time;
- migration work would distract from research/memory/search objectives.

Instead, measure:

```text
stored bytes
index growth
memory/vector count
research evidence growth
daily reads/writes
```

Create a migration trigger only when actual usage approaches a meaningful portion of the free limits.

## 4. Cloud Storage is future blob storage, not current core storage

Add Cloud Storage when a concrete feature needs blobs.

Potential examples:

- uploaded PDFs,
- images,
- email attachments,
- exports,
- domain-app documents.

Do not use Firestore/DynamoDB for large binary content.

However, the accepted bounded Phase 5 research design intentionally does not store full fetched pages or raw search responses, so research alone does not require Cloud Storage.

Future seam:

```python
class BlobStore(Protocol):
    ...
```

Implement it only when the first blob feature exists.

## 5. Generation-model upgrade strategy

The current repo correctly chooses the generation model through runtime `AI_MODEL`.

The deployment example still references `gemini-2.5-flash`.

As of 2026-10-02, `gemini-3.8-flash` is a newer stable Flash model and currently has free-tier Standard input/output pricing.

Recommended change:

1. do not alter the `LLMClient` contract;
2. deploy/test `AI_MODEL=gemini-3.8-flash` in an opt-in environment;
3. rerun provider token-count compatibility tests;
4. verify configured context/output ceilings;
5. rerun streaming/error/cancellation/provider-quality checks;
6. only then update the recommended deployment default.

This should be a configuration/verification change, not an application refactor.

## 6. Embedding upgrades require a migration plan

Current accepted behavior:

```text
gemini-embedding-001
768 dimensions
normalized vectors
Firestore vector KNN
model/dimension compatibility filtering
```

Gemini Embedding 2 is a newer free-tier option, but changing embedding models is not equivalent to changing a generation model.

Before migration define:

- target dimensions,
- whether old/new vectors coexist,
- re-embedding strategy,
- vector-index creation,
- query compatibility,
- rollback,
- evaluation comparison,
- deletion of obsolete indexes/data if desired.

Do not silently repoint the environment variable and make old vectors unreadable.

## 7. AWS portability: selective migration, not multi-cloud v1

DynamoDB is attractive as a future free durable store because its Always Free storage allowance is much larger.

Do not implement DynamoDB now.

Preserve portability through existing repository contracts and add AWS adapters only after a concrete trigger.

Potential future hybrid:

```text
Cloud Run API/worker
      |
      +--> DynamoDB: canonical records
      |
      +--> separate vector-index implementation
      |
      +--> Cloud Storage: blobs, if already used
      |
      '--> Gemini API
```

There is no requirement that model provider, compute, document store, blob store, and vector index live in one cloud.

## 8. DynamoDB migration is two problems

### A. Durable structured records

Candidate data:

- conversations,
- messages,
- memory metadata/content,
- lifecycle events,
- research sessions/evidence.

The repository layer should make this feasible.

### B. Vector retrieval

DynamoDB does not replace the current Firestore cosine-KNN behavior by itself.

A later AWS-compatible memory backend could use, for example:

- DynamoDB for canonical records plus a separate local/vector index;
- a purpose-built vector service;
- another storage engine if justified.

Keep the `MemoryRepository`/retrieval contract explicit enough that canonical persistence and nearest-neighbor search can eventually be split without changing context assembly.

Do not build that split until migration is warranted.

## 9. Cost safeguards

Free tier is a goal, not a hard guarantee.

Continue to use:

- Cloud Run `min-instances=0`,
- bounded/max instance configuration,
- billing budgets/alerts,
- request/data-size bounds,
- short Pub/Sub envelopes,
- explicit provider rate limits,
- limited logging of safe metadata,
- no unbounded page/raw-response retention,
- opt-in external/provider evaluations.

A budget alert is not a hard spending ceiling.

## 10. Sensitive-data provider policy

Gemini's free Developer API tier currently states that content may be used to improve Google products.

Therefore:

- continue using synthetic/non-sensitive data while the current public bootstrap is unauthenticated;
- do not treat "free" as sufficient justification for routing health or other sensitive data to a provider;
- provider suitability should be reviewed separately from cost before real personal data is enabled.
