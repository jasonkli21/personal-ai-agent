# Next-scope Phase 2 compatibility guide — Application registry and manifest model

Status: implemented and locally verified before this regenerated chapter; real domain providers/actions remain future work.

This compatibility record preserves the completed Phase 2 handoff while the detailed plan remains at `personal-ai-next-scope-detailed-implementation-plans/plans/phase-2-implementation-plan.md`.

Phase 2 introduced a typed application definition/registry for standalone Personal AI plus Travel, Shopping, Finance, and Health, including capability/policy metadata and unavailable stubs. Registration advertises capability but grants no data access, and core orchestration should not branch on app names.

Phase 10 migrates persistence underneath these contracts; it does not reopen or rewrite the Phase 2 product scope.
