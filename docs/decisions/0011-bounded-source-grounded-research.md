# ADR 0011: bounded source-grounded research

Status: accepted, 2026-10-02. User explicitly authorized Phase 5.

Research uses a standalone opt-in request and request-owned SSE execution.
Creation is transactional and idempotent per owner/request key; execution is
fenced once and never implicitly retried after process loss. Disconnect marks a
safe failure. Existing chat and memory flows remain independent.

Typed queries, attempts, source observations, evidence and selection are stored
inside one bounded session aggregate. Two physical collections,
`research_sessions` and `research_request_keys`, permit atomic provenance and
request replay. No full pages or raw responses are retained. Expiry excludes
records without deleting audit history; deletion/retention requires explicit
operator action. No scheduled jobs are introduced.

Brave web-search API snippets are the one external integration. The endpoint is
fixed; redirects and publisher-page fetching are forbidden. Unsafe source URLs
are rejected before inclusion. Result content is untrusted data. A separate
storage-rights gate and secret key are required before provider enablement.
See the [reviewed plan](../phase-5-implementation-plan.md) for official terms and
bounds. A TTL is eligibility, not a substitute for contractual deletion duties.

Grounded synthesis accepts only structured literal quotations of selected
passages. The model cannot introduce free-form assertions; all selected records
must remain visible so selection cannot conceal possible disagreements. Final
citations are generated from persisted source metadata. Broader prose synthesis
and semantic contradiction detection need separate evaluation.

Consequences: this phase produces useful cited evidence excerpts with explicit
uncertainty, at the cost of less fluent synthesis. Serial, bounded execution is
simple to reason about and validate. Larger investigations and asynchronous
execution are deferred; Phase 6 consumes these evidence contracts.
