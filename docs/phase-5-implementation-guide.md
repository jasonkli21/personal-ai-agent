# Phase 5 implementation guide

Phase 5 is implemented locally under [the reviewed plan](phase-5-implementation-plan.md)
and [ADR 0011](decisions/0011-bounded-source-grounded-research.md). It remains opt-in.
External provider/emulator/deployment checks are pending, as are the earlier-phase
external checks. No Phase 6 entities/ranking, domain agents, iterative loop,
authentication or research-to-memory promotion was introduced.

## Delivered map

| Plan | Delivered code and verification |
| --- | --- |
| P5.0 | Thirteen synthetic full-pipeline `evaluation/research-fixtures.json` cases, no-research baseline with no fresh evidence, `evaluation/research.py`; pytest executes every fixture |
| P5.1 | ADR 0011, `agents/research/contracts.py`, `evidence/contracts.py`, `search/contracts.py`, typed settings and [HTTP/SSE contract](api-contract.md#phase-5-standalone-research-research-v1) |
| P5.2 | `agents/research/repositories.py`, `storage/transactions.py`: owner-scoped atomic creation, idempotency conflict, run fencing, revision and append-only provenance; fake and installed-SDK boundary tests |
| P5.3 | `search/policy.py`: normalized deterministic single-pass planning, replaceable protocol, validated bounded custom output and deterministic fallback |
| P5.4 | `search/providers/brave.py`: fixed endpoint, no redirects, decoded-body bounds, process rate spacing, safe errors, bounded transient retries; mock HTTP transport coverage |
| P5.5 | `evidence/pipeline.py`: markup stripping, conservative content hashing, exact merge with all source IDs, retained near duplicates, differing URL passages, explicit expiry and source exclusions |
| P5.6 | Relevance/provider-order/freshness/diversity components, stable selection order, optional injected reranker with full-set validation/fallback, counted context and exclusions |
| P5.7 | `context/assembler.py:assemble_research`, shared provider counter and LLM abstraction; strict JSON full-passage quotation validation and generated citations; no memory/chat writes |
| P5.8 | `api/research.py`, gated `/research` UI and Next.js proxies, read-only inspection, `make research-eval`, CI, opt-in checks and this handoff |

Primary commits: plan review `64971b2`, contracts/storage `403a79b`, pipeline/API
`49432de`, integration/UI `1ed9974`; the release record captures acceptance evidence. See
[release evidence](releases/phase-5-source-grounded-research.md) for tested revision
and results.

## Request and execution boundary

`POST /v1/research` requires a question, freshness intent (`general` default or
`current`) and UUID idempotency key. The normalized request fingerprint excludes
the key but includes schema/freshness. Reusing a key with different input is a
409; a matching replay returns the existing session, including its stale/failed
status. A new intentional investigation needs a new key.

`POST /v1/research/{id}/run` claims one pending session. Concurrent execution is
409. A terminal replay emits only its stored terminal state and never searches.
A stream owns its work. Milestones follow persistence and contain only schema,
IDs, counts and safe state. The answer is fetched separately from session detail.
No unvalidated model delta is shown. Disconnect fails the session; cancellation
waits for bounded in-flight storage work before cleanup. A response-start failure
or process loss may prevent cleanup; detail derives `execution_abandoned` after
the persisted deadline. This is a view, not a background mutation or resume.

Queries are stored before execution. An immutable `started` attempt is persisted
before each provider call; its separate terminal attempt links via
`parent_attempt_id`. An interrupted started record does not assert success or
that no provider charge occurred. Attempts and evidence remain append-only.
Storage conflicts/outages produce safe failures; a failure to persist termination
is exposed through the recorded deadline. There are no worker/Pub/Sub research
jobs in this phase.

## Source and freshness policy

Brave supplies only web-result descriptions. The application never requests
publisher URLs, follows redirects, uses browser automation, or bypasses page
access restrictions. Provider requests use one fixed HTTPS endpoint and a named
user agent; environment proxy settings are ignored. Returned URLs must use
HTTP(S), omit credentials, and exclude literal local/private/reserved addresses,
local names and unusual ports. URL metadata validation is not a DNS resolution
or permission to fetch; future fetchers must independently resolve and fence
network destinations on every connection/redirect.

Provider response bodies are capped after decoding; raw responses are discarded.
Snippets are stripped of markup, script/style text and bounded at 1,200 characters;
oversized passages are excluded rather than silently truncated. Titles/URLs
remain bounded metadata. Publication dates are retained only if explicitly
provided by an adapter; Brave descriptions do not establish publication times.
If a supplied date predates the applicable freshness window, exclude the source
as `stale`. An absent date stays unknown; retrieval time does not prove the page
was recently published or independently verified.

`general` observations expire after 24 hours; `current` after 1 hour by default.
Selection checks actual expiry again. The result expires at its earliest selected
record's expiry, and both API and UI withhold stale answers. Expiry affects use,
not deletion. Source observations and expired evidence remain auditable.
Exact passage fingerprints merge while retaining all observation/citation links.
Canonical URL repeats with differing passages and near duplicates remain visible,
including differing numbers/negation. This does not identify entities or decide
which observation is true.

## Selection and synthesis limits

The deterministic selector scores lexical relevance, source-host diversity, provider order and freshness.
Zero-overlap evidence is excluded; this lexical baseline may miss relevant
paraphrases. All remaining eligible records must fit; if any is omitted for
budget, return insufficient evidence so potential disagreements are not hidden.
An optional trusted injected reranker must preserve the entire evidence set and
falls back on failure. There is no trained ranker or additional model planner.

The shared assembler retains the question, counts the instruction and entire
source wrappers with the same token counter as chat, and preserves response
reserve/safety margin. Real mode uses Gemini counting; offline mode explicitly
uses estimates. Research has no conversation history or memory hints.

Synthesis requires JSON containing one exact full-passage quotation per selected
record, in order. Unknown IDs, altered/missing quotations, duplicate JSON keys,
extra fields or oversized output are rejected. The application renders only
validated passages plus numbered source citations and a fixed uncertainty
notice. This enforces attribution of excerpts, not semantic entailment of broad
model prose; fluent multi-source conclusions are deliberately deferred. Even a
valid excerpt can be wrong or contain malicious instructions: display it as
source data. No research result is passed to memory extraction.

## Configuration and local offline workflow

Every research setting is in `backend/.env.example`. Defaults:

| Keys | Defaults |
| --- | --- |
| `RESEARCH_ENABLED`, `RESEARCH_INSPECTION_ENABLED`, `RESEARCH_PROVIDER_STORAGE_APPROVED` | `false` |
| `RESEARCH_STORAGE` | `firestore`; `memory` is an explicit disposable single-process demo |
| `RESEARCH_SEARCH_ADAPTER` | `fake`; production option `brave` |
| `RESEARCH_PLANNER`, `RESEARCH_RERANKER` | `deterministic` |
| `RESEARCH_API_KEY` | Empty secret |
| `RESEARCH_MAX_QUERIES`, `RESEARCH_MAX_SOURCES` | 1 (max 3), 8 (max 12) |
| `RESEARCH_MAX_RESPONSE_BYTES` | 131072 per attempt (max 262144) |
| `RESEARCH_MAX_REDIRECTS`, `RESEARCH_MAX_CONCURRENCY` | Fixed 0 / 1 |
| `RESEARCH_ATTEMPT_LIMIT` | 2 (max 3); quota/rejected/malformed failures do not retry |
| `RESEARCH_EVIDENCE_TTL_GENERAL_SECONDS`, `RESEARCH_EVIDENCE_TTL_CURRENT_SECONDS` | 86400 / 3600 |
| `RESEARCH_MAX_EVIDENCE_CONTEXT_TOKENS` | 4096, also bounded by total input allocation |
| `RESEARCH_TIMEOUT_SECONDS`, `RESEARCH_PROVIDER_TIMEOUT_SECONDS` | 30 / 10; whole session deadline includes tools/counting/synthesis |
| `RESEARCH_MIN_REQUEST_INTERVAL_SECONDS` | 1; process-local spacing, distributed quotas need external enforcement |

Storage RPCs have a five-second deadline and no hidden SDK retries. Cleanup may
add bounded storage time after cancellation/deadline. Optional extension code
must itself respect deadlines; no third-party arbitrary planner/reranker runs
by default. Settings prevent enabling Brave with memory storage, absent key or
absent storage-rights acknowledgement. Do not equate the boolean with acquiring
contractual rights.

For a credential-free manual demo, use the normal locked README install steps,
then set in untracked `backend/.env`:

```dotenv
RESEARCH_ENABLED=true
RESEARCH_STORAGE=memory
RESEARCH_SEARCH_ADAPTER=fake
RESEARCH_INSPECTION_ENABLED=true
```

In untracked `frontend/.env.local`, set `RESEARCH_ENABLED=true` and optionally
`RESEARCH_INSPECTION_ENABLED=true`. Restart both apps and open `/research`.
Use **Synthetic research evidence?**. It returns a labelled synthetic excerpt
with an example.org citation; that URL is a fixture, not a verified live page.
Fake search and fake synthesis need no Firestore or model key. The demo repository
is process-local and loses sessions on restart. Ordinary chat still uses its
existing Firestore/Gemini configuration.

The UI preserves the creation key after uncertain network failure and offers
request retry, saved-session refresh, stop and explicit new request. It can
reopen `/research?session=UUID`. API and proxy inspection require separate gates;
inspection reveals only IDs, score/exclusion/count/duplicate metadata, no raw
queries/passages and no provider calls. The bootstrap explicitly leaves research
and inspection off. The fixed owner/public bootstrap is still unauthenticated.

## Persistence, migrations and retention

Physical collections:

- `research_sessions`: schema/policy `research-v1`, typed bounded aggregate.
  Up to 3 queries, 9 actual calls (18 append-only start/terminal attempt records),
  12 observations/passages, one selection, bounded answer/citations. No raw body.
- `research_request_keys`: SHA-256 of owner plus request key; owner/session mapping.
  Created atomically with the aggregate. No cross-owner lookup or dedupe.

All reads are point lookups; no composite index is required. Before enabling
real persistence, apply the `research_sessions` field exemptions in
`firestore.indexes.json` for `request`, `queries`, `attempts`, `observations`,
`evidence`, `selection`, `answer`, `citations`, `run_token`:

```sh
for field in request queries attempts observations evidence selection answer citations run_token; do
  gcloud firestore indexes fields update "$field" --database='(default)' \
    --collection-group=research_sessions --disable-indexes
done
```

See the [official field-index command](https://docs.cloud.google.com/sdk/gcloud/reference/firestore/indexes/fields/update).
Bootstrap keeps research off and does not provision these optional exemptions.
No existing chat/memory migration is required. Future incompatible records must
use a new schema version and explicit migration. Do not enable Firestore TTL on
only one collection: orphaning the request-key mapping breaks replay.

No automatic deletion policy is implemented. Operators must select a documented
retention period allowed by the provider agreement, export only permitted audit
metadata, and explicitly delete sessions plus their key mappings together when
required. Do not enable durable real results without suitable storage/AI-use
rights and a retention/deletion process. In-memory demos have process lifetime
retention. No source query/body/passages are intentionally logged by application
telemetry; keep HTTP debug logging off because outbound URLs include query text.

## External verification remains opt-in

Before enabling real search, review the subscription's current
[storage-rights FAQ](https://brave.com/search/api/) and
[terms](https://api-dashboard.search.brave.com/documentation/resources/terms-of-service).
The ordinary terms do not grant arbitrary durable result storage or AI reuse;
obtain explicit suitable rights first. The code gate is an acknowledgement seam,
not legal authorization. Supply the secret only via an untracked env file or
Secret Manager; grant the API runtime identity access only to that secret.

Run from `backend` with deliberately configured synthetic environments:

```sh
RUN_RESEARCH_EMULATOR_TEST=1 python -m pytest tests/test_research_manual.py -q
RUN_RESEARCH_BRAVE_TEST=1 python -m pytest tests/test_research_manual.py -q
```

The emulator check requires explicit `FIRESTORE_PROJECT_ID` and
`FIRESTORE_EMULATOR_HOST`; it leaves random owner-namespaced synthetic records and
verifies independent-client reopening, replay and fenced terminal persistence.
The provider check requires `RESEARCH_PROVIDER_STORAGE_APPROVED=true` and
`RESEARCH_API_KEY`, makes one public synthetic verification search limited to
two results, checks bounded attributed snippets, and leaves no durable results.
Neither check establishes full Gemini synthesis quality or Cloud Run behavior.

External closeout also requires: ready index exemptions, API restart persistence,
real Gemini counting/strict-output acceptance and attribution inspection, deployed
browser/proxy disconnect, plan-wide rate/spend limits, quota/timeout negative
checks, and a provider-compliant deletion procedure. Synthetic local fixtures
cannot prove semantic entailment, provider freshness, license suitability or
cloud security. Do not store personal queries/results during smoke checks.
