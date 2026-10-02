"""Build immutable decision snapshots from validated, owner-scoped evidence."""

import json
import logging
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from personal_ai.agents.research.contracts import ResearchSession
from personal_ai.decisions.contracts import (
    CandidateProposal,
    DecisionCreateRequest,
    DecisionInspection,
    DecisionResult,
    DecisionSnapshot,
    EvidenceSnapshot,
    PolicyVersions,
    RankingPolicy,
    Recommendation,
    SuppliedEvidence,
)
from personal_ai.decisions.repositories import DecisionError, DecisionRepository
from personal_ai.entities.research import (
    CanonicalEntity,
    EntityAlias,
    EntityClaim,
    EntityMatch,
    EvidenceReference,
)
from personal_ai.ranking.policy import (
    CLAIM_VERIFICATION_POLICY_VERSION,
    claim_assertion_supported,
    evaluate_candidates,
    literal_supported,
    normalize_name,
    rank_with_domain_features,
    resolve_candidate,
)
from personal_ai.settings import Settings
from personal_ai.storage.errors import ResourceNotFoundError

logger = logging.getLogger(__name__)


def decision_id_for(owner_id: str, idempotency_key: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"decision-v1:{owner_id}:{idempotency_key}")


def _entity_id_for(owner_id: str, proposal: CandidateProposal) -> UUID:
    identifiers = {
        key.casefold(): " ".join(value.casefold().split())
        for key, value in proposal.identifiers.items()
    }
    canonical = json.dumps(
        [owner_id, proposal.entity_type, sorted(identifiers.items())],
        separators=(",", ":"),
    )
    return uuid5(NAMESPACE_URL, f"canonical-entity-v1:{canonical}")


def _claim_id_for(entity_id: UUID, proposal) -> UUID:
    value = proposal.typed_value.model_dump(mode="json")
    key = json.dumps(
        [
            str(entity_id), CLAIM_VERIFICATION_POLICY_VERSION, proposal.attribute, proposal.scope, value,
            proposal.original_value, proposal.unit, proposal.currency,
            sorted(str(item) for item in proposal.evidence_ids),
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return uuid5(NAMESPACE_URL, f"entity-claim-v1:{key}")


def _alias_id_for(owner_id: str, entity_id: UUID, alias: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"entity-alias-v1:{owner_id}:{entity_id}:{normalize_name(alias)}")


def _session_evidence(
    session: ResearchSession,
) -> tuple[tuple[EvidenceReference, ...], dict[UUID, str]]:
    if session.selection is None or session.state != "completed":
        raise DecisionError("decision_evidence_unavailable", 409)
    observations = {source.id: source for source in session.observations}
    evidence_by_id = {item.id: item for item in session.evidence}
    references: list[EvidenceReference] = []
    passages: dict[UUID, str] = {}
    for evidence_id in session.selection.evidence_ids:
        evidence = evidence_by_id.get(evidence_id)
        if evidence is None:
            raise DecisionError("decision_evidence_invalid", 422)
        passages[evidence.id] = evidence.passage
        for source_id in evidence.source_observation_ids:
            source = observations.get(source_id)
            if source is None or source.owner_id != session.owner_id:
                raise DecisionError("decision_evidence_invalid", 422)
            references.append(
                EvidenceReference(
                    evidence_id=evidence.id,
                    source_observation_id=source.id,
                    owner_id=session.owner_id,
                    research_session_id=session.id,
                    origin="research_session",
                    url=source.canonical_url,
                    title=source.title,
                    observed_at=evidence.observed_at,
                    expires_at=evidence.expires_at,
                    expiry_policy=evidence.expiry_policy,
                    content_fingerprint=evidence.content_fingerprint,
                )
            )
    return tuple(references), passages


def _supplied_evidence(
    items: tuple[SuppliedEvidence, ...], owner_id: str
) -> tuple[tuple[EvidenceReference, ...], dict[UUID, str]]:
    references: list[EvidenceReference] = []
    passages: dict[UUID, str] = {}
    for item in items:
        if item.owner_id != owner_id:
            raise DecisionError("decision_evidence_owner_mismatch", 422)
        references.append(item.reference())
        passages[item.evidence_id] = item.passage
    return tuple(references), passages


def _make_claim(
    *,
    owner_id: str,
    entity_id: UUID,
    subject_name: str,
    proposal,
    refs_by_id: dict[UUID, tuple[EvidenceReference, ...]],
    passages: dict[UUID, str],
) -> EntityClaim:
    if any(evidence_id not in refs_by_id for evidence_id in proposal.evidence_ids):
        raise DecisionError("decision_evidence_not_found", 422)
    evidence_refs_by_key = {
        (ref.evidence_id, ref.source_observation_id): ref
        for evidence_id in proposal.evidence_ids
        for ref in refs_by_id[evidence_id]
    }
    refs = tuple(evidence_refs_by_key[key] for key in sorted(evidence_refs_by_key, key=lambda pair: (str(pair[0]), str(pair[1]))))
    supported = any(
        claim_assertion_supported(
            subject_name,
            proposal.attribute,
            proposal.original_value,
            proposal.typed_value,
            passages[evidence_id],
        )
        for evidence_id in proposal.evidence_ids
    )
    return EntityClaim(
        id=_claim_id_for(entity_id, proposal),
        entity_id=entity_id,
        owner_id=owner_id,
        attribute=proposal.attribute,
        typed_value=proposal.typed_value,
        original_value=proposal.original_value,
        unit=proposal.unit,
        currency=proposal.currency,
        evidence_refs=refs,
        evidence_ids=tuple(sorted(set(proposal.evidence_ids), key=str)),
        observed_at=max(ref.observed_at for ref in refs),
        expires_at=min(ref.expires_at for ref in refs),
        claim_status="verified" if supported else "unverified",
        verification_policy_version=CLAIM_VERIFICATION_POLICY_VERSION,
        scope=proposal.scope,
    )


class DecisionService:
    def __init__(
        self,
        settings: Settings,
        repository: DecisionRepository,
        research_repository=None,
        *,
        owner_id: str = "local",
        clock=lambda: datetime.now(UTC),
        ranker=evaluate_candidates,
        domain_feature_calculator=None,
        domain_feature_context: dict | None = None,
    ):
        self.settings = settings
        self.repository = repository
        self.research_repository = research_repository
        self.owner_id = owner_id
        self.clock = clock
        self.ranker = ranker
        self.domain_feature_calculator = domain_feature_calculator
        self.domain_feature_context = domain_feature_context or {}

    def create(self, request: DecisionCreateRequest) -> DecisionResult:
        if not self.settings.decision_enabled:
            raise ResourceNotFoundError("decision not found")
        decision_id = decision_id_for(self.owner_id, request.idempotency_key)
        fingerprint = request.fingerprint(self.owner_id)
        try:
            replay = self.repository.get(self.owner_id, decision_id)
        except ResourceNotFoundError:
            replay = None
        if replay is not None:
            if replay.decision.request_fingerprint != fingerprint:
                raise DecisionError("idempotency_conflict")
            return replay
        if len(request.candidates) > min(
            self.settings.decision_max_candidates, self.settings.decision_max_comparison_rows
        ):
            raise DecisionError("decision_candidate_limit", 422)
        now = self.clock().astimezone(UTC)
        if request.research_session_id is not None:
            research_repository = self.research_repository
            if callable(research_repository):
                research_repository = research_repository()
            if research_repository is None:
                raise ResourceNotFoundError("research not found")
            session = research_repository.get(self.owner_id, request.research_session_id)
            if session.expires_at <= now:
                raise DecisionError("decision_evidence_expired", 409)
            source_refs, passages = _session_evidence(session)
            if any(ref.owner_id != self.owner_id for ref in source_refs):
                raise DecisionError("decision_evidence_owner_mismatch", 422)
        else:
            source_refs, passages = _supplied_evidence(request.supplied_evidence, self.owner_id)

        if any(ref.observed_at > now for ref in source_refs):
            raise DecisionError("decision_evidence_from_future", 422)
        if len(source_refs) > 250:
            raise DecisionError("decision_evidence_limit", 422)
        refs_by_id: dict[UUID, tuple[EvidenceReference, ...]] = {}
        for ref in source_refs:
            refs_by_id.setdefault(ref.evidence_id, ())
            refs_by_id[ref.evidence_id] += (ref,)

        entity_pool: dict[str, list[CanonicalEntity]] = {}
        alias_pool: list[EntityAlias] = []
        claim_pool: list[EntityClaim] = []
        resolution_claim_cache: dict[
            tuple[tuple[UUID, ...], tuple[str, ...]], tuple[EntityClaim, ...]
        ] = {}
        matches: list[EntityMatch] = []
        candidate_entities: dict[UUID, CanonicalEntity] = {}
        candidate_claims: dict[UUID, list[EntityClaim]] = {}
        candidate_aliases: dict[UUID, dict[UUID, EntityAlias]] = {}

        provisional_subject_ids = [
            uuid5(decision_id, f"candidate-subject:{index}")
            for index in range(len(request.candidates))
        ]
        proposed_claims = [
            tuple(
                _make_claim(
                    owner_id=self.owner_id,
                    entity_id=provisional_subject_ids[index],
                    subject_name=candidate.canonical_name,
                    proposal=claim_proposal,
                    refs_by_id=refs_by_id,
                    passages=passages,
                )
                for claim_proposal in candidate.claims
            )
            for index, candidate in enumerate(request.candidates)
        ]

        for index, (candidate, subject_id, input_claims) in enumerate(
            zip(request.candidates, provisional_subject_ids, proposed_claims, strict=True)
        ):
            existing = entity_pool.get(candidate.entity_type)
            if existing is None:
                entity_limit = max(100, self.settings.decision_max_candidates * 8)
                existing = list(
                    self.repository.list_entities(
                        self.owner_id, candidate.entity_type,
                        limit=entity_limit,
                    )
                )
                if len(existing) > entity_limit:
                    raise DecisionError("decision_entity_resolution_limit", 409)
                entity_pool[candidate.entity_type] = existing
                ids = tuple(entity.id for entity in existing)
                alias_pool.extend(self.repository.list_aliases(self.owner_id, ids))

            candidate_refs = tuple(
                ref
                for evidence_id in sorted(
                    {item for claim_proposal in candidate.claims for item in claim_proposal.evidence_ids},
                    key=str,
                )
                for ref in refs_by_id.get(evidence_id, ())
            )
            name_supported = any(
                literal_supported(candidate.canonical_name, passages[evidence_id])
                for evidence_id in {item.evidence_id for item in candidate_refs}
                if evidence_id in passages
            )
            supported_identifiers = {}
            for key, value in candidate.identifiers.items():
                if key.casefold() == "url":
                    from personal_ai.search.policy import canonical_url

                    try:
                        normalized_value = canonical_url(value)
                    except ValueError:
                        continue
                    if any(ref.url == normalized_value for ref in candidate_refs):
                        supported_identifiers[key] = normalized_value
                elif any(
                    literal_supported(value, passages[evidence_id])
                    for evidence_id in {ref.evidence_id for ref in candidate_refs}
                    if evidence_id in passages
                ):
                    supported_identifiers[key] = value
            candidate_for_resolution = candidate.model_copy(
                update={"identifiers": supported_identifiers}
            )
            resolution_attributes = tuple(sorted({item.attribute for item in candidate.claims}))
            entity_ids = tuple(entity.id for entity in existing)
            cache_key = (entity_ids, resolution_attributes)
            if resolution_attributes and cache_key not in resolution_claim_cache:
                resolution_claims = self.repository.list_claims(
                    self.owner_id, entity_ids, resolution_attributes, limit=500
                )
                if len(resolution_claims) > 500:
                    raise DecisionError("decision_claim_limit", 422)
                resolution_claim_cache[cache_key] = resolution_claims
                claim_pool.extend(resolution_claims)
            fallback_id = uuid5(decision_id, f"unresolved-candidate:{index}")
            match = resolve_candidate(
                decision_id=decision_id,
                subject_id=subject_id,
                owner_id=self.owner_id,
                proposal=candidate_for_resolution,
                proposed_claims=input_claims,
                evidence_refs=candidate_refs,
                entities=tuple(existing),
                aliases=tuple(alias_pool),
                claims_by_entity={
                    entity.id: tuple(claim for claim in claim_pool if claim.entity_id == entity.id)
                    for entity in existing
                },
                new_entity_id=fallback_id,
                now=now,
                threshold=self.settings.entity_match_threshold,
                match_id=uuid5(decision_id, f"entity-match:{index}"),
            )[0]
            if not name_supported and not supported_identifiers:
                match = EntityMatch(
                    id=match.id,
                    decision_id=decision_id,
                    subject_id=subject_id,
                    owner_id=self.owner_id,
                    candidate_entity_id=fallback_id,
                    candidate_entity_ids=(),
                    selected_entity_id=None,
                    outcome="no_match",
                    confidence=0,
                    feature_values={"identity_evidence_missing": 1.0},
                    evidence_ids=tuple(sorted({ref.evidence_id for ref in candidate_refs}, key=str)),
                    created_at=now,
                )

            selected_id = match.selected_entity_id
            if selected_id is None:
                selected_id = fallback_id
                if match.outcome == "no_match" and supported_identifiers:
                    selected_id = _entity_id_for(self.owner_id, candidate_for_resolution)
            entity = next((value for value in existing if value.id == selected_id), None)
            if entity is None:
                entity = CanonicalEntity(
                    id=selected_id,
                    entity_type=candidate.entity_type,
                    canonical_name=candidate.canonical_name,
                    owner_scope=f"owner:{self.owner_id}",
                    owner_id=self.owner_id,
                    identifiers=supported_identifiers,
                    created_at=now,
                    updated_at=now,
                )
                existing.append(entity)
            candidate_entities[selected_id] = entity
            match = match.model_copy(update={"candidate_entity_id": selected_id})
            matches.append(match)

            final_claims = tuple(
                _make_claim(
                    owner_id=self.owner_id,
                    entity_id=selected_id,
                    subject_name=candidate.canonical_name,
                    proposal=claim_proposal,
                    refs_by_id=refs_by_id,
                    passages=passages,
                )
                for claim_proposal in candidate.claims
            )
            for claim in final_claims:
                candidate_claims.setdefault(selected_id, []).append(claim)
                claim_pool.append(claim)
            source_evidence_ids = tuple(sorted({ref.evidence_id for ref in candidate_refs}, key=str))
            alias_names = list(candidate.aliases)
            if normalize_name(candidate.canonical_name) != normalize_name(entity.canonical_name):
                alias_names.append(candidate.canonical_name)
            for alias_text in alias_names:
                if not any(
                    literal_supported(alias_text, passages[evidence_id])
                    for evidence_id in {ref.evidence_id for ref in candidate_refs}
                    if evidence_id in passages
                ):
                    continue
                normalized = normalize_name(alias_text)
                if not normalized:
                    continue
                alias = EntityAlias(
                    id=_alias_id_for(self.owner_id, selected_id, normalized),
                    entity_id=selected_id,
                    owner_id=self.owner_id,
                    normalized_alias=normalized,
                    source_evidence_ids=source_evidence_ids,
                    created_at=now,
                )
                alias = next(
                    (old_alias for old_alias in alias_pool if old_alias.id == alias.id),
                    alias,
                )
                candidate_aliases.setdefault(selected_id, {})[alias.id] = alias
                alias_pool.append(alias)

        unique_entities = tuple(sorted(candidate_entities.values(), key=lambda item: str(item.id)))
        unique_aliases = tuple(
            sorted(
                {alias.id: alias for aliases in candidate_aliases.values() for alias in aliases.values()}.values(),
                key=lambda item: str(item.id),
            )
        )
        evaluation_attributes = tuple(sorted({
            *(constraint.attribute for constraint in request.constraints),
            *(preference.attribute for preference in request.preferences),
            *(claim.attribute for claims in candidate_claims.values() for claim in claims),
        }))
        persisted_claims = (
            self.repository.list_claims(
                self.owner_id,
                tuple(entity.id for entity in unique_entities),
                evaluation_attributes,
                limit=500,
            )
            if unique_entities and evaluation_attributes
            else ()
        )
        if len(persisted_claims) > 500:
            raise DecisionError("decision_claim_limit", 422)
        claims_by_entity = {}
        for entity in unique_entities:
            by_id = {}
            for claim in (*persisted_claims, *candidate_claims.get(entity.id, ())):
                if claim.entity_id != entity.id:
                    continue
                existing_claim = by_id.get(claim.id)
                if existing_claim is not None and existing_claim != claim:
                    raise DecisionError("claim_immutability_conflict")
                by_id[claim.id] = claim
            if len(by_id) > 40:
                raise DecisionError("decision_candidate_claim_limit", 422)
            claims_by_entity[entity.id] = tuple(sorted(by_id.values(), key=lambda item: str(item.id)))
        unique_claims = tuple(sorted(
            {claim.id: claim for claims in claims_by_entity.values() for claim in claims}.values(),
            key=lambda item: str(item.id),
        ))

        rank_args = {
            "decision_id": decision_id,
            "entities": unique_entities,
            "claims_by_entity": claims_by_entity,
            "constraints": request.constraints,
            "preferences": request.preferences,
            "now": now,
            "preference_weight": self.settings.decision_feature_preference_weight,
            "identity_matches": tuple(matches),
        }
        ranking_failed = False
        try:
            evaluations, state, selected_id = self.ranker(**rank_args)
        except Exception as error:  # noqa: BLE001 - safe unranked eligible fallback
            logger.info("Decision ranking failed; preserving eligible candidates error_class=%s", type(error).__name__)
            evaluations, state, selected_id = evaluate_candidates(**rank_args, score_enabled=False)
            ranking_failed = True

        feature_policy_version = None
        domain_feature_weights = {}
        if self.domain_feature_calculator is not None:
            feature_policy_version = self.domain_feature_calculator.policy_version
            domain_feature_weights = self.domain_feature_calculator.feature_weights
            if not ranking_failed:
                try:
                    feature_values = self.domain_feature_calculator.calculate_features(
                        entities=unique_entities,
                        claims_by_entity=claims_by_entity,
                        constraints=request.constraints,
                        preferences=request.preferences,
                        evaluations=evaluations,
                        eligible_entity_ids=tuple(
                            item.entity_id for item in evaluations if item.eligibility
                        ),
                        now=now,
                        context=self.domain_feature_context,
                    )
                    evaluations, state, selected_id = rank_with_domain_features(
                        tuple(evaluations),
                        unique_entities,
                        feature_values,
                        state,
                    )
                except Exception as error:  # noqa: BLE001 - preserve hard-filter outcomes
                    logger.info(
                        "Domain ranking extension failed; preserving eligibility error_class=%s",
                        type(error).__name__,
                    )
                    evaluations, state, selected_id = evaluate_candidates(
                        **rank_args, score_enabled=False
                    )

        evaluations_by_entity = {item.entity_id: item for item in evaluations}
        eligible = [item for item in evaluations if item.eligibility]
        eligible.sort(
            key=lambda item: (
                item.rank if item.rank is not None else 10_000,
                normalize_name(candidate_entities[item.entity_id].canonical_name),
                str(item.entity_id),
            )
        )
        candidate_order = tuple(item.entity_id for item in eligible)
        supporting_claim_ids: tuple[UUID, ...] = ()
        recommendation_evidence_ids: tuple[UUID, ...] = ()
        if selected_id is not None:
            selected_evaluation = evaluations_by_entity[selected_id]
            supported_claims = tuple(
                claim for claim in claims_by_entity[selected_id]
                if claim.id in selected_evaluation.claim_ids
                and claim.claim_status == "verified"
                and claim.verification_policy_version == CLAIM_VERIFICATION_POLICY_VERSION
                and claim.expires_at > now
            )
            supporting_claim_ids = tuple(sorted((claim.id for claim in supported_claims), key=str))
            recommendation_evidence_ids = tuple(sorted(
                {ref.evidence_id for claim in supported_claims for ref in claim.evidence_refs}, key=str
            ))
        explanation_codes = tuple(sorted({
            *[status.reason for evaluation in evaluations for status in evaluation.attribute_statuses],
            *[outcome.reason for evaluation in evaluations for outcome in evaluation.constraint_outcomes],
            *(('ranking_unavailable',) if state == "eligible_unranked" else ()),
        }))
        recommendation = Recommendation(
            status=state,
            selected_entity_id=selected_id,
            candidate_order=candidate_order,
            supporting_claim_ids=supporting_claim_ids,
            evidence_ids=recommendation_evidence_ids,
            explanation_codes=explanation_codes,
        )

        evidence_ref_map = {
            (ref.evidence_id, ref.source_observation_id): ref for ref in source_refs
        }
        for claim in unique_claims:
            evidence_ref_map.update({
                (ref.evidence_id, ref.source_observation_id): ref for ref in claim.evidence_refs
            })
        if len(evidence_ref_map) > 250:
            raise DecisionError("decision_provenance_limit", 422)
        evidence_snapshot = EvidenceSnapshot(
            id=uuid5(decision_id, "decision-evidence-snapshot-v1"),
            decision_id=decision_id,
            owner_id=self.owner_id,
            evidence_refs=tuple(sorted(
                evidence_ref_map.values(),
                key=lambda ref: (str(ref.evidence_id), str(ref.source_observation_id)),
            )),
            created_at=now,
        )
        decision = DecisionSnapshot(
            id=decision_id,
            owner_id=self.owner_id,
            request_fingerprint=request.fingerprint(self.owner_id),
            research_session_id=request.research_session_id,
            constraint_set=request.constraints,
            preferences=request.preferences,
            candidate_ids=tuple(entity.id for entity in unique_entities),
            evidence_snapshot_id=evidence_snapshot.id,
            policy_versions=PolicyVersions(
                claim_verification=CLAIM_VERIFICATION_POLICY_VERSION,
                entity_match_threshold=self.settings.entity_match_threshold,
                ranking_policy=RankingPolicy(
                    feature_weights={
                        "preference": self.settings.decision_feature_preference_weight,
                        **domain_feature_weights,
                    }
                ),
                domain_features=feature_policy_version,
                max_candidates=self.settings.decision_max_candidates,
                max_comparison_rows=self.settings.decision_max_comparison_rows,
            ),
            state=state,
            selected_entity_id=selected_id,
            recommendation=recommendation,
            created_at=now,
        )
        result = DecisionResult(
            decision=decision,
            recommendation=recommendation,
            evidence_snapshot=evidence_snapshot,
            entities=unique_entities,
            claims=unique_claims,
            aliases=unique_aliases,
            matches=tuple(matches),
            evaluations=tuple(evaluations),
        )
        return self.repository.create(result)

    def detail(self, decision_id: UUID) -> DecisionResult:
        return self.repository.get(self.owner_id, decision_id)

    def inspect(self, decision_id: UUID) -> DecisionInspection:
        if not self.settings.decision_inspection_enabled:
            raise ResourceNotFoundError("decision not found")
        result = self.detail(decision_id)
        return DecisionInspection(
            decision_id=decision_id,
            state=result.decision.state,
            policy_versions=result.decision.policy_versions,
            selected_entity_id=result.decision.selected_entity_id,
            selected=tuple(item for item in result.evaluations if item.eligibility),
            excluded=tuple(item for item in result.evaluations if not item.eligibility),
            matches=result.matches,
            evidence_refs=result.evidence_snapshot.evidence_refs,
        )
