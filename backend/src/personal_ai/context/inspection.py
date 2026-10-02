"""Read-only selection metadata; inspection never invokes a provider."""

from collections.abc import Sequence
from dataclasses import asdict

from personal_ai.context.assembler import ContextAssembler
from personal_ai.context.contracts import BudgetReport, ContextError, ConversationSummaryRepository
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.entities import Message
from personal_ai.llm.client import ChatMessage
from personal_ai.settings import Settings


class ContextInspector:
    def __init__(self, settings: Settings, summaries: ConversationSummaryRepository) -> None:
        self.settings = settings
        self.summaries = summaries

    def inspect(self, active: Sequence[Message], retrieval=None) -> dict:
        report = {
            "counter_kind": "estimated",
            "selected": [],
            "excluded": [],
            "summary": None,
            "budget": None,
            "overflow": None,
            "diagnostics": [],
        }
        users = [
            i
            for i, m in enumerate(active)
            if m.role.value == "user" and m.status.value == "completed"
        ]
        if not users:
            return report
        index = users[-1]
        pending = active[index]
        counter = EstimatedTokenCounter()
        assembler = ContextAssembler(self.settings, counter, self.summaries)

        def metadata(message: Message) -> dict:
            return {
                "id": str(message.id),
                "role": message.role.value,
                "created_at": message.created_at.isoformat(),
                "characters": len(message.content),
            }

        try:
            result = assembler.assemble(active[:index], pending, refresh=False, retrieval=retrieval)
        except ContextError as error:
            count = counter.count((ChatMessage(pending.role, pending.content),))
            report.update(
                {
                    "overflow": error.code,
                    "budget": asdict(
                        BudgetReport(
                            self.settings.max_context_tokens,
                            self.settings.max_response_tokens,
                            self.settings.context_safety_margin_tokens,
                            assembler.input_budget(),
                            count.tokens,
                            0,
                            0,
                            count.tokens,
                            "estimated",
                        )
                    ),
                    "excluded": [{**metadata(m), "reason": "mandatory_overflow"} for m in active],
                }
            )
            return report
        if retrieval is not None:
            selected_memories = set(result.selected_memory_ids)
            exclusions = dict(result.excluded_memories)
            lifecycle_metadata = dict(retrieval.inspection_metadata)
            scores = {score.memory_id: score for score in retrieval.scores}
            report["memory"] = {
                "mode": "supplied-record fit estimate; no semantic query or prior-use claim",
                "tokens": result.memory_tokens,
                "diagnostics": retrieval.diagnostics,
                "requested_variant": retrieval.requested_variant,
                "applied_variant": retrieval.applied_variant,
                "policy_version": retrieval.policy_version,
                "policy_identity": retrieval.policy_identity,
                "lifecycle_event_ids": [str(item) for item in retrieval.lifecycle_event_ids],
                "records": [{
                    "id": str(s.memory.id), "type": s.memory.memory_type,
                    "source_conversation_id": (
                        str(s.memory.source_conversation_id)
                        if hasattr(s.memory, "source_conversation_id") else None
                    ),
                    "source_message_ids": [
                        str(i) for i in getattr(s.memory, "source_message_ids", ())
                    ],
                    "effective_at": s.memory.effective_at.isoformat(),
                    "created_at": s.memory.created_at.isoformat(),
                    "selected": s.memory.id in selected_memories,
                    "selection_kind": "fit_estimate",
                    "reason": exclusions.get(s.memory.id),
                    "similarity": None,
                    "score": scores[s.memory.id].score if s.memory.id in scores else None,
                    "score_reason": (
                        scores[s.memory.id].reason if s.memory.id in scores else None
                    ),
                    "score_components": ({
                        "importance": scores[s.memory.id].importance,
                        "recency": scores[s.memory.id].recency,
                        "frequency": scores[s.memory.id].frequency,
                        "confidence": scores[s.memory.id].confidence,
                    } if s.memory.id in scores else None),
                    **lifecycle_metadata.get(s.memory.id, {}),
                    "estimated_tokens": counter.count((ChatMessage("system", s.memory.content),)).tokens,
                } for s in retrieval.candidates],
            }
        selected = set(result.selected_message_ids)
        excluded = dict(result.excluded)
        summary = result.summary
        report.update(
            {
                "budget": asdict(result.budget),
                "selected": [metadata(m) for m in active if m.id in selected],
                "excluded": [
                    {**metadata(m), "reason": excluded.get(m.id, "after_latest_user")}
                    for m in active
                    if m.id not in selected
                ],
                "summary": {
                    "id": str(summary.id),
                    "source_message_ids": [str(i) for i in summary.source_message_ids],
                    "coverage_message_ids": [
                        str(i) for i in (summary.coverage_message_ids or summary.source_message_ids)
                    ],
                    "skipped_message_ids": [
                        str(i) for i in summary.coverage_message_ids
                        if i not in summary.source_message_ids
                    ],
                    "coverage_fingerprint": summary.coverage_fingerprint,
                    "source_fingerprint": summary.source_fingerprint,
                    "covers_through_message_id": str(summary.covers_through_message_id),
                    "summary_token_count": summary.summary_token_count,
                    "source_token_count": summary.source_token_count,
                    "counter_kind": summary.counter_kind,
                }
                if summary
                else None,
                "diagnostics": result.diagnostics,
            }
        )
        return report
