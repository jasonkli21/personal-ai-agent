# Target Architecture

Status: integrated next-scope architecture  
Date: 2026-10-05

## 1. Current repository architecture

The current `personal-ai-agent` repository is approximately:

```text
Browser
  |
  v
Cloud Run: public Next.js / React web
  |
  | server-side /api proxy
  | Cloud Run service identity + end-user Google ID token
  v
Cloud Run: private FastAPI API
  |
  +---------------------------+-----------------------------+
  |                           |                             |
  v                           v                             v
Chat services          Research / Decisions          Domain modules
  |                           |                             |
  +---------------------------+-----------------------------+
                              |
                              v
                    shared context assembly
                 conversation + summary + memory
                 + evidence under token budgets
                              |
              +---------------+----------------+
              |                                |
              v                                v
       Gemini API                       search/domain providers
       generation                       Brave / Nominatim /
       structured memory                Open Food Facts / fakes
       extraction
              |
              +--> Gemini API embeddings
                   gemini-embedding-001
                             |
                             v
                        Firestore
                  memory vector storage
                             |
                             v
                   Firestore vector KNN


Durable Firestore data:
  conversations
  messages/summaries
  memories + embeddings
  memory lifecycle state
  research sessions/evidence
  canonical entities/claims
  decisions
  iterative research state

Gated memory-lifecycle work:
  Firestore job -> Pub/Sub -> private Cloud Run worker -> Firestore

Security/operations:
  Google OIDC
  Cloud Run IAM
  Secret Manager
  Cloud Build
  Artifact Registry
  Cloud Scheduler / maintenance paths
```

Cloud Storage is not currently used by normal request paths.

---

## 2. Target system shape

```text
                 Native Chat / Developer UI
                           |
        +------------------+-------------------+
        |                                      |
        v                                      v
  General requests                      Domain applications
                                        Travel / Shopping
                                        Finance / Health
                                                |
                                                v
                               Application / workspace envelope
                                                |
                                                v
+--------------------------------------------------------------------------------+
|                              PERSONAL AI RUNTIME                               |
|                                                                                |
|  Application Registry --> Policy / Permissions                                |
|            |                    |                                               |
|            v                    v                                               |
|      Context Planner ---> Context Providers                                    |
|            |             / Memory / Domain / Search / Tools                    |
|            v                                                                   |
|      Context Builder ----> provenance + token/sensitivity accounting           |
|            |                                                                   |
|            v                                                                   |
|      Inference Task Profiler                                                   |
|            |                                                                   |
|            v                                                                   |
|  +---------------------- Inference Router -------------------------------+      |
|  | hard eligibility -> task quality -> quota scarcity -> route/cascade  |      |
|  +----------+------------------+----------------------+-------------------+      |
|             ^                  ^                      ^                          |
|             |                  |                      |                          |
|      Model Registry       Quota Ledger          Evaluation Profiles             |
|             |                  |                      |                          |
|             +------------------+----------------------+                          |
|                                |                                                 |
|                         Provider Gateway                                         |
|                  LiteLLM adapter + native adapters                              |
+--------------------------------+------------------------------------------------+
                                 |
            +----------------+----------------+----------------+
            |                |                |
            v                v                v
         Gemini            Groq          Cloudflare
      primary / embed    fast secondary   Workers AI
      strict-free if     strict-free if   strict-free if
        verified           verified         verified

Possible later extensions:
  Cerebras / Mistral / OpenRouter / GitHub Models / Hugging Face / others
```

Search/retrieval providers remain distinct from model providers even if one vendor offers both.

### 2.1 Additive ChatGPT-plan interaction path

ChatGPT plan usage is a separate user-controlled execution lane layered beside the existing cloud provider gateway:

```text
Domain app / Personal AI web UI
        |
        +-----------------------------+
        |                             |
        v                             v
Personal AI cloud runtime       Local/native ChatGPT Plan Bridge
(context / policy / threads)      (user-controlled credentials)
        |                             |
        | build bounded               | OAuth / model discovery
        | ContextPackage              | Responses API stream
        v                             v
Browser/native sidecar  -----------------------> OpenAI Responses API
        ^                             |
        | streamed normalized output |
        +-----------------------------+
        |
        v
Personal AI conversation persistence
(provider/model attribution, no ChatGPT OAuth token)
```

The bridge is required because persistent Sign in with ChatGPT authentication credentials must not be stored in the managed Personal AI cloud environment.

The cloud backend continues to own:

- application/workspace authorization;
- context planning and retrieval;
- sensitivity policy;
- conversation/thread state;
- provenance;
- mutation proposal policy.

The user-controlled bridge owns:

- SIWC OAuth/OIDC/PKCE;
- credential storage/refresh;
- account/model discovery;
- Responses API execution/streaming;
- ChatGPT-plan-specific error handling.

The browser/native app coordinates the two paths but never receives reusable ChatGPT OAuth tokens.


---

## 3. Target data plane

```text
                         Personal AI Runtime
                                |
             +------------------+------------------+
             |                                     |
             v                                     v
        Firestore                            Cloud Storage
   operational/queryable                    artifact/blob tier
             |                                     |
  +----------+-----------+             +-----------+-----------+
  |          |           |             |           |           |
 chats     memory      routing      detailed     raw evals   exports
messages   vectors     summaries      traces      JSONL      bundles
research   KNN         quota state    debug       replay     selected
decisions  lifecycle   registries     artifacts    data       research
  |                                      |
  +---------------- metadata/ref --------+
```

Rules:

- Firestore remains the canonical query/transaction store.
- Firestore retains memory vectors and vector KNN.
- Cloud Storage holds bulky immutable artifacts.
- Firestore stores references and searchable summary metadata for those artifacts.
- Do not make Cloud Storage a shadow database.
- Do not duplicate authoritative domain data into either store.
- Treat Firestore bytes/operations, GCS bytes/operations, Cloud Run compute/network, and Artifact Registry image storage as finite free-tier resources with operational monitoring.

---

## 4. Request envelope

Conceptual:

```json
{
  "user_id": "...",
  "application_id": "health",
  "workspace_id": "...",
  "conversation_id": "...",
  "request_id": "...",
  "message": "...",
  "capabilities": [],
  "client_context": {}
}
```

Semantics:

- `user_id`: authenticated principal.
- `application_id`: origin app.
- `workspace_id`: optional domain scope.
- `conversation_id`: AI conversation scope.
- `request_id`: trace/idempotency scope.
- `capabilities`: bounded client-declared capabilities.
- `client_context`: bounded non-authoritative UI/session context.

Standalone chat has a canonical app identity.

### 4.1 Additive explicit-provider fields

A request that launches the AI sidecar may additionally carry non-secret selection metadata:

```json
{
  "inference_mode": "automatic_strict_free | explicit_provider",
  "explicit_provider": "openai_chatgpt_plan | null",
  "explicit_model": "account-visible-model-slug | null",
  "context_selection": {},
  "response_action_capabilities": ["copy"]
}
```

Rules:

- provider selection is user intent, not a hint the automatic router may ignore;
- no ChatGPT OAuth token is carried in this envelope;
- `context_selection` can narrow otherwise-authorized context, especially for Health/Finance;
- `response_action_capabilities` reflects what the domain UI may safely do with an answer.


---

## 5. Application registry

Maps app to:

- context providers,
- tools/actions,
- policies,
- memory namespace,
- sensitivity defaults,
- cross-app behavior,
- optional budget hints.

---

## 6. Context providers

Provider goals:

- hide domain storage details,
- typed bounded responses,
- app/user/workspace scope,
- provenance,
- sensitivity,
- predictable failures,
- independent testing.

Conceptual:

```python
class ContextProvider:
    provider_id: str

    async def get_profile(self, request, selection): ...
    async def get_current_context(self, request, selection): ...
    async def search(self, request, query): ...
    async def get_entity(self, request, entity_ref): ...
    async def get_history(self, request, window): ...
```

---

## 7. Context source classes

```text
GLOBAL_PROFILE
DOMAIN_PROFILE
DOMAIN_CURRENT_STATE
DOMAIN_HISTORY
AI_MEMORY
CONVERSATION
EXTERNAL_RESEARCH
TOOL_RESULT
CLIENT_CONTEXT
```

Source class affects trust, policy, freshness, priority, and inference sensitivity.

### 7.1 Sidecar context-package source

Add a normalized `SIDECAR_CONTEXT_PACKAGE`/equivalent boundary above provider execution, composed from existing source classes. It is not a new source of truth.

The package should preserve:

- context items and their source classes;
- provenance and authority;
- effective sensitivity;
- token/size budget;
- selected/excluded categories;
- conversation history required for the turn;
- domain mutation restrictions.

The same package can be consumed by the normal cloud inference runtime or by the explicit ChatGPT-plan bridge after policy checks.


---

## 8. Context planner

Decides **what information to retrieve**, not which model to use.

Inputs:

- request,
- app/workspace identity,
- available providers,
- tool capabilities,
- lightweight conversation state,
- policy.

Start deterministic.

---

## 9. Context builder

Combines:

```text
system/security instructions
+ application policy
+ global context
+ authoritative domain context
+ AI memory
+ conversation
+ external evidence
+ tool state
```

Respect:

- total/per-source budgets,
- relevance,
- recency,
- authority,
- sensitivity,
- provenance.

It computes effective downstream inference sensitivity.

---

## 10. Policy boundary

Before context retrieval:

- principal/app access,
- provider/field access,
- cross-app policy,
- sensitivity,
- operation class.

Before model invocation:

- provider data-policy eligibility,
- strict-free eligibility,
- capability/context fit.

Before mutation:

- domain validation,
- confirmation,
- auditability.

---

## 11. Context provenance and inspection

Trace:

- planner decisions,
- provider calls,
- policy checks,
- exclusions,
- token counts,
- final source outline,
- inference task,
- candidates/selected model,
- route reason,
- fallback/cascade,
- compact usage metadata,
- optional detailed-artifact URI.

Verbose traces belong in Cloud Storage when retained; Firestore should retain compact searchable metadata.

---

## 12. Inference runtime boundary

Conceptual:

```python
@dataclass(frozen=True)
class InferenceRequest:
    task_type: TaskType
    input: object
    required_capabilities: frozenset[Capability]
    sensitivity: Sensitivity
    quality_floor: float | None
    strict_free: bool = True
    allow_escalation: bool = True
```

Separate actual operations:

- stream generation,
- non-streamed generation,
- structured generation,
- embeddings.

Do not force every provider into an oversized universal interface.

---

## 13. Provider gateway

```text
Personal AI inference interfaces
        |
        v
ProviderGateway / Backend
        |
        +-- GeminiBackend
        +-- GroqBackend
        +-- CloudflareBackend
        +-- LiteLLM-backed implementation where useful
        |
        v
Provider APIs
```

Personal AI owns policy. The gateway owns request/response/error normalization.

### Gemini

- migrate existing generation/memory extraction behind neutral contracts,
- preserve `gemini-embedding-001` initially,
- strict-free eligibility is account/model configuration.

### Groq

- preferred secondary provider,
- only Groq Free-plan eligible models may enter strict-free candidate sets,
- use rate-limit/usage headers when available to improve quota accounting,
- concrete model list remains configuration.

### Cloudflare Workers AI

- required third provider,
- only Workers Free-plan eligible models may enter strict-free candidate sets,
- model list remains configuration and may change independently of the application.

### 13.1 ChatGPT Plan Bridge

This is a special backend shape rather than a normal server-side provider adapter:

```text
Personal AI normalized inference request
        |
        +-- automatic_strict_free -> server ProviderGateway -> Gemini/Groq/Cloudflare
        |
        +-- explicit ChatGPT plan -> client bridge protocol
                                     |
                                     +-- selected account
                                     +-- selected account-visible model
                                     +-- OAuth refresh
                                     +-- POST /v1/responses
                                     +-- normalize streamed events/errors
```

Conceptual bridge interface:

```python
class ChatGPTPlanBridge(Protocol):
    async def connection_status(...): ...
    async def list_accounts(...): ...
    async def list_models(...): ...
    async def stream_response(context_package, model, request_nonce): ...
    async def disconnect(...): ...
```

The bridge protocol should expose normalized account/model/status metadata but **never** reusable OAuth tokens.

Current Responses constraints for this lane should be isolated inside the bridge/adapter. The rest of Personal AI should not depend directly on temporary SIWC request-shape limitations.

### 13.2 Local bridge transport/security

For the hosted web UI, prefer a loopback-only helper or equivalent user-controlled runtime with:

- loopback/local IPC binding by default;
- explicit allowed-origin configuration for Personal AI/domain frontends;
- short-lived request/session nonce or equivalent client authorization;
- anti-CSRF protections for browser-triggered actions;
- no wildcard credential-bearing CORS;
- token redaction from logs/errors;
- OS-protected credential storage where available.

A native application may embed the credential-bearing client runtime directly if the supported SIWC flow and platform security model are verified during implementation.


---

## 14. Provider/model registry

Conceptual:

```yaml
models:
  cloudflare/example-free-model:
    provider: cloudflare
    enabled: true
    strict_free_eligible: true

    capabilities:
      chat: true
      stream: true
      structured_output: true

    data_policy:
      max_sensitivity: LOW
      policy_status: VERIFIED

    quota:
      source: configured_or_observed

    quality_profile:
      memory_extraction: 0.91
      query_rewrite: 0.94
```

For Groq, strict-free eligibility is still model/account specific:

```yaml
models:
  groq/example-free-model:
    provider: groq
    enabled: true
    strict_free_eligible: true
```

Unknown values remain unknown.

### 14.1 User-entitled provider profile

The provider/model registry should be able to describe an explicit user-entitled provider without admitting it to strict-free automatic routing:

```yaml
providers:
  openai_chatgpt_plan:
    auth_mode: user_oauth_plan
    selection_mode: explicit_user
    automatic_candidate: false
    credential_runtime: local_or_user_controlled
    model_catalog: account_discovered
    hosted_conversation_state: false
```

Account-specific model slugs are discovered through the authenticated bridge and cached only as non-secret, short-lived operational metadata where useful.


---

## 15. Quota/resource ledger

Track:

- observed requests/tokens,
- configured limits,
- reset times,
- cooldown,
- provider health,
- confidence/source of quota estimate.

Possible state confidence:

```text
exact
derived
configured
unknown
```

Do not fabricate precision.

---

## 16. Task profiler

Examples:

```text
chat -> CHAT_RESPONSE
memory extraction -> MEMORY_EXTRACTION
research query rewrite -> QUERY_REWRITE
research synthesis -> RESEARCH_SYNTHESIS
```

Do not spend a model call to identify tasks the caller already knows.

### 16.1 ChatGPT plan usage state

Do not merge ChatGPT-plan limits into the strict-free quota ledger as if they were equivalent resources.

Track a separate compact status such as:

```text
connection: connected | disconnected | reauth_required | unavailable
usage: available | limit_reached | unavailable | unknown
selected_account_ref: local bridge opaque ref
selected_model: account-visible slug
```

Persist only safe provider/model/result metadata in Personal AI. Account credentials and refresh state remain in the user-controlled runtime.


---

## 17. Routing pipeline

```text
InferenceRequest
      |
1. strict-free filter
2. sensitivity/data-policy filter
3. capability/context-size filter
4. health/cooldown/quota filter
5. task-specific quality floor
6. scarcity-adjusted scoring
7. execute + account + trace
8. bounded fallback/cascade
```

Hard filters always precede scoring.

### 17.1 Explicit ChatGPT route

```text
Sidecar request
   |
   +-- inference_mode = automatic_strict_free
   |      -> existing routing pipeline unchanged
   |
   +-- inference_mode = explicit_provider(openai_chatgpt_plan)
          -> Personal AI context/policy checks
          -> local bridge availability/auth/model checks
          -> ChatGPT plan request
          -> no automatic provider fallback
```

The automatic router does not score ChatGPT-plan models against Gemini/Groq/Cloudflare.


---

## 18. Quota scarcity

A deterministic utility can later resemble:

```text
utility =
    task_quality
  - quota_scarcity_penalty
  - latency_penalty
  - reliability_penalty
```

Cost is constrained to zero in strict-free mode rather than being a weighted term.

---

## 19. Bounded cascades

Example:

```text
abundant free model
 -> candidate output
 -> deterministic validator
    -> pass
    -> fail -> stronger eligible free model
```

Validators include:

- schema,
- exact source/provenance,
- hard constraints,
- required citations/fields,
- authoritative IDs.

Bounded depth only.

---

## 20. Embedding runtime

Current:

```text
Gemini API / gemini-embedding-001
        |
        v
Firestore vector
        |
        v
Firestore vector KNN
```

Target abstraction:

```text
EmbeddingRequest
    |
EmbeddingBackend
    |
vector + metadata:
  provider
  model
  dimensions
  normalization/task type
```

A provider/model change requires explicit vector/index migration.

Cloud Storage is not part of the online vector-search path.

---

## 21. Artifact storage boundary

Conceptual:

```python
class ArtifactStore(Protocol):
    async def put(...): ...
    async def get(...): ...
    async def delete(...): ...
```

Initial implementations:

- in-memory/fake for tests,
- GCS for cloud.

Artifact reference should include:

- URI/key,
- content type,
- content hash,
- size,
- sensitivity,
- created time,
- retention class,
- owning request/run/export ID.

Initial artifact uses:

- detailed routing traces,
- evaluation raw outputs,
- export bundles,
- debug/replay artifacts.

---

## 22. Search and retrieval

```text
task
 -> query planning/rewrite
 -> search providers
 -> fetch/extract
 -> evidence normalize
 -> dedupe/freshness
 -> rerank
 -> evidence compression
 -> context builder
 -> synthesis
```

Avoid dependence on one model provider's proprietary grounding.

---

## 23. Memory architecture

```text
conversation
 -> bounded extraction
 -> provenance validation
 -> lifecycle/storage
 -> query-conditioned retrieval
 -> context builder
```

The inference router may select extraction/summarization models; memory retains semantic/provenance guarantees.

### 23.1 AI sidecar component architecture

Provide a reusable provider-neutral sidecar shell that domain applications can integrate without implementing ChatGPT auth themselves.

Conceptual component boundaries:

```text
AISidecar
  +-- ProviderSelector
  +-- ContextInspector / ContextSelector
  +-- ConversationView
  +-- PromptComposer
  +-- StreamRenderer
  +-- CopyAction
  +-- DraftInsertAction (optional)
  +-- MutationProposalAction (later)
  +-- ChatGPTConnectionControls
```

Domain apps supply:

- launch scope/entity/workspace;
- permitted context categories;
- display labels for context;
- safe response actions;
- mutation proposal adapter once Phase 23 exists.

Personal AI supplies context/policy/conversation behavior. The ChatGPT bridge supplies only the user-entitled inference transport.


---

## 24. Domain adapters

### Travel
Profile, active trip, itinerary, reservations, preferences/history.

### Shopping
Profile, active project, requirements, saved/rejected products, history.

### Finance
Profile, portfolio, account summary, policy, budget summary, research state.

### Health
Profile, today/current state, conditions, medications, constraints, goals, trends/history.

---

## 25. Cross-app broker

All cross-app access passes through Personal AI policy. Effective inference sensitivity reflects the most restrictive supplied context.

---

## 26. Read and mutation architecture

Read:

```text
request
 -> plan
 -> authorize
 -> retrieve
 -> assemble
 -> task profile
 -> route
 -> reason
 -> respond
```

Mutation:

```text
request
 -> retrieve/reason
 -> propose structured mutation
 -> domain validation
 -> confirmation
 -> domain executes
```

### 26.1 Sidecar read/apply separation

Before the mutation framework exists:

```text
ChatGPT/AI response
   -> display
   -> Copy
   -> optional Insert into non-authoritative draft field
```

After the mutation framework exists:

```text
AI structured proposal
   -> domain validation
   -> explicit user confirmation
   -> authoritative domain mutation
```

A generic sidecar answer never gains direct database-write authority merely because ChatGPT produced it.


---

## 27. Evaluation architecture

```text
fixtures
  +-> Gemini
  +-> Groq
  +-> Cloudflare
        |
        v
task scores / latency / reliability
        |
        v
versioned model quality profiles
        |
        v
router
```

Raw outputs go to Cloud Storage; summary scores/metadata go to Firestore.

---

## 28. Failure behavior

### Free provider exhausted
Recompute eligible strict-free candidates, otherwise fail/defer explicitly.

### Provider 5xx
Bounded retry, health penalty/cooldown, safe fallback.

### No sensitivity-safe provider
Return a policy/capacity failure or deterministic answer path.

### All free providers exhausted
Never automatically enter paid inference.

### GCS artifact write failure
Do not fail a successful user-facing inference solely because optional debug/eval artifact persistence failed, unless the artifact is required for the operation (for example, an explicit export).

### 28.1 ChatGPT-plan-specific failures

### Local bridge absent/unreachable
Show setup/reconnect guidance; leave strict-free Personal AI available.

### Consent or plan-use scope missing
Keep the account connection state separate from plan-use authorization. Offer explicit reauthorization.

### Token expired/revoked
Refresh locally when allowed; otherwise require sign-in again. Never forward token material through the cloud backend.

### Model no longer available
Refresh the account-specific model list and require explicit reselection if needed.

### ChatGPT plan/app usage limit reached
Stop the ChatGPT-plan request, surface a Manage usage action, and optionally offer an explicit switch to Personal AI automatic free routing. Do not invent a reset time.

### Responses stream interrupted/incomplete
Do not persist an assistant turn as successful until terminal completion semantics indicate success. Preserve partial text only as UI/transient state unless product policy explicitly supports drafts.


---

## 29. Migration approach

1. reconcile with current code;
2. preserve current context/memory/research APIs;
3. add app identity/registry/providers/builder/planner/policy;
4. broaden inference seams;
5. add Gemini/Groq/Cloudflare adapters;
6. add strict-free registry;
7. add accounting;
8. add GCS artifact tier;
9. add deterministic routing;
10. evaluate;
11. add quota-aware routing/cascades;
12. integrate real domain apps;
13. optimize retrieval/memory;
14. add/verify strict-$0 cloud-resource guardrails and image/artifact retention;
15. experiment with adaptive routing.


16. add the additive ChatGPT-plan local bridge/auth path after neutral inference seams exist;
17. add ChatGPT account/model/status metadata without admitting it to automatic strict-free routing;
18. add the reusable AI sidecar before domain UI integrations depend on it;
19. integrate bounded ChatGPT sidecar context into Travel/Shopping/Finance/Health alongside their existing Personal AI context integrations;
20. harden bridge security, plan-limit recovery, provider attribution, and no-token-in-cloud guarantees during integrated hardening.

No full rewrite.
