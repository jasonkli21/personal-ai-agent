# Storage and Artifact Strategy

Status: proposed storage extension  
Date: 2026-10-05

## 1. Goal

Use the available GCP free storage efficiently without adding a second database prematurely.

Target split:

```text
Firestore
  -> hot, queryable, transactional, indexed, vector-aware state

Cloud Storage
  -> bulky, immutable or append-style artifacts that do not need database queries
```

Cloud Storage expands practical free storage headroom, but it is not a 5-GB extension of Firestore semantics.

---

## 2. Current baseline

The repository currently uses Firestore for:

- conversations/messages,
- working summaries,
- memories,
- memory embeddings,
- vector KNN retrieval,
- memory lifecycle state,
- research sessions/evidence,
- canonical entities/claims,
- decisions,
- iterative research state,
- operational/account data.

The current deployment docs intentionally defer Cloud Storage because existing request paths do not persist blobs/full publisher pages.

The new provider-routing/evaluation scope changes that: detailed traces and raw evaluation output are natural artifact workloads.

### 2.1 Additive credential-storage boundary for ChatGPT-plan usage

ChatGPT-plan integration adds a third **security boundary**, not a third cloud database:

```text
Firestore
  -> Personal AI operational/queryable state

Cloud Storage
  -> bulky immutable artifacts

User-controlled local/native/self-hosted credential store
  -> ChatGPT SIWC authentication credentials only
```

Persistent ChatGPT access/refresh tokens must not be stored in Firestore, Cloud Storage, Secret Manager, browser storage, logs, traces, analytics, or exports.

The local credential store is outside the GCP persistence model and exists only to satisfy the explicit ChatGPT-plan integration.


---

## 3. Firestore responsibilities

Keep in Firestore:

### Conversation/context
- conversations,
- messages,
- summaries,
- compact context-inspection metadata.

### Memory
- memory records,
- source provenance,
- embeddings,
- embedding model/dimensions,
- lifecycle events/state,
- vector KNN indexes.

### Research/decisions
- bounded research-session metadata,
- evidence metadata/excerpts allowed by provider policy,
- entities/aliases/claims,
- decision snapshots/evaluations.

### Runtime control
- application registry state where persisted,
- provider/model registry state where persisted,
- quota ledger,
- provider health/cooldown,
- routing summaries,
- evaluation-run summaries.

### Artifact metadata
- object key/URI,
- type,
- content hash,
- bytes,
- sensitivity,
- owner/request/run IDs,
- creation time,
- retention class,
- deletion status.

### ChatGPT-safe operational metadata

Firestore may retain non-secret metadata needed to understand Personal AI conversations, for example:

- provider = `openai_chatgpt_plan`;
- model slug/display label used for a completed turn;
- explicit-provider route mode;
- completion/failure class;
- redacted context-category/sensitivity summary;
- local bridge connection state only if represented as ephemeral status, not credentials.

Prefer local-only storage for ChatGPT account registration identifiers unless cloud persistence provides a concrete product benefit.


---

## 4. Cloud Storage responsibilities

Initial approved artifact classes:

1. **Detailed routing/context traces**
   - candidate models,
   - scoring inputs,
   - cascade/validation details,
   - detailed context manifest where policy permits.

2. **Evaluation artifacts**
   - raw model outputs,
   - JSONL fixture results,
   - comparison/replay data,
   - per-model run artifacts.

3. **Account exports**
   - bounded export bundle,
   - temporary downloadable object,
   - explicit cleanup.

4. **Debug/replay artifacts**
   - only when intentionally retained.

5. **Selected research artifacts**
   - only if source/provider storage rights permit,
   - not full-page archival by default.

### ChatGPT trace constraints

When a ChatGPT-plan turn produces an optional trace/evaluation artifact:

- strip Authorization headers and OAuth tokens;
- strip authorization URLs containing token/account hints;
- avoid full ChatGPT account identifiers when an opaque local reference is sufficient;
- retain only the minimum request/context detail needed for debugging/evaluation;
- apply the same or stricter sensitivity/retention class as the underlying context.


---

## 5. What must not move to Cloud Storage

Do not use GCS as the primary store for:

- active conversations,
- memory records,
- memory vectors,
- vector indexes,
- quota/health state,
- current research execution state,
- decision state,
- authoritative domain application data.

Do not require scanning object listings to answer normal application queries.

### ChatGPT authentication data that must never enter GCS

Do not store:

- SIWC access tokens;
- SIWC refresh tokens;
- retained ID tokens;
- PKCE verifiers;
- OAuth state/nonce values after the transient auth flow;
- raw credential files;
- copied browser cookies/session data.


---

## 6. ArtifactStore abstraction

Conceptual:

```python
@dataclass(frozen=True)
class ArtifactRef:
    key: str
    content_type: str
    size_bytes: int
    sha256: str
    sensitivity: Sensitivity
    retention_class: str

class ArtifactStore(Protocol):
    async def put(self, key, data, metadata) -> ArtifactRef: ...
    async def get(self, ref: ArtifactRef) -> bytes: ...
    async def delete(self, ref: ArtifactRef) -> None: ...
```

Initial implementations:

- `InMemoryArtifactStore` / fake,
- `GCSArtifactStore`.

Keep storage SDK details behind the boundary.

---

## 7. Object layout

Illustrative only:

```text
traces/YYYY/MM/DD/<request-id>.json.gz
evaluations/<eval-version>/<run-id>/results.jsonl.gz
exports/<owner-id>/<export-id>.zip
debug/<date>/<artifact-id>.json.gz
research/<session-id>/<artifact-id>.json.gz
```

Do not expose raw object keys as authorization.

### 7.1 Local credential-store model

Implementation-specific details should remain behind a local credential interface, for example:

```python
class ChatGPTCredentialStore(Protocol):
    async def list_registrations(...): ...
    async def load(...): ...
    async def save(...): ...
    async def delete(...): ...
```

Preferred implementations should use OS-protected credential/key storage when practical. A protected local file may be used only if it follows the current SIWC guidance and has restrictive permissions.

This interface belongs to the local/user-controlled bridge, not the Cloud Run backend.


---

## 8. Firestore reference model

Example compact Firestore metadata:

```json
{
  "artifact_id": "...",
  "owner_id": "...",
  "type": "evaluation_results",
  "storage": "gcs",
  "key": "evaluations/...",
  "size_bytes": 123456,
  "sha256": "...",
  "sensitivity": "low",
  "created_at": "...",
  "retention_class": "evaluation_30d"
}
```

Normal query/indexing happens on metadata, not object contents.

---

## 9. Compression and format

Prefer:

- JSON for individual trace objects,
- JSONL for bulk evaluation results,
- gzip compression for text-heavy artifacts,
- ZIP only for user-facing exports or multi-file bundles.

Avoid storing thousands of tiny objects when one bounded JSONL artifact per evaluation run is sufficient.

---

## 10. Retention

Retention is explicit.

Suggested initial classes:

```text
debug_short
evaluation_standard
export_temporary
research_policy_bound
pinned_fixture
```

Implementation should map these to configurable durations rather than embedding assumptions in every caller.

Pinned fixtures should be rare and intentional.

### 10.1 Export and deletion behavior for ChatGPT-plan data

Personal AI account exports may include ordinary conversation content and provider/model attribution according to existing export policy, but must never include reusable ChatGPT credentials.

Disconnecting ChatGPT should:

- clear local credentials/registration state as defined by the integration;
- attempt remote revocation where supported;
- leave existing Personal AI conversation records intact unless the user separately deletes them;
- make future ChatGPT-plan requests fail closed until reauthorized.


---

## 11. Privacy and authorization

Artifact sensitivity can be equal to or greater than its Firestore summary.

Requirements:

- service-side authorization before reads,
- no public bucket/object default,
- do not put raw sensitive values in object names,
- owner/request/run scope in metadata,
- redaction where raw data is unnecessary,
- deletion/export paths include artifact references.

Sensitive Health/Finance traces should default to minimal retention or no verbose artifact unless explicitly needed.

---

## 12. Failure semantics

### Optional debug/evaluation artifact failure

Do not turn a successful inference into a user-visible failure solely because optional artifact persistence failed.

Record a compact Firestore warning/metric where possible.

### Required artifact failure

Exports and explicitly requested retained artifacts must fail atomically/clearly if storage fails.

### Orphan handling

If GCS write succeeds but Firestore metadata write fails:

- attempt cleanup,
- otherwise surface for bounded orphan reconciliation.

If Firestore metadata exists but object is absent:

- mark missing/corrupt,
- do not silently synthesize data.

### 12.1 ChatGPT bridge storage failure semantics

Failure to load/save/refresh local ChatGPT credentials should fail only the ChatGPT-plan request path. It must not corrupt Personal AI Firestore/GCS state or prevent automatic strict-free providers from operating.

Never fall back by copying tokens into cloud storage as a recovery mechanism.


---

## 13. Free-tier guardrails

The implementation should track:

- Firestore stored/index bytes,
- GCS stored bytes,
- GCS operation counts if available,
- artifact creation rate,
- artifact type distribution,
- retention/deletion success.

Current free-tier quotas are operational facts and should be verified at deployment time rather than hard-coded into business logic.

Use a GCP region/bucket configuration that is currently free-tier eligible. Track Cloud Storage operations as well as bytes: a large number of tiny trace objects can exhaust free Class A operations before storage capacity. Ordinary Cloud Billing budget alerts are not hard caps; use service/application guardrails and spend caps only where supported.

---

## 14. Why this comes before DynamoDB

DynamoDB should not be added merely because Firestore has less free storage.

First:

1. move bulky artifacts out of Firestore,
2. use bounded retention,
3. monitor structured/queryable data growth,
4. verify index/vector contribution,
5. optimize records where appropriate.

Only consider a second database if **structured/queryable state itself** approaches the Firestore limit after these steps.

---

## 15. DynamoDB escape-hatch trigger

Suggested architectural trigger, not an exact operational threshold:

```text
normal:
  Firestore comfortably below storage limit
  -> no second database

warning:
  structured Firestore data/indexes show sustained high utilization
  after artifact offload and retention tuning
  -> investigate portability/migration

migration:
  measured structured-state growth cannot stay within free budget
  without harmful product compromises
  -> evaluate DynamoDB or another store
```

Do not build DynamoDB into the main implementation roadmap today.

---

## 16. Embeddings and storage

Current memory retrieval uses:

```text
Gemini API embeddings
  -> Firestore vector fields
  -> Firestore vector KNN
```

A second document store or GCS does not replace this capability.

An embedding migration must explicitly address:

- model,
- dimensions,
- vector compatibility,
- Firestore indexes,
- re-embedding,
- rollback.

---

## 17. Acceptance criteria for artifact tier

The artifact-storage phase is complete when:

- verbose evaluation output can be stored outside Firestore;
- verbose routing/context traces can optionally be stored outside Firestore;
- Firestore retains searchable artifact metadata/reference;
- tests use a fake/in-memory artifact store;
- cloud implementation uses private GCS;
- storage failures have defined semantics;
- retention/deletion is bounded;
- memory vectors and canonical operational records remain in Firestore;
- no DynamoDB dependency is introduced.


- no ChatGPT access/refresh/ID token or raw SIWC credential file is persisted in Firestore, GCS, Secret Manager, browser storage, logs, traces, analytics, or exports;
- ChatGPT provider/model attribution can be stored without storing reusable credentials;
- local credential storage is covered by dedicated tests and restrictive permissions/OS protection where available;
- ChatGPT trace/evaluation artifact paths demonstrably redact auth/account secrets.
