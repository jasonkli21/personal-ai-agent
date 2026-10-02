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

## Delivered Phase 6 decision flow

Phase 6 consumes the bounded Phase 5 result or other explicitly supplied,
validated evidence. It does not plan or run new searches as part of a decision.
The current flow is:

```text
validated candidate proposals and evidence
  -> owner, source, excerpt-fingerprint, and freshness checks
  -> conservative canonical entity resolution
  -> immutable claims and conflict/completeness status
  -> deterministic hard constraints
  -> preference ranking of eligible candidates
  -> persisted decision snapshot and cited result view
```

Phase 8 may later iterate: inspect missing or unreliable evidence, create a
focused follow-up query, and stop within a bounded budget.

## Shared platform contracts

- **Search adapters** return source-native results; they do not decide recommendations.
- **Evidence** preserves source URL or provider identity, observation time, and expiry. Phase 6 links claims to these observations without converting them into permanent entity facts.
- **Entity resolution** accepts unique stable identifiers or a sufficiently supported fresh attribute match; name similarity alone cannot select an entity.
- **Constraints** are executable requirements such as a budget cap, dates, availability, or dimensions. Application code evaluates them deterministically before ranking.
- **Ranking** scores explicit preferences only for eligible candidates. Memory-derived preference integration is not part of Phase 6.
- **Presentation** uses persisted results and source links. It does not add model-written factual claims or elevate prior recommendations into facts.

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
