# Phase 9 authorization matrix

**Status:** application enforcement implemented; production IAM and owner-data
migration remain operator tasks. **Reviewed:** 2026-10-03.

| Surface | Principal | Owner scope / authority | Audit and safe failure |
| --- | --- | --- | --- |
| `/health` | Cloud Run invoker for deployed service; no end-user principal | Bounded readiness metadata only | Request ID and status logged; no account data returned |
| Conversation CRUD, messages, regenerate, edit/retry, context inspection | Verified Google OIDC principal; local/test-only fixed principal in those environments | Owner ID derived from issuer plus stable `sub`; repositories receive it through `get_current_owner_id`; client-supplied owner IDs are ignored | Missing/invalid token gives safe 401; foreign or missing record is 404; SSE gets a request ID and is owner-scoped before stream creation |
| Research and iterative research, including run/event/reconnect/cancel/resume | Same verified principal | Session/run repositories receive the resolved owner ID for every read, write, and idempotency key | Same 404 for foreign IDs; run leases and event cursors remain repository/service fenced |
| Proposed itinerary proposal create/detail | Same verified principal | Proposal idempotency and result records are keyed by a deterministic owner/key digest; optional research sessions are loaded through the same owner-scoped research repository | Same 404 for foreign IDs; concurrent replay is 409; provider calls use existing bounded daily reservations; request/context/output are not logged |
| Decisions and domain comparisons/lookups | Same verified principal | Decision, evidence, domain result, and provider-reservation repositories receive owner ID | Safe 404/409; provider kill switch and daily reservation run before external work |
| Account export | Verified principal with a Google token issued within `AUTH_RECENT_TOKEN_SECONDS` | Exact owner-only query over the enumerated owner data collections; no owner ID is accepted from the body | No-store JSON download; audit event contains opaque actor/target identifiers; oversized export is rejected |
| Deletion request/status/confirm/cancel | Recent token for state changes; verified owner token for status | Request ID is deterministic from owner and idempotency key; repository verifies stored owner on every access | Audit events are idempotent; foreign/missing request is 404; conflicts are 409. Physical deletion is not implemented, so deployment keeps the feature disabled |
| Pub/Sub memory push `/tasks/memory` | Google-signed OIDC token with configured audience and exact Pub/Sub invoker service-account email; Cloud Run IAM also restricts invokers | Opaque durable job ID; worker reloads owner and source state from Firestore | Invalid identity 401; signing-key outage 503; malformed/terminal payloads acknowledged without payload logging |
| Scheduled maintenance `/tasks/maintenance` | Google-signed OIDC token with configured audience and separate maintenance invoker service account | Only one active principal-to-owner mapping is accepted; bounded batch; no physical deletion | Invalid identity 401; ambiguous multi-owner state or infrastructure failure 503; event counts and opaque IDs only |
| Principal bootstrap and privileged lifecycle actions | Verified end-user or explicitly configured service identity | Firestore identity mapping or the requesting owner | Immutable audit records use opaque owner identifiers, action, target class/ID, result, correlation ID, and UTC timestamp |

The API has no administrative browser route. Firestore administrative actions
are operator actions and must use a separate controlled identity; broad project
owner/editor access is not an application authorization mechanism.

## Routes and repository boundary

All application routers are behind the authentication middleware. Route
dependencies obtain the current owner from `request.state.principal`; route
payloads do not select an owner. Existing repositories check the supplied owner
again when loading an individual record, including SSE run/session access and
retry targets. Shared canonical entities explicitly marked `owner_id="*"` are
read-only catalog records; owner-specific claims and snapshots remain scoped.

The current fixed `local` records are not visible to the authenticated owner
until the dry-run-first [migration](phase-9-owner-migration.md) is reviewed and
applied. That tool requires an active owner mapping and a repeated target ID. Apply
supports chat-only databases and refuses any later-phase legacy records before
writes; full aggregate/derived-key migration remains unimplemented.
