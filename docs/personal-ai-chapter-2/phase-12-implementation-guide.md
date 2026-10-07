# Phase 12 implementation guide — Context builder refactor

Phase 12 adds one budgeted model-input builder for chat and the existing
standalone generation preparations. It combines the active conversation branch
and compatible working summary with eligible memory and any typed provider
items prepared from explicit caller selections. The builder does not choose
sources; deterministic planning remains Phase 13 scope.

## Runtime contracts

- [`context/builder.py`](../../backend/src/personal_ai/context/builder.py)
  defines `ContextBuildItem`, the validated `ContextBuildPolicy`, the shared
  `ContextBuilder`, sensitivity ordering, and the metadata-only manifest.
  Default source priorities are deterministic: global profile, AI memory,
  domain profile, current domain state, external research, tool results,
  domain history, client context, then provider-supplied conversation items.
- `ContextBuildPolicy` uses the ordinary input budget after response reserve and
  safety margin. Per-source ceilings come from the existing memory/research
  caps and the new `context_profile_max_tokens`,
  `context_domain_max_tokens`, `context_tool_max_tokens`, and
  `context_client_max_tokens` settings. Standalone task paths can apply their
  narrower task input limit.
- Every candidate is counted with its actual source wrapper and with the full
  candidate prompt. The builder keeps the mandatory newest user message and
  complete active-branch turns selected by the existing assembler. It omits
  whole optional source items with a stable reason when a source or global cap
  would be exceeded. A required item that is stale, unverified, or does not fit
  fails preparation.
- Typed provider items are rendered with their authority, timestamps, source
  references, entity references, field classifications, and typed payload.
  Source text is labelled as data, not executable instructions. Expired items
  are omitted. Permission dependencies are rechecked through an injected
  `ContextPermissionRevalidator`; if no revalidator exists or a check fails,
  the item is omitted. A required source failure stops preparation.
- Effective sensitivity is the monotonic join of the base conversation
  classification and each injected source item. The `unknown` classification
  ranks conservatively above `restricted`. Mixed field classifications remain
  present in the source item sent to the model.
- `AssembledContext.manifest` records the actual message IDs, summary identity,
  effective sensitivity, counter kind/version, global and per-source counts,
  injected item IDs, source authority, provenance counts, and omission reasons.
  It contains no prompt content. A debug log emits the same safe metadata.
- `ContextAssembler.assemble_research_context` is the structured standalone
  result used by research evidence selection, itinerary proposals, and booking
  extraction. `assemble_research` remains a tuple compatibility wrapper.
  Proposal travel projections are classified as authoritative sensitive
  domain context; research observations remain external; booking documents are
  client-supplied sensitive context.
- The development context inspector is read-only and labels its result
  `estimated_current_view`, with `actual_build: false` and
  `historical_reconstruction: false`. It never claims exact reconstruction of
  a past prompt or invokes a provider.

## Scope limits

Phase 12 does not add automatic source selection, real domain database
providers, provider routing, LLM-assisted planning, or domain mutations. The
permission-revalidator seam fails closed for items with permission dependencies
until a current grant implementation is supplied. The fixed local owner and
development authentication limits remain unchanged.

See the [implementation evidence](phase-12-implementation-evidence.md) for the
tested source state, checks, skipped environments, and remaining gates.
