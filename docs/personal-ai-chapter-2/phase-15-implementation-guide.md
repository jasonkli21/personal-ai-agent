# Phase 15 implementation guide — Permissions and sensitivity policy

Phase 15 adds the locally enforceable part of the server-owned context policy.
It is **partial**: code-defined policy versions are not immutable Postgres
references, cross-app grants remain disabled, and revocation dependencies do not
yet travel through every derived-context surface. The [implementation evidence](phase-15-implementation-evidence.md)
records the exact tested tree and remaining gates.

## Runtime contracts

- [`applications/contracts.py`](../../backend/src/personal_ai/applications/contracts.py)
  defines `ApplicationContextPolicy`, provider/operation declarations, and
  field-level sensitivity, source-access, and model-disclosure decisions. A
  policy has a version label, denies unknown sensitivity, defaults to denying
  cross-application context, and caps model disclosure. Shared adapters have
  explicit bounded field rules. Unlisted providers or fields are denied.
- [`applications/registry.py`](../../backend/src/personal_ai/applications/registry.py)
  declares the initial application policies. Finance and Health use the same
  typed configuration path as Travel and Shopping. Their restricted fields
  (for example, payment/tax identifiers and diagnoses) are denied before a
  provider call; Health context has no policy entry in other applications.
  Capability registration continues to describe availability and never grants
  disclosure permission by itself.
- [`context/authorization.py`](../../backend/src/personal_ai/context/authorization.py)
  evaluates the complete selection set against the authenticated application
  scope before source factories run. It joins the server classification with
  provider labels and rejects unknown, mismatched, or over-ceiling sensitivity.
- [`context/assembler.py`](../../backend/src/personal_ai/context/assembler.py)
  applies policy before memory retrieval is invoked by chat, and checks baseline
  disclosure before summary lookup/refresh or token counting. It checks the
  sensitivity join before counting model input and records the policy version
  label on the build manifest.
- [`context/providers.py`](../../backend/src/personal_ai/context/providers.py)
  repeats whole-plan policy checks before provider construction and source
  access, then applies item checks before the result can reach model-input
  construction. Existing permission dependencies remain attached to typed
  context items and are revalidated by the builder before injection.
- [`llm/client.py`](../../backend/src/personal_ai/llm/client.py) defines the
  provider-neutral `InferenceContext`. [`services/chat_turns.py`](../../backend/src/personal_ai/services/chat_turns.py)
  passes the assembled effective sensitivity, policy ceiling, and policy version
  to the inference client. [`llm/gemini.py`](../../backend/src/personal_ai/llm/gemini.py)
  validates that envelope before generation; it is internal control metadata and
  is not sent as provider prompt content.
- [`test_context_authorization.py`](../../backend/tests/test_context_authorization.py)
  covers preflight denial before source, summary, or counting work, item-level
  sensitivity joining, and the inference envelope. The context-plan baseline
  carries the declared policies for its synthetic applications.

The API supplies `RequestScope` from its server-side authentication/application
resolution path. Client labels do not become policy facts. Current source access
continues to require matching owner/application/workspace scope and the provider
contract. `ContextPermissionDependency` carries a permission ID, version,
purpose, and optional source/destination application IDs for future revocable
grants; no grant is enabled by these fields.

## Scope limits

- Cross-app sharing remains hard denied. No user-facing permission UI or live
  domain provider was added.
- Policy versions are code labels. Phase 14's unresolved immutable Postgres
  policy/source-version reference contract remains open; the Phase 15 trace
  label does not close it.
- Profile and memory item permissions are rechecked before injection, but
  conversation messages and summaries do not yet carry source grant dependencies
  end-to-end. Revocation through all history, summaries, caches, traces, exports,
  and artifacts is not complete.
- The local policy does not prove deployed application/workspace membership,
  provider data-use/retention behavior, cloud IAM, or production security.
  Synthetic providers and offline tests establish only the stated local code
  contracts; no regulatory-readiness claim follows.
- The root README was reviewed. No README edit was needed because this phase
  changes server-side policy enforcement without changing setup, user-visible
  capabilities, provider support, or deployment behavior.
