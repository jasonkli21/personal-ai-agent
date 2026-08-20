# ADR 0001: Use Gemini behind an internal LLM client boundary

- Status: accepted
- Date: 2026-08-19

## Context

Phase 1 needs hosted model inference, while the project must retain the ability to replace a provider without changing its application behavior. A fixed model identifier in source would make routine configuration changes unnecessarily invasive.

## Decision

Use the Google Gen AI Python SDK for the initial Gemini chat adapter. Select the Gemini model at runtime from `AI_MODEL`; do not hard-code a model ID. Application code outside the adapter depends only on an internal `LLMClient` protocol.

The provider is acceptable only for non-sensitive development content after the account's applicable data-use, retention, regional, billing, and access settings have been reviewed. It is not approved for real sensitive personal data yet: the current app has no authentication or deliberate provider-data policy.

## Consequences

- Provider-specific SDK calls and credentials stay within the LLM adapter.
- Tests can substitute a fake `LLMClient` and require neither a key nor network access.
- Deployments must set `AI_MODEL` and supply credentials through approved configuration; model changes do not require source edits.
- Before entering real personal data, the account and provider terms must be re-reviewed and the product security boundary improved.
