# Itinerary proposal prerequisite independent review

Reviewed through `1d23b0b` (implementation `d13cf36`, evaluator `efcd481`).
Contract remains proposed pending remediation and coordinator verification.

## Findings requiring fixes

1. **High: partial time patch intent is lost across serialization.**
   `ProposalSetItemTimes` distinguishes omitted endpoints with model_fields_set,
   matching the travel preview's partial-update behavior. But FastAPI response
   serialization and ProposalRecord.model_dump(mode="json") emit both default
   endpoint fields. A start-only operation becomes end_time:null when persisted
   or sent over HTTP, and travel clears the existing end time. Preserve omitted
   fields in the wire and durable representation or explicitly normalize both
   times against the evolving projection before storage/return. Verify semantic
   equivalence with travel preview after HTTP and Firestore round trips,
   including repeated time operations, clear-one endpoint, and cross-day moves.

2. **High: elapsed deadline/event-loop boundary is incomplete.**
   create() claims storage before asyncio.timeout and persists terminal storage
   after it. _generate resets a fresh monotonic deadline and synchronously calls
   ContextAssembler.assemble_research on the async request thread, including
   Gemini network token counting. Thus configured timeout does not bound the
   complete operation, can block unrelated requests, and fresh counting and
   stream budgets exceed remaining time. Reuse one absolute deadline established
   before claiming storage; run synchronous projection/counting in bounded
   worker execution; propagate remaining budget to storage/counter/stream and
   reserve terminal persistence time deliberately. Preserve running fences on
   uncertain/cancelled work and never repeat model dispatch. Do not claim a hard
   bound that shielded storage cleanup cannot meet. Add slow claim/count/stream/
   terminal-write tests plus concurrent event-loop responsiveness and no second
   model call after timeout/replay. Ensure provider streams close explicitly on
   oversize/invalid output/cancellation.

## Policy to resolve for travel acceptance

Travel ADR 0010 currently requires cited evidence for proposals, while upstream
permits context-only scheduling edits with zero citations when no research
sessions are supplied. Keep that distinction explicit and reviewable. A
context-only edit may rely on traveler instruction/current itinerary without
claiming current opening hours/availability. Before acceptance, align consumer
policy and wire provenance so context-only proposals cannot be mistaken for
externally supported proposals. Do not simply relabel uncited evidence work as
context-only after an evidence failure. Generation remains off by default.

## Verification scope

Review covered DTO/handle/protection bounds, operation sequence, research
provenance and expiry, owner-scoped replay and terminal fencing, HTTP/auth
safeguards, account-export/retention integration, and provider/context seams.
Use fresh Luna Extra High for substantive fixes. Preserve pre-existing
frontend/tsconfig.tsbuildinfo and avoid unrelated upstream changes/deployment.
