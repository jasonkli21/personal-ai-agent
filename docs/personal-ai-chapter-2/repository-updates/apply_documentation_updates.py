#!/usr/bin/env python3
"""Apply Chapter 2 documentation link/status corrections to a personal-ai-system checkout.

Run from the repository root after copying this chapter to docs/personal-ai-chapter-2.
The script intentionally does not change root README architecture: Phase 10 does that
only after the persistence migration is implemented.
"""
from pathlib import Path

root=Path.cwd()
if not (root/'docs').is_dir() or not (root/'README.md').exists():
    raise SystemExit('Run from personal-ai-system repository root')

OLD='personal-ai-next-scope-chatgpt-integrated-v2/'
NEW='personal-ai-chapter-2/'

living=['docs/project-brief.md','docs/architecture.md','docs/implementation-plan.md','docs/gcp-deployment.md']
for rel in living:
    p=root/rel
    text=p.read_text()
    text=text.replace(OLD,NEW)
    text=text.replace('## Reconciled next-scope handoff — 2026-10-05',
                      '## Chapter 2 next-scope handoff — 2026-10-06')
    text=text.replace('[comprehensive Phase 0 reconciliation]',
                      '[Chapter 2 Phase 0 reconciliation]')
    text=text.replace('verifies the additive application/context, provider/routing, Firestore/GCS and ChatGPT/domain handoff against revision `ad1dea5912af81eda0c9c5d6a41180ce186a07a5`.',
                      'records the original Phase 0 review against code revision `ad1dea5912af81eda0c9c5d6a41180ce186a07a5` and the 2026-10-06 amendment that adds Phase 10 to migrate planned persistence from Firestore to DynamoDB + Neon Postgres/pgvector.')
    # Current roadmap terminology/numbers after the 2026-10-06 regeneration.
    text=text.replace('Its next-scope Phases 0–28 are separate from the existing implementation history.',
                      'Chapter 2 remains separate from the original repository phase history: next-scope Phases 0–2 are complete, Phase 10 is next, and former next-scope Phases 3–28 are preserved under the chapter numbering map.')
    text=text.replace('. Phase 0 changes documentation only; next-scope Phase 1 has not been implemented.', '')
    text=text.replace('next-scope Phase 8 must route it through shared preparation',
                      'Chapter 2 Phase 16 must route it through shared preparation')
    text=text.replace('Next-scope provider preflight (Phase 9), bounded ledger retention (11), artifact provisioning (12) and integrated release closeout (28) must resolve and verify this conflict before claiming strict-free cloud readiness.',
                      'Chapter 2 Phase 10 must remove the Firestore/TTL dependency during persistence migration; provider adapters and eligibility (17–18), bounded ledger retention (19), artifact provisioning (20), and integrated release closeout (36) must then verify strict-free cloud readiness.')
    p.write_text(text)

# Historical records: retain old paragraph semantics, add explicit current mapping.
hist_updates={
    'docs/phase-9-implementation-evidence.md': '''\n\n## Chapter 2 supersession note — 2026-10-06\n\nThe former next-scope planning package has been superseded by [Personal AI Chapter 2](personal-ai-chapter-2/README.md). The historical 2026-10-05 statement is retained as evidence of the plan at that time. In the current numbering, former Phase 11 ledger work is Phase 19, former Phase 12 artifact work is Phase 20, and former Phase 28 integrated closeout is Phase 36. New Phase 10 first owns the Firestore → DynamoDB/Neon Postgres migration, including removal of the strict-$0-incompatible Firestore TTL dependency from the normal target runtime.\n''',
'docs/decisions/0006-context-token-budget.md': '''\n\n## Chapter 2 numbering/storage amendment — 2026-10-06\n\nThe current forward-looking plan is [Personal AI Chapter 2](../personal-ai-chapter-2/README.md). The 2026-10-05 extension paragraph above is historical; its former next-scope Phase 8 is now Chapter 2 Phase 16. Phase 10 first migrates durable persistence to DynamoDB + Neon Postgres/pgvector. The accepted token-budget/counting guarantee itself is unchanged by this renumbering/storage amendment.\n'''
}
for rel,addition in hist_updates.items():
    p=root/rel; text=p.read_text()
    # Avoid a broken old-package link while preserving historical wording.
    text=text.replace(OLD,NEW)
    heading=addition.splitlines()[2]
    if heading not in text:
        text=text.rstrip()+addition
    p.write_text(text)

print('Documentation updates applied. Review git diff before committing.')
