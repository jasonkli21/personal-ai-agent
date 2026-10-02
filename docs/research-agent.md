# Research-agent model

The system is one reusable AI/research substrate. Thin travel and shopping
intelligence may reuse its capabilities. Future separate applications may own
authoritative domain records, business rules, and rich UI without forking the
core research or memory behavior.

## Delivered Phase 5 boundary

The gated standalone research request performs one bounded pass over Brave
search-result snippets, preserves expiring source observations, and returns
validated literal excerpts with citations. It runs in the direct request/SSE
path, without chat history, memory hints, publisher-page fetches, entity
resolution, recommendations, or Pub/Sub research jobs. See the
[Phase 5 guide](phase-5-implementation-guide.md) and
[release record](releases/phase-5-source-grounded-research.md).

## Later decision-support direction

The following flow is a roadmap, not delivered Phase 5 behavior:

```text
Question
  -> constraint extraction
  -> research plan
  -> source retrieval
  -> evidence extraction and freshness checks
  -> entity resolution
  -> hard filters
  -> preference-aware soft ranking
  -> evidence-backed synthesis
```

The future research loop may iterate: after each pass, inspect what is missing or unreliable, create a focused follow-up query, and stop only when the evidence is sufficient for the requested decision.

## Shared platform contracts

- **Search adapters** return source-native results; they do not decide recommendations.
- **Evidence** preserves source URL or provider identity, observation time, and expiry. Phase 6 may link it to entities without converting an observation into permanent fact.
- **Entity resolution** creates a canonical object from differently named or partially overlapping source records.
- **Constraints** are executable requirements such as a budget cap, dates, or product dimensions. Application code evaluates them deterministically.
- **Ranking** considers softer trade-offs, including durable preferences recovered from memory.
- **Synthesis** explains the answer and cites its current evidence; it does not elevate previous conclusions into facts.

## Domain modules

`domains/travel` may eventually supply research schemas, adapters, and ranking
features for places, neighborhoods, hotels, flights, and restaurants;
`domains/shopping` may do the same for products, merchants, offers,
specifications, and reviews. An external travel or shopping application owns
its editable itinerary or purchase state. The core returns attributed research
candidates and decision support for that application to validate and use.

## Evaluation questions

The scaffold anticipates evaluations such as:

- Does retrieved memory improve a recommendation without overriding current constraints?
- Are expired prices or availability excluded from an answer?
- Do variants from different sources resolve to the same entity correctly?
- Does the ranking satisfy hard constraints before optimizing preferences?
- Can the agent identify an evidence gap and issue a focused follow-up search?
