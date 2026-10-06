# Next-scope Phase 2 implementation guide — Application registry

Status: implemented locally; deterministic backend verification recorded in the
[Phase 2 evidence](phase-2-implementation-evidence-2026-10-05.md)

Date: 2026-10-05

This is **next-scope Phase 2**, distinct from the repository's original Phase 2
context-window management. It implements the
[Phase 2 plan](personal-ai-next-scope-detailed-implementation-plans/plans/phase-2-implementation-plan.md)
on top of the next-scope Phase 1 request and persistence scope.

## Registration contract

`backend/src/personal_ai/applications/contracts.py` defines the versioned
`ApplicationDefinition`, `CapabilityRegistration`, sensitivity defaults,
optional context budget hints, workspace support, cross-application
declarations, and the resolved `ApplicationContextRequest`. IDs and policy
values are bounded and validated. Unsupported schema versions, duplicate
references, inconsistent capability availability, contradictory budget or
cross-app declarations, and scope/manifest mismatches fail clearly.

`backend/src/personal_ai/applications/registry.py` validates unique app and
capability IDs, provider/tool kinds, application references, and comparison
module references before retaining registrations. Unknown app lookup raises
`application_not_registered`. The registry is constructible from supplied
definitions and capability registrations for deterministic tests.

The initial registry contains `personal_ai`, `travel`, `shopping`, `finance`,
and `health`. It composes the existing Travel and Shopping `DomainModule`
registrations by reference; their comparison modules remain comparison
contracts and do not become authoritative app state. Existing shared
conversation assembly is registered as an available context capability.
Memory remains unavailable in the default registry while its retrieval path is
feature-gated. Application-level Travel, Shopping, Finance, and Health providers
and tools are explicit unavailable stubs. Their metadata does not imply a
working adapter or action.

All initial cross-app declarations are disabled. The contract can describe a
future declaration-only relationship, but registration does not grant a data
share or workspace access. `DenyWorkspaceAuthorizer` remains the default.
Sensitivity classifications and budget hints are metadata only in this phase;
they do not change retrieval, enforce a new provider policy, or select a model.

## Request and consumer path

Authentication middleware accepts a syntactically valid application ID only
when the injected/default registry contains it. A valid but unknown ID returns
the stable `application_not_registered` 404. Scope syntax errors remain
rejected before a request reaches a service. The canonical built-in IDs remain
the five initial manifests, while adding a registered manifest no longer
requires expanding a core `Literal` or app-name branch.

Dependency wiring resolves the selected definition and pairs it with the
server-derived `RequestScope`. Conversation services receive that immutable
request contract. Chat turn preparation passes it into `ContextAssembler`,
which checks that the pending and active messages match its owner/application/
workspace scope. The assembler uses the persisted, scope-enveloped pending
message. Provider dispatch and model selection remain in their existing
boundaries; Phase 2 adds no domain retrieval or action execution.

## Files and interfaces

- `backend/src/personal_ai/applications/contracts.py` — versioned manifest,
  capability, sensitivity, budget, cross-app, and request-context contracts.
- `backend/src/personal_ai/applications/registry.py` — validation, lookup,
  built-in manifests, capability status, and existing comparison-module
  composition.
- `backend/src/personal_ai/auth/scope.py` — validates extensible app slugs;
  registry lookup is now the app allowlist.
- `backend/src/personal_ai/auth/middleware.py` — rejects unknown registered
  scopes and validates manifest workspace support.
- `backend/src/personal_ai/api/dependencies.py` and `main.py` — registry
  injection and manifest resolution through FastAPI dependencies.
- `backend/src/personal_ai/services/conversations.py`,
  `services/chat_turns.py`, and `context/assembler.py` — carry the scoped app
  context into existing conversation and context preparation paths.
- `backend/tests/test_applications.py` and
  `backend/tests/test_conversation_routes.py` — manifest validation, stub
  status, unknown app denial, comparison composition, and synthetic app flow.

No frontend or infrastructure change was needed. No routes for domain context,
cross-app grants, provider routing, or domain mutations were added.

## Remaining boundaries

Offline tests establish manifest and consumer contracts only. They do not
establish workspace membership, Firestore isolation/index readiness, deployed
IAM/proxy behavior, live provider eligibility, or domain application access.
Next-scope Phase 1's documented legacy standalone foreign-read and external
verification gaps remain open. Finance and Health data remain unavailable
through application context stubs. Later phases own typed providers, field
policy, cross-app grants, and actions.
