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
