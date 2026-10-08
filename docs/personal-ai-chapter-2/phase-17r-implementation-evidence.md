# Phase 17R implementation evidence — LiteLLM execution substrate

- Date: 2026-10-08
- Tested source revision: `26436ba8dd3f7090360eef74f33693910bde7e12` (runtime and test commits; documentation follows)
- LiteLLM version: `1.102.1`, exactly pinned in `backend/pyproject.toml` and `backend/uv.lock`
- Scope: Gemini, Groq, and Cloudflare Workers AI generation; Gemini token counting and embeddings

## Delivered boundary

`backend/src/personal_ai/llm/litellm_gateway.py` is the only module that loads or calls LiteLLM. Existing provider-facing names delegate to this gateway; context counting and memory embeddings use the same execution boundary. Personal AI contracts remain the only interface used by services and applications. The old custom OpenAI-compatible transport was removed after the intercepted SDK tests covered its remaining contract checks, and the direct `google-genai` runtime dependency was removed.

Each invocation selects a provider profile, endpoint, model, credential, and account scope from explicit settings. Calls disable SDK and HTTP retries, redirects, cache, and content callbacks; LiteLLM Proxy/Router, load balancing, and cross-provider fallback are not used. The gateway applies bounded request, completion, streaming, SSE event, and SSE line sizes before SDK parsing, validates returned provider/model identity and terminal state, and converts errors to content-free Personal AI errors.

## Operation and counter compatibility

| Operation | Identity and tested request shape | Counter and provenance | Current use |
| --- | --- | --- | --- |
| Gemini bounded and streamed generation | `gemini` + configured model + `gemini-content-v1`; system instructions and user/assistant contents are serialized to Gemini `generateContent` or `streamGenerateContent` | Gemini `countTokens`; `kind=provider`, `confidence=authoritative`, with matching provider/model/serializer identity | Active chat and existing workflows |
| Gemini structured generation | Same Gemini identity; `generationConfig.response_json_schema` is included | The count request contains the same SDK-transformed system instruction, content, and schema as generation | Active only when required schema serialization is verified |
| Groq generation | `groq` + configured model + `groq-chat-completions-v1`; explicit Groq chat-completions endpoint | No approved same-endpoint authoritative counter | Available behind the external-provider and preflight gates; excluded from current workflows that require authoritative counts |
| Cloudflare Workers AI generation | `cloudflare_workers_ai` + configured model + `cloudflare-workers-ai-chat-v1`; account-scoped endpoint and per-call token | No approved same-endpoint authoritative counter | Available behind the external-provider and preflight gates; excluded from current workflows that require authoritative counts |
| Gemini embeddings | Persisted `google_genai` space, configured embedding model/dimensions, L2 normalization, `RETRIEVAL_DOCUMENT` / `RETRIEVAL_QUERY`, version `v1` | Not a generation-token-count operation | Preserved for memory embeddings |

The pinned SDK's Gemini count helper does not itself establish the complete count request contract. The gateway uses the pinned Gemini transform and optional-parameter serializer to construct the exact `generateContentRequest` envelope, including Personal AI's shared system instruction, caller system instruction, and response schema, then calls Gemini's provider `countTokens` endpoint. Tests compare the serialized count and generation bodies. A schema that LiteLLM drops for an unknown model fails before dispatch.

Provider-reported usage remains `reported`; SDK-synthesized usage is labeled `estimated`; missing usage remains unavailable. For Gemini, a bounded response shim supplies an empty optional `usageMetadata` field only to the SDK parser when absent, while Personal AI continues to expose no usage for that response. Groq's parser receives a default `service_tier` only when the provider omits it. Cloudflare's LiteLLM adapter may synthesize usage, which remains labeled estimated.

## Pinned SDK compatibility shims

- Gemini count requests use LiteLLM 1.102.1's Gemini request transformation and optional parameter mapping because the public token helper does not attest the exact shared system/schema body.
- Gemini generation responses may omit optional `usageMetadata`; an SDK-only parser copy adds `{}` without changing raw evidence or Personal AI usage metadata.
- Groq's pinned transform expects `service_tier`; the SDK-only response copy supplies `default` when absent.
- Cloudflare's SDK path selects a module-level HTTP handler instead of the per-call handler. A narrow context-local hook routes the SDK call to the explicitly configured account-scoped client without changing account credentials or endpoints globally.
- Non-streaming response headers are adjusted when the bounded parser copy changes body length; streaming paths preserve wire headers.

## Verification

- Focused gateway and affected workflow tests: `90 passed` (one upstream Pydantic warning).
- Full backend suite: `783 passed, 26 skipped, 2 failed` out of 811. The two failures are `test_registered_synthetic_application_uses_shared_preparation_without_app_branching` and `test_assembler_rechecks_grants_and_injects_typed_source_with_actual_manifest` in untouched `backend/tests/test_context_sources.py`; both use one-day permission fixtures that are expired on 2026-10-08. The first reports `expired` instead of `permission_unverified`; the second therefore omits the fixture item.
- `make backend-lint`: passed (`ruff check .`).
- `make backend-build`: passed; source distribution and wheel built.
- `git diff --check`: passed.
- Intercepted tests cover the pinned SDK request/response path, explicit auth and endpoints, count/generation schema parity, unsupported schema rejection, identity and usage provenance, stream terminal/cancellation/timeout behavior, one-send failures, size limits, external-provider preflight, callback/cache/log controls, concurrent Cloudflare account isolation, and embedding-space compatibility.

## Remaining gates

No live provider, account/tier eligibility, privacy suitability, strict-free eligibility, paid-path, cloud, or production checks were run. Synthetic intercepted responses prove only local SDK and Personal AI contract behavior. Gemini remains the only provider used by current application workflows; Groq and Cloudflare lack approved authoritative counters. The two date-sensitive `context_sources` failures remain outside this phase and are not counted as passing verification.
