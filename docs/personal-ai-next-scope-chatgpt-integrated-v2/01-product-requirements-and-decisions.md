# Product Requirements and Architectural Decisions

Status: integrated next-scope design  
Date: 2026-10-05

## 1. Background

The Personal AI system is intended to become the reusable AI layer behind several specialized applications rather than a single standalone chatbot.

Current / planned domain applications:

- **Travel** — trip planning, itinerary management, reservations, destination research, activity and food discovery, extraction from email and other sources.
- **Finance / Investing** — portfolio and financial data, investment research, budgeting / personal finance workflows, account and holdings context.
- **Shopping** — product search and discovery, requirements tracking, saved products, comparison and recommendation workflows.
- **Health** — flexible personal health profile, diet, exercise, sleep, goals, conditions, medications, restrictions, daily tracking, and recommendations.

The existing Personal AI foundations remain useful:

- model/provider abstraction,
- conversation management,
- memory,
- retrieval,
- research/search,
- evidence/provenance,
- deterministic constraints/ranking,
- tools/connectors,
- orchestration,
- evaluation/tracing,
- streaming and async execution,
- Firestore persistence,
- Firestore vector search.

The domain applications expose a missing architectural layer:

> **Personal AI needs explicit support for structured, authoritative, domain-owned context.**

The strict-free goal exposes a second:

> **Personal AI needs a provider-neutral inference runtime that can turn limited hosted free-tier capacity into one coherent, quality-optimized platform.**

The new evaluation/routing scope exposes a third:

> **Personal AI needs a dedicated artifact tier so verbose traces, evaluation outputs, exports, and other bulky immutable data do not consume scarce Firestore storage.**

The ChatGPT-plan integration exposes a fourth, additive architectural requirement:

> **Personal AI should support an explicitly user-selected ChatGPT-plan inference lane and reusable in-application AI sidecar without weakening or redefining the automatic strict-free runtime.**

This lane is intentionally different from the Gemini/Groq/Cloudflare pool:

- the user explicitly connects and selects a ChatGPT account/plan;
- eligible requests use Sign in with ChatGPT and the OpenAI Responses API;
- persistent ChatGPT authentication credentials remain local or in a runtime controlled by that user;
- the cloud-hosted Personal AI backend never stores ChatGPT access/refresh tokens;
- ChatGPT-plan usage is not an automatic fallback for strict-free routing;
- Personal AI remains the owner of conversation state, context selection, provenance, and domain boundaries.


---

## 2. Product objective

The project should optimize **system intelligence**, not merely raw model intelligence.

Target:

> Build the best practical personal AI system possible under a normal-runtime inference budget of $0, using hosted providers and improving end-to-end quality through context, memory, search, retrieval, deterministic tooling, routing, storage discipline, and evaluation.

The system should support:

- native/general chat,
- research and decision support,
- reusable AI APIs for domain applications,
- structured extraction,
- memory maintenance,
- context-aware recommendations,
- future tool/action workflows.

### 2.1 Strict-free constraint

In strict-free mode:

- no paid model may be selected automatically;
- no fallback may silently enter a billable model tier;
- no local LLM/GPU is required;
- expiring promotional credits are not a required dependency;
- GCP infrastructure should remain inside recurring free allowances;
- ordinary budget alerts must not be mistaken for hard spend caps;
- conservative application/service usage guards and kill switches should prevent known free-tier exhaustion where the cloud service itself will not hard-fail;
- provider/service eligibility is configuration/operational state;
- if no eligible zero-cost route or resource remains, the request degrades, optional work is disabled/deferred when safe, or the operation fails explicitly.

"Fully free" is an operating mode across inference and supporting cloud infrastructure, not a claim that providers will keep today's free tiers forever.

### 2.2 Harness-first optimization

Because free-tier models can be weaker or inconsistent, the platform should improve quality by:

1. retrieving better information,
2. sending less irrelevant context,
3. decomposing tasks,
4. performing deterministic work in code,
5. choosing models per task,
6. validating outputs,
7. escalating only when measured value exists,
8. evaluating all of the above.

### 2.3 Additive ChatGPT-plan mode

The project may expose a **ChatGPT plan** as an interactive, user-authorized inference option in addition to strict-free hosted providers.

This does **not** change the strict-free contract in Section 2.1:

- Gemini/Groq/Cloudflare automatic routing remains governed by strict-free eligibility;
- ChatGPT-plan usage is a separate user-entitled channel, not a zero-cost provider candidate automatically consumed by the router;
- selecting ChatGPT must be explicit at the user/session/request level;
- exhaustion, revocation, or unavailability of ChatGPT-plan usage must not silently consume a paid API key, ChatGPT credits, or another billing path;
- the UI may offer the user an explicit switch back to the strict-free runtime.

Initial product surface:

- reusable AI sidecar/drawer on desktop/web;
- bottom-sheet/full-screen equivalent on mobile where the integration is supported;
- visible provider/account/model state;
- bounded context preview/selection;
- streamed answer;
- **Copy** as the universal first action;
- **Insert** only into non-authoritative draft/edit surfaces;
- **Apply** only after the mutation-proposal framework validates and confirms a structured domain change.


---

## 3. Core ownership principle

### 3.1 Personal AI owns

- model invocation,
- provider normalization,
- inference task classification,
- model/provider routing policy,
- provider health/quota accounting,
- conversation,
- AI memory,
- retrieval over AI-owned memory,
- research and external search,
- context planning,
- context assembly and budgeting,
- reusable deterministic validation/ranking,
- permissions enforcement at the AI boundary,
- provenance,
- tracing and evaluation,
- AI-owned artifact metadata,
- retention policy for AI-generated artifacts.

### 3.1A ChatGPT local/user-controlled runtime owns

For ChatGPT-plan usage, a local/native/self-hosted runtime controlled by the authenticated user owns:

- Sign in with ChatGPT OAuth/OIDC/PKCE flow;
- ChatGPT access/refresh token storage and refresh;
- account/workspace registration state required by SIWC;
- account-specific model discovery;
- direct Responses API request execution and streaming;
- local bridge authorization between an approved Personal AI client and the credential-bearing runtime.

The cloud-hosted Personal AI backend must not persist or proxy reusable ChatGPT authentication tokens.


### 3.2 Domain applications own

- user-facing domain UI,
- authoritative domain database,
- domain schemas,
- business logic,
- validation,
- domain workflows,
- domain-specific profile data,
- current/daily state,
- transactional state,
- authoritative mutation rules.

Examples:

- Health owns the medication list.
- Finance owns the portfolio.
- Travel owns the itinerary.
- Shopping owns saved projects and requirements.

Personal AI may retrieve, reason over, summarize, and propose changes, but should not silently become the source of truth.

---

## 4. Context model

User context remains distinct layers.

### 4.1 Global user context

Owned by Personal AI.

Examples:

- units,
- locale,
- response preferences,
- application-independent defaults,
- durable cross-domain preferences appropriate to share.

Keep this small.

### 4.2 Domain profile

Owned by the corresponding domain app.

Examples:

- Health: conditions, medications, allergies, dietary restrictions, goals, routines, extensible attributes.
- Travel: style, lodging, pace, food, transport constraints, budget, accessibility.
- Finance: goals, risk profile, investing policy, tax preferences, portfolio constraints.
- Shopping: product/spec/aesthetic preferences, budgets, exclusions, household context.

### 4.3 Current / active domain state

Owned by the domain app.

Examples:

- today's health state,
- active trip / itinerary,
- current portfolio,
- active shopping project.

### 4.4 AI memory

Owned by Personal AI.

Examples:

- conversational preferences,
- prior reasoning outcomes,
- remembered decisions,
- soft context learned from chat,
- unresolved threads.

AI memory is not authoritative domain state.

### 4.5 External evidence

Time-bounded observation, not memory and not authoritative domain state.

Examples:

- hotel price,
- product availability,
- public-source claim,
- restaurant hours.

Retain source/provenance and freshness.

---

## 5. Application-aware requests

Every domain request should carry:

- `application_id`,
- optional `workspace_id`,
- authenticated principal,
- `conversation_id` when relevant,
- `request_id`,
- bounded client context/capabilities.

Personal AI uses this to determine:

- available providers,
- permitted context,
- tools/actions,
- sensitivity,
- memory namespace,
- model/provider eligibility.

Standalone chat remains a canonical app identity rather than an unscoped bypass.

---

## 6. Typed domain context providers

Personal AI accesses domain state through typed provider interfaces, not direct DB access.

Conceptual:

```python
class ContextProvider:
    async def get_profile(...): ...
    async def get_current_context(...): ...
    async def search(...): ...
    async def get_entity(...): ...
    async def get_history(...): ...
```

Provider results must be:

- typed,
- bounded,
- authorized,
- provenance-bearing,
- sensitivity-bearing,
- predictable on failure.

The core routes by capabilities/metadata rather than app-name conditionals.

### 6.1 ChatGPT sidecar context package

The ChatGPT sidecar uses the same typed context-provider architecture rather than bypassing it.

Personal AI should be able to produce a bounded `ContextPackage` containing:

- application/workspace/request identity;
- user prompt;
- selected conversation history needed for the turn;
- authorized domain context items;
- provenance/authority/sensitivity metadata;
- instructions describing domain ownership and mutation limits;
- an explicit list/summary of context exposed to ChatGPT.

The browser/native client passes that package to the user-controlled ChatGPT runtime. The package must never contain Personal AI service credentials or ChatGPT OAuth credentials.

Sensitive apps should expose stronger UI controls:

- **Finance:** default to the narrow entity/account/portfolio slice required by the question; make broader portfolio context visible before sending.
- **Health:** default to minimal context and show/select sensitive categories such as medications, conditions, labs, sleep, diet, and activity before sending when practical.


---

## 7. Selective context retrieval

Do not dump full profiles/histories into every prompt.

Flow:

1. classify/identify the task,
2. select relevant context categories,
3. authorize sources,
4. retrieve bounded context,
5. combine with memory/research/conversation under budgets,
6. compute effective sensitivity,
7. route only to eligible model providers.

Context minimization improves both privacy and weak-model quality.

---

## 8. Context inspection and provenance

Developers must be able to inspect:

- planner decisions,
- sources queried,
- categories returned,
- policy checks,
- final model context,
- exclusions,
- token contributions,
- source authority,
- transformations,
- selected provider/model,
- route reason,
- artifact references for verbose trace detail.

Every item should retain:

- source application/provider/ref,
- retrieval timestamp,
- authoritative vs inferred,
- source class,
- sensitivity,
- transformations.

The system should answer:

> Why did the model know this, and why was this provider/model allowed to see it?

---

## 9. Inference task model

Calls to hosted models should be explicit tasks.

Initial task classes may include:

- `CHAT_RESPONSE`,
- `STRUCTURED_EXTRACTION`,
- `MEMORY_EXTRACTION`,
- `QUERY_REWRITE`,
- `RESEARCH_PLANNING`,
- `RESEARCH_SYNTHESIS`,
- `CONTEXT_PLANNING`,
- `SUMMARIZATION`,
- `TOOL_SELECTION`,
- `DECISION_EXPLANATION`.

An inference request should be able to specify:

- required capabilities,
- sensitivity,
- context size,
- schema/structured-output requirement,
- latency preference,
- quality floor,
- escalation permission,
- strict-free requirement.

---

## 10. Required provider scope

### 10.1 Gemini

Gemini is the initial provider because the repository already uses it for:

- streamed generation,
- structured memory extraction,
- `gemini-embedding-001` embeddings.

The architecture should preserve current behavior while moving these behind provider-neutral contracts.

Gemini models enter strict-free routing only when the configured account/model path is verified zero-cost.

### 10.2 Groq

Groq is the preferred secondary hosted provider in the main plan.

Use cases:

- high-speed hosted inference,
- task-specific alternatives to Gemini,
- structured extraction / query rewriting / summarization where evaluation supports them,
- additional free model capacity,
- provider resilience.

Only models currently available to the configured Groq Free plan may enter strict-free routing. Exact per-model limits remain operational configuration/account state rather than source-code constants.

### 10.3 Cloudflare Workers AI

Cloudflare Workers AI is the third required hosted provider in the main plan.

Use cases:

- broader model-family diversity,
- additional daily free inference capacity,
- task-specialized alternatives,
- overflow when Gemini or Groq quota is constrained,
- provider resilience.

Only models available on Workers Free may enter strict-free routing. Cloudflare's concrete model set is operational configuration and may change independently of the code.

### 10.4 Possible extensions

Not required in the main phased plan:

- Cerebras,
- Mistral,
- OpenRouter free-model pool,
- GitHub Models,
- Hugging Face Inference Providers,
- future hosted zero-cost tiers.

These may be added after the initial provider architecture is proven and only when they provide a concrete quality, quota, capability, or privacy benefit.

### 10.4 ChatGPT plan through Sign in with ChatGPT — additive explicit lane

ChatGPT-plan usage is required as an additive integration but is **not** a fourth automatic strict-free provider.

Role:

- user-selected high-quality interactive chat/reasoning inside the Personal AI UI and domain-app sidecars;
- account-specific model choice when the signed-in account exposes multiple eligible models;
- optional comparison/evaluation target without changing the automatic strict-free provider pool.

Current integration constraints must be treated as volatile operational facts and re-verified during implementation/release review. The implementation should currently assume:

- eligible ChatGPT Plus/Pro users may authorize plan-backed requests without supplying an API key;
- authorization does not expose the user's existing ChatGPT conversations or ChatGPT memory to Personal AI;
- direct plan-backed inference uses the public Responses API with the user-authorized OAuth token;
- current HTTP usage requires streaming and non-persistent OpenAI response storage, so Personal AI must provide required conversation history/context for each turn;
- model availability is account/workspace specific and should be discovered rather than hard-coded;
- plan limits and app-specific limits are external state and may stop requests independently of Personal AI's free-provider quota ledger.

Provider profile metadata should distinguish this lane from ordinary API providers, for example:

```yaml
provider: openai_chatgpt_plan
auth_mode: user_oauth_plan
selection_mode: explicit_user
strict_free_eligible: false
automatic_fallback_eligible: false
credential_location: user_controlled_runtime
conversation_storage: personal_ai
```

`strict_free_eligible: false` here means **not eligible for automatic strict-free routing**, not that the application incurs per-request API spend when an eligible user explicitly uses their ChatGPT plan.


## 11. Provider/model capability registry

Provider/model facts must be configuration-driven.

Profiles should represent:

- provider/model ID,
- enabled state,
- strict-free eligibility,
- generation/stream/structured-output/tool/vision capability,
- context/output limits,
- free-tier quota shape,
- reset semantics,
- observed latency/reliability,
- provider data-use/privacy class,
- task-specific evaluation scores,
- embedding compatibility where applicable.

Volatile quotas/pricing must not become business-logic constants.

---

### 11.1 Additional registry fields for user-entitled providers

Where relevant, provider/model profiles should also represent:

- authentication mode;
- selection mode (`automatic` vs `explicit_user`);
- credential execution boundary;
- account/workspace model visibility;
- whether background/automated use is allowed;
- whether provider-hosted conversation state is available;
- whether plan/usage limits are opaque, shared, or directly observable.

These fields are additive and do not change the existing strict-free model-profile requirements.


## 12. Provider normalization

Preferred stance:

- use LiteLLM SDK behind an internal adapter where useful;
- retain native adapters where needed;
- do not expose LiteLLM-specific types above the inference layer;
- do not delegate high-level routing policy to LiteLLM;
- do not deploy a separate LiteLLM proxy initially without a concrete need.

Personal AI owns the routing intelligence.

---

## 13. Provider usage and quota accounting

For every model invocation record safe metadata such as:

- provider/model,
- task type,
- request count,
- input/output tokens where available,
- latency,
- success/failure,
- 429/rate-limit events,
- 5xx/provider errors,
- retry/cascade step,
- route reason,
- quota/reset metadata where available.

Quota state can come from:

- provider headers/usage,
- configured limits,
- locally observed counts/tokens,
- known reset schedules.

Unknown remains explicitly unknown.

---

## 14. Routing requirements

### 14.1 Hard eligibility

Candidate must satisfy:

- strict-free status,
- enabled/healthy state,
- sensitivity/data-use policy,
- capabilities,
- context/output limits,
- cooldown/quota state.

Privacy is a hard filter.

### 14.2 Task-aware quality

Use project-specific task evaluations.

Prefer:

> the least scarce eligible model that meets the task's quality requirement.

### 14.3 Quota scarcity

Consider:

- remaining/estimated quota,
- time until reset,
- expected demand,
- task importance,
- available substitutes.

Start deterministic.

### 14.4 Fallback

Fallback must be:

- bounded,
- strict-free,
- capability-safe,
- sensitivity-safe,
- traceable.

---

### 14.5 Explicit-provider route

When the user chooses ChatGPT:

1. validate that the ChatGPT local/user-controlled bridge is available;
2. validate an authorized ChatGPT account and plan-use scope;
3. validate that the selected model is currently offered to that account;
4. apply Personal AI context/sensitivity policy;
5. show or record the bounded context that will be sent;
6. execute the request through the local/user-controlled runtime;
7. stream the normalized response back into the sidecar;
8. persist Personal AI conversation state according to normal application policy.

Do not silently fall back from ChatGPT to Gemini/Groq/Cloudflare or vice versa. A failure may offer a user-visible provider switch, but the choice remains explicit.


## 15. Bounded model cascades

Where deterministic validation exists:

```text
abundant eligible model
    -> output
    -> validator
       -> pass: return
       -> fail: stronger eligible model
```

Validators may include:

- JSON/schema,
- provenance/source checks,
- hard constraints,
- citation existence,
- ID/range validation,
- consistency against authoritative state.

No unbounded self-critique loops.

---

## 16. Embedding and retrieval requirements

Embeddings must be a distinct boundary from generation.

Current baseline:

```text
Gemini API
  gemini-embedding-001
        |
        v
Firestore vector field
        |
        v
Firestore KNN / cosine retrieval
```

Requirements:

- retain provider/model identity,
- dimensions,
- normalization/task semantics,
- vector/index compatibility,
- migration/re-embedding rules.

Do not move memory vectors into Cloud Storage.

Do not dynamically round-robin embeddings across incompatible vector spaces.

---

### 16.1 Conversation-state requirement for ChatGPT-plan turns

Personal AI remains the durable conversation owner for ChatGPT-plan turns.

Requirements:

- retain provider/model attribution on each turn;
- store the user's prompt and accepted assistant response under existing conversation policy;
- reconstruct bounded history for subsequent ChatGPT turns;
- do not assume OpenAI-hosted persistent conversation state is available for SIWC plan-backed HTTP requests;
- allow the same Personal AI thread to switch providers only through an explicit user action, while retaining which provider produced each turn.


## 17. Storage requirements

Use a two-tier storage model.

### 17.1 Firestore — operational/queryable state

Store:

- conversations/messages/summaries,
- memories and vectors,
- memory lifecycle data,
- research/evidence metadata,
- canonical entities/claims,
- decisions,
- iterative-research state,
- application/provider registry,
- quota/provider-health summaries,
- routing/evaluation summary metadata,
- Cloud Storage artifact references.

### 17.2 Cloud Storage — bulky immutable artifacts

Store when useful:

- detailed routing/context traces,
- raw evaluation outputs,
- JSON/JSONL experiment artifacts,
- account export bundles,
- large debug/replay artifacts,
- selected research artifacts only when retention rights/policy permit.

Do not duplicate canonical domain/application state into Cloud Storage.

### 17.3 Retention

Artifacts must have:

- explicit type,
- owner/request/run reference,
- created timestamp,
- sensitivity,
- retention class,
- deletion status,
- content hash where useful.

Use compression for JSON/JSONL where appropriate.

Retention should be bounded so the free allocation does not become an accidental archive.

---

## 18. Search and retrieval requirements

Treat retrieval quality as a major lever.

Experiment with:

- query rewriting,
- hybrid lexical/semantic retrieval,
- entity-aware retrieval,
- reranking,
- deduplication,
- freshness,
- evidence compression,
- context packing.

Do not depend on proprietary model-provider grounding as the only research path.

---

## 19. Memory requirements

Preserve:

- attributable source,
- conservative extraction,
- explicit lifecycle,
- contradiction/supersession,
- bounded retrieval,
- separation from evidence,
- separation from authoritative domain state.

Provider diversity may be evaluated for memory subtasks without weakening provenance guarantees.

---

## 20. Cross-application context

Cross-app context is supported but not globally enabled.

Examples:

- Health dietary restrictions -> Travel food.
- Health ergonomic constraints -> Shopping.
- Finance budget context -> Shopping.
- Travel plans -> Shopping.

Sharing must be permission-aware and reflected in inference sensitivity.

---

## 21. Read vs write separation

Operation classes:

1. Read
2. Search
3. Reason
4. Propose mutation

Preferred mutation flow:

```text
Personal AI
 -> proposes structured change
 -> domain app validates
 -> user confirms if required
 -> domain app stores authoritative change
```

---

### 21.1 AI sidecar interaction model

The reusable sidecar should be application-aware but provider-neutral.

Minimum controls:

- provider selector showing `Personal AI (automatic free routing)` vs `ChatGPT plan` when connected;
- ChatGPT account/model indicator when that lane is active;
- visible **Using ChatGPT plan** state;
- context summary/inspection before or while sending;
- streaming response;
- Copy action;
- explicit disconnect/switch-account/manage-usage actions;
- clear errors for local bridge unavailable, auth expired/revoked, model unavailable, or plan/app usage limit reached.

The sidecar should never present ChatGPT-plan mode as the user's normal chatgpt.com session. It does not inherit ChatGPT history or memory.


## 22. Security and privacy

Authorization must answer:

- Can the origin app access this context?
- Can this field/class be returned?
- Is cross-app use permitted?
- Which model providers may receive it?
- Is the operation read-only/mutating?
- Is confirmation required?

Unknown provider data policy should default conservatively for sensitive use.

### 22.1 ChatGPT credential and bridge requirements

Persistent SIWC credentials are outside the cloud data plane.

Do not store ChatGPT access/refresh tokens in:

- Firestore;
- Cloud Storage;
- Secret Manager;
- browser local/session storage;
- application logs, traces, analytics, support bundles, or exports.

Use protected local/native/self-hosted credential storage under the user's control. The bridge itself should:

- bind to loopback/local IPC by default;
- authenticate/authorize the calling client;
- use origin allowlists and anti-CSRF/request-nonce controls where browser access is used;
- never return reusable OAuth tokens to the browser or cloud backend;
- redact account/token material from diagnostics;
- support explicit sign-out/disconnect and credential revocation/recovery behavior.


---

## 23. Domain-specific requirements

### Travel
Profile, active trip, itinerary, lodging, transport, reservations, preferences, budget, constraints. Preferred first real integration.

### Shopping
Profile, active project, requirements, saved/rejected products, shortlist, history, constraints.

### Finance
Portfolio/account summary, holdings, policy, goals, budget/cash-flow summaries, research state, scenario assumptions. Keep observed/calculated/assumed/AI-interpreted distinct.

### Health
Flexible structured profile, current/today state, conditions, medications, restrictions, goals, trends/history. Use the strictest context and provider eligibility.

### ChatGPT sidecar requirements by domain

#### Travel

- Sidecar may include current trip/day, itinerary items, reservations, transport constraints, preferences, and selected research evidence.
- Default UX should support itinerary/neighborhood/activity questions with Copy first.
- After the mutation framework exists, structured suggestions may become user-confirmed itinerary proposals.

#### Shopping

- Sidecar may include active project, selected products, requirements, saved/rejected products, budget, and comparison evidence.
- Default UX should make selected products/context visible.
- Later Apply actions may update shortlist/requirements only through Shopping validation.

#### Finance

- Sidecar starts read-only.
- Keep observed/calculated/assumed/AI-interpreted data distinct in the context package.
- Broader account/portfolio context should be intentionally selected and visible.
- No trade or financial transaction execution through generic sidecar output.

#### Health

- Sidecar starts read-only with the strictest context minimization.
- Sensitive categories should be visible/selectable where practical.
- Do not allow generic model text to directly modify medications, conditions, measurements, or clinical records.
- Later structured proposals still require Health validation and user confirmation.


---

## 24. Evaluation requirements

Measure:

- end-answer quality,
- structured-output correctness,
- provenance/citation correctness,
- memory extraction precision,
- retrieval relevance/omission,
- context efficiency,
- hard-constraint compliance,
- routing correctness,
- provider failure recovery,
- latency,
- quota consumption,
- unnecessary escalation,
- sensitive-data routing violations,
- Firestore/artifact storage growth.

Raw evaluation outputs should generally be stored as Cloud Storage artifacts, with summary/index metadata in Firestore.

ChatGPT-specific evaluation should measure, when enabled:

- sidecar context relevance and omission;
- explicit-provider selection correctness;
- local bridge/auth recovery;
- model-list refresh behavior;
- usage-limit behavior;
- provider attribution on stored turns;
- sensitive context preview/selection;
- absence of reusable credentials in cloud persistence/logs/artifacts;
- Copy/Insert/Apply boundary correctness.

ChatGPT model quality may be benchmarked against strict-free providers, but those results do not make ChatGPT an automatic strict-free candidate.


---

## 25. Non-goals

Do not:

- migrate all domain data into Personal AI;
- use AI memory as authoritative domain state;
- query domain databases directly from core orchestration;
- send all available data to every request;
- enable unrestricted cross-app sharing;
- allow arbitrary model-written mutations;
- scatter app branching through core code;
- hard-code current free-tier quotas;
- depend on local Ollama/GPU;
- round-robin providers without task/privacy awareness;
- weaken privacy during fallback;
- store bulky evaluation/trace artifacts indefinitely in Firestore;
- move vector retrieval into Cloud Storage;
- add DynamoDB before measured structured-state pressure justifies it;
- build learned routing before deterministic baselines exist.

Additional ChatGPT-specific non-goals:

- do not iframe/embed or automate the chatgpt.com consumer UI;
- do not ask for ChatGPT passwords, session cookies, or browser-session scraping;
- do not expose ChatGPT OAuth tokens to cloud services or browser JavaScript;
- do not assume access to ChatGPT conversation history, memory, custom instructions, or unrelated account context;
- do not automatically spend ChatGPT-plan allowance for background work unless a future supported flow is explicitly authorized by the user and policy permits it;
- do not treat ChatGPT-plan usage as a hidden fallback from strict-free routing;
- do not let ChatGPT sidecar responses directly mutate authoritative Travel/Shopping/Finance/Health state outside the mutation-proposal path.


---

## 26. Key design decisions

1. Preserve Personal AI as shared intelligence infrastructure.
2. Keep domain apps authoritative.
3. Add explicit context federation.
4. Keep domain state, AI memory, and external evidence distinct.
5. Make app/workspace identity first-class.
6. Add typed context providers and app registry.
7. Keep context selective, budgeted, and inspectable.
8. Make sensitivity/cross-app authorization first-class.
9. Separate reason/read/search from proposed mutation.
10. Make strict-free hosted inference an architectural constraint.
11. Require no local model hardware.
12. Use Gemini as the migrated primary provider.
13. Add Groq as the preferred secondary free provider.
14. Add Cloudflare Workers AI as the third explicit free provider.
15. Keep additional providers as extensions, not required phases.
16. Normalize providers behind internal interfaces; use LiteLLM where useful.
17. Add provider/model capability/privacy profiles.
18. Add accounting before quota-aware routing.
19. Route by task quality and eligibility.
20. Treat free quota as scarce, expiring compute inventory.
21. Use bounded cascades and deterministic validation.
22. Keep embeddings explicitly versioned/provider-aware.
23. Keep Firestore for hot/queryable/vector state.
24. Add Cloud Storage for bulky immutable artifacts.
25. Retain bounded artifacts and monitor storage growth.
26. Use project-specific evaluations to drive optimization.
27. Treat Cloud Run, Firestore, Cloud Storage, Artifact Registry, Pub/Sub, Secret Manager, and other infrastructure as finite free-tier resources.
28. Use spend caps where supported, but retain application/operational guards because spend caps are limited and ordinary budget alerts do not cap usage.


29. Add ChatGPT-plan usage as a separate explicit user-entitled lane, not as a fourth automatic strict-free provider.
30. Use Sign in with ChatGPT and supported Responses API flows; never scrape or embed the consumer ChatGPT UI.
31. Keep persistent ChatGPT auth credentials local or in a user-controlled runtime; never store them in the managed Personal AI cloud backend.
32. Keep Personal AI as the conversation/context owner for ChatGPT-plan turns.
33. Add a reusable provider-neutral AI sidecar to Travel, Shopping, Finance, and Health.
34. Make Copy the universal initial action; gate Insert/Apply by domain authority and the mutation-proposal framework.
35. Apply stricter explicit context selection and minimization to Finance and Health ChatGPT sidecar requests.
36. Treat ChatGPT model availability and plan limits as account-specific operational state, not source-code constants.
37. Do not silently fall back between ChatGPT-plan usage and the automatic strict-free provider pool.
