# Free-Tier Inference and Routing Design

Status: integrated design detail  
Date: 2026-10-05

## 1. Goal

Build a hosted inference layer that maximizes useful AI quality while normal-runtime model inference remains at **$0** and no local LLM hardware is required.

This is not simple API fallback.

The runtime should use:

- task-specific model strengths,
- context sensitivity,
- capabilities,
- provider health,
- free-tier scarcity/reset behavior,
- project-specific evaluations,
- deterministic validators,
- bounded escalation.

---

## 2. Required providers

### 2.1 Gemini

Role:

- migrated primary provider,
- current streamed generation,
- current structured memory extraction,
- current `gemini-embedding-001` embedding provider.

Strict-free requirement:

- only models/accounts verified to have zero-cost usage enter strict-free routes.

### 2.2 Groq

Role:

- preferred secondary free provider,
- very low latency for interactive/internal subtasks,
- additional strong open-model capacity,
- useful for structured extraction, query rewrite, summarization, and synthesis when project evaluations support them.

Strict-free requirement:

- only models available under the configured Groq Free plan may enter strict-free routing;
- per-model RPM/RPD/TPM/TPD constraints are quota-ledger inputs, not source-code assumptions.

### 2.3 Cloudflare Workers AI

Role:

- third required free provider,
- additional daily hosted-inference capacity,
- broader model-family diversity,
- overflow and task-specialized alternatives.

Strict-free requirement:

- only models allowed on Workers Free may be enabled for strict-free routing;
- a model requiring Workers Paid is ineligible even when the account has a daily free neuron allocation.

### 2.4 Possible extensions

Not required in the main plan:

- Cerebras,
- Mistral,
- OpenRouter free pool,
- GitHub Models,
- Hugging Face,
- additional hosted zero-cost providers.

The provider abstraction should make these cheap to add later after a concrete quality, capacity, capability, or privacy need appears.

### 2.3A ChatGPT plan — separate explicit user-entitled lane

ChatGPT-plan usage through Sign in with ChatGPT is additive to this design, but it is intentionally **outside the automatic strict-free provider pool**.

Role:

- optional user-selected interactive provider for chat/reasoning in Personal AI and domain sidecars;
- account-specific model selection;
- no API key required when an eligible ChatGPT account authorizes plan usage.

It must not change the required strict-free providers above:

- Gemini remains the migrated primary provider;
- Groq remains the preferred secondary free provider;
- Cloudflare Workers AI remains the third required free provider.

Selection rules:

- never score ChatGPT-plan models as automatic strict-free candidates;
- never consume ChatGPT-plan usage unless the user explicitly selected that provider for the request/session;
- never silently switch to paid OpenAI API billing or ChatGPT credits;
- never silently fall back from ChatGPT to a strict-free provider or vice versa.

Persistent ChatGPT auth tokens remain local or in a user-controlled runtime, so ChatGPT-plan execution uses a client/local bridge rather than the managed server-side provider gateway.


## 3. Framework stance

### LiteLLM

Use for commodity work where beneficial:

- provider normalization,
- request/response translation,
- streaming differences,
- common errors/usage,
- basic retry primitives.

Do not delegate:

- privacy eligibility,
- strict-free eligibility,
- task classification,
- task quality,
- quota scarcity,
- escalation,
- domain policy.

Personal AI remains the policy engine.

---

## 4. Strict-free definition

An endpoint is eligible only if:

1. enabled,
2. verified zero-cost in the current account/tier,
3. required capabilities fit,
4. quota/capacity is available,
5. data-use policy fits sensitivity,
6. no local model compute is required.

Excluded as required dependencies:

- paid overflow,
- expiring credits,
- local Ollama/GPU,

---

## 5. Layering

```text
Caller
  |
  v
InferenceRuntime
  |
  +--> task profile
  +--> sensitivity
  +--> required capabilities
  |
  v
InferenceRouter
  |
  +--> model registry
  +--> eval profiles
  +--> quota ledger
  +--> provider health
  +--> provider data policy
  |
  v
ProviderGateway
  |
  +--> Gemini
  +--> Groq
  +--> Cloudflare
  +--> LiteLLM-backed normalization where useful
```

### 5.1 Additive explicit-provider branch

```text
Caller
  |
  +--> automatic_strict_free
  |       -> InferenceRouter
  |       -> Gemini / Groq / Cloudflare
  |
  +--> explicit_provider = openai_chatgpt_plan
          -> context/policy validation
          -> ChatGPTPlanBridge
          -> account/model/auth/usage checks
          -> OpenAI Responses API
```

The normal `InferenceRouter` remains responsible for strict-free automatic selection. The explicit-provider branch reuses normalized request/output types where practical but does not reuse strict-free candidate scoring.


---

## 6. Contracts

Generation operations:

```python
class GenerationBackend(Protocol):
    async def generate(...): ...
    async def generate_structured(...): ...
    def stream(...): ...
```

Embeddings:

```python
class EmbeddingBackend(Protocol):
    async def embed(...): ...
```

Each model call emits normalized metadata:

- provider,
- model,
- task,
- input/output tokens if available,
- latency,
- result/error class,
- retry/cascade IDs.

### 6.1 ChatGPT plan bridge contract

A ChatGPT-plan adapter should normalize current SIWC/Responses requirements behind a narrow interface.

Current operational assumptions to verify at implementation time:

- use account-authorized OAuth bearer credentials;
- discover account-visible models dynamically;
- HTTP inference uses `store: false` and `stream: true`;
- required history/context is supplied in the request rather than relying on persistent provider-side conversation state;
- only supported Responses fields/tools are sent;
- terminal success is recognized from completed stream semantics;
- SIWC-specific admission/auth/usage errors are normalized into stable Personal AI error classes where possible.

Do not expose temporary SIWC request-shape restrictions above the bridge boundary.


---

## 7. Task profiles

Initial:

| Task | Key requirements | Optimization |
|---|---|---|
| Chat response | streaming, visible quality | quality |
| Memory extraction | structured precision | abundant model + validator |
| Query rewrite | short output | speed/quota |
| Research planning | structure/reasoning | moderate quality |
| Research synthesis | evidence/context | stronger eligible model |
| Summarization | long input | context fit |
| Tool selection | schema/tools | reliability |
| Decision explanation | grounded synthesis | quality |

Do not create task labels that do not alter routing/evaluation.

---

## 8. Model profiles

Conceptual:

```yaml
provider/model:
  enabled: true
  strict_free_eligible: true

  capabilities:
    stream: true
    structured_output: true
    tools: false

  limits:
    context_tokens: 131072

  data_policy:
    status: verified
    max_sensitivity: low

  quota:
    source: configured_or_observed

  eval:
    profile_version: ...
    scores:
      memory_extraction: ...
      research_synthesis: ...
```


### 8.1 ChatGPT-plan model profiles

ChatGPT-plan model entries are account-scoped observations, not static strict-free profiles.

Useful metadata:

```yaml
openai_chatgpt_plan/account-model:
  provider: openai_chatgpt_plan
  enabled: true
  selection_mode: explicit_user
  strict_free_eligible: false
  model_source: account_discovery
  capabilities: observed_or_documented
  usage_state: available_or_unknown
```

Do not hard-code the model list. Refresh when the user connects/switches accounts or when a selected model is rejected/unavailable.


---

## 9. Accounting and quota ledger

Usage event:

```json
{
  "request_id": "...",
  "task_type": "MEMORY_EXTRACTION",
  "provider": "...",
  "model": "...",
  "latency_ms": 620,
  "input_tokens": 1320,
  "output_tokens": 180,
  "status": "success",
  "retry_index": 0,
  "cascade_step": 0
}
```

Quota state can be:

```text
exact
derived
configured
unknown
```

Unknown stays unknown.

### 9.1 Separate ChatGPT-plan usage accounting

Record safe per-turn metadata such as:

- provider = `openai_chatgpt_plan`;
- selected model;
- app/workspace/task;
- latency;
- completion/failure;
- normalized auth/eligibility/usage-limit error class;
- token usage if the route returns trustworthy usage metadata.

Do not store OAuth access/refresh tokens, authorization URLs containing sensitive hints, or raw credential diagnostics.

ChatGPT plan limits are user/account/app external state. Do not fabricate remaining quota or reset time when OpenAI only reports that usage is unavailable/exceeded.


---

## 10. Hard eligibility

Reject if:

```text
not enabled
OR not strict-free eligible
OR sensitivity fails
OR capability missing
OR context too large
OR hard cooldown
OR known quota exhausted
```

Only survivors are scored.


### 10.1 Explicit ChatGPT-plan eligibility

Reject a user-selected ChatGPT-plan request if any required condition fails:

```text
not explicitly selected
OR local/user-controlled bridge unavailable
OR account not authenticated
OR plan-use scope not granted
OR user/workspace not eligible
OR selected model not currently available
OR sensitivity/policy disallows the requested context
OR known ChatGPT app/plan usage unavailable
```

This eligibility check is separate from strict-free candidate filtering.


---

## 11. Static task routing

Establish deterministic task routes before scarcity optimization.

Example:

```yaml
routes:
  memory_extraction:
    quality_floor: 0.90
    preferred:
      - gemini/verified-free-model
      - groq/verified-free-model
      - cloudflare/verified-free-model

  research_synthesis:
    quality_floor: 0.87
    preferred:
      - gemini/verified-free-model
      - groq/verified-free-model
      - cloudflare/verified-free-model
```

Concrete model IDs remain environment/configuration.

---

## 12. Evaluation-driven quality

Project-specific scores matter more than public overall rankings.

Measure:

### Memory
- precision,
- attribution,
- false-memory rate,
- schema success.

### Research
- claim/evidence alignment,
- conflict handling,
- completeness,
- citations.

### Decisions
- hard constraints,
- ranking,
- grounded explanation.

### Chat
- coherence,
- instruction/context use.

Provider-backed evaluations in this roadmap are opt-in and strict-free. Paid-provider experiments, if ever performed separately, are outside this implementation plan.

Raw outputs should be stored as Cloud Storage artifacts; summary metrics in Firestore.

### 12.1 ChatGPT evaluation use

ChatGPT-plan models may be included in optional benchmark runs when the user explicitly enables that consumption.

Those scores may help the user understand quality tradeoffs, but they must not:

- automatically add ChatGPT to strict-free routing;
- cause background benchmark traffic without user authorization;
- convert plan allowance into a hidden capacity pool for normal automatic operation.


---

## 13. Scarcity policy

Free capacity has opportunity cost.

Consider:

- estimated quota remaining,
- time until reset,
- reserve,
- substitutes,
- task quality floor.

Start simple.

---

## 14. Candidate scoring

After hard filters:

```text
score =
    task_quality
  - scarcity_penalty
  - latency_penalty
  - reliability_penalty
```

Dollar cost is constrained to zero in strict-free mode.

### 14.1 No scarcity scoring across entitlements

Do not compare ChatGPT plan allowance against Gemini/Groq/Cloudflare quota in the scarcity score.

The two modes express different product choices:

- **automatic strict-free:** system optimizes among verified zero-cost hosted providers;
- **explicit ChatGPT plan:** user intentionally spends their plan allowance for this interaction.

The UI can surface both choices, but the router does not silently arbitrage between them.


---

## 15. Failure/fallback

Safe fallback:

1. normalize error,
2. update health/quota state,
3. recompute eligible candidates,
4. select next within the same free/privacy/capability constraints,
5. stop at bounded attempts.

Never:

- broaden sensitivity eligibility,
- enter a paid provider/model from strict-free mode,
- enter Cloudflare paid-only models,
- retry indefinitely.

### 15.1 ChatGPT-plan failure behavior

If a ChatGPT-plan request fails:

1. normalize the failure;
2. refresh/reauthenticate only when the error calls for it;
3. refresh model list if the selected model is unavailable;
4. surface plan/app usage-limit guidance when relevant;
5. stop.

The UI may offer **Switch to Personal AI free routing**, but that action creates a new explicit request choice rather than an automatic fallback.


---

## 16. Cascades

Good:

```text
abundant free model
 -> structured output
 -> deterministic validation
 -> accept or escalate
```

Examples:

- memory extraction,
- travel/product extraction,
- structured query planning.

Bad:

- a model merely grading its own confidence.

---

## 17. Harness compensation

Move deterministic work out of models.

Research:

```text
query rewrite
 -> search
 -> normalize
 -> dedupe
 -> freshness
 -> entity resolve
 -> constraints
 -> rerank
 -> evidence pack
 -> synthesis
```

Memory:

```text
bounded source
 -> extraction
 -> provenance validation
 -> lifecycle
 -> retrieval
 -> context packing
```

---

## 18. Embedding policy

Keep a stable embedding space.

Current initial profile:

```text
provider = Gemini API
model = gemini-embedding-001
dimensions = 768
storage = Firestore vector
retrieval = Firestore KNN
```

Any embedding-provider change requires compatibility/migration planning.

Do not use Cloud Storage for online vector retrieval.

---

## 19. Artifact behavior

Routing should emit two levels of telemetry:

### Compact Firestore metadata

- request/task,
- selected provider/model,
- route reason,
- token/latency summary,
- error/cascade summary,
- artifact URI if retained.

### Optional detailed Cloud Storage artifact

- full candidate list,
- detailed route scoring,
- context manifest,
- validation/cascade details,
- raw evaluation output.

This prevents router observability from becoming the dominant Firestore storage consumer.

### 19.1 ChatGPT-plan observability

Compact Personal AI metadata may retain:

- request/task/app;
- provider/model;
- route mode = explicit ChatGPT;
- latency/status/error class;
- context-category manifest/redacted sensitivity summary.

Verbose artifacts must never include reusable ChatGPT credentials. Sensitive Health/Finance context should continue to follow the existing minimal/no verbose artifact default.


---

## 20. Sensitive-data routing

Effective sensitivity comes from:

- origin app,
- selected domain fields,
- memory categories,
- tool/external results where relevant.

If no provider qualifies, no model call is valid.

### 20.1 Sensitive context in explicit ChatGPT mode

Explicit selection does not bypass policy.

The context builder must still:

- authorize requested domain fields;
- compute effective sensitivity;
- minimize the context sent;
- preserve cross-app permission rules;
- allow stricter per-provider policy if configured.

For Health and Finance, the sidecar should additionally expose a human-readable context selection/preview so the user can narrow sensitive categories before sending when practical.


---

## 21. Adaptive routing — later

Possible later experiments:

- learned complexity classifier,
- RouteLLM-style strong/weak routing,
- contextual bandit.

Hard deterministic filters remain immutable:

```text
strict-free
privacy
capability
context limits
cooldown
```

---

## 22. Success criteria

- better end quality than a single-provider baseline,
- simple tasks conserve scarce stronger free quota,
- difficult tasks still reach the strongest eligible free model,
- provider failure degrades safely,
- no sensitive unsafe fallback,
- no strict-free request can incur paid inference,
- routing decisions are inspectable,
- verbose observability does not exhaust Firestore,
- provider additions do not require domain/context rewrites.


- ChatGPT-plan usage can be added without changing Gemini/Groq/Cloudflare strict-free routing semantics;
- ChatGPT-plan requests occur only after explicit user selection and authorization;
- reusable ChatGPT credentials never enter managed cloud persistence/logging;
- ChatGPT model/usage changes degrade with clear reconnect/reselect/manage-usage behavior;
- a ChatGPT failure never silently consumes a different provider or billing path.
