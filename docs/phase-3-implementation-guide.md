# Phase 3 implementation guide

Phase 3 simple memory is implemented locally. The [plan](phase-3-implementation-plan.md)
remains the scope reference; [ADR 0009](decisions/0009-simple-attributable-memory.md)
records decisions and clarifications. Gates remain disabled by default. Real
Gemini extraction/embeddings, emulator memory persistence, Firestore vector index
readiness and deployed behavior are unverified. Phase 4 has not started.

## Plan-to-code map

| Plan | Implementation | Offline evidence |
| --- | --- | --- |
| P3.0 | `evaluation/memory-fixtures.json`, `evaluation/memory.py` | Fourteen named synthetic cases; separate-conversation Phase 2 baseline, deterministic identities/vectors/order, safe failure results |
| P3.1 | ADR 0009, `memory/contracts.py`, settings | Four types, strict candidates/records, UTC/source/vector/config validation |
| P3.2 | `memory/repositories.py`, `firestore.indexes.json` | Fake owner isolation, duplicates, active-only KNN; mocked Firestore transaction/source and SDK-vector serialization checks |
| P3.3 | `llm/memory.py`, `memory/fake.py` | Locked SDK with mocked HTTP: batching/order, task types, configured dimensions, malformed responses and safe errors |
| P3.4 | `memory/policy.py`, `memory/services.py` | Exact user excerpts, all four types, confidence, dates, sensitive/external denial, source rewrite, duplicate, provider/storage failure |
| P3.5 | `MemoryRetriever` | Threshold, bounded candidates, owner/status/model/dimension/source revalidation, correction/time ordering, no-match and failure fallback |
| P3.6 | Context assembler/inspector extensions, `memory/inspection.py`, development panel/proxy | Whole-record fit, original prompt/history retention, summary/memory/recent-turn coexistence, separate inspection gate, read-only provenance metadata |
| P3.7 | `ChatTurnService`, injectable memory dependencies | Normal/regenerate/edit paths retrieve after persistence; successful terminal frame precedes extraction; failures leave SSE and assistant status intact |
| P3.8 | `make memory-eval`, offline CI, manual tests and release record | All local checks recorded in [release evidence](releases/phase-3-simple-memory.md) |

## Runtime sequence

The existing conversation reservation persists the user/branch mutation first.
Retrieval embeds that user's query, searches bounded owner-scoped compatible
active vectors, validates source user statements against their current active
branches, and offers a small ordered set to the context assembler. Retrieval
failure returns safe diagnostics and no memory. It does not prevent the answer.

The assembler first produces its existing valid Phase 2 context. It counts a
labelled historical-memory block together with that complete request, adding
whole records only when the block and total budgets permit. Optional memory
never displaces fitting recent history or a summary. This deliberately prefers
conversation continuity over recall when context is full. A memory counting
failure returns the already counted Phase 2 request. System instructions remain
in the provider's system channel; the memory block precedes the summary and raw
history. The newest user prompt remains last.

After durable assistant completion and a successful ASGI send of
`response.completed`, the server schedules bounded extraction in a retained,
in-process task that runs the service in a worker thread. Closing the browser or
proxy stream after the terminal event does not cancel that task. It does not add
SSE messages or modify assistant status. Process shutdown can still interrupt
the work; there is no queue/replay or exactly-once processing promise, and
repeated attempts are idempotent. No worker or Pub/Sub flow is added.

Extraction persists exact excerpts beginning with one of the supported
first-person markers, and accepts them only as unquoted, complete assertions
that start at the beginning of a source sentence. A `semantic_summary` is an explicit user generalization
such as “I usually take a sketchbook on walks,” rather than an inferred summary.
The policy rejects unsupported model paraphrases and asserted effective dates
that do not appear in the retained excerpt. Sensitive/external terms and
configured denied terms reject the supplied user statement before extraction or
embedding. Deny rules are conservative heuristics, not a complete classifier.
Review both provider-data suitability and the public unauthenticated deployment
boundary before enabling memory for any personal content.

## Records and provenance

The dedicated `memories` collection stores the plan's required fields plus a
rationale code and `source_turn_id` (completed assistant ID). User-source IDs,
roles and content determine the fingerprint and deterministic identity. Normalize
only for deduplication; retain original wording. Observation/effective/creation
times are UTC; implicit effective time equals observation time, while asserted
times require an explicit matching ISO date in the source excerpt.

Firestore writes atomically validate the completed assistant, owner, conversation,
source user statements, source fingerprint, and ancestor root-cut state. A
concurrent source edit conflicts with these reads. Fake writes use the source
message repository's mutation lock for equivalent semantics. Existing duplicate
records are returned without replacing text or vectors. Old memories remain
stored; retrieval excludes source statements no longer on an active completed
branch. Regenerating an assistant does not erase a still-active user's statement.

Vector search prefilters `owner_id`, `status`, `embedding_model`, and
`embedding_dimensions`, then performs cosine nearest-neighbor lookup with a
fixed limit. No collection scan or incompatible fallback is permitted. Retrieval
uses .05-wide similarity bands, corrections first within a band, newest effective
time, exact similarity, then UUID. Old qualifying records can still be selected;
this is a preference rule, not automatic conflict resolution.

## Configuration

All settings are in [backend examples](../backend/.env.example). Defaults:

| Setting | Default |
| --- | --- |
| `MEMORY_ENABLED`, `MEMORY_EXTRACTION_ENABLED`, `MEMORY_INSPECTION_ENABLED` | false |
| `MEMORY_EMBEDDING_MODEL`, `MEMORY_EMBEDDING_DIMENSIONS` | `gemini-embedding-001`, 768 |
| `MEMORY_EMBEDDING_BATCH_SIZE` | 8 |
| `MEMORY_MAX_CANDIDATES_PER_TURN` | 4 |
| `MEMORY_RETRIEVAL_CANDIDATE_LIMIT`, `MEMORY_RETRIEVAL_LIMIT` | 20, 4 |
| `MEMORY_MIN_SIMILARITY` | .8 |
| `MEMORY_MAX_CONTEXT_TOKENS` | 512 |
| `MEMORY_TIMEOUT_SECONDS` | 5 |
| `MEMORY_SENSITIVE_TERMS` | empty JSON array |

Dimensions must be 1–2048 for Firestore; provider-specific supported dimensions
also need manual verification. Retrieval and optional memory counting each use
at most one quarter of remaining Phase 2 preparation time, capped by the memory
timeout. Extraction uses its own total deadline. Provider RPCs disable retries;
memory/provenance storage RPCs use remaining timeouts. A Firestore commit with a
lost acknowledgement can still have succeeded; deterministic identities make a
later retry safe. No automatic embedding migration is supported.

## Provision vector indexes before enabling retrieval

The [index manifest](../firestore.indexes.json) describes the default 768-dimensional
composite vector index. The bootstrap deploy script deliberately leaves all gates
off and provisions only Phase 1/2 indexes. For an intentional memory deployment,
create the memory index using the configured dimension and wait until it is READY
before changing gates (the model/dimension metadata fields are index prefilters):

```sh
gcloud firestore indexes composite create \
  --database='(default)' --collection-group=memories --query-scope=COLLECTION \
  --field-config=field-path=owner_id,order=ascending \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=embedding_model,order=ascending \
  --field-config=field-path=embedding_dimensions,order=ascending \
  --field-config='field-path=embedding,vector-config={"dimension":"768","flat":"{}"}'

gcloud firestore indexes composite list --database='(default)' --format=json
```

Select the deliberate test project first; record index readiness without credentials
or raw memory content. If using another dimension, update the vector index as well
as environment configuration. Missing/unsupported indexes produce non-fatal empty
retrieval with `retrieval_failed`; no scan fallback is attempted. The emulator
check below only asserts persistence, not production KNN/index behavior.

## Read-only development inspection

Enable `CONTEXT_INSPECTION_ENABLED=true` in both backend and frontend local env
files, and `MEMORY_INSPECTION_ENABLED=true` in both. Enable backend `MEMORY_ENABLED`
if you want memory-fit selection rather than disabled behavior. Open
`/development/context`, supply a synthetic conversation UUID and up to 20 memory
UUIDs (comma separated in the panel; repeated `memory_ids` query parameters on the
API). IDs can be obtained from deliberate synthetic extraction outcomes or storage
inspection; no memory-list/edit API is introduced.

The report estimates supplied-record fit and includes type, source conversation
and user-message IDs, observation/effective/creation times, content-token estimates,
selected versus excluded state and reason, and aggregate memory-block tokens.
Budget `memory_tokens` reports the marginal counted addition to the whole request;
the memory block token count includes its own counting overhead and enforces its
separate ceiling. The report omits memory text/vectors and uses null similarity because no embedding or
semantic search is performed. It neither recreates a prior live request nor
asserts query relevance. Selected means “fits this planning request,” not “was used
previously.” Foreign/unknown IDs return 404, malformed IDs/oversized lists 422;
missing gates return 404. Summary inspection remains read-only and separately gated.

## Verification and opt-in checks

Follow the root README's locked installation, Python 3.11+, uv 0.11.13, Node 22,
and pnpm 11.19.0. Offline commands:

```sh
make backend-test backend-lint context-eval memory-eval
make frontend-test frontend-lint frontend-typecheck
make backend-build frontend-build
bash -n infrastructure/gcp/deploy.sh
git diff --check
```

Fixtures use invented statements, UUIDv5 identities and deterministic fake vectors.
Each query has a separate conversation whose Phase 2 baseline contains no source
fact. Results record safe IDs, scores, reasons, configuration and counts, never
raw private text. They measure the fixed policy, not live embedding quality.

Additional checks from `backend`, with deliberately configured environments:

```sh
RUN_MEMORY_MANUAL_TEST=1 python -m pytest tests/test_memory_manual.py::test_live_synthetic_embedding_and_extraction -q
RUN_MEMORY_EMULATOR_TEST=1 python -m pytest tests/test_memory_manual.py::test_emulator_create_and_get_synthetic_memory -q
RUN_MEMORY_TURN_MANUAL_TEST=1 python -m pytest tests/test_memory_manual.py::test_live_synthetic_turn_persists_memory_and_retrieves_across_conversations -q
```

The emulator test requires `FIRESTORE_EMULATOR_HOST` explicitly exported, creates
invented owner-scoped records with fake vectors, and verifies idempotent retrieval
by ID. The end-to-end test requires a deliberate synthetic Firestore project,
provider credentials, configured vector index, and model capabilities; it streams
a synthetic statement, verifies durable memory and then cross-conversation KNN.
Tests leave their synthetic records in storage for inspection. Record date,
revision, model/dimension/configuration, result and limitations only. These tests
are skipped by default and have not been run in the release evidence.
