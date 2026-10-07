# Development instructions

This repository is a personal learning and research project for building a reusable AI substrate around chat, context, memory, retrieval, evidence, and evaluation. Read [the documentation router](docs/README.md) for task-specific context and [current state](docs/current-state.md) for the implemented boundary; do not treat future plans as evidence of delivery.

## Authority and scope

When sources disagree, use this order: (1) code, executable contracts, migrations, and tests; (2) release/review/verification evidence; (3) accepted ADRs; (4) architecture and product intent; (5) active plans, which authorize sequencing but do not prove delivery; (6) historical documents. Security and privacy constraints take precedence. Chapter 2 documents describe future work unless current code and evidence show it has been implemented.

Before editing, inspect `git status` and preserve existing user changes. Keep this file durable; update it only when operating rules or authority boundaries change. Update status/evidence docs when behavior or verification changes, and record date, tested revision, checks, results, and remaining gaps when acceptance evidence changes. Keep one living implementation status in `docs/current-state.md`. Do not expand product scope merely because a later plan exists.

## Durable boundaries

- Keep routes and UI thin. Services and domain modules own behavior; browser calls use the Next.js API proxy.
- Keep provider SDKs inside `backend/src/personal_ai/llm` and provider adapters. Services depend on neutral contracts.
- Route every model turn through the shared token-budgeted context assembler.
- Treat summaries as lossy, branch-scoped working context, not long-term memory.
- Preserve parent/supersedes links and superseded messages. Regenerate and edit/retry use only the active branch as model context.
- Keep durable user memory separate from time-sensitive external evidence. Preserve source, observation time, and freshness; enforce hard constraints in code before preference ranking.
- Domain applications own their authoritative records, rules, and rich UI. Shared modules provide reusable AI-side capabilities.
- Keep experiments gated until evaluated against a baseline. Fakes and offline checks do not establish provider, emulator, cloud, deployment, or production-security behavior.

## Identity and data handling

The fixed `local` owner is only a local/test development identity. Deployed requests require verified Google user/service identity and private API invocation; local code does not establish readiness for personal data. Do not commit credentials, personal chats, or private data. Keep credentials in untracked environment files or Secret Manager.

## Task routing and checks

| Task | Start here |
| --- | --- |
| Any implementation or documentation task | [docs/README.md](docs/README.md), then its task-specific route |
| Current architecture or release readiness | [docs/current-state.md](docs/current-state.md) |
| Local setup and developer commands | [README.md](README.md) and `Makefile` |

Follow the root README for setup. Run the existing checks relevant to changed code; use the Makefile for backend/frontend tests, lint, type checks, evaluations, and builds. Keep provider/emulator checks opt-in; do not make offline tests require an unavailable manual environment. For documentation-only changes, review links/content and run `git diff --check`. Never report cloud, emulator, or provider checks as passed based on fakes.
