# ADR 0002: Use Firestore Native mode with test fakes

- Status: accepted
- Date: 2026-08-19

## Context

Phase 1 needs durable conversation and message storage in the planned GCP topology, but local automated checks must run without cloud credentials or a GCP project.

## Decision

Use Firestore in Native mode for deployed persistence. Automated local tests use a fake repository. Manual local development may use the Firestore Emulator when it is explicitly configured.

## Consequences

- Repository interfaces must hide Firestore client details from application services and API routes.
- The deployed implementation can persist data across service restarts without introducing a second production datastore.
- Tests remain deterministic and offline; emulator setup is optional for manual validation.
- Future schema, index, ownership, backup, export, and deletion decisions remain explicit work rather than being implied by this choice.
