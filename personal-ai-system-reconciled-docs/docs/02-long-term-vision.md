# Long-Term Vision

Status: reconciled design direction  
Date: 2026-10-02

## 1. Mission

`personal-ai-system` is a personal learning and research platform for understanding the systems around LLMs:

- streaming conversation,
- persistence,
- context management,
- memory,
- retrieval,
- evidence-grounded research,
- ranking,
- evaluation,
- and eventually richer tool/action workflows.

It is not intended to host a frontier model.

Long term, it should also become a reusable AI interface for multiple specialized personal applications.

## 2. Product topology

The system should support two kinds of client:

### A. Native/general-purpose AI client

The repository's existing chat/research UI remains useful for:

- general conversation,
- memory experiments,
- research-agent experiments,
- development inspection,
- evaluation/debugging.

### B. Rich domain applications

Separate applications may provide domain-specific experiences:

```text
travel-app
  itinerary editor
  map
  bookings
  day-by-day planning
  travel research

shopping-app
  product workspaces
  comparisons
  price/offer tracking
  research evidence
  purchase history

health-app
  timeline
  measurements
  labs
  medication history
  uploaded records
```

These UIs should not be forced into a generic chat surface.

## 3. Responsibility boundary

The long-term rule is:

> Domain applications own authoritative domain state. `personal-ai-system` owns reusable AI/research capabilities and may provide shared domain intelligence.

Examples:

Travel application owns:

- trip dates,
- itinerary items,
- reservation state,
- user edits,
- booking identifiers.

Shopping application owns:

- saved lists/projects,
- user-selected requirements,
- purchase state,
- manually corrected product information.

Health application owns:

- measurements,
- imported records,
- medications,
- user-entered timeline data.

`personal-ai-system` owns or coordinates:

- model-provider access,
- context assembly,
- memory retrieval,
- external research,
- evidence/provenance,
- entity/ranking logic where reusable,
- structured extraction,
- tool orchestration,
- evaluation and experiment variants.

## 4. Current domain modules vs. future app repositories

The existing `domains/travel` and `domains/shopping` direction should remain useful.

Interpret these as shared AI-side domain modules that may provide:

- schemas used during research,
- source adapters,
- constraint/ranking logic,
- domain-specific prompt/tool definitions,
- normalization rules,
- evidence-to-entity mappings.

A future `travel-app` repository can consume those capabilities without duplicating them.

This avoids two bad extremes:

1. making the core system a monolith that owns every app's UI/database;
2. duplicating AI/research logic independently in every app.

## 5. Shared contracts to grow only when required

Likely future integration contracts include:

```text
conversation / assistant request
research request
structured extraction request
typed tool invocation
proposed action/change set
evidence/citation result
memory/context request
```

Do not create a universal manifest/plugin framework until real consumers require one.

The first external domain app should be allowed to use a small, explicit API.

Only repeated patterns should be promoted into a generic SDK or app registration model.

## 6. Structured results over prose parsing

A rich application should not need to scrape the assistant's natural-language response to modify its state.

Example future travel result:

```json
{
  "kind": "itinerary_patch",
  "trip_id": "trip-123",
  "operations": [
    {
      "op": "move",
      "item_id": "museum-456",
      "date": "2026-12-19",
      "time": "10:00"
    }
  ],
  "evidence_ids": []
}
```

The domain application:

1. validates the operation,
2. renders a preview/diff,
3. asks for approval when needed,
4. applies the mutation through its own backend.

The AI system proposes or executes through explicit tools; it does not silently become the source of truth.

## 7. Memory and evidence remain different

Preserve the repository's existing invariant:

- memory = durable, attributable user knowledge;
- evidence = an external observation at a point in time.

Examples:

```text
Memory:
"User usually prefers quieter, walkable neighborhoods."

Evidence:
"Hotel X was listed at $218/night at 2026-10-02T17:20Z."
```

Memory may influence search planning/ranking, but fresh evidence and hard constraints take precedence.

## 8. Cross-application memory must be scoped

The current single-owner model provides an identity seam, but not authorization.

Future memory access should become explicit by scope, for example:

```text
global preferences
travel preferences/history
shopping preferences/history
health-private context
app-specific context
entity-specific context
```

Cross-domain access should be policy-controlled.

Health context should never become globally available to unrelated applications by default.

## 9. ChatGPT can be a client, not a free backend provider

Long term, the system may expose tools through MCP/compatible integration so a general ChatGPT interface can call the personal system.

That should be treated as another client/interface.

It is separate from adding an OpenAI API `ModelProvider`, which would use separately billed API access rather than a consumer ChatGPT subscription.

This is optional and should not affect the near-term architecture.
