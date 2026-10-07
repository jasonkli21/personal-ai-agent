# ChatGPT plan integration and shared AI sidecar

## Position in the roadmap

The former ChatGPT Phases 17.1–17.4 are preserved as Phases 25.1–25.4. The integration remains purely additive: it does not replace automatic strict-$0 providers, change domain authority, or remove any existing roadmap scope.

## Core boundary

ChatGPT-plan use is an **explicit user-controlled execution lane** backed by a local/user-controlled credential runtime. Managed Personal AI services may prepare authorized context and persist safe turn attribution, but reusable ChatGPT OAuth credentials never enter managed cloud persistence.

Credential exclusion covers Postgres, DynamoDB, GCS, Secret Manager, browser storage, managed logs/traces, analytics, and exports.

`CHATGPT_PLAN` is distinct from `EXPLICIT_BYOK` provider API capacity under the [execution-mode boundary](03-free-tier-inference-and-routing.md#execution-identity-and-cost-modes). A ChatGPT subscription does not supply OpenAI API billing capacity. Neither lane is an automatic free-quota fallback; explicit selection preserves all shared authorization/privacy/sensitivity checks. BYOK credential-reference options do not relax the ChatGPT exclusions above.

## Phase 25.1 — authentication/local bridge

Revalidate current supported Sign in with ChatGPT requirements before implementation. Implement supported OAuth/OIDC/PKCE, protected local credential lifecycle, account-specific model discovery, direct supported Responses streaming, explicit terminal/error handling, a fake bridge, and a secure paired browser-to-local transport where supported. Native mobile remains a capability gate rather than an assumed desktop-loopback copy.

## Phase 25.2 — runtime/policy/usage integration

Represent `openai_chatgpt_plan` as explicit-only. It never enters automatic strict-free candidates or fallback. Explicit selection still passes normal context/sensitivity/provider-policy checks. External turn prepare/finalize uses the canonical DynamoDB conversation branch/idempotency store after Phase 10; query-rich policy/profile state remains Postgres-owned. Persist only safe provider/model/status/latency/usage attribution with trust provenance.

## Phase 25.3 — shared sidecar

One reusable sidecar/drawer/bottom-sheet uses the shared context planner/providers/policy/builder. It shows selected bounded context before send, provider/model status, and explicit switching. Copy is universal; Insert is only for non-authoritative drafts; interrupted output stays transient unless deliberately saved as draft.

## Phase 25.4 — domain contract

Travel, Shopping, Finance, and Health integrate through the same launch/context/action hooks. Apps do not implement their own ChatGPT authentication. Domain-specific policies may narrow fields/actions without forking the sidecar. Authoritative Apply remains disabled until Phase 31.

These are reference integrations of the [Application Integration Contract](02-target-architecture.md#application-integration-contract). Phase 25.4 extends that contract with optional host/sidecar hooks using existing scope, definition, provider registration, policy, planner, builder, provenance, and authority boundaries; it does not introduce a second ChatGPT-domain framework. A synthetic app must integrate through the same registered hooks without core app-name branches or a required shared client SDK.

## Domain authority

Producing model/provider is provenance, never write authority. Phase 31 typed mutation proposals require domain validation, exact confirmation, idempotency, and authoritative post-state before any AI-assisted write.

## Storage interaction

ChatGPT integration does not change the Phase 10 canonical-store rule:

- completed conversation turns/branch state -> DynamoDB;
- query-rich Personal-AI knowledge/control metadata -> Postgres;
- large allowed artifacts -> GCS after Phase 20;
- reusable ChatGPT credentials -> none of the managed stores.

## README maintenance

The root README should be updated by the implementing phases only when the corresponding capability becomes real and user-visible—for example when explicit ChatGPT-plan support or the shared sidecar is actually available. It should describe capability/setup at a high level, not OAuth internals, transport proofs, or detailed work packages.
