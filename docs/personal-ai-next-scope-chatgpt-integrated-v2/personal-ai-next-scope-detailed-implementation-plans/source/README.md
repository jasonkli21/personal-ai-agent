# Personal AI — Final Integrated Next-Scope Handoff

Status: proposed integrated design and implementation handoff  
Date: 2026-10-05

## Purpose

This package reconciles three extensions to the existing `personal-ai-agent` system:

1. **Domain context federation** for Travel, Finance / Investing, Shopping, and Health.
2. **A fully free hosted-AI runtime** that maximizes end-to-end quality using zero-cost hosted model tiers rather than local-model hardware or paid inference.
3. **A two-tier GCP storage model** that keeps queryable/vector operational state in Firestore and moves bulky immutable artifacts to Cloud Storage.

This update adds a **fourth, purely additive extension**:

4. **ChatGPT-plan integration through Sign in with ChatGPT** — an explicitly user-selected, user-entitled inference lane and reusable AI sidecar for Travel, Shopping, Finance, and Health. This does not replace or weaken the strict-free Gemini/Groq/Cloudflare runtime.


The system should evolve incrementally from the repository's existing Cloud Run + Firestore + Pub/Sub + Gemini architecture. It is not a rewrite.

## Product thesis

> **Build a cloud-hosted personal AI runtime that uses optimized context, memory, search, retrieval, deterministic tooling, evaluation-driven model routing, and multiple hosted free-tier providers to maximize end-to-end intelligence while keeping normal model inference spend at $0 and requiring no local model hardware.**

The system is intended to serve both:

- a first-party chat/research experience, and
- a reusable AI substrate for Travel, Shopping, Finance, Health, and future applications.

A complementary product goal is:

> **Let the user bring an eligible ChatGPT plan into the same Personal AI conversation/context system without giving the managed cloud backend custody of ChatGPT credentials or coupling domain apps to chatgpt.com.**


## Core ownership rule

> **Personal AI owns intelligence, context assembly, inference policy, and AI-owned memory. Domain applications own authoritative domain state.**

Personal AI owns or coordinates:

- conversation and AI memory,
- context planning and budgeting,
- search/retrieval and evidence,
- deterministic validation/ranking,
- task classification,
- provider/model routing,
- free-tier quota/resource accounting,
- provider-sensitivity eligibility,
- evaluation/tracing,
- artifact metadata and AI-generated artifacts.

Domain applications continue to own:

- authoritative domain databases,
- domain schemas and validation,
- business logic,
- transactional/current state,
- authoritative mutation rules,
- rich application UI.

## Current repository baseline

The current repository uses:

- Next.js/React web on Cloud Run,
- FastAPI API on Cloud Run,
- a private Cloud Run worker,
- Firestore Native mode for durable records,
- Firestore vector KNN for long-term-memory retrieval,
- Pub/Sub for gated memory-lifecycle jobs,
- Secret Manager for provider credentials,
- Gemini API for generation,
- Gemini API `gemini-embedding-001` for memory embeddings,
- provider adapters for search/domain data.

Cloud Storage is not currently in the runtime path.

## Target storage shape

```text
                         Personal AI
                              |
             +----------------+----------------+
             |                                 |
             v                                 v
        Firestore                        Cloud Storage
    hot/queryable state                  artifact/blob tier
             |                                 |
     conversations                         detailed traces
     messages/summaries                    evaluation output
     memories + vectors                    export bundles
     evidence metadata                     debug artifacts
     decisions                              selected retained
     routing/quota state                    research artifacts
     artifact references
```

Firestore remains the canonical operational/query store. Cloud Storage is not a second database and does not replace Firestore vector search.

## Target inference-provider scope

### Required in the main implementation plan

1. **Gemini**
   - existing primary provider,
   - generation,
   - current embedding provider,
   - free-tier candidate where account/model eligibility is verified.

2. **Groq**
   - preferred secondary hosted free-tier provider,
   - high-speed complement to Gemini,
   - useful for task-specific routing, structured work, and overflow,
   - only models available under the verified Groq Free plan may enter strict-free routing.

3. **Cloudflare Workers AI**
   - explicit third hosted free-tier provider,
   - broadens model-family diversity and daily free inference capacity,
   - useful for overflow and task-specialized alternatives,
   - only Workers Free-eligible models may enter strict-free routing.

### Possible extensions, not part of the required plan

Examples include:

- Cerebras,
- Mistral,
- OpenRouter free models,
- GitHub Models,
- Hugging Face Inference Providers,
- other hosted zero-cost providers that later satisfy capability, privacy, and strict-free requirements.

These should not create required implementation phases until there is a concrete reason to add them.

### Additive ChatGPT plan lane

ChatGPT is intentionally different from the required automatic provider pool.

```text
Travel / Shopping / Finance / Health / Native Chat
                    |
                    v
             Shared AI Sidecar
                /         \\
               /           \\
              v             v
Personal AI automatic    ChatGPT plan
strict-free runtime      explicit user choice
      |                       |
Gemini/Groq/Cloudflare   local/user-controlled bridge
                              |
                              v
                       OpenAI Responses API
```

Rules:

- Sign in with ChatGPT is explicit and optional.
- The cloud backend never stores reusable ChatGPT OAuth credentials.
- ChatGPT does not receive automatic access to ChatGPT conversation history/memory through this integration.
- Personal AI still owns context selection, conversation state, provenance, and domain mutation boundaries.
- ChatGPT plan models never enter the automatic strict-free candidate pool.
- Failure/limit exhaustion never silently changes provider or billing mode.


## Framework stance

Use existing infrastructure where it removes commodity provider work, but keep Personal AI's routing intelligence internal.

Preferred layering:

```text
Personal AI inference policy
        |
        v
Internal provider/gateway boundary
        |
        +-- LiteLLM SDK adapter where useful
        +-- native adapters where justified
        |
        v
Gemini / Groq / Cloudflare
```

LiteLLM is a provider-normalization dependency, not the owner of:

- task classification,
- privacy policy,
- quality scoring,
- quota economics,
- escalation decisions,
- domain/application policy.

A separate LiteLLM proxy service is not required initially.

For ChatGPT-plan requests, provider-specific transport/auth logic lives in a local/native/self-hosted bridge controlled by the user, not in the managed cloud provider gateway. The bridge handles SIWC auth, token refresh, account-specific model discovery, Responses streaming, and ChatGPT-specific errors while exposing normalized results to the sidecar.


## Strict-free mode

Strict-free mode must:

- never silently use paid inference;
- never automatically switch from a free endpoint/model to a billable one;
- require no local LLM/GPU;
- keep GCP infrastructure inside verified recurring free allowances;
- treat provider quotas, pricing, and cloud free-tier ceilings as mutable operational configuration;
- use conservative usage guards, kill switches, alerts, and spend caps where available rather than assuming billing budgets are hard caps;
- explicitly fail, disable optional work, or degrade when a zero-cost resource is unavailable.

The target is $0 normal operation across both inference and the supporting cloud stack. A billing-enabled cloud account may still be required; that does not make ordinary paid usage acceptable.

## Shared AI sidecar

The four domain applications should integrate a common sidecar rather than each building ChatGPT-specific UI/auth logic.

Initial actions:

- **Copy** everywhere;
- **Insert** only into non-authoritative drafts;
- **Apply** only after the existing mutation-proposal framework validates a typed change and the user confirms it.

Travel and Shopping can use broad-but-bounded context more freely. Finance and Health should default to minimal context and expose clearer sensitive-category selection/preview.


## Documents

1. `01-product-requirements-and-decisions.md`
   - integrated product requirements,
   - domain ownership/context rules,
   - strict-free requirements,
   - provider scope,
   - storage rules,
   - privacy and non-goals.

2. `02-target-architecture.md`
   - current repository architecture,
   - target context federation,
   - inference runtime,
   - Gemini / Groq / Cloudflare roles,
   - Firestore + Cloud Storage data plane,
   - embedding/vector boundary.

3. `03-free-tier-inference-and-routing.md`
   - detailed router design,
   - task/model profiles,
   - quota scarcity,
   - evaluation,
   - cascades,
   - strict-free provider handling.

4. `04-storage-and-artifact-strategy.md`
   - Firestore vs Cloud Storage responsibilities,
   - artifact-store abstraction,
   - retention,
   - storage-budget monitoring,
   - DynamoDB trigger/escape-hatch policy.

5. `05-phased-implementation-plan.md`
   - narrow dependency-ordered phases,
   - explicit Gemini/Groq/Cloudflare adapter phase,
   - explicit Cloud Storage phase,
   - domain integration sequence,
   - later optimization and adaptive-routing phases.

6. `06-free-tier-bottlenecks.md`
   - likely $0-capacity bottlenecks,
   - operational quota snapshot,
   - mitigation and graceful-degradation rules.

7. `07-final-review-record.md`
   - package-wide consistency checks,
   - final corrections made before handoff.

8. `08-chatgpt-plan-and-ai-sidecar.md`
   - Sign in with ChatGPT / local bridge architecture,
   - explicit-provider routing relationship,
   - conversation/context ownership,
   - sidecar UX for Travel/Shopping/Finance/Health,
   - credential/security requirements,
   - failure/usage-limit behavior,
   - mapping to the consolidated additive Phase 17 implementation block and its subphases.


## Implementation stance

- Reconcile against the actual repository before coding.
- Preserve working memory/search/research/context behavior.
- Do not move authoritative domain data into Personal AI.
- Do not move memory vectors into Cloud Storage.
- Do not store verbose artifacts indefinitely in Firestore.
- Do not make volatile free-tier limits business-logic constants.
- Treat cloud infrastructure usage as part of the strict-$0 objective, not only model inference.
- Prefer more small phases over a few broad phases.


- Preserve the full substantive scope and ordering of the original roadmap; insert one additive Phase 17 ChatGPT account-integration/AI-sidecar block, then renumber the original downstream phases to 18-28 without changing their scope.
- Never store SIWC access/refresh/ID tokens in Firestore, GCS, Secret Manager, browser storage, logs, traces, analytics, or exports.
- Keep ChatGPT-plan use explicit and outside strict-free automatic candidate selection.
- Re-verify current SIWC/Responses constraints at implementation/release time instead of hard-coding preview behavior.
