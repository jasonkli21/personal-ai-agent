# Phase 22 implementation guide — Cross-provider task evaluation matrix

Phase 22 adds an internal evaluation runner for measuring task quality against the registered endpoint catalog. It extends Phase 21 routing, Phase 19 physical-attempt accounting, and Phase 20 artifact storage. It does not change application provider selection or create a second send/accounting path.

## Ownership and flow

`ProviderMatrixRunner` loads held-out synthetic-public fixtures and a versioned `RoutingTaskProfile`, then iterates the current `EndpointRegistry` profiles. It turns fixture messages into `ChatMessage` values and passes them through the shared Phase 12 `ContextBuilder` with a 128,000-token ceiling and an explicitly estimated, versioned byte counter. The context manifest and prepared-message digest enter the run/case identities. Each fixture/profile pair receives a stable request ID and a case identity bound to the complete fixture manifest, endpoint configuration, task configuration, context build, and policy version.

For each pair, the runner creates a `RoutingRequestFacts` value with strict-free requirements and routes through `RoutingDecisionService`. A temporary `EvaluationQualityGate` can waive only missing production quality evidence for that exact run, case, prepared input, task, policy, and endpoint configuration. P21 checks the prepared-message digest again at finalization, before reserving an attempt. P21 still performs candidate filtering, authorization, quota admission, reservation, and its one-use dispatch claim. A selected endpoint is prepared through the provider-neutral generation adapter and sent once. P19 remains the owner of the physical attempt and its success, failure, timeout, unknown, usage, and quota outcome.

Postgres owns compact evaluation run/case summaries, exact gate bindings, and versioned quality profiles. P19 remains the canonical owner of attempts and quota. When output retention is explicitly approved, typed output-only batches use the Phase 20 artifact service; compact references and `evaluation_run_id` links remain in Postgres. Fixture messages, reference answers, prompts, credentials, and arbitrary exception text are not written to evaluation summaries or raw-output batches.

## Eligibility, bounds, and failure behavior

Evaluation requirements always use `STRICT_FREE`, public sensitivity, and automatic mode. The gate cannot waive cost, authorization/membership, privacy, capabilities, model limits, endpoint-specific count/schema compatibility, quota admission, deadlines, or any other P21 hard filter. An absent or expired gate authority denies the route. Paid, unknown-cost, and explicit-only profiles remain excluded by existing admission.

Runs are capped at 512 fixtures and 10,000 total fixture/profile cases. The runner executes sequentially, allows one physical attempt per pair, and does not reselect or make auxiliary calls. The shared context builder's byte estimate is labeled `estimated` and only supplies conservative local bounds for the public synthetic fixture; it does not claim provider-token accuracy. Task profiles requiring an authoritative token-counting capability fail before a run is created. A task requiring token counting must wait for an endpoint-compatible preparation flow.

Skipped endpoints are recorded as `not_run`; failed or ambiguous sends are recorded without provider response text. P19's pending/unknown attempt semantics remain authoritative. A later run for the same case/profile is denied while an earlier run is active or its P19 attempt is pending, unknown, or timed out. In Postgres, an advisory transaction lock serializes matching case identities and the older run is the deterministic winner when runs overlap.

## Scoring and quality profiles

The deterministic scorer checks schema validity, citation precision and coverage, provenance, exact held-out claim support, answer relevance, hard constraints, and privacy sentinels. It records token/usage confidence, quota units/confidence, and latency when available. It does not use an LLM judge.

Each live endpoint receives an unpromoted profile bound to the endpoint/account/configuration digest, task configuration, policy, scoring-policy version, tested revision, fixture manifest, seed, sample count, coverage, confidence, metrics, and freshness window. Skipped and synthetic-only endpoints do not receive live quality evidence. Publication is explicit and requires a same-manifest baseline, sufficient samples/coverage/confidence, the task floor, passed hard boundaries, freshness, and the declared benefit. P21 accepts only a qualified profile that still matches the current endpoint and task identities.

## Raw output retention

Raw retention defaults to deny. A retention authority must approve the exact run, endpoint, source, account scope, policy reference, and expiry. Live output is written only through a Phase 20 store whose identity is GCS-backed; the artifact service still enforces its own enablement, owner lifecycle, budgets, and retention. The typed raw-output contract has no prompt or fixture-input field. Compact quality and run records remain in Postgres regardless of raw-output retention.

## Verification and remaining boundary

The deterministic harness test uses synthetic executors and still exercises P21 and P19. The opt-in Postgres suite covers persisted runs, P21/P19 dispatch, stale-gate denial, unresolved-send blocking, and same-case concurrency. These checks do not establish live-provider behavior or Postgres migration acceptance.

The repository currently has no Phase 15 accepted end-to-end revocation contract and no deployed evaluation job identity. Consequently this phase adds no API route, UI, or live-provider command. A live run must be invoked only from a trusted internal composition that supplies current P21 authorization and P19/Phase 20 authorities. Gemini, Groq, and Cloudflare eligibility remains determined by the existing registry and verified endpoint facts; the runner contains no provider-specific policy branches. See the [Phase 22 evidence](phase-22-implementation-evidence.md) for tested revision and open gates.
