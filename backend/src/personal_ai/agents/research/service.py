"""One fenced, deadline-bounded research pass; no chat or memory writes."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from functools import partial
from time import monotonic
from uuid import uuid4

import anyio

from personal_ai.agents.research.contracts import ResearchError, ResearchSession, evolve
from personal_ai.evidence.contracts import AdapterAttempt, SearchQuery
from personal_ai.evidence.pipeline import extract_evidence, select_evidence, validate_synthesis
from personal_ai.search.contracts import SearchResult
from personal_ai.search.policy import DeterministicPlanner, SnippetExtractor, planned_queries


async def io_call(function, *args, **kwargs):
    # Shield thread work to completion before stream cleanup performs the next write.
    task = asyncio.create_task(anyio.to_thread.run_sync(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            await task
        raise


def event(name, **data):
    return (
        f"event: research.{name}\ndata: {json.dumps({'schema_version': 'research-v1', **data})}\n\n"
    )


class ResearchService:
    def __init__(
        self,
        settings,
        repository,
        adapter,
        context,
        llm,
        *,
        owner_id="local",
        clock=None,
        planner=None,
        extractor=None,
        reranker=None,
    ):
        self.settings, self.repository, self.adapter = settings, repository, adapter
        self.context, self.llm, self.owner_id = context, llm, owner_id
        self.clock = clock or (lambda: datetime.now(UTC))
        self.planner = planner or DeterministicPlanner()
        self.extractor = extractor or SnippetExtractor()
        self.reranker = reranker

    async def create(self, request):
        now = self.clock()
        session = ResearchSession(
            id=uuid4(),
            owner_id=self.owner_id,
            request=request,
            request_fingerprint=request.fingerprint(),
            state="pending",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(hours=24),
        )
        return self.view(await io_call(self.repository.create, session))

    def view(self, session):
        now = self.clock()
        if session.state == "running" and session.execution_deadline <= now:
            return evolve(
                session,
                state="failed",
                failure_code="execution_abandoned",
                answer=None,
                citations=(),
            )
        if session.state in {"completed", "pending", "insufficient", "failed"} and session.expires_at <= now:
            return evolve(session, state="expired", answer=None, citations=())
        return session

    async def detail(self, session_id):
        return self.view(await io_call(self.repository.get, self.owner_id, session_id))

    async def prepare_run(self, session_id):
        session = await self.detail(session_id)
        if session.iterative_run_id is not None:
            raise ResearchError("research_session_owned_by_iterative_run", 409)
        if session.state not in {"pending", "running"}:
            return session
        now = self.clock()
        return await io_call(
            self.repository.claim,
            self.owner_id,
            session_id,
            uuid4(),
            now,
            now + timedelta(seconds=self.settings.research_timeout_seconds),
        )

    async def stream(self, session):
        if session.state != "running":
            yield event(
                "terminal",
                session_id=str(session.id),
                state=session.state,
                failure_code=session.failure_code,
            )
            return
        current = session
        terminal = False
        seconds = max(0, (session.execution_deadline - self.clock()).total_seconds())
        deadline = monotonic() + seconds

        async def save(**changes):
            nonlocal current
            candidate = evolve(
                current, updated_at=self.clock(), revision=current.revision + 1, **changes
            )
            current = await io_call(self.repository.save, candidate)
            return current

        try:
            async with asyncio.timeout(seconds):
                yield event("started", session_id=str(current.id), state="running")
                normalized = await io_call(
                    planned_queries,
                    self.planner,
                    current.request.question,
                    self.settings.research_max_queries,
                )
                queries = tuple(
                    SearchQuery(
                        id=uuid4(),
                        session_id=current.id,
                        owner_id=current.owner_id,
                        normalized_query=q,
                        sequence=i,
                        created_at=self.clock(),
                    )
                    for i, q in enumerate(normalized)
                )
                await save(queries=queries)
                yield event("planned", session_id=str(current.id), query_count=len(queries))
                results, successful = [], {}
                for query in queries:
                    if len(results) >= self.settings.research_max_sources:
                        break
                    for number in range(1, self.settings.research_attempt_limit + 1):
                        started, error_code, retryable = self.clock(), None, False
                        begun = AdapterAttempt(
                            id=uuid4(),
                            session_id=current.id,
                            query_id=query.id,
                            owner_id=current.owner_id,
                            adapter=self.adapter.name,
                            idempotency_key=f"{query.id}:{number}:start",
                            attempt_number=number,
                            status="started",
                            started_at=started,
                        )
                        await save(attempts=(*current.attempts, begun))
                        try:
                            fetched = await self.adapter.search(
                                query.normalized_query,
                                self.settings.research_max_sources - len(results),
                            )
                            if not isinstance(fetched, (list, tuple)) or any(
                                not isinstance(r, SearchResult) for r in fetched
                            ):
                                raise ResearchError("search_invalid_response")
                        except ResearchError as error:
                            allowed = {
                                "search_quota",
                                "search_timeout",
                                "search_unavailable",
                                "search_rejected",
                                "search_invalid_response",
                                "search_response_oversized",
                                "research_configuration_invalid",
                            }
                            error_code = error.code if error.code in allowed else "search_failed"
                            retryable = bool(getattr(error, "retryable", False))
                            fetched = ()
                        except Exception:  # noqa: BLE001 - record unexpected adapter failure safely
                            error_code, fetched = "search_failed", ()
                        attempt = AdapterAttempt(
                            id=uuid4(),
                            session_id=current.id,
                            query_id=query.id,
                            owner_id=current.owner_id,
                            adapter=self.adapter.name,
                            idempotency_key=f"{query.id}:{number}:result",
                            parent_attempt_id=begun.id,
                            attempt_number=number,
                            status="failed" if error_code else "completed",
                            started_at=started,
                            completed_at=self.clock(),
                            error_code=error_code,
                        )
                        await save(attempts=(*current.attempts, attempt))
                        yield event(
                            "attempt",
                            session_id=str(current.id),
                            query_id=str(query.id),
                            attempt_id=str(attempt.id),
                            state=attempt.status,
                        )
                        if not error_code:
                            limit = self.settings.research_max_sources - len(results)
                            results.extend((query.id, r) for r in fetched[:limit])
                            successful[query.id] = attempt
                            break
                        if not retryable or number == self.settings.research_attempt_limit:
                            await save(
                                queries=tuple(
                                    q.model_copy(
                                        update={"state": "failed", "executed_at": self.clock()}
                                    )
                                    if q.id == query.id
                                    else q
                                    for q in current.queries
                                )
                            )
                            raise ResearchError(error_code)
                    updated_queries = tuple(
                        q.model_copy(update={"state": "completed", "executed_at": self.clock()})
                        if q.id == query.id
                        else q
                        for q in current.queries
                    )
                    await save(queries=updated_queries)
                observations, evidence = await io_call(
                    extract_evidence,
                    current,
                    results,
                    successful,
                    self.extractor,
                    self.clock(),
                    self.settings,
                )
                await save(observations=observations, evidence=evidence)
                yield event(
                    "evidence",
                    session_id=str(current.id),
                    source_count=len(observations),
                    evidence_count=len(evidence),
                )
                selection, messages = await io_call(
                    select_evidence, current, self.context, self.clock(), deadline, self.reranker
                )
                await save(selection=selection)
                yield event(
                    "selected",
                    session_id=str(current.id),
                    evidence_count=len(selection.evidence_ids),
                )
                # Conservatively refuse to silently omit potentially conflicting eligible records.
                if not selection.evidence_ids or "budget" in selection.excluded.values():
                    code = (
                        "empty_plan"
                        if not queries
                        else "no_results"
                        if not results
                        else "extraction_no_evidence"
                        if not evidence
                        else "insufficient_evidence"
                    )
                    await save(state="insufficient", failure_code=code)
                else:
                    output = ""
                    async for delta in self.llm.stream(messages):
                        if not isinstance(delta, str) or len(output) + len(delta) > 20000:
                            raise ResearchError("synthesis_oversized")
                        output += delta
                    try:
                        answer, citations = validate_synthesis(current, output)
                    except ResearchError:
                        await save(state="insufficient", failure_code="invalid_citations")
                    else:
                        selected = set(selection.evidence_ids)
                        expiry = min(e.expires_at for e in current.evidence if e.id in selected)
                        if expiry <= self.clock():
                            await save(state="insufficient", failure_code="evidence_expired")
                        else:
                            await save(
                                state="completed",
                                answer=answer,
                                citations=citations,
                                expires_at=expiry,
                            )
                terminal = True
                yield event(
                    "terminal",
                    session_id=str(current.id),
                    state=current.state,
                    failure_code=current.failure_code,
                )
        except (asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as error:  # noqa: BLE001 - no provider details reach clients
            code = "research_timeout" if isinstance(error, TimeoutError) else "research_failed"
            if isinstance(error, ResearchError):
                code = error.code if error.code.startswith("search_") else "research_failed"
            with anyio.CancelScope(shield=True):
                try:
                    await save(state="failed", failure_code=code)
                except Exception:  # noqa: BLE001 - deadline-derived failure survives storage outage
                    code = "storage_unavailable"
            terminal = True
            yield event("terminal", session_id=str(current.id), state="failed", failure_code=code)
        finally:
            if not terminal:
                with anyio.CancelScope(shield=True):
                    try:
                        current = await io_call(self.repository.get, self.owner_id, session.id)
                        if current.state == "running":
                            await save(state="failed", failure_code="research_cancelled")
                    except Exception:  # noqa: BLE001 - durable execution deadline remains visible
                        logging.getLogger(__name__).info("Research cancellation persistence failed")
