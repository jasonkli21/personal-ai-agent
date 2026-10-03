# Phase 8 implementation guide

Phase 8 adds bounded iterative research over the Phase 5 evidence pipeline and
Phase 6 decision service. It is implemented locally after explicit
authorization. Research, iteration, and progress gates remain disabled by
default. The fixed `local` owner is still a development boundary, not
authentication. See [release evidence](releases/phase-8-iterative-research.md)
for offline results and open external checks.

## Delivered map

| Plan | Implementation and evidence |
| --- | --- |
| P8.0 | Eighteen deterministic paired cases in `evaluation/iterative-research-fixtures.json`; each executes the real Phase 5 and Phase 8 services against the same fake sources/clock, with checked baseline snapshots and a result schema. |
| P8.1 | Accepted [ADR 0016](decisions/0016-bounded-iterative-research.md) and [ADR 0017](decisions/0017-iterative-research-budget.md); typed run, iteration, gap, assessment, proposal, event, and ledger contracts; transition validator; migration/index manifest. |
| P8.2 | Owner-scoped run/session/idempotency repository; revision and lease fences; atomic Firestore run/session commit; append-only event/evidence history; safe recovery tests. |
| P8.3–P8.4 | Deterministic sufficiency checks and named gap classes; schema-validated follow-up templates carry only the selected gap ID, user candidate/attribute IDs and frozen domains. The planner cannot send query text, facts, constraints, or adapter calls. |
| P8.5 | Bounded state machine reuses Phase 5 search, extraction, evidence selection, shared token assembler and LLM boundary. Explicit decisions re-evaluate through `DecisionService`; hard constraints and claim verification remain authoritative. |
| P8.6 | Gated API/SSE and same-origin Next.js proxies; persisted read-only event reconnect, explicit cancel/resume actions, budget/gap/timeline view, and UI/proxy regressions. Single-pass remains the selected default. |
| P8.7 | `make iterative-research-eval`, CI integration, this guide, release evidence, API contract and architecture updates. |

## Run, iteration, and recovery behavior

The `ResearchRun` finite state machine is `pending → assessing → planning →
searching → extracting → assessing`, with zero or more bounded assessment and
follow-up cycles, followed by `synthesizing → completed|insufficient`. Provider
and synthesis failures, cancellation, and exhausted/no-productive-work exits
end in explicit terminal states. `iterative_contracts.py` defines and checks
every permitted state edge. Every transition appends an ordered event in the
same durable run update.

The service persists the planned Phase 5 query, gap link and query reservation
before dispatch. It persists a `started` adapter attempt and source, cost,
elapsed-time and domain reservations before each provider call. A separate
terminal attempt and the evidence/session update commit with the transition to
assessment. Synthesis reserves its token, cost and time capacity before the
LLM call; the shared context assembler and strict Phase 5 citation validator
remain in the path. Provider SDKs stay inside the existing adapters and
`llm` package.

Runs are idempotent by owner and request key. The backing Phase 5 session uses
a derived key namespace and an immutable `iterative_run_id`; Phase 5 claim and
save paths reject iterative-owned sessions, including a pending session after
iterative cancellation. A single-pass request with the same caller key cannot
adopt the iterative session. Run/session writes check owner,
revision and lease in one Firestore transaction. The session remains the
authoritative location for queries, attempts, observations, evidence,
selection, answer and citations. The run stores versioned policy/budget
snapshots, iteration/gap/assessment history, safe events and the resource
ledger.

`POST .../cancel` fences the run as terminal. In-flight work may finish at its
external provider, but a stale lease/revision cannot persist a late result.
Closing a browser stream only disconnects the view; it does not cancel the
run. Reconnect reads `GET .../runs/{id}` and `GET .../events?after=N` and never
starts work. The explicit resume action can claim an expired lease when the
last durable state is safe. A started provider/model call without a committed
terminal result is uncertain: recovery settles its full reservation, records
`side_effect_uncertain`, returns an incomplete result and does not retry that
call. A committed result is recovered by its stable query/attempt identity
without repeating the side effect. A retryable provider failure is a safe
boundary: the completed failed attempt is retained and the next numbered
attempt reuses the same query.

Each backing session is durably marked with its iterative run ID. Phase 5
ordinary execution rejects these sessions at both service and repository save
boundaries. Cancelling a still-pending run also terminalizes its backing
session. Expired lease owners cannot renew themselves or commit ordinary late
writes. Resume cursors are checked against persisted event sequences before a
claim; `Last-Event-ID` crosses the same-origin proxy unchanged.

| State | Allowed next states | Durable external work |
| --- | --- | --- |
| `pending` | `assessing`, `cancelled`, `failed` | None |
| `assessing` | `assessing`, `planning`, `synthesizing`, `insufficient`, `failed`, `cancelled` | Evidence/decision evaluation only |
| `planning` | `planning`, `searching`, `assessing`, `insufficient`, `failed`, `cancelled` | Query and all applicable reservations persisted first |
| `searching` | `searching`, `extracting`, `assessing`, `insufficient`, `failed`, `cancelled` | Started attempt/reservations persisted first |
| `extracting` | `assessing`, `failed`, `cancelled` | Evidence/session and transition commit together |
| `synthesizing` | `synthesizing`, `completed`, `insufficient`, `failed`, `cancelled` | Context/token/cost/time reserve persisted first |
| terminal | none | Cancelled/failed/insufficient/completed are immutable |

## Gap and planner policy

The deterministic assessor emits only `initial_coverage`,
`required_fact_missing`, `evidence_stale`, `source_conflict`,
`candidate_coverage`, `identity_ambiguity`, and `citation_support` gaps.
Each assessment gives its gap records immutable assessment provenance and a
semantic key. Repeated open requirements therefore remain auditable without
being marked resolved merely because a new assessment produced a new record;
all records for a requirement are resolved only when the requirement actually
disappears. A conflict finding carries the exact set of participating evidence
IDs and is aggregated to one bounded gap per assessment. The UI displays the
latest status per semantic key while the run retains history. A gap with no
safe follow-up is marked unresolvable and remains visible.

`FollowupProposal` is a validated template action tied to one selected gap. It
has no free-form query, fact, constraint, or candidate-claim field. The service
validates its template, gap, target/attribute, and exact recorded hostname set,
then builds the query deterministically from the original user question, the
gap's permitted qualifier, and `site:` restrictions. Repeated normalized
queries are not dispatched. The query is persisted in the ordinary Phase 5
session with `parent_query_id` and `gap_id`.

An optional `decision_intent` accepts user-authored candidates, hard
constraints and preferences; candidate claims are rejected. The service may
propose only conservative subject-bound typed claims directly supported by
fresh, exact-identity evidence (currently explicit unambiguous currency/price
assertions). Proposals include exact evidence IDs and pass through the
existing `DecisionService`, which remains the sole identity, claim, freshness,
conflict and hard-constraint verifier. Negation, multiple values, other
candidates, wrong identifiers and wrong scope produce no claim proposal.
Candidate identities are not persisted before there is evidence-backed claim
support. Paired fixtures prove that a missing required price can become a
verified Phase 6 claim after follow-up and improve `research_needed` to a safe
recommendation; stale, conflicting, variant-mismatched and out-of-scope values
remain unverified. Generic answer sufficiency also requires coverage of all
meaningful question terms, with explicit conservative aliases for common fact
types; uncertain coverage remains incomplete.

## Budget versions and stopping

Each run snapshots `iterative-research-policy-v1` and
`evidence-quality-budget-v1`; changing current settings cannot alter a saved
run. Defaults and validated ceilings are:

| Setting | Default | Maximum | Use |
| --- | ---: | ---: | --- |
| `ITERATIVE_MAX_ITERATIONS` | 3 | 5 | Assessment/follow-up cycles |
| `ITERATIVE_MAX_QUERIES` | 3 | 3 | Total searches, including initial query |
| `ITERATIVE_MAX_SOURCES` | 12 | 12 | Source observations returned by attempts |
| `ITERATIVE_MAX_ELAPSED_SECONDS` | 90 | 300 | Run wall-time ceiling |
| `ITERATIVE_MAX_TOKENS` | 16,000 | 32,768 | Synthesis/context ceiling |
| `ITERATIVE_MAX_PROVIDER_COST` | USD 0.05 | USD 1.00 | Estimated provider-cost ceiling |
| `ITERATIVE_ALLOWED_DOMAINS` | `example.org` | 12 hosts | Exact hostname allowlist for accepted results and follow-up templates |
| `ITERATIVE_SYNTHESIS_RESERVE_TOKENS` | 4,096 | 8,192 | Retained before search work |
| `ITERATIVE_SYNTHESIS_RESERVE_SECONDS` | 20 | 60 | Retained before search work |
| `ITERATIVE_SYNTHESIS_COST_USD` | USD 0.005 | USD 0.10 | Retained synthesis-cost estimate |
| `ITERATIVE_SEARCH_COST_USD` | USD 0.005 | USD 0.10 | Search-attempt estimate |

The immutable ledger records reservation and settlement for iterations,
queries, sources, tokens, provider cost, elapsed time and allowed domains. One
absolute deadline starts at run creation and caps assessment, adapter calls,
synthesis and final commit; synthesis receives only time remaining before that
deadline. Run elapsed use is recorded once as actual wall time, including an
overrun caused by late work; it is never clamped to the ceiling. Normal
settlements record bounded use; cancelled/uncertain attempts settle their full
reservation conservatively. Search and synthesis costs are
configured estimates because the current provider interfaces do not return
billing data; they are not invoices. Elapsed time uses both monotonic attempt
duration and run wall time. The shared token counter records the selected
context count; each synthesis reserves selected input and bounded output
tokens before dispatch, can extend its initial reserve within the frozen total
token ceiling, and consumes the complete reservation if uncertain. The model
boundary enforces provider output-token limits and a provider-neutral response
size ceiling. Policy values that affect dispatch (search cost, retry count,
provider timeout and synthesis output ceiling) are frozen per run. Limits are
validated before dispatch and again at settlement.

Terminal reasons are `sufficient`, `iteration_budget_exhausted`,
`query_budget_exhausted`, `source_budget_exhausted`,
`token_budget_exhausted`, `provider_cost_budget_exhausted`,
`elapsed_budget_exhausted`, `no_productive_query`, `provider_error`,
`synthesis_error`, `side_effect_uncertain`, `cancelled`, and
`evidence_insufficient`. A successful evidence synthesis with unresolved
required gaps is `insufficient` with a partial cited answer; when no safe
answer can be synthesized, the saved session has no answer and the UI keeps
the gaps and stop reason visible.

## API, UI, storage, and gates

The routes and safe event schema are specified in the [API contract](api-contract.md#phase-8-iterative-research-iterative-research-v1). Resume accepts a `Last-Event-ID` cursor and validates its persisted sequence before claiming a lease.
The frontend uses same-origin `/api/research/iterative` proxy routes. The
research mode selector appears only when the frontend's
`NEXT_PUBLIC_ITERATIVE_RESEARCH_ENABLED`, `ITERATIVE_RESEARCH_ENABLED`, and
`ITERATIVE_PROGRESS_ENABLED` settings are all true. Backend routes separately
require `RESEARCH_ENABLED`, `ITERATIVE_RESEARCH_ENABLED`, and
`ITERATIVE_PROGRESS_ENABLED`. Defaults remain false and single-pass remains
selected by default. Candidate decisions also require `DECISION_ENABLED`.

Firestore adds `iterative_research_runs` and
`iterative_research_request_keys`; no existing records are rewritten and no
backfill is needed. Point reads use no composite index. The field exemption
manifest covers large run snapshots/arrays. See
[migration notes](migrations/phase-8-iterative-research.md) and
`firestore.indexes.json`; apply index exemptions before enabling durable
Firestore runs. Do not configure TTL for only one of the session/run/key
collections because that can orphan replay mappings or provenance.

Do not enter secrets or private material into public research queries. Search
providers receive the user's initial question and the bounded follow-up text;
query text is retained with the Phase 5 session. Progress events do not contain
question/query text, evidence passages, prompts, provider traces or hidden
reasoning. This does not make the fixed `local` owner an authenticated private
data boundary.

## Verification and remaining gaps

`make iterative-research-eval` runs 18 paired Phase 5/Phase 8 cases offline,
including the full three-query/six-assessment loop with multiple required
facts and the negative typed-claim fixtures.
`backend/tests/test_iterative_research*.py` covers state/schema validation,
storage ownership/idempotency, reservation reconciliation, retry/restart,
uncertain side effects, cancel races, late-write fencing, reconnect reads,
route gates and safe SSE payloads. `frontend/src/app/research/research-panel.test.tsx`,
`frontend/src/lib/iterative-research-api.test.ts`, and the proxy tests cover
single-pass defaults, iterative partial results, gap/timeline visibility,
replay sequence/run checks, bounded rendered response/link validation, gates,
nonempty-cursor reconnect and explicit cancellation.

Offline checks use deterministic clocks, in-memory repositories, synthetic
sources and fake LLM/search adapters only. Real Firestore transaction/restart
behavior, production index readiness, Brave/Gemini limits and attribution,
provider cost accuracy, public browser disconnect behavior, deployed GCP
behavior, authentication, provider data rights and deletion/retention
operations remain external work. Phase 8 adds no worker, scheduler, background
autonomy, booking/purchase operation, authentication, or Phase 9 behavior.
