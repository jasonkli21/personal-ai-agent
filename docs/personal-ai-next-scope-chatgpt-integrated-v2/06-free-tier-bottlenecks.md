# Free-Tier Bottlenecks and Capacity Risks

Status: reviewed operational planning note  
Date: 2026-10-05

## 1. Purpose

The system can plausibly remain at $0 for normal single-user use, but "free" is constrained by several independent resource pools.

The runtime and deployment process should:

- measure usage;
- prevent accidental paid overflow;
- degrade gracefully;
- preserve scarce high-quality capacity;
- keep provider/storage facts configurable;
- stop optional work before known free ceilings;
- alert on unexpected cloud spend or quota pressure.

Current numerical limits below are an operational snapshot only and must be re-verified during deployment/release review.

---

## 2. Likely bottlenecks and risks

### 2.1 Hosted model quota and provider availability — highest day-to-day risk

One visible request can fan out into several model calls:

```text
user request
  -> context/task work
  -> query rewrite
  -> extraction
  -> memory operation
  -> research synthesis
  -> validation/escalation
```

Without per-operation budgets, agentic call amplification can exhaust free quotas quickly.

**Gemini:** free input/output tokens exist for supported models, but exact model access/rate limits are account/project specific and may change. The configured account dashboard remains authoritative.

**Groq:** current Free-plan limits for several strong text models are 30 RPM, 1,000 RPD, 8K TPM, and 200K TPD. Long-context calls can hit token limits well before request-count limits. Groq exposes request/token rate-limit headers; feed them into the quota ledger.

**Cloudflare Workers AI:** Workers Free currently provides 10,000 neurons/day, resetting daily. Some resource-intensive models require Workers Paid, so strict-free eligibility must be model-specific rather than provider-wide.

Mitigate with task-aware routing, high-level call budgets, context minimization, deterministic work outside the model, bounded cascades, quota/health accounting, and explicit capacity failure instead of paid overflow.

### 2.1A ChatGPT-plan usage and local-bridge availability — separate optional lane

ChatGPT-plan integration introduces a capacity constraint that is **not** part of the automatic strict-free provider pool.

Current behavior to treat as an operational snapshot:

- eligible Plus/Pro accounts can authorize plan-backed requests;
- app usage contributes to the user's ChatGPT-plan usage/limits rather than a separate Personal AI API quota;
- app-specific usage limits may also apply;
- a limit error does not necessarily reveal an exact reset time;
- connection/authorization/model availability can change independently of Personal AI.

Mitigate by:

- consuming ChatGPT plan usage only after explicit user selection;
- showing `Using ChatGPT plan` clearly;
- providing Manage usage, reconnect, switch-account, and explicit Switch to Personal AI free routing actions;
- never doing automatic background benchmarking or fallback through ChatGPT;
- treating `available / limit_reached / unavailable / unknown` as coarse state rather than fabricating a quota ledger.

A missing local bridge or unavailable ChatGPT plan must not prevent Gemini/Groq/Cloudflare strict-free operation.


### 2.2 Search quota — likely first non-model bottleneck

Research can consume several searches per visible user request.

Brave Search currently costs $5 per 1,000 Search requests and supplies $5 in recurring monthly credits, equivalent to about 1,000 Search requests/month. Brave does not call this a standalone free API plan, and signup requires a card check; its documentation says the prepaid amount can be set to $0.

At three searches per research request:

```text
1,000 searches / month
÷ 3 searches / research task
≈ 333 research tasks / month
```

Mitigate by searching only when freshness/external evidence is needed, deduplicating/reusing safe recent results, deterministic query planning, bounding iterative research, configuring Brave so no prepaid balance is purchased, maintaining an application-level monthly search budget below the recurring credit, and adding other free search/data sources later behind the adapter boundary.

Do not make proprietary model grounding the only research path.

### 2.3 Privacy can shrink the usable free-provider pool

A provider can have remaining quota but still be ineligible for the request.

Gemini's current free API tier states that submitted content may be used to improve Google products. Groq, Cloudflare, and future providers require independent policy review.

Example:

```text
public travel/product research
  -> broad free-provider set

Health / Finance context
  -> potentially much narrower set
```

Privacy is a hard route constraint. A "no eligible free provider" result is preferable to weakening policy.

### 2.3A ChatGPT credential/runtime security risk

Because the main Personal AI deployment is managed Cloud Run, ChatGPT-plan credentials cannot simply become another Secret Manager secret.

Primary risks:

- accidentally persisting OAuth access/refresh tokens in cloud storage or logs;
- exposing tokens to browser JavaScript;
- permissive localhost CORS allowing another website to drive the credential-bearing bridge;
- copying credentials into support/debug bundles;
- treating a managed multi-user backend as the user-controlled runtime.

Mitigate with a loopback/local-IPC bridge or verified native/user-controlled runtime, OS-protected credential storage where available, strict allowed origins/client authorization, anti-CSRF/request nonces, aggressive credential redaction, and dedicated negative tests.


### 2.4 Cloud billing spillover risk

A recurring free tier is not automatically a hard $0 ceiling.

Google Cloud alerts-only budgets do not cap spending. Google now has spend-cap budgets in Preview for selected services, including Cloud Run and Gemini API, but spend caps are service/project scoped, have enforcement latency, and do not cover every persistent/storage service.

Mitigate with spend caps where the current service is eligible, alerts at conservative thresholds, application kill switches, explicit free-tier usage guards, disabling optional work first, deployment/release checks that re-verify current quotas, and never treating an alerts-only budget as a hard cap.

### 2.5 Firestore storage/index/vector growth

Current Firestore Standard free usage includes:

- 1 GiB stored data,
- 50,000 reads/day,
- 20,000 writes/day,
- 20,000 deletes/day,
- 10 GiB outbound/month.

For one user, daily operations are unlikely to bind first. Stored/index bytes are more relevant because memories, vectors, metadata, and indexes accumulate.

Mitigate by moving verbose artifacts to Cloud Storage, bounding evidence retention, keeping routing metadata compact, monitoring vector/index growth, avoiding copies of authoritative application state, and considering another database only after measured structured-state pressure remains after artifact offload.

### 2.6 Cloud Storage operations can bind before bytes

Current recurring free usage in `us-east1`, `us-west1`, and `us-central1` includes:

- 5 GB-months regional storage,
- 5,000 Class A operations/month,
- 50,000 Class B operations/month,
- 100 GB outbound from North America to most destinations/month.

A trace-per-object design can exceed Class A operations before approaching 5 GB.

Mitigate with compressed JSON/JSONL, one bounded artifact per evaluation run where practical, trace sampling, explicit retention classes, and no automatic retention of every debug trace.

### 2.7 Cloud Run compute and outbound data

Current request-based Cloud Run free usage includes:

- 2 million requests/month,
- 180,000 vCPU-seconds/month,
- 360,000 GB-seconds/month,
- 1 GB outbound data transfer from North America/month.

Request count should be generous for a single user. Long iterative research, large page/document fetching, and cross-cloud data movement are more plausible risks.

Mitigate with `min-instances=0`, elapsed-time/concurrency budgets, targeted extraction, bounded response/document sizes, and avoiding large-file proxying.

### 2.8 Artifact Registry image storage

Artifact Registry currently provides only **0.5 GiB-month** of free storage per billing account before storage charges.

This can be surprisingly easy to exceed if immutable backend/frontend images accumulate after many deployments.

Mitigate with small multi-stage images, bounded retention of obsolete image digests, cleanup that preserves images needed for active revisions/rollback, and deployment-time image-size monitoring.

Cloud Build's current free allowance is comparatively generous for this project's expected build frequency, so stored images are the more likely CI/CD storage constraint.

### 2.9 Paid-only managed features

Firestore free usage does not include several convenient features such as TTL deletes, PITR, backup storage, restore operations, and clone operations.

Strict-free mode should not silently enable these.

Use explicit bounded cleanup/export behavior where practical. Treat paid managed features as separate opt-in choices rather than defaults.

### 2.10 Secret Manager

Current recurring free usage includes:

- 6 active secret versions/month,
- 10,000 access operations/month,
- 3 rotation notifications/month.

With Gemini, Groq, Cloudflare, Brave, and domain API credentials, active version count is worth monitoring.

Mitigate by caching secrets per process instead of reading Secret Manager per inference call, disabling/destroying obsolete versions appropriately, and avoiding unnecessary version churn.

### 2.11 Embedding quota and embedding migration

Gemini embeddings currently have free-tier availability for supported models, but embedding rate limits/model lifecycle are separate from text generation.

A model change can require:

```text
new embedding model/dimensions
 -> re-embed memories
 -> rebuild/replace Firestore vector index
```

Mitigate by using a stable active embedding profile, persisting model/dimensions with every vector, explicit migration, bounded background re-embedding, and evaluation before migration.

### 2.12 Provider/free-tier churn

Free tiers and models can change independently of the code.

Cloudflare already distinguishes free-plan models from resource-intensive paid-plan-only models. Other providers can change quotas/model IDs or deprecate endpoints.

Mitigate with a configuration-driven model registry, compatibility smoke tests, at least two usable generation providers, graceful route disablement, and deployment/release-time free-tier verification.

### 2.13 ChatGPT integration/API-preview churn

Sign in with ChatGPT plan usage is a newer integration surface and current Responses request restrictions/model availability may change.

Mitigate by:

- isolating SIWC/Responses quirks in `ChatGPTPlanBridge`;
- capability probing/account model discovery rather than fixed model IDs;
- release-time verification of auth scopes, request requirements, supported tools/inputs, and usage error semantics;
- keeping the normal Personal AI provider gateway independent of this lane.


---

## 3. Expected bottleneck order

For a single active user, the likely practical order is:

```text
1. model token/request quota
2. search quota
3. privacy-driven provider eligibility
4. cloud billing spillover / missing hard caps
5. Firestore stored/index/vector bytes
6. Cloud Storage Class A operations
7. Cloud Run compute / outbound transfer
8. Artifact Registry image storage
9. embedding/provider churn
10. Secret Manager / Pub/Sub / ordinary Firestore operation counts
```

The exact order depends heavily on how aggressively research/evaluation features are used.

Optional ChatGPT-plan bottlenecks sit beside, rather than inside, this ordering:

```text
ChatGPT explicit lane only:
  A. user plan/app usage limit
  B. local bridge/auth availability
  C. account/model eligibility churn
```

These do not change the automatic strict-free bottleneck order above.


---

## 4. Resource-ledger direction

Treat free services as finite inventories:

```text
ResourceLedger
  +-- Gemini capacity
  +-- Groq capacity
  +-- Cloudflare neurons
  +-- search requests
  +-- Firestore bytes / operations
  +-- GCS bytes / operations
  +-- Cloud Run compute / network
  +-- Artifact Registry bytes



Separate explicit-user entitlement state (not scarcity-scored with the above):

```text
ChatGPTPlanStatus
  +-- connection/auth state
  +-- account-visible models
  +-- usage available / limit reached / unavailable / unknown
```
```

Do not build one universal scheduler immediately.

Recommended progression:

1. model quota ledger,
2. Firestore/GCS storage observability,
3. search quota budget,
4. cloud infrastructure release/kill-switch guardrails,
5. expand only when measurement proves value.

---

## 5. Strict-$0 failure semantics

### Interactive inference

```text
eligible alternate free provider
 -> route there

no eligible provider
 -> explicit capacity/policy response
```

### Explicit ChatGPT-plan inference

```text
ChatGPT plan selected + available
  -> execute through local/user-controlled bridge

ChatGPT plan unavailable / limit reached / auth invalid
  -> stop ChatGPT request
  -> show recovery/manage-usage guidance
  -> optionally offer explicit switch to Personal AI automatic free routing
```

Never silently switch billing/provider mode.


### Optional background work

```text
quota/resource unavailable
 -> defer or skip when safe
```

### Storage

```text
optional debug artifact cannot be retained
 -> skip artifact + bounded warning

required export cannot be stored
 -> fail export explicitly
```

### Cloud infrastructure

```text
approaching a configured free ceiling
 -> disable optional work
 -> trigger alert / kill switch
 -> preserve required data paths
```

Never silently enable paid inference, paid-only Cloudflare models, paid GCP managed features, prepaid Brave usage, or privacy-ineligible providers.

---

## 6. Operational source snapshot

Re-verify these during deployment; they are not runtime constants.

- **Groq Free-plan rate limits:** `https://console.groq.com/docs/rate-limits`
- **Cloudflare Workers AI pricing/free allocation:** `https://developers.cloudflare.com/workers-ai/platform/pricing/`
- **Gemini API pricing/data-use tiers:** `https://ai.google.dev/gemini-api/docs/pricing`
- **Brave Search API pricing:** `https://brave.com/search/api/`
- **Google Cloud Free Program:** `https://docs.cloud.google.com/free/docs/free-cloud-features`
- **Firestore quotas/pricing:** `https://docs.cloud.google.com/firestore/quotas`
- **Artifact Registry pricing:** `https://cloud.google.com/artifact-registry/pricing`
- **Cloud Billing budgets/spend caps:** `https://docs.cloud.google.com/billing/docs/how-to/budgets`

ChatGPT-plan operational references should also be re-verified during release review:

- Sign in with ChatGPT overview: `https://developers.openai.com/siwc/`
- Open-source/local plan usage: `https://developers.openai.com/siwc/token-sharing-open-source`
- Accounts/sessions/security: `https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions`
- Models/inference: `https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference`
- Preview limitations: `https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations`
- Errors/recovery: `https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery`
- Terms: `https://openai.com/policies/sign-in-with-chatgpt-terms/`


---

## 7. Practical conclusion

The system can plausibly remain free for a long time as a single-user platform, but a fully free design needs to optimize more than model selection.

The most important risks are:

1. **model-call amplification**,
2. **search-query amplification**,
3. **privacy shrinking the free-provider pool**,
4. **cloud services continuing into billable usage after a free allowance**,
5. **retained telemetry/vector/image storage growth**.

These are more likely to force operational or architectural changes than ordinary request counts.
