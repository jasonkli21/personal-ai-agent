# Architecture

This document describes durable system boundaries. For implemented behavior and verification status, see [current-state.md](current-state.md); for task-specific implementation guides, use the [documentation router](README.md).

## System shape

```text
Browser -> public Next.js sign-in/UI -> same-origin API proxy -> private FastAPI API
                                                            |-- chat -> context -> LLM
                                                            |-- research -> search -> evidence
                                                            |                    '--> context -> LLM
                                                            |-- optional memory
                                                            |-- Postgres/pgvector: durable knowledge and research
                                                            '--> DynamoDB: conversations and runtime state

Gated lifecycle work -> Pub/Sub -> private Cloud Run worker

External domain applications -> explicit core API
  external applications own authoritative domain records, rules, and rich UI
```

The web application uses Next.js, React, and TypeScript. FastAPI and Uvicorn power the API and worker; Cloud Run is the deployment target. Repository contracts hide persistence details from services, and `llm` hides model-provider details. The current persistence composition and its verification limits are summarized in [current state](current-state.md) and the [root README](../README.md).

## Ownership boundaries

- `services` owns conversation and durable chat-turn behavior.
- `agents/research` coordinates bounded single-pass and iterative research. Search adapters and the `llm` package own provider-specific calls.
- `auth` verifies deployed identity, resolves owner mappings, and owns request safeguards and account-data controls. API routes derive owners from verified principals; `local` is an explicit development seam.
- `context` selects token-budgeted active conversation turns, compatible working summaries, and optional labeled memory. Summaries are lossy branch-scoped working context, not long-term memory.
- `memory` owns attributable durable user knowledge and its lifecycle. `evidence` owns external observations with source, observation time, and freshness.
- `search` plans and fetches source material through adapters; `entities` represents canonical research identities and evidence-backed claims.
- `decisions` retains evidence snapshots and candidate evaluations. `ranking` applies freshness/conflict rules and hard constraints before soft preferences.
- `domains` adds bounded travel and shopping schemas, provider mappings, constraints, ranking features, and comparison views over shared services. It does not own authoritative trips, bookings, or purchases.
- `applications` registers app manifests and capability metadata; registration does not itself grant cross-application data access.
- `evaluation` measures memory, research, and domain behavior before experimental behavior is promoted.

## Data-lifetime and persistence rules

Memory and external evidence are different data classes. User preferences may remain useful over time; prices, inventory, availability, and opening hours are observations and require an explicit freshness policy. Recommendations retain their source evidence and policy rather than becoming facts.

The current runtime assigns conversation/message timelines and operational state to DynamoDB, and query-rich durable records and vectors to Postgres/pgvector. These stores remain behind repository contracts. Cross-store writes must preserve their correctness and recovery boundaries; details belong in [ADR 0021](decisions/0021-polyglot-persistence-foundation.md) and the [storage contract](personal-ai-chapter-2/phase-10-storage-ownership-and-access-patterns.md).

External domain applications own authoritative trips, bookings, purchases, and other domain records. The shared substrate may hold source-attributed preferences and evidence, but it does not silently replace that authority.
