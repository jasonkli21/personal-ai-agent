# Domain Application Integration

Status: long-term design direction; not current implementation scope  
Date: 2026-10-02

## 1. Goal

Allow rich applications to reuse `personal-ai-system` without forcing them to share one UI or independently reimplement AI infrastructure.

Potential repositories:

```text
personal-ai-system/
travel-app/
shopping-app/
health-app/        # later, after security/privacy prerequisites
```

This is compatible with keeping shared `domains/travel` and `domains/shopping` modules inside `personal-ai-system`.

## 2. Recommended ownership model

```text
                       personal-ai-system
          shared model/context/memory/research/evidence
                  optional domain intelligence
                           ^
                           |
                    stable HTTP/API seam
                           |
      +--------------------+--------------------+
      |                    |                    |
  travel-app           shopping-app         health-app
  own domain DB        own domain DB        own domain DB
  rich itinerary UI    rich compare UI      rich timeline UI
```

The domain app should remain usable as an application even when AI features are temporarily unavailable.

## 3. Travel application

### Core UI

- trip overview,
- day-by-day editable itinerary,
- drag/drop or direct editing,
- maps,
- booked vs. tentative items,
- hotel/flight/restaurant reservations,
- travel time,
- notes and attachments,
- research side panel.

### AI-assisted features

Initial useful integrations:

1. itinerary-aware chat;
2. activity/place/food/hotel research;
3. booking-email extraction;
4. proposed itinerary changes;
5. conflict/overload detection;
6. neighborhood comparison grounded in current evidence and saved preferences.

Example flow:

```text
booking email
  -> explicit import/user action
  -> structured extraction
  -> candidate reservation
  -> travel-app confirmation
  -> travel-app persists authoritative reservation
```

Do not let `personal-ai-system` silently persist a trip mutation merely because it extracted one.

### Shared-core requirements this may eventually create

- structured extraction endpoint;
- typed tool/action results;
- app-provided context references;
- domain-scoped memory;
- place/travel source adapters;
- action approval/diff metadata.

Introduce each only when the travel app actually needs it.

## 4. Shopping application

### Core UI

- research projects/lists,
- requirement editor,
- comparison matrix,
- candidate products,
- merchants/offers,
- price observations,
- review/source evidence,
- saved/eliminated/purchased states.

### AI-assisted features

- turn natural-language intent into explicit candidate constraints;
- research candidate products;
- summarize attributable review evidence;
- normalize product variants;
- compare candidates after hard filters;
- import receipts/order confirmations;
- retrieve prior purchase/preferences when relevant.

Hard constraints remain deterministic. For example, code—not an LLM—decides whether `$2,199 <= $2,000`.

### Shared-core requirements this may create

- entity resolution,
- offer/evidence freshness,
- structured product attributes,
- explainable ranking,
- preference-aware reranking,
- receipt/order extraction.

## 5. Health application

Health should be treated differently from travel/shopping.

### Possible UI

- longitudinal timeline,
- measurements,
- labs,
- medication history,
- appointment notes,
- exercise/sleep imports,
- document uploads,
- evidence-backed summaries.

### Potential AI assistance

- extract structured values from a user-provided record;
- summarize changes over a period;
- prepare a concise appointment summary;
- surface correlations for exploration while preserving uncertainty;
- explain terminology with clear source separation.

### Required prerequisites before real personal health data

Do not begin real health-data integration until the platform has:

- authentication,
- authorization,
- deliberate sensitive-data policy,
- provider suitability review,
- secure blob/document handling if uploads are supported,
- export/deletion controls,
- audit/provenance,
- strict separation of authoritative measurements from AI observations.

The current public unauthenticated bootstrap is not an acceptable health-data boundary.

## 6. Integration API evolution

Do not commit to this entire API now. A likely evolution is:

```text
current:
  /v1/conversations/...
  future bounded research endpoint

later, only if needed:
  structured extraction
  typed tool/action run
  app context lookup
  proposed change set
```

Prefer concrete endpoints/contracts discovered through one domain app over a generic agent RPC from day one.

## 7. Separate UI, shared intelligence

A shared React component library may eventually be useful for generic pieces such as:

- streamed assistant panel,
- citations,
- evidence cards,
- run progress,
- proposed-action preview.

It should be optional.

Travel maps/timelines, shopping matrices, and health charts should remain app-owned UI.
