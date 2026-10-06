# Free-tier inference and routing

## Principles

The project optimizes for a fully hosted strict-$0 AI system without requiring local AI hardware. Model/search quota is expected to be the near-term throughput limiter, but durable storage and cloud resource use accumulate over time and are tracked separately.

## Provider boundary

Phase 16 establishes neutral generation/streaming/structured-output/counting/embedding seams. Phase 17 adds concrete Gemini/Groq/Cloudflare adapters. Phase 18 describes model/account capability/free/privacy facts. Phase 19 measures usage/quota. Phase 21 adds deterministic task routing, Phase 22 measures quality, Phase 23 adds quota-aware scarcity, Phase 24 adds bounded cascades, and Phase 35 later explores adaptive routing only in shadow/offline first.

Provider SDK types never leak into context/domain logic. Current quotas/model availability are not application constants.

## Strict-free eligibility

Hard admission precedes scoring:

1. enabled/configured account/model;
2. verified zero-cost eligibility for that account/tier;
3. provider data/privacy eligibility for effective sensitivity;
4. task capability and context/output limits;
5. known cooldown/exhaustion constraints;
6. only then deterministic routing priorities/quality/scarcity.

Unknown eligibility does not justify a potentially billable path. Unknown quota remains unknown rather than fake precision.

## Model bottleneck vs. storage

Model/search quotas are resettable flow constraints; database/object storage is cumulative stock. Phase 10 therefore chooses storage primarily by data model/access pattern while still exploiting complementary free tiers:

- DynamoDB for high-volume operational timeline state;
- Postgres/pgvector for query-rich durable knowledge;
- GCS for large artifacts later.

The architecture does not add providers or clouds solely to maximize theoretical quotas. New backends remain behind interfaces and are activated incrementally.

## ChatGPT plan lane

Phases 25.1–25.4 add explicit user-controlled ChatGPT-plan execution through a local/user-controlled credential bridge. It is not part of automatic strict-free candidate sets and never silently falls back in either direction. Context/policy rules are identical to automatic inference.

## Evaluation discipline

Measured project-specific quality profiles precede quality-aware/scarcity/cascade promotion. Skipped live providers have no measured score. Model judges may supplement deterministic/schema/provenance/hard-constraint scoring but are not the sole evaluator.
