# Research-agent model

The system is one reusable research platform. Travel and shopping are domain modules that configure it; they should not fork the orchestration or memory architecture.

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
- **Evidence** preserves source URL or provider identity, observation time, expiry, source type, and entity links.
- **Entity resolution** creates a canonical object from differently named or partially overlapping source records.
- **Constraints** are executable requirements such as a budget cap, dates, or product dimensions. Application code evaluates them deterministically.
- **Ranking** considers softer trade-offs, including durable preferences recovered from memory.
- **Synthesis** explains the answer and cites its current evidence; it does not elevate previous conclusions into facts.

## Domain modules

`domains/travel` will eventually work with places, neighborhoods, hotels, flights, and itineraries. `domains/shopping` will work with products, merchants, offers, specifications, and reviews. Each may add provider adapters and ranking features, but both use the shared research, evidence, entity, memory, and evaluation layers.

## Evaluation questions

The scaffold anticipates evaluations such as:

- Does retrieved memory improve a recommendation without overriding current constraints?
- Are expired prices or availability excluded from an answer?
- Do variants from different sources resolve to the same entity correctly?
- Does the ranking satisfy hard constraints before optimizing preferences?
- Can the agent identify an evidence gap and issue a focused follow-up search?
