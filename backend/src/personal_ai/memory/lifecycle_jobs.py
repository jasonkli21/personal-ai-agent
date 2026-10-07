"""Durable job creation, Pub/Sub notification, post-turn accounting, and worker logic."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Literal
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud import pubsub_v1
from pydantic import ConfigDict

from personal_ai.auth.scope import (
    ApplicationScope,
    ApplicationScopedRecord,
    application_scope_context,
)
from personal_ai.llm.errors import LLMError
from personal_ai.memory.contracts import Memory
from personal_ai.memory.deadlines import lifecycle_deadline, rpc_timeout
from personal_ai.memory.lifecycle import MemoryJob, ScorePolicy
from personal_ai.memory.lifecycle_policy import (
    CONTRADICTION_POLICY_VERSION,
    DERIVATION_POLICY_VERSION,
    FORGETTING_POLICY_VERSION,
    DeterministicMemoryConsolidator,
    contradiction_decision,
    forgetting_decision,
    make_event,
)
from personal_ai.memory.lifecycle_repositories import job_idempotency_id
from personal_ai.storage.errors import ResourceNotFoundError, StorageError

logger = logging.getLogger(__name__)


class MemoryJobNotification(ApplicationScopedRecord):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: UUID
    scope_version: Literal[2] = 2
    schema_version: Literal[1] = 1


class PubSubMemoryJobPublisher:
    """Publish only an opaque durable job ID and schema version."""

    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client

    def publish(self, job: MemoryJob, *, timeout: float = 10):
        project = self.settings.gcp_project_id
        if not project:
            raise ValueError("memory_lifecycle_project_missing")
        # A worker delivery often has nothing to publish. Construct an owned
        # publisher only for actual notification work and always release it.
        client = self.client or pubsub_v1.PublisherClient()
        try:
            topic = client.topic_path(project, self.settings.memory_lifecycle_topic)
            payload = MemoryJobNotification(
                job_id=job.id,
                application_id=job.application_id,
                workspace_id=job.workspace_id,
            ).model_dump_json().encode()
            client.publish(topic, payload, retry=None, timeout=timeout).result(timeout=timeout)
        finally:
            if self.client is None:
                try:
                    client.stop()
                except Exception as error:  # noqa: BLE001 - preserve the publication result
                    logger.info("Memory publisher cleanup failed error_class=%s", type(error).__name__)
                finally:
                    try:
                        client.transport.close()
                    except Exception as error:  # noqa: BLE001 - preserve the publication result
                        logger.info(
                            "Memory publisher transport cleanup failed error_class=%s",
                            type(error).__name__,
                        )


class MemoryLifecycleCoordinator:
    """Runs optional work after terminal SSE send; all failures remain non-fatal."""

    def __init__(self, settings, lifecycle, memories, *, extraction=None, publisher=None):
        self.settings, self.lifecycle, self.memories = settings, lifecycle, memories
        self.extraction = extraction
        self.publisher = publisher

    def after_completed(self, completed, selected_memory_ids=()):
        # Discovery/accounting can perform several bounded RPCs per candidate.
        # Their combined work also needs a ceiling, beyond individual RPC limits.
        with lifecycle_deadline(self.settings.memory_job_execution_seconds):
            self._after_completed(completed, selected_memory_ids)

    def _after_completed(self, completed, selected_memory_ids):
        extraction_result = None
        if self.extraction is not None:
            try:
                extraction_result = self.extraction.run(completed)
            except Exception as error:  # noqa: BLE001 - post-turn memory is optional
                logger.info("Memory extraction failed error_class=%s", type(error).__name__)
        if self.settings.memory_enabled and self.settings.memory_lifecycle_worker_enabled:
            for memory_id in dict.fromkeys(selected_memory_ids):
                self._record_injected(completed, memory_id)
            created = tuple(getattr(extraction_result, "created", ()))
            queued = set()
            for memory_id in created:
                try:
                    related = self.lifecycle.discover_related(
                        owner_id=completed.owner_id,
                        memory_id=memory_id,
                        limit=self.settings.memory_consolidation_max_sources,
                    )
                    candidates = tuple(sorted(set(related), key=str))
                    if self.settings.memory_consolidation_enabled and len(candidates) >= 2:
                        queued.add(("consolidation", candidates))
                except Exception as error:  # noqa: BLE001 - discovery is bounded optional work
                    logger.info(
                        "Memory candidate discovery failed error_class=%s", type(error).__name__
                    )
            maintenance_candidates = []
            if self.settings.memory_contradiction_automation_enabled:
                try:
                    maintenance_candidates.extend(
                        self.lifecycle.discover_maintenance_candidates(
                            owner_id=completed.owner_id,
                            limit=self.settings.memory_consolidation_max_sources,
                        )
                    )
                except Exception as error:  # noqa: BLE001 - discovery failure cannot affect chat
                    logger.info(
                        "Memory contradiction discovery failed error_class=%s", type(error).__name__
                    )
            if self.settings.memory_forgetting_enabled:
                try:
                    maintenance_candidates.extend(
                        self.lifecycle.discover_forgetting_candidates(
                            owner_id=completed.owner_id,
                            older_than=completed.created_at - timedelta(days=365),
                            limit=self.settings.memory_consolidation_max_sources,
                        )
                    )
                except Exception as error:  # noqa: BLE001 - discovery failure cannot affect chat
                    logger.info(
                        "Memory forgetting discovery failed error_class=%s", type(error).__name__
                    )
            if maintenance_candidates:
                candidates = tuple(dict.fromkeys(maintenance_candidates))[
                    : self.settings.memory_consolidation_max_sources
                ]
                queued.add(("maintenance", tuple(sorted(candidates, key=str))))
            for job_type, candidate_ids in sorted(
                queued, key=lambda item: (item[0], tuple(map(str, item[1])))
            ):
                self._enqueue(completed, job_type, candidate_ids)

    def _record_injected(self, completed, memory_id: UUID):
        try:
            key = f"retrieved:{completed.owner_id}:{completed.id}:{memory_id}"
            old = self.lifecycle.find_event(
                owner_id=completed.owner_id, memory_id=memory_id, idempotency_key=key
            )
            if old:
                return
            state = self.lifecycle.get_state(owner_id=completed.owner_id, memory_id=memory_id)
            event = make_event(
                owner_id=completed.owner_id,
                memory_id=memory_id,
                event_type="retrieved",
                reason_code="injected_into_completed_turn",
                policy_version=self.settings.memory_scoring_policy_version,
                idempotency_key=key,
                expected_state_version=state.state_version,
                occurred_at=completed.created_at,
            )
            self.lifecycle.apply_event(
                event, completed_assistant_id=completed.id,
                completed_assistant_conversation_id=completed.conversation_id,
            )
        except Exception as error:  # noqa: BLE001 - frequency is advisory
            logger.info("Memory retrieval accounting failed error_class=%s", type(error).__name__)

    def _enqueue(self, completed, job_type, candidate_ids):
        now = completed.created_at.astimezone(UTC)
        candidate_ids = tuple(sorted(set(candidate_ids), key=str))[:4]
        if not candidate_ids:
            return
        key = f"{job_type}:{completed.owner_id}:{completed.id}:" + ",".join(map(str, candidate_ids))
        policy = self._policy_snapshot()
        job = MemoryJob(
            id=job_idempotency_id(key),
            owner_id=completed.owner_id,
            job_type=job_type,
            candidate_memory_ids=candidate_ids,
            policy_version=self.settings.memory_scoring_policy_version,
            policy_snapshot=policy,
            max_attempts=self.settings.memory_job_max_attempts,
            idempotency_key=key,
            created_at=now,
            updated_at=now,
        )
        try:
            persisted, _ = self.lifecycle.create_job(job)
            self._publish(persisted)
        except Exception as error:  # noqa: BLE001 - durable job creation failure is best effort
            logger.info("Memory job enqueue failed error_class=%s", type(error).__name__)

    def _policy_snapshot(self):
        score = ScorePolicy(
            version=self.settings.memory_scoring_policy_version,
            similarity_weight=self.settings.memory_score_similarity_weight,
            importance_weight=self.settings.memory_score_importance_weight,
            recency_weight=self.settings.memory_score_recency_weight,
            frequency_weight=self.settings.memory_score_frequency_weight,
            confidence_weight=self.settings.memory_score_confidence_weight,
            half_life_days=self.settings.memory_recency_half_life_days,
        )
        return {
            "score_policy_identity": score.identity,
            "score_policy_version": score.version,
            "derivation_policy_version": DERIVATION_POLICY_VERSION,
            "contradiction_policy_version": CONTRADICTION_POLICY_VERSION,
            "forgetting_policy_version": FORGETTING_POLICY_VERSION,
            "similarity_weight": score.similarity_weight,
            "importance_weight": score.importance_weight,
            "recency_weight": score.recency_weight,
            "frequency_weight": score.frequency_weight,
            "confidence_weight": score.confidence_weight,
            "half_life_days": score.half_life_days,
        }

    def _publish(self, job):
        if self.publisher is None:
            return
        scope = ApplicationScope(
            application_id=job.application_id,
            workspace_id=job.workspace_id,
        )
        with application_scope_context(scope):
            self.publisher.publish(job, timeout=rpc_timeout())
            self.lifecycle.mark_published(
                owner_id=job.owner_id, job_id=job.id, updated_at=job.updated_at
            )

    def republish_pending(self, *, limit: int = 50, owner_id: str | None = None):
        if (
            not self.settings.memory_enabled
            or not self.settings.memory_lifecycle_worker_enabled
        ):
            return 0
        with lifecycle_deadline(self.settings.memory_job_execution_seconds):
            recover = getattr(self.memories, "recover_pending_effects", None)
            if recover is not None:
                if owner_id is None:
                    raise RuntimeError("memory_effect_recovery_owner_required")
                recover(owner_id=owner_id, limit=limit)
            if self.publisher is None:
                return 0
            return self._republish_pending(limit=limit)

    def _republish_pending(self, *, limit):
        jobs = self.lifecycle.pending_for_publish(now=datetime.now(UTC), limit=limit)
        published = 0
        for job in jobs:
            self._publish(job)
            published += 1
        return published


class MemoryLifecycleWorker:
    """Bounded processor that derives all authority from durable job/source state."""

    def __init__(
        self, settings, lifecycle, memories, messages, embedder, *, clock=None, consolidator=None
    ):
        self.settings, self.lifecycle, self.memories, self.messages = (
            settings,
            lifecycle,
            memories,
            messages,
        )
        self.embedder = embedder
        self.clock = clock or (lambda: datetime.now(UTC))
        self.consolidator = consolidator or DeterministicMemoryConsolidator()

    def process(
        self,
        job_id: UUID,
        *,
        application_id: str = "personal_ai",
        workspace_id: str | None = None,
    ) -> Literal["completed", "busy", "retry", "disabled"]:
        scope = ApplicationScope(application_id=application_id, workspace_id=workspace_id)
        with application_scope_context(scope), lifecycle_deadline(
            self.settings.memory_job_execution_seconds
        ):
            return self._process(job_id)

    def _process(self, job_id):
        if not self.settings.memory_enabled or not self.settings.memory_lifecycle_worker_enabled:
            return "disabled"
        job = self.lifecycle.get_job_by_id(job_id=job_id)
        now = self.clock().astimezone(UTC)
        claimed = self.lifecycle.claim_job(
            owner_id=job.owner_id,
            job_id=job_id,
            now=now,
            lease_seconds=self.settings.memory_job_lease_seconds,
        )
        if claimed is None:
            current = self.lifecycle.get_job_by_id(job_id=job_id)
            return "completed" if current.status in ("completed", "terminal") else "busy"
        token = claimed.lease_token
        assert token is not None
        deadline = monotonic() + self.settings.memory_job_execution_seconds
        try:
            versions = {
                "derivation_policy_version": DERIVATION_POLICY_VERSION,
                "contradiction_policy_version": CONTRADICTION_POLICY_VERSION,
                "forgetting_policy_version": FORGETTING_POLICY_VERSION,
            }
            if any(
                claimed.policy_snapshot.get(key, expected) != expected
                for key, expected in versions.items()
            ):
                raise ValueError("unsupported_job_policy")
            if claimed.policy_version != "score-v1":
                raise ValueError("unsupported_job_policy")
            if claimed.job_type == "consolidation":
                result = self._consolidate(claimed, token, deadline)
            else:
                result = self._maintenance(claimed, token, deadline)
            if result == "stale_lease":
                return "busy"
            if not self.lifecycle.complete_job(claimed, token=token, now=self.clock()):
                return "busy"
            return "completed"
        except TimeoutError:
            self.lifecycle.fail_job(
                claimed, token=token, now=self.clock(), reason="execution_timeout", retryable=True
            )
            return "retry"
        except (OSError, RuntimeError, StorageError, LLMError, GoogleAPICallError, RetryError):
            self.lifecycle.fail_job(
                claimed,
                token=token,
                now=self.clock(),
                reason="dependency_unavailable",
                retryable=True,
            )
            return "retry"
        except (ValueError, TypeError):
            self.lifecycle.fail_job(
                claimed,
                token=token,
                now=self.clock(),
                reason="invalid_job_or_source",
                retryable=False,
            )
            return "completed"
        except Exception as error:  # noqa: BLE001 - unexpected worker faults are safely retryable
            logger.info("Memory job failed error_class=%s", type(error).__name__)
            self.lifecycle.fail_job(
                claimed, token=token, now=self.clock(), reason="processing_failed", retryable=True
            )
            return "retry"

    def _remaining(self, deadline):
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("memory_job_timeout")
        return remaining

    def _consolidate(self, job, token, deadline):
        if not self.settings.memory_consolidation_enabled:
            return "disabled"
        plan = self.consolidator.plan(
            owner_id=job.owner_id,
            source_ids=job.candidate_memory_ids,
            job=job,
            settings=self.settings,
            memories=self.memories,
            messages=self.messages,
            lifecycle=self.lifecycle,
            embedder=self.embedder,
            now=self.clock(),
            timeout=self._remaining(deadline),
        )
        if plan.derived is None:
            return plan.reason
        return self.lifecycle.commit_consolidation(
            job=job, token=token, derived=plan.derived, now=self.clock()
        )

    def _maintenance(self, job, token, deadline):
        records = []
        for memory_id in job.candidate_memory_ids:
            self._remaining(deadline)
            try:
                memory = self.memories.get(
                    owner_id=job.owner_id, memory_id=memory_id, timeout=self._remaining(deadline)
                )
            except ResourceNotFoundError:
                continue
            if isinstance(memory, Memory):
                records.append(memory)
        for first in records:
            for second in records:
                if first.id == second.id:
                    continue
                newer, older = (
                    (first, second) if first.effective_at > second.effective_at else (second, first)
                )
                decision = contradiction_decision(older, newer)
                if decision == "none":
                    continue
                if not self.settings.memory_contradiction_automation_enabled:
                    continue
                event_type = "superseded" if decision == "supersede" else "review_required"
                key = f"{job.id}:{event_type}:{older.id}:{newer.id}"
                if self.lifecycle.find_event(
                    owner_id=job.owner_id, memory_id=older.id, idempotency_key=key
                ):
                    return "replayed"
                state = self.lifecycle.get_state(owner_id=job.owner_id, memory_id=older.id)
                event = make_event(
                    owner_id=job.owner_id,
                    memory_id=older.id,
                    event_type=event_type,
                    reason_code="clear_newer_correction"
                    if decision == "supersede"
                    else "ambiguous_contradiction",
                    policy_version=CONTRADICTION_POLICY_VERSION,
                    idempotency_key=key,
                    expected_state_version=state.state_version,
                    occurred_at=self.clock(),
                    related_memory_ids=(newer.id,),
                    job_id=job.id,
                )
                outcome = self.lifecycle.apply_event(event, job=job, lease_token=token)
                if outcome.reason == "state_version_conflict":
                    raise RuntimeError("state_version_conflict")
                if outcome.reason == "stale_lease":
                    return "stale_lease"
                if outcome.status == "applied":
                    return "applied"
                if outcome.status == "replayed":
                    return "replayed"
        if self.settings.memory_forgetting_enabled:
            for memory in records:
                self._remaining(deadline)
                state = self.lifecycle.get_state(owner_id=job.owner_id, memory_id=memory.id)
                dependencies = self.lifecycle.dependencies(
                    owner_id=job.owner_id, memory_id=memory.id, limit=100
                )
                if len(dependencies) >= 100:
                    continue
                active_dependency = False
                complete = True
                for dependency_id in dependencies:
                    try:
                        dependency_state = self.lifecycle.get_state(
                            owner_id=job.owner_id, memory_id=dependency_id
                        )
                    except Exception:  # noqa: BLE001 - unknown dependency state protects source
                        complete = False
                        break
                    if dependency_state.retrieval_status == "active":
                        active_dependency = True
                        break
                decision = forgetting_decision(
                    memory,
                    state,
                    now=self.clock(),
                    dependencies=dependencies,
                    dependency_lookup_complete=complete,
                )
                if not decision.eligible or active_dependency:
                    continue
                key = f"{job.id}:forgotten:{memory.id}"
                if self.lifecycle.find_event(
                    owner_id=job.owner_id, memory_id=memory.id, idempotency_key=key
                ):
                    return "replayed"
                event = make_event(
                    owner_id=job.owner_id,
                    memory_id=memory.id,
                    event_type="forgotten",
                    reason_code=decision.reason,
                    policy_version=FORGETTING_POLICY_VERSION,
                    idempotency_key=key,
                    expected_state_version=state.state_version,
                    occurred_at=self.clock(),
                    job_id=job.id,
                )
                outcome = self.lifecycle.apply_event(event, job=job, lease_token=token)
                if outcome.reason == "state_version_conflict":
                    raise RuntimeError("state_version_conflict")
                if outcome.reason == "stale_lease":
                    return "stale_lease"
                if outcome.status in ("applied", "replayed"):
                    return outcome.status
        return "no_action"
