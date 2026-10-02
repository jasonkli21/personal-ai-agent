# Research feature

The gated `/research` page delegates to `app/research/research-panel.tsx` and the
bounded `lib/research-api.ts` SSE client. Browser calls use Next.js research
proxies with shared cancellation propagation. Backend services own research
behavior. See `docs/phase-5-implementation-guide.md` for contracts and limits.
