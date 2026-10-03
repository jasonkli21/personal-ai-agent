# Phase 8 in-session review and remediation

Date: 2026-10-03 (America/Los_Angeles).

Reviewed from clean HEAD `e67a38a`, together against `cb38e1b`:
`d94f759` (contracts/storage), `4a3e9bf` (orchestration/evaluation/API),
`3674935a5159b4387daf93be8606f854635c1546` (UI/docs), and
`e67a38a` (release evidence). Remediation is complete in the uncommitted
working tree based on `e67a38a`; verification is recorded in
[Phase 8 release evidence](phase-8-iterative-research.md).

## Review findings

1. **P1 — iteration assessment capacity is smaller than the loop.**
   `ResearchRun.assessments` and `decision_ids` permit five records, but the loop
   assesses before and after searches and again at iteration boundaries. A valid
   three-query run hits six assessments and is converted into `provider_error`.
   Reproduced with three required money attributes and three fake responses:
   three searches, five persisted assessments, final `insufficient/provider_error`.
   Derive history bounds from the FSM and remove redundant reassessments or size
   contracts safely. Test a full default three-query run and maximum configured
   iterations/recovery, with accurate exhaustion reasons rather than exceptions.
   Also bound valid candidate/constraint combinations that can emit more than
   thirty gaps before work; do not mislabel schema overflow as provider failure.

2. **P1 — persistent gaps falsely appear resolved.** `_gap` includes assessment
   count and iteration in its ID, while `_merge_gaps` resolves every old ID absent
   from the next assessment. The same still-missing price therefore becomes a
   resolved old gap plus a new open gap. Reproduced directly across assessments.
   Use stable semantic gap identity and preserve immutable assessment provenance;
   status becomes resolved only after the actual requirement/conflict disappears.
   Preserve exhausted/unresolvable status and conflict evidence history.

3. **P1 — decision intent cannot gain verified facts.** Every accepted candidate
   must have no claims; `_assess` passes those same empty candidates to
   `DecisionService`, which derives candidate evidence/identity from claim
   proposals. Even fresh explicit `Synthetic Widget costs 40.00 USD` evidence
   cannot improve a price decision. Implement a conservative evidence-to-proposal
   mapping using supported typed literals/subject-bound assertions, exact evidence
   IDs, and existing Phase 6 verification as sole authority. Ambiguous/negated,
   conflicting, stale, wrong-variant/scoped facts must fail closed. Do not let
   planners supply facts or infer prices. Add a paired fixture where a follow-up
   genuinely fills a required claim and changes a safe decision, plus negative
   fixtures; merely collecting more snippets is not sufficient acceptance.
   Generic sufficiency also currently means any word overlap; a source containing
   only one requested fact or a common word can mark a multipart question
   sufficient. Use explicit structured task requirements or a conservative
   supported-coverage assessment; classify unknown sufficiency as incomplete.

4. **P1 — single-pass execution can bypass run fencing and cancellation.**
   Backing sessions have no immutable marker linking them to their iterative
   orchestrator. The ordinary Phase 5 run route can claim a pending backing
   session. Cancelling before the first claim leaves that session pending.
   Reproduction: `create` iterative run, `cancel`, then Phase 5
   `ResearchService.prepare_run(run.session_id)` succeeds with `running`.
   Mark iterative ownership durably and reject single-pass execution at service
   and repository boundaries. Cancel pending/running sessions atomically with
   their runs. Ordinary legacy single-pass records must retain parity.

5. **P1 — elapsed budget and expired leases do not fence synthesis.** `_finish`
   checks remaining time once but grants the whole synthesis reserve timeout,
   never checks wall deadline afterward, and clamps reported elapsed usage.
   Reproduced by advancing the deterministic clock 80 seconds before synthesis
   and 15 during it: `completed/sufficient` at 95 seconds for a 90-second budget,
   with only 15 recorded seconds. Apply one absolute run deadline to assessment,
   provider counting/selection, search, synthesis and final commit; reserve
   synthesis time without granting time past that deadline. `_assert_lease` and
   repository commits also ignore lease expiry; do not let expired writers renew
   themselves or commit late results. Tests must use independent wall/attempt
   clocks and storage delays, not only zero-duration fake operations.

6. **P1 — started work can be reported as free after unexpected failure.**
   `_execute` catches unexpected errors and `_stop` releases reservations with
   `uncertain=False` even in searching/extracting/synthesizing. This can lose
   provider cost/token/source reservations after a side effect. Infer uncertainty
   from durable attempts/state and settle conservatively. `_settle` uses unchecked
   model copies; duration rounding or over-reserve settlements can later invalidate
   the entire run. Validate and reconcile once with truthful terminal reasons.

7. **P1 — cost/token policy is not completely frozen or accounted.** Search cost
   and retry/timeout/adapter behavior are read from live settings after run creation;
   changing cost settings changes the saved policy and replay ledger. Snapshot all
   cost/budget dispatch parameters needed by a run. Repeated Gemini counting calls
   in `_assess/_select` have no explicit elapsed/cost accounting. Token usage counts
   only selected input; output up to 20,000 characters is not budgeted, so narrow
   token limits are not enforced across the model turn. Reserve complete input and
   bounded output before model dispatch, use the shared assembler/counter and
   provider-neutral output limits, and settle actual/conservative usage. Permit
   safely extending a synthesis reserve within the overall max, rather than
   treating the initial reserve as the whole configurable token budget. Be explicit
   about estimates and any counter RPC policy; no claim of real billing accuracy.

8. **P2 — hostname policy disagrees with its contract.** ADR/guide promise exact
   hostnames, but `_host_allowed` accepts every subdomain. Three subdomains under
   one allowed host can also exceed the one-host ledger reservation and fail after
   the adapter call. Reproduced `other.example.org` accepted for `example.org`.
   Enforce the frozen exact-host set consistently in initial/follow-up dispatch,
   accepted observations and ledger settlement; exclude unlisted sources without
   breaking accounting or disguising provider calls.

9. **P2 — browser resume does not send its cursor.** The client parser starts at
   `after`, but `iterativeResearchApi.resume` sends no Last-Event-ID; the server
   replays from sequence zero. Resuming after any viewed timeline throws an invalid
   progress error. Send/validate the cursor before claiming work, and test an
   actual nonempty timeline resume across client/proxy/route. Validate cursor
   headers before `start/resume` mutates the run, including unreasonable future
   cursors that would hide initial persisted events.

10. **P2 — new UI responses are trusted unchecked.** `get/cancel` blindly cast
    JSON and progress validates only a few IDs/sequence fields. Malformed budget,
    events/gaps/decision IDs or session/source links reach immediate render
    dereferences. Validate the consumed shape, states, bounded counts and all
    rendered links, retain strict run/session/sequence fencing and reject partial
    trailing frames/oversized coalesced chunks correctly. UI should show a
    recoverable error, not crash or accept unsupported progress fields.

## Verification handoff

Use the required offline checks, all existing evaluations and the strengthened
paired iterative evaluator. Update guides/ADRs/migration/API/docs and release
evidence to match final behavior; record date and tested revision accurately.
Provider/emulator/GCP, billing, Node 22 and Docker verification remain gaps from
the implementation handoff. Tests must stay credential-free and synthetic.

## Remediation results

1. Assessment/gap/decision history is explicitly bounded for the full default
   three-query loop, and a paired fixture reaches three searches and six
   assessments with a truthful exhaustion reason. Candidate/constraint
   combinations are also capped before work.
2. Gaps retain per-assessment provenance and semantic keys; all open records
   stay open while the same requirement persists and resolve only when absent.
   Conflict findings aggregate their exact evidence IDs into a bounded record.
3. Exact-subject explicit money literals can form claim proposals with exact
   evidence IDs, but Phase 6 remains their sole verifier. Candidate identities
   are not persisted before supported claims exist. Generic sufficiency now
   requires conservative coverage of meaningful question terms. Paired fixtures
   prove a follow-up can change `research_needed` to a safe recommendation;
   stale, conflicting, wrong-variant and wrong-scope facts fail closed.
4. Iterative backing sessions carry immutable run ownership. Phase 5 claim/save
   paths reject them, and cancel terminalizes pending/running sessions.
5. A creation-time wall deadline fences transitions, dispatch, synthesis and
   commit. Synthesis cannot borrow time beyond it; lease expiry cannot be
   self-renewed. Late elapsed use is charged truthfully and the answer withheld.
6. Unexpected failures infer uncertainty from durable state and settle started
   work conservatively. Ledger settlements are validated and reconciled.
7. Dispatch costs, retries, provider timeout and output ceiling are frozen.
   Synthesis reserves selected input plus bounded output tokens, may extend its
   reserve only within the total limit, and enforces token and character limits.
8. Allowed-domain checks use exact hostnames for observations and accounting.
9. `Last-Event-ID` is sent through the client/proxy and validated before start
   or resume claims. Future and invalid cursors are rejected.
10. Frontend run, session, gap, event, progress and citation-link shapes are
    validated before rendering; incomplete trailing SSE frames are rejected.
    Timeline gaps render the latest status per semantic key.

Offline verification passed: 433 backend tests, Ruff, all seven evaluations,
78 frontend tests, frontend lint/typecheck/build, backend package build, and
`git diff --check`. Twelve backend/manual tests were skipped. Python 3.11.15,
uv 0.11.13, pnpm 11.19.0 and bundled Node 24.19.0 were used; Node 22 was
unavailable. No live provider, cloud project or Firestore emulator was used.

## Final light pass

Creation uses an owner-scoped deterministic run ID so retrying after a backing
session write succeeds without orphaning its ownership marker. Synthesis keeps
its original reserve when a smaller output limit needs fewer tokens, while
settling only the bounded input/output charge. Progress counts distinct open
requirements; conflict identity stays stable as its evidence changes. Price
proposals accept explicit amount/currency literals and fail closed when multiple
price scopes make attribution ambiguous. Three additional regressions cover
partial creation recovery, the smaller output limit and persistent gap counts.
