# Phase 17 implementation evidence — Concrete provider adapters

Date: 2026-10-07 (America/Los_Angeles)

## Tested tree and delivery

Verification ran on the complete Phase 17 working tree based on
`419a8bce0c9a24e9cd0a90458aebbdaf668d5f17` immediately before its single
commit. The existing Gemini generation, structured-generation, counting, and
embedding adapters continue to satisfy the Phase 16 neutral contracts. This
phase adds explicit Groq and Cloudflare Workers AI generation adapters behind
those contracts, including bounded/streamed requests, terminal normalization,
reported usage, safe rate-limit metadata, structured-output capability gates,
and cancellation cleanup. Offline HTTPX fixtures exercise the provider wire
profiles without making network calls.

New live-provider flags default off. Enabling a provider requires credentials,
an explicit model, free-tier and privacy attestations, and a preflight
reference; structured output additionally requires a model-specific
compatibility attestation. No account, tier, privacy, strict-free, or live
compatibility checks were performed. These attestations are configuration
gates, not verified provider facts.

The current application remains wired to Gemini. The new adapters do not
provide authoritative input-token counting on the same endpoint/model/
serializer, which current workflows require before dispatch. The explicit
factory supports adapter construction but adds no routing or discovery. The
root `README.md` was reviewed and updated to describe the new local adapter
support and its enablement boundary.

## Checks

Commands used the repository backend virtual environment. No frontend files
changed.

| Command | Result |
| --- | --- |
| `source backend/.venv/bin/activate && make backend-test backend-lint backend-build` (with `UV_CACHE_DIR=/private/tmp/personal-ai-phase17-uv-cache` for the build) | Passed: 787 passed, 26 skipped, one existing Starlette/httpx deprecation warning; Ruff passed; source distribution and wheel built successfully. |
| `source backend/.venv/bin/activate && make context-eval context-plan-eval memory-eval memory-lifecycle-eval research-eval iterative-research-eval itinerary-proposal-eval` | Passed: all seven deterministic offline evaluation targets completed successfully. |
| `git diff --check` | Passed after the final documentation changes. |

The 26 skipped tests include opt-in local persistence, cloud smoke, and manual
provider/context checks. They remain unverified. No live Groq, Cloudflare,
Gemini, Postgres, DynamoDB Local, cloud, IAM, paid-provider, or deployed
security check was run. No frontend verification was run because no frontend
files changed.

## Remaining gates and limits

- Groq and Cloudflare account/model free-tier eligibility, provider data-use
  suitability, and live request/stream/structured-output compatibility need
  independent preflight evidence before either live gate is enabled.
- The Cloudflare free-tier attestation must confirm that the selected model is
  usable without paid billing or prepaid credits; model eligibility changes
  over time and is not encoded in a fixed allowlist.
- Current chat and task workflows remain Gemini-only until each alternate
  provider can supply an authoritative count tied to its generation endpoint,
  model, and serializer.
- Phase 14 immutable Postgres policy/source-version references and Phase 15
  revocation through derived context remain partial and unchanged.
- Offline fixtures establish transport contracts only. They do not establish
  provider account eligibility, privacy compatibility, quality, production
  identity, cloud IAM, or deployed security.

## Review follow-up verification

Date: 2026-10-07 (America/Los_Angeles)

Tested revision: `fa677656e771674d0f9ea31a64301c4ca9841f0c`, based on the Phase 17
implementation commit `432bb1f0504fa5b190c546741803e75ea4b61da1`. The findings
were reviewed against the Phase 17 adapter/preflight acceptance criteria and
the Phase 15/16 sensitivity and neutral-inference contracts. All five were
valid. This follow-up keeps routing and live enablement out of scope.

The adapters now bind an approved privacy sensitivity ceiling and exact
response-model aliases to each configured provider account/model preflight.
Requests above that ceiling fail before transport. Completion and streaming
responses have byte limits before parsing, and SSE line/event limits. A
stop-like terminal reason with empty or whitespace-only text is incomplete.
Completions and streams require the returned model ID to match the configured
model or an explicitly approved exact alias; streams report the verified
returned ID. Offline fixtures cover all sensitivity levels on both adapters,
denial with zero transport calls, empty output, oversized responses, model
matching/aliases/mismatches, and Cloudflare stream, interruption, safe 429/5xx,
cancellation cleanup, and unavailable usage. No live-provider request was
made. The account-specific privacy and eligibility evidence gate remains open.

| Command/check | Result |
| --- | --- |
| `pytest backend/tests/test_provider_adapters.py -q` | Passed: 57 adapter contract tests. |
| `make backend-test backend-lint` | Passed on the tested commit: 830 passed, 26 skipped, one existing Starlette/httpx deprecation warning; Ruff passed. |
| `UV_CACHE_DIR=/private/tmp/personal-ai-review-uv-cache make backend-test backend-lint backend-build` | Passed on the same tracked source tree immediately before commit: backend suite and Ruff passed; sdist and wheel built. |
| `make context-eval context-plan-eval memory-eval memory-lifecycle-eval research-eval iterative-research-eval itinerary-proposal-eval` | All seven deterministic offline evaluations completed successfully on the same tracked source tree. |
| `git diff --check` | Passed after the implementation and documentation updates. |

The 26 skipped tests remain opt-in/manual checks. The application still uses
Gemini only; Groq and Cloudflare live flags remain off. No account/tier,
privacy suitability, strict-$0, live compatibility, paid path, cloud, emulator,
or deployed-security check was performed. No README edit was needed because
the configured provider and user-facing runtime behavior did not change.
