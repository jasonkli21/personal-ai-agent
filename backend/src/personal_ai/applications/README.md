# Application registry

This package owns typed application manifests and deterministic composition of application, capability, and comparison-domain metadata. It lets a request resolve its application and declared workspace shape before the shared context and capability paths run.

## Ownership and limits

- `contracts.py` defines versioned manifests, workspace requirements, memory namespaces, provider/tool/comparison-domain IDs, sensitivity defaults, declaration-only cross-application references, and advisory context-budget hints.
- `registry.py` validates references and exposes immutable-by-interface registrations.
- Capability `available` metadata says an implementation exists; feature gates can still disable it in a deployment.
- A manifest describes which providers/tools/domains an application declares. It does not own that application's records or rules, implement a missing provider/tool, select an inference provider, or grant cross-application data access. Declarations are not authorization.
- Sensitivity defaults and budget hints are metadata; enforcement and provider selection remain in their owning policy/runtime layers.
- External domain applications retain authority over their data, business rules, and rich UI.

## Entry points and verification

Start with `contracts.py` and `registry.py`. The principal tests are `backend/tests/test_applications.py` and `backend/tests/test_application_scope.py`; the request integration boundary is described in the [Chapter 2 Phase 2 guide](../../../../docs/personal-ai-chapter-2/phase-2-implementation-guide.md). See also [system architecture](../../../../docs/architecture.md) and [application integration plans](../../../../docs/personal-ai-chapter-2/personal-ai-next-scope-detailed-implementation-plans/README.md).
