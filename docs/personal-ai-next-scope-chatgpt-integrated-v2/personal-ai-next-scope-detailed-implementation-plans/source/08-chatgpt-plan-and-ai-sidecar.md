# ChatGPT Plan Integration and Shared AI Sidecar

Status: additive integrated design detail  
Date: 2026-10-05

## 1. Goal

Add an optional ChatGPT-powered interaction surface to Personal AI and its Travel, Shopping, Finance, and Health applications without changing the existing domain-context, strict-free inference, routing, storage, or domain-authority plans.

The integration should let an eligible user:

1. choose **Continue with ChatGPT**;
2. authorize supported ChatGPT-plan usage;
3. choose an account-visible ChatGPT model;
4. open a reusable AI sidecar inside a domain application;
5. send a bounded, inspectable Personal AI context package to ChatGPT;
6. stream the answer in-app;
7. Copy the answer, optionally insert it into a safe draft surface, and later Apply typed changes only through the mutation-proposal framework.

The system must not embed/scrape the chatgpt.com consumer interface and must not move reusable ChatGPT credentials into the managed Personal AI cloud backend.

---

## 2. Relationship to the existing plan

The existing automatic runtime remains unchanged:

```text
automatic strict-free inference
  -> Gemini
  -> Groq
  -> Cloudflare Workers AI
```

ChatGPT is additive:

```text
explicit user choice
  -> ChatGPT plan
  -> Sign in with ChatGPT
  -> user-controlled bridge/runtime
  -> OpenAI Responses API
```

ChatGPT is **not**:

- a fourth automatic strict-free provider;
- a fallback target when free API quota is exhausted;
- a replacement for Gemini/Groq/Cloudflare;
- a source of ChatGPT conversation history or memory for Personal AI;
- a new authoritative store for domain state.

---

## 3. Current external constraints to re-verify

As of 2026-10-05, current OpenAI documentation/terms indicate:

- eligible ChatGPT Plus/Pro users can authorize supported plan-backed AI requests from open-source/local applications without supplying an API key;
- plan-use authorization is separate from basic identity sign-in;
- the flow does not grant access to the user's existing ChatGPT conversations or other ChatGPT account context;
- persistent SIWC authentication tokens must remain local or in a runtime controlled by the user, not in a remote managed environment;
- direct plan-backed inference uses the public Responses API;
- current HTTP requests require `store: false` and `stream: true` and the required context/history must be supplied with the request;
- account-visible models should be discovered using the authenticated account instead of hard-coded;
- supported fields/tools differ from normal Responses API usage and should remain isolated in the bridge;
- user/app plan usage can become unavailable or hit limits independently of Personal AI's strict-free provider quotas.

These are operational integration facts, not permanent architecture constants. Re-verify before implementation and release.

---

## 4. Target architecture

```text
                    +-----------------------------+
                    | Travel / Shopping / Finance |
                    | Health / Personal AI Chat   |
                    +--------------+--------------+
                                   |
                                   v
                           Shared AI Sidecar
                                   |
                    +--------------+--------------+
                    |                             |
                    v                             v
          Personal AI cloud runtime       Local/native ChatGPT bridge
          -------------------------       ---------------------------
          app/workspace auth              SIWC OAuth/OIDC/PKCE
          context planner                 secure credential storage
          domain context providers        token refresh/revocation
          policy/sensitivity              account model discovery
          conversation state              Responses streaming
          provenance                      SIWC error normalization
          mutation boundaries                     |
                    |                             v
                    |                    OpenAI Responses API
                    |                             |
                    +---------- browser/native ---+
                                   |
                                   v
                         persist completed turn
                         in Personal AI thread
```

The browser/native client coordinates the flow but does not receive reusable ChatGPT OAuth credentials.

---

## 5. Local/user-controlled bridge

### Responsibilities

- stable host identity required by the supported SIWC flow;
- account registration/sign-in;
- PKCE/state/nonce handling;
- ID-token validation and account identity;
- plan-use scope validation;
- access/refresh token storage and serialized refresh;
- sign-out/disconnect/revocation recovery;
- model discovery for the selected account;
- direct Responses API execution and stream processing;
- ChatGPT-specific error normalization;
- safe connection/status API for the sidecar.

### Storage

Preferred:

- OS-protected credential/key store when available;
- otherwise a protected user-local credential file only when compatible with current official guidance.

Forbidden:

- Firestore;
- Cloud Storage;
- Secret Manager;
- browser local/session storage;
- logs/traces/analytics;
- account exports;
- support bundles.

### Browser bridge security

For a hosted web UI using a loopback bridge:

- bind loopback/local IPC by default;
- allow only explicitly configured Personal AI/domain origins;
- require a short-lived bridge session/request nonce or equivalent caller authorization;
- enforce anti-CSRF controls;
- never use wildcard credential-bearing CORS;
- never return access/refresh tokens to JavaScript;
- redact auth/account material from diagnostics.

---

## 6. Provider and routing model

Two modes are first-class:

```text
AUTOMATIC_STRICT_FREE
EXPLICIT_PROVIDER
```

For `AUTOMATIC_STRICT_FREE`, the existing router selects among verified Gemini/Groq/Cloudflare candidates.

For `EXPLICIT_PROVIDER(openai_chatgpt_plan)`, Personal AI:

1. builds/authorizes bounded context;
2. verifies that ChatGPT is explicitly selected;
3. checks bridge connection/auth/model status;
4. passes the context package to the bridge;
5. receives normalized streaming output;
6. persists the completed turn with provider/model attribution.

Do not automatically score or cascade across these two modes.

A ChatGPT failure may expose a button such as **Switch to Personal AI free routing**, but that creates a new explicit user choice.

---

## 7. Conversation ownership

Personal AI remains the durable thread owner.

Store per turn:

- user message;
- accepted assistant response;
- provider;
- model;
- application/workspace/thread IDs;
- provenance/context summary according to existing policy;
- completion/failure metadata where useful.

Do not assume OpenAI-hosted persistent conversation state for ChatGPT-plan HTTP requests. Build bounded history from Personal AI's thread for each turn.

This also permits an explicit provider switch within a Personal AI thread while preserving exactly which provider generated every answer.

---

## 8. Context-package contract

Conceptual:

```json
{
  "application_id": "travel",
  "workspace_id": "trip-...",
  "conversation_id": "...",
  "request_id": "...",
  "prompt": "...",
  "conversation_history": [],
  "context_items": [],
  "effective_sensitivity": "...",
  "context_manifest": [],
  "domain_rules": [],
  "allowed_response_actions": ["copy"]
}
```

Every context item retains:

- source app/provider/ref;
- source class;
- authoritative vs inferred;
- sensitivity;
- retrieval timestamp/freshness;
- transformations.

The sidecar should show a human-readable context manifest rather than requiring the user to inspect raw JSON.

---

## 9. Shared AI sidecar UX

### Desktop/web

Prefer a right-side drawer so the user can inspect the underlying app while chatting.

Required elements:

- provider selector;
- ChatGPT account/model selector when connected;
- `Using ChatGPT plan` indicator;
- context summary/selector;
- conversation view;
- prompt composer;
- streaming state;
- Copy action;
- reconnect/manage-usage/switch-provider actions.

### Mobile

Prefer bottom-sheet to full-screen chat behavior.

Native mobile SIWC mechanics must be verified against current supported flows before storing credentials directly in the mobile client. This does not block the existing Health mobile roadmap; the ChatGPT sidecar can be enabled on supported clients independently.

### Response actions

#### Copy — initial universal action

Always safe from a domain-authority perspective.

#### Insert — limited

Only into explicitly non-authoritative draft/edit surfaces. Insertion is not equivalent to persisting domain truth.

#### Apply — later

Only after Phase 23 converts output to a typed mutation proposal, the domain validates it, and the user confirms where required.

---

## 10. Domain behavior

### Travel

Typical context:

- active trip/day;
- itinerary;
- lodging/transport/reservations;
- travel preferences/constraints;
- selected places/research evidence.

Example uses:

- fill an open afternoon;
- compare neighborhoods;
- critique an itinerary day;
- suggest food near current plans.

Initial action: Copy/draft.  
Later: user-confirmed itinerary mutation proposal.

### Shopping

Typical context:

- active shopping project;
- requirements/constraints/budget;
- selected/saved/rejected products;
- product evidence/comparison fields.

Example uses:

- compare selected products;
- explain tradeoffs;
- propose requirement changes;
- identify missing research.

Initial action: Copy/draft.  
Later: user-confirmed shortlist/requirement proposal.

### Finance

Start read-only.

Typical context:

- selected security/account/portfolio slice;
- investment policy/goals;
- research state;
- scenario assumptions;
- observed/calculated/assumed/AI-interpreted labels.

UX requirements:

- default to narrow selected scope;
- broader portfolio/account context is visible and explicitly includable;
- no trade/transaction execution through generic sidecar text.

### Health

Start read-only and most restrictive.

Typical selectable categories:

- current/today state;
- sleep/activity window;
- diet/nutrition;
- medications;
- conditions;
- allergies/restrictions;
- goals;
- labs/measurements where supported.

UX requirements:

- default to minimum necessary context;
- show sensitive included categories;
- allow narrowing before send where practical;
- never let generic model text directly alter medication/condition/clinical truth.

---

## 11. Privacy and policy

Explicit provider selection does not bypass Personal AI policy.

Before a ChatGPT request:

1. authenticate the Personal AI user;
2. authorize the origin app/workspace;
3. authorize each requested context class/field;
4. apply cross-app policy;
5. compute effective sensitivity;
6. apply ChatGPT-provider sensitivity policy;
7. present/narrow context where required;
8. send only the bounded package.

The user's ChatGPT account does not automatically become a trusted destination for every Personal AI field merely because the user connected it.

---

## 12. Usage and errors

Maintain separate state from the strict-free quota ledger:

```text
connection:
  connected | disconnected | reauth_required | unavailable

usage:
  available | limit_reached | unavailable | unknown
```

Handle at least:

- consent declined / plan-use scope missing;
- selected user/workspace not eligible;
- token expired/revoked;
- bridge unavailable;
- selected model unavailable;
- plan/app usage limit reached;
- usage status unavailable;
- Responses stream failed/incomplete/interrupted.

Do not fabricate remaining quota or reset time.

Do not silently switch to:

- OpenAI API-key billing;
- ChatGPT credits;
- another ChatGPT account;
- Gemini/Groq/Cloudflare.

An explicit user action may choose another supported route.

---

## 13. Observability and persistence

Safe cloud metadata may include:

- `provider=openai_chatgpt_plan`;
- model slug/display label;
- route mode;
- app/workspace/request/thread IDs;
- latency/result/error class;
- redacted context manifest/sensitivity;
- token counts if reliably returned.

Never retain in cloud observability:

- access/refresh/ID tokens;
- Authorization headers;
- PKCE verifier/state/nonce after auth;
- raw credential files;
- sensitive authorization URLs;
- unnecessary account identifiers.

Sensitive Finance/Health detailed traces remain minimal/no-retention by default under the existing artifact policy.

---

## 14. Evaluation

Evaluate ChatGPT integration separately from automatic routing quality.

Measure:

- context relevance/omission;
- sensitive context leakage/over-fetch;
- provider attribution correctness;
- bridge availability/reconnect behavior;
- model-list refresh;
- auth/usage error recovery;
- incomplete-stream handling;
- Copy/Insert/Apply boundary correctness;
- token/credential absence from persistence/logging;
- Travel/Shopping/Finance/Health UX quality.

Optional ChatGPT model quality benchmarks may inform user-facing choices but must not automatically place ChatGPT into the strict-free router.

---

## 15. Implementation mapping

The original substantive roadmap is preserved. A single additive block is inserted after the existing Phase 16 substrate:

- **Phase 17 — ChatGPT account integration and AI sidecar**
  - **17.1 Authentication and local bridge**
  - **17.2 Provider/runtime integration, policy, and usage handling**
  - **17.3 Shared AI sidecar UI**
  - **17.4 Domain integration contract**

The original domain phases are renumbered but retain their scope:

- Travel: **Phase 18**
- Shopping: **Phase 19**
- Finance: **Phase 20**
- Health: **Phase 21**
- Cross-app federation: **Phase 22**
- Mutation proposal framework: **Phase 23**
- Existing optimization/adaptive-routing phases: **24-27**
- Integrated evaluation and hardening: **Phase 28**

The domain phases gain sidecar-specific tasks without removing any original tasks. Phase 22 keeps cross-app context visible/auditable in sidecar requests; Phase 23 gates Apply actions through typed mutation proposals; Phase 28 adds bridge/auth/usage/context/action-boundary hardening.

---

## 16. Acceptance criteria

The additive ChatGPT integration is complete when:

- existing Gemini/Groq/Cloudflare strict-free routing still satisfies all original acceptance criteria;
- ChatGPT plan use requires explicit user authorization and provider selection;
- no reusable ChatGPT credential is stored in managed Personal AI cloud persistence or browser storage;
- account-specific model discovery works;
- completed ChatGPT turns are represented in Personal AI conversations with provider/model attribution;
- context sent to ChatGPT is bounded, policy-authorized, and inspectable;
- Travel and Shopping sidecars work with relevant scoped context;
- Finance and Health sidecars apply stricter context minimization/selection;
- Copy works universally;
- Insert cannot silently create authoritative state;
- Apply uses typed mutation proposal + domain validation + confirmation;
- limit/revocation/model/bridge failures are explicit and never silently change billing/provider mode.

---

## 17. External operational references

Re-verify at implementation/release time:

- `https://developers.openai.com/siwc/`
- `https://developers.openai.com/siwc/token-sharing-open-source`
- `https://developers.openai.com/siwc/token-sharing-open-source/sign-in`
- `https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions`
- `https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference`
- `https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations`
- `https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery`
- `https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms`
- `https://openai.com/policies/sign-in-with-chatgpt-terms/`
