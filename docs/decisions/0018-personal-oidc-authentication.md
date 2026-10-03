# ADR 0018: Personal authentication and owner authorization

- **Status:** accepted for Phase 9 implementation
- **Date:** 2026-10-03
- **Decision owner:** project owner

## Context

The application serves one personal account, currently maps every request to
the unauthenticated `local` owner, and deploys its API publicly. Phase 9 must
replace that trust assumption across the API, repository owner parameters,
streams, proxies, workers, export, deletion, and scheduled work. The project
uses Google Cloud Run and already depends on Google Cloud libraries. No identity
provider, client ID, allowlisted account, or production project credentials are
present in the repository.

## Decision

Use **Google Identity Services with Google OpenID Connect ID tokens** for the
single personal account. The API accepts an identity only after a Google client
library validates the token signature, allowed issuer, exact configured web
client audience, expiration, and verified account email. A configured exact
email allowlist controls initial account bootstrap. The stable Google `sub`
claim—not email, request data, or a header-supplied user ID—is used to create an
opaque deterministic owner ID and an auditable principal-to-owner mapping.

The web client keeps the short-lived ID token in memory and sends it only to
same-origin Next.js API proxies over HTTPS. The Next.js proxy forwards the user
token separately from its own Cloud Run service identity. The API is a private
Cloud Run service, invokable only by the dedicated web runtime service account;
the API still verifies the end-user token on every data request. `/health` may
return bounded readiness metadata without a user principal. Development mode
may use the fixed `local` owner only when the explicit environment is `local`
or `test`; a staging or production configuration with missing or development
authentication fails closed at startup.

Tokens are not written to browser storage, application storage, audit records,
or logs. Export and deletion require a token newer than the configured
reauthentication window. Google account recovery is the account-recovery path.
Access removal requires removing the exact allowlist entry and/or disabling
the Google sign-in client/account; already-issued tokens expire within the
provider's token lifetime. This provider limitation is documented.

## Alternatives considered

- **Cloud Run IAM as end-user auth:** good service-to-service boundary, but a
  browser sign-in flow and user-to-owner mapping are still needed. It is used
  for the web-to-API boundary, not as the application identity source.
- **Identity-Aware Proxy:** suitable for deployments fronted by a configured
  load balancer, but requires external HTTPS/load-balancer and custom-domain
  setup that is not present in this repository. It can replace the browser
  identity integration later while keeping the principal contract.
- **Firebase Authentication:** offers persistent client sessions and broader
  account-management features but adds a second project configuration and
  identity persistence model that this single-account use case does not need.
- **Self-managed username/password:** adds credential storage, reset, and
  recovery responsibility without improving the current single-owner use case.

## Consequences

- Production is unusable until a Google OAuth web client, exact allowlisted
  account, authorized origins, TLS URL, and private API IAM binding are
  configured.
- The browser must sign in again after its memory-only credential expires or
  the page reloads. This avoids persistent browser tokens at the cost of
  convenience.
- Stable principal IDs survive email changes. Existing `local` records are
  not silently reassigned; a separate dry-run-first, audited migration is
  required before those records become visible to the account.
- Signed identity, audience, account allowlist, owner mapping, and repository
  owner filtering remain distinct checks; one cannot substitute for the other.
- The implementation does not authorize production traffic or establish
  provider retention, backup, deletion, or legal suitability.

## References

- [Google backend authentication guidance](https://developers.google.com/identity/sign-in/web/backend-auth)
- [Google Identity Services server-side token verification](https://developers.google.com/identity/gsi/web/guides/verify-google-id-token)
- [Cloud Run service-to-service authentication](https://docs.cloud.google.com/run/docs/authenticating/service-to-service)
