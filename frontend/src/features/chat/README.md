# Chat feature

`chat-state.ts` owns reconciliation of the visible conversation branch. The
`app/page.tsx` client coordinates navigation, streaming, and composition through
the API client; backend services own durable branch state and model behavior.

Component and API regression tests live separately under `frontend/tests`.
