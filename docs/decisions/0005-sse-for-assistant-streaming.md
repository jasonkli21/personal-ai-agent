# ADR 0005: Use server-sent events for browser-facing streaming

- Status: accepted
- Date: 2026-08-19

## Context

The browser must receive incremental assistant output during chat completion. Phase 1 needs a simple, one-way server-to-browser transport that fits ordinary HTTP infrastructure.

## Decision

Use Server-Sent Events (SSE) for browser-facing assistant output. Do not use WebSockets in Phase 1.

## Consequences

- The API exposes a documented SSE event format and the frontend consumes incremental events over HTTP.
- Streaming failures can be represented in the same response stream and persisted through the message lifecycle.
- Bidirectional real-time protocols and their connection-management concerns remain out of scope until a future requirement justifies them.
