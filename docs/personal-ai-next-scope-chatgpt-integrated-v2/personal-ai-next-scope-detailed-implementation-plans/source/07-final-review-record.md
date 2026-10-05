# Final Review Record

Date: 2026-10-05

This package received a final consistency pass before delivery.



A second additive consistency pass incorporated **ChatGPT-plan integration through Sign in with ChatGPT**. No previously planned domain-context, strict-free provider, routing, storage, evaluation, or hardening work was removed.

## Verified package-level decisions

- Required hosted inference providers are **Gemini, Groq, and Cloudflare Workers AI**.
- Groq is the preferred secondary provider after Gemini.
- Cloudflare Workers AI is the third required provider for model diversity and additional free capacity.
- Other free providers remain optional extensions only.
- Strict-free applies to both model inference and supporting cloud infrastructure.
- Firestore remains the canonical operational/vector store.
- Cloud Storage is the artifact/blob tier, not a second database.
- DynamoDB remains an escape hatch rather than planned implementation.
- Current Gemini memory embeddings remain provider-separated and Firestore-vector compatible until an explicit migration.
- The original implementation roadmap was deliberately fine-grained across phases 0–27, with provider contracts, adapters, accounting, storage, routing, evaluation, and quota optimization kept separate; that substantive scope is preserved, with downstream numbering shifted only by the additive ChatGPT block.

- ChatGPT plan usage is a separate explicit user-entitled inference lane; it is not a fourth automatic strict-free provider.
- The required automatic hosted provider set remains Gemini, Groq, and Cloudflare Workers AI.
- Persistent ChatGPT authentication tokens stay local or in a user-controlled runtime and are forbidden from managed cloud persistence/logging.
- Personal AI remains the conversation/context/provenance owner for ChatGPT-plan turns.
- A reusable AI sidecar is added for Travel, Shopping, Finance, and Health with Copy first, bounded context inspection, and mutation Apply only through domain validation.
- Finance and Health receive stricter explicit context-minimization/selection behavior.
- The original roadmap scope and dependency order remain intact. ChatGPT auth/bridge, provider/runtime policy, usage handling, shared sidecar UI, and domain-integration contract are grouped into one additive Phase 17 block; the original downstream phases are renumbered to 18-28 without changing their substantive scope.
- Current SIWC/Responses constraints are treated as operational facts to re-verify, not permanent business-logic assumptions.


## Review fixes included

- removed stale package-version labeling;
- normalized provider ordering and terminology across all documents;
- bounded the concrete-provider phase so routing/evaluation work does not leak into it;
- clarified that Cloud Billing alerts are not hard spend caps;
- added spend-cap/application-guard guidance for strict-$0 operation;
- added Artifact Registry image storage as a potential free-tier bottleneck;
- added a Brave Search $0-prepay/usage-guard note;
- added an operational source snapshot for volatile free-tier facts;
- revalidated document references and phase numbering.
- consolidated previously scattered ChatGPT insertion phases into one Phase 17 block with subphases 17.1-17.4, while preserving all existing non-ChatGPT scope and downstream ordering.


- added a dedicated ChatGPT integration design document and cross-linked the integration through every existing package document;
- isolated the local/user-controlled ChatGPT credential runtime from the existing managed Cloud Run provider gateway;
- added explicit-provider failure semantics and no-silent-fallback rules;
- added credential redaction/storage acceptance criteria;
- added sidecar domain behavior for Travel, Shopping, Finance, and Health;
- added ChatGPT-plan usage/auth/model-churn operational risks and release-time reference checks.

Operational quotas/pricing remain external facts and must be re-verified at deployment time.
