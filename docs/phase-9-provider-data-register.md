# Phase 9 provider-data register

**Status:** policy gates and configuration are implemented; provider contract
and account-specific retention review remains open. **Date:** 2026-10-03.

| Provider / path | Data sent | Retention/training/residency evidence | Default / gate |
| --- | --- | --- | --- |
| Gemini chat and context summaries | Active conversation context, current user message, and summary inputs | Not verified for the intended Google project, account, region, or selected model. Review the provider contract and project data controls before real personal data. | `AI_PROVIDER=gemini` is required by the GCP bootstrap, but real chat is inaccessible until authenticated; production remains blocked pending policy review. |
| Gemini memory extraction/embeddings | Completed assistant turn or selected memory text and embedding inputs | Not independently verified; memory remains disabled by default | `MEMORY_ENABLED=false`, extraction false |
| Brave Search | Research question/query terms and result retrieval request | Existing Phase 5 provider policy approval is still required; no account-specific retention review recorded here | Search adapter defaults to fake; research disabled |
| Nominatim / OpenStreetMap | Place-search terms, result count, configured contact/user-agent | Existing Phase 7 provider policy approval, contact identity, and request interval remain required | Travel disabled; adapter defaults to fake |
| Open Food Facts | Barcode/product lookup and configured user-agent | Existing Phase 7 policy gate and source-use review remain required | Shopping disabled; adapter defaults to fake |
| Google OIDC | Authentication request and account identity claims | Google identity is used only to verify the exact configured personal account; application logs and storage do not retain the ID token | Exact audience, verified Gmail or verified Workspace domain claim, and one-email allowlist are required |

No real-provider call is used as evidence for a completed test. Before enabling
an adapter, record the provider policy version, permitted purposes, retention,
training, residency, deletion limitations, and responsible operator in this
register and the feature guide. `EXTERNAL_PROVIDERS_KILL_SWITCH_ENABLED` blocks
provider-backed API operations before their provider work begins.
