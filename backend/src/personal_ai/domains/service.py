"""Domain adapters and views layered over the shared Phase 5–6 services."""

import asyncio
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from personal_ai.decisions.contracts import DecisionCreateRequest
from personal_ai.decisions.repositories import DecisionError
from personal_ai.decisions.service import DecisionService
from personal_ai.domains.contracts import (
    ComparisonCell,
    ComparisonSource,
    DomainClaimExtension,
    DomainComparisonCreateRequest,
    DomainComparisonResult,
    DomainComparisonRow,
    DomainComparisonSnapshot,
    DomainContractError,
    DomainInspection,
    DomainLookupRequest,
    DomainLookupReservation,
    ProviderObservationExtension,
)
from personal_ai.domains.providers import (
    DomainProviderError,
    FirestoreProviderRateLimiter,
)
from personal_ai.domains.registry import DomainModule, get_domain, registry
from personal_ai.domains.repositories import (
    DomainRepository,
    DomainRepositoryError,
    lookup_reservation_id,
)
from personal_ai.entities.research import EntityClaim
from personal_ai.storage.errors import ResourceNotFoundError


class DomainService:
    def __init__(
        self,
        settings,
        decision_repository,
        repository: DomainRepository,
        research_repository=None,
        *,
        owner_id: str = "local",
        clock=lambda: datetime.now(UTC),
        adapters: dict[str, object] | None = None,
    ):
        self.settings = settings
        self.decision_repository = decision_repository
        self.repository = repository
        self.research_repository = research_repository
        self.owner_id = owner_id
        self.clock = clock
        self.adapters = adapters or {}

    def registrations(self):
        return tuple(
            module.registration_for(True)
            for module in registry().values()
            if self._is_enabled(module.registration.domain_id)
        )

    def _is_enabled(self, domain_id: str) -> bool:
        return bool(getattr(self.settings, f"{domain_id}_enabled", False))

    def _module(self, domain_id: str) -> DomainModule:
        try:
            module = get_domain(domain_id)
        except ValueError as error:
            raise ResourceNotFoundError("domain not found") from error
        if not self.settings.decision_enabled or not self._is_enabled(domain_id):
            raise ResourceNotFoundError("domain not found")
        return module

    def require_domain(self, domain_id: str) -> DomainModule:
        return self._module(domain_id)

    def create(self, domain_id: str, request: DomainComparisonCreateRequest) -> DomainComparisonResult:
        return self._create(domain_id, request)

    def _create(
        self,
        domain_id: str,
        request: DomainComparisonCreateRequest,
        *,
        lookup_reservation: DomainLookupReservation | None = None,
    ) -> DomainComparisonResult:
        module = self._module(domain_id)
        if len(request.decision.candidates) > min(
            self.settings.domain_max_comparison_rows,
            self.settings.decision_max_comparison_rows,
        ):
            raise DomainContractError("domain_comparison_limit")
        decision_request = module.prepare_decision(request.decision)
        provider_observations = request.provider_observations
        if request.decision.research_session_id is not None:
            provider_observations = (
                *provider_observations,
                *self._research_observations(
                    request.decision.research_session_id,
                    request.decision.candidates,
                ),
            )
        self._validate_provider_observations(module, provider_observations)
        decision_result = DecisionService(
            self.settings,
            self.decision_repository,
            research_repository=self.research_repository,
            owner_id=self.owner_id,
            clock=self.clock,
            domain_feature_calculator=module,
        ).create(decision_request)

        now = self.clock().astimezone(UTC)
        comparison_id = uuid5(
            NAMESPACE_URL,
            f"domain-comparison-v1:{domain_id}:{decision_result.decision.id}:{module.registration.field_schema_version}",
        )
        try:
            previous = self.repository.get(self.owner_id, comparison_id)
        except ResourceNotFoundError:
            previous = None
        if previous is not None:
            if previous.comparison.decision_id != decision_result.decision.id:
                raise DomainContractError("domain_comparison_conflict", 409)
            if lookup_reservation is None:
                return previous
            try:
                return self.repository.complete_lookup(
                    lookup_reservation.id,
                    lookup_reservation.fence_token,
                    previous,
                )
            except DomainRepositoryError as error:
                raise DomainContractError(error.code, 409) from error

        self._validate_decision_references(decision_result, provider_observations)
        extension_claims = self._domain_claims(module, decision_result.claims)
        if len(extension_claims) > 200:
            raise DomainContractError("domain_claim_limit")
        rows = self._comparison_rows(
            module,
            decision_result,
            provider_observations,
            now,
        )
        registration = module.registration_for(True)
        snapshot = DomainComparisonSnapshot(
            id=comparison_id,
            decision_id=decision_result.decision.id,
            owner_id=self.owner_id,
            domain_id=domain_id,
            candidate_ids=decision_result.decision.candidate_ids,
            field_schema_version=registration.field_schema_version,
            feature_policy_version=registration.feature_policy_version,
            decision_policy_versions=decision_result.decision.policy_versions,
            constraints=decision_result.decision.constraint_set,
            preferences=decision_result.decision.preferences,
            rendered_at=now,
            state=decision_result.decision.state,
            rows=rows,
        )
        result = DomainComparisonResult(
            registration=registration,
            comparison=snapshot,
            provider_observations=provider_observations,
            domain_claims=extension_claims,
        )
        try:
            if lookup_reservation is not None:
                return self.repository.complete_lookup(
                    lookup_reservation.id,
                    lookup_reservation.fence_token,
                    result,
                )
            return self.repository.create(result)
        except DomainRepositoryError as error:
            raise DomainContractError(error.code, 409) from error

    async def lookup(self, domain_id: str, request: DomainLookupRequest) -> DomainComparisonResult:
        module = self._module(domain_id)
        if request.max_results > self.settings.domain_max_results:
            raise DomainContractError("domain_result_limit")
        # Reject malformed domain constraints before reserving an idempotency key
        # or making a provider request.
        module.prepare_decision(DecisionCreateRequest(
            idempotency_key=request.idempotency_key,
            constraints=request.constraints,
            preferences=request.preferences,
        ))
        now = self.clock().astimezone(UTC)
        proposed_fence_token = uuid4()
        reservation = DomainLookupReservation(
            id=lookup_reservation_id(self.owner_id, domain_id, request.idempotency_key),
            owner_id=self.owner_id,
            domain_id=domain_id,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request.fingerprint(self.owner_id, domain_id),
            fence_token=proposed_fence_token,
            created_at=now,
            updated_at=now,
        )
        try:
            reservation = self.repository.reserve_lookup(reservation)
        except DomainRepositoryError as error:
            raise DomainContractError(error.code, 409) from error
        if reservation.request_fingerprint != request.fingerprint(self.owner_id, domain_id):
            raise DomainContractError("idempotency_conflict", 409)
        if reservation.state == "completed":
            if reservation.comparison_id is None:
                raise DomainContractError("domain_lookup_result_missing", 503)
            return self.detail(domain_id, reservation.comparison_id)
        if reservation.state == "failed":
            code = reservation.failure_code or "domain_lookup_failed"
            status = reservation.failure_status or 503
            if reservation.failure_kind == "provider":
                raise DomainProviderError(code, status)
            raise DomainContractError(code, status)
        if reservation.state == "uncertain":
            raise DomainContractError("domain_lookup_outcome_unknown", 503)
        # A record already in reserved state belongs to another dispatch unless
        # its fencing token matches the token minted for this attempt.
        if reservation.fence_token != proposed_fence_token:
            raise DomainContractError("domain_lookup_in_progress", 409)
        try:
            adapter = self.adapters.get(domain_id)
            if adapter is None:
                rate_limiter = None
                if domain_id == "travel" and self.settings.travel_places_adapter == "osm_nominatim":
                    rate_limiter = self._firestore_rate_limiter("osm_nominatim")
                elif domain_id == "shopping" and self.settings.shopping_products_adapter == "open_food_facts":
                    rate_limiter = self._firestore_rate_limiter("open_food_facts")
                adapter = module.get_adapter(self.settings, rate_limiter=rate_limiter)
            if domain_id == "travel":
                records = await adapter.lookup(request.query, request.max_results)
                if len(records) > request.max_results:
                    raise DomainProviderError("travel_provider_invalid_response")
                provider = "osm_nominatim" if adapter.name == "osm_nominatim" else "fake_travel_places"
                candidates, evidence, observations = module.map_place_records(
                    tuple(records),
                    owner_id=self.owner_id,
                    provider=provider,
                    now=self.clock().astimezone(UTC),
                    ttl_seconds=self.settings.travel_place_ttl_seconds,
                )
            elif domain_id == "shopping":
                product = await adapter.lookup_barcode(request.query)
                records = (product,) if product is not None else ()
                provider = "open_food_facts" if adapter.name == "open_food_facts" else "fake_shopping_catalog"
                candidates, evidence, observations = module.map_product_records(
                    tuple(records),
                    owner_id=self.owner_id,
                    provider=provider,
                    now=self.clock().astimezone(UTC),
                    ttl_seconds=self.settings.shopping_product_ttl_seconds,
                )
            else:
                raise ResourceNotFoundError("domain not found")
            if len(candidates) > self.settings.decision_max_candidates:
                raise DomainContractError("domain_result_limit")
            decision = DecisionCreateRequest(
                idempotency_key=request.idempotency_key,
                candidates=candidates,
                constraints=request.constraints,
                preferences=request.preferences,
                supplied_evidence=evidence,
            )
            return self._create(
                domain_id,
                DomainComparisonCreateRequest(
                    decision=decision,
                    provider_observations=observations,
                ),
                lookup_reservation=reservation,
            )
        except DomainProviderError as error:
            self._fail_lookup(reservation, state="failed", kind="provider", error=error)
            raise
        except (DomainContractError, DecisionError) as error:
            self._fail_lookup(reservation, state="failed", kind="contract", error=error)
            raise
        except asyncio.CancelledError:
            self._fail_lookup(reservation, state="uncertain")
            raise
        except Exception as error:
            self._fail_lookup(reservation, state="uncertain")
            raise DomainContractError("domain_lookup_outcome_unknown", 503) from error

    def _fail_lookup(self, reservation, *, state, kind=None, error=None):
        try:
            self.repository.fail_lookup(
                reservation.id,
                reservation.fence_token,
                state=state,
                failure_kind=kind,
                failure_code=getattr(error, "code", None),
                failure_status=getattr(error, "status", None),
            )
        except Exception as storage_error:  # noqa: BLE001 - retain conservative reserved state
            import logging

            logging.getLogger(__name__).info(
                "Domain lookup reservation could not be finalized error_class=%s",
                type(storage_error).__name__,
            )

    def detail(self, domain_id: str, comparison_id: UUID) -> DomainComparisonResult:
        self._module(domain_id)
        result = self.repository.get(self.owner_id, comparison_id)
        if result.comparison.domain_id != domain_id:
            raise ResourceNotFoundError("domain comparison not found")
        return result

    def inspect(self, domain_id: str, comparison_id: UUID) -> DomainInspection:
        if not self.settings.domain_inspection_enabled:
            raise ResourceNotFoundError("domain comparison not found")
        result = self.detail(domain_id, comparison_id)
        return DomainInspection(
            comparison_id=result.comparison.id,
            domain_id=domain_id,
            source_policy_version=result.registration.source_policy_version,
            feature_policy_version=result.registration.feature_policy_version,
            provider_names=tuple(sorted({item.provider for item in result.provider_observations})),
            observation_ids=tuple(item.source_observation_id for item in result.provider_observations),
            claim_ids=tuple(item.claim_id for item in result.domain_claims),
        )

    def _validate_provider_observations(self, module: DomainModule, observations) -> None:
        allowed = set(module.registration.source_adapters)
        for item in observations:
            if item.owner_id != self.owner_id:
                raise DomainContractError("domain_evidence_owner_mismatch")
            if item.provider not in allowed and item.provider != "fake" and not item.provider.startswith("fake_"):
                raise DomainContractError("domain_provider_unregistered")
            if item.provider == "brave" and not (
                self.settings.research_enabled and self.settings.research_provider_storage_approved
            ):
                raise DomainContractError("domain_provider_policy_required", 404)

    def _firestore_rate_limiter(self, provider: str):
        client = getattr(self.repository, "client", None)
        if client is None:
            return None
        return FirestoreProviderRateLimiter(client, provider)

    def _research_observations(self, session_id, candidates):
        repository = self.research_repository
        if callable(repository):
            repository = repository()
        if repository is None:
            return ()
        try:
            session = repository.get(self.owner_id, session_id)
        except ResourceNotFoundError:
            return ()  # DecisionService reports the canonical missing-session error.
        if session.selection is None or session.state != "completed":
            return ()
        selected = set(session.selection.evidence_ids)
        evidence = {item.id: item for item in session.evidence if item.id in selected}
        sources = {item.id: item for item in session.observations}
        observation_claims = {
            evidence_id
            for candidate in candidates
            for claim in candidate.claims
            for evidence_id in claim.evidence_ids
        }
        extensions = []
        for evidence_id in sorted(observation_claims & evidence.keys(), key=str):
            item = evidence[evidence_id]
            for source_id in item.source_observation_ids:
                source = sources.get(source_id)
                if source is None:
                    continue
                extensions.append(ProviderObservationExtension(
                    source_observation_id=source.id,
                    evidence_id=item.id,
                    owner_id=self.owner_id,
                    provider=source.provider,
                    provider_object_id=None,
                    entity_kind="web_source",
                    adapter_version=f"phase5-{source.provider}-snippet-v1",
                    attribution=(
                        f"Source observed through Phase 5 ({source.provider}); the cited page is the authority."
                    ),
                    policy_url=(
                        "https://api-dashboard.search.brave.com/documentation/resources/terms-of-service"
                        if source.provider == "brave"
                        else None
                    ),
                    url=source.canonical_url,
                    title=source.title,
                    observed_at=item.observed_at,
                    expires_at=item.expires_at,
                ))
        return tuple(extensions)

    @staticmethod
    def _validate_decision_references(decision_result, observations) -> None:
        refs = {
            (ref.evidence_id, ref.source_observation_id, ref.owner_id, ref.url, ref.observed_at, ref.expires_at)
            for ref in decision_result.evidence_snapshot.evidence_refs
        }
        for item in observations:
            if (
                item.evidence_id,
                item.source_observation_id,
                item.owner_id,
                item.url,
                item.observed_at,
                item.expires_at,
            ) not in refs:
                raise DomainContractError("domain_provider_observation_invalid")

    @staticmethod
    def _domain_claims(module: DomainModule, claims: tuple[EntityClaim, ...]) -> tuple[DomainClaimExtension, ...]:
        field_keys = {field.key for field in module.registration.fields}
        return tuple(
            DomainClaimExtension(
                claim_id=claim.id,
                domain_id=module.registration.domain_id,
                attribute=claim.attribute,
                typed_value=claim.typed_value,
                original_value=claim.original_value,
                evidence_ids=claim.evidence_ids,
                observed_at=claim.observed_at,
                expires_at=claim.expires_at,
            )
            for claim in sorted(claims, key=lambda item: str(item.id))
            if claim.attribute in field_keys and claim.attribute not in module.registration.supported_features
        )

    @staticmethod
    def _comparison_rows(module: DomainModule, decision_result, observations, now):
        observation_by_pair = {
            (item.evidence_id, item.source_observation_id): item for item in observations
        }
        claims_by_id = {item.id: item for item in decision_result.claims}
        evaluations = {item.entity_id: item for item in decision_result.evaluations}
        entities = {item.id: item for item in decision_result.entities}
        display_fields = tuple(
            field for field in module.registration.fields
            if field.key not in module.registration.supported_features
        )
        rows = []
        for entity_id in decision_result.decision.candidate_ids:
            evaluation = evaluations[entity_id]
            entity = entities[entity_id]
            allowed_claim_ids = set(evaluation.claim_ids)
            claims = [claims_by_id[item] for item in allowed_claim_ids if item in claims_by_id]
            cells = []
            for field in display_fields:
                field_claims = [item for item in claims if item.attribute == field.key]
                statuses = [item for item in evaluation.attribute_statuses if item.attribute == field.key]
                distinct_values = []
                for claim in field_claims:
                    if not any(claim.typed_value == known.typed_value for known in distinct_values):
                        distinct_values.append(claim)
                if len(distinct_values) > 1:
                    status = "conflicting"
                elif statuses:
                    status = _status_priority(statuses)
                elif not field_claims:
                    status = "missing"
                elif any(item.expires_at <= now for item in field_claims):
                    status = "stale"
                elif any(item.claim_status != "verified" for item in field_claims):
                    status = "unverified"
                else:
                    status = "verified"
                formatted = []
                for claim in sorted(field_claims, key=lambda item: str(item.id)):
                    value = module.format_claim(field.key, claim)
                    if value not in formatted:
                        formatted.append(value)
                if status == "conflicting":
                    text = "Conflicting values: " + " / ".join(formatted) if formatted else None
                else:
                    text = " / ".join(formatted) if formatted else None
                source_map = {}
                for claim in field_claims:
                    for ref in claim.evidence_refs:
                        key = (ref.evidence_id, ref.source_observation_id)
                        provider = observation_by_pair.get(key)
                        source_map[key] = ComparisonSource(
                            evidence_id=ref.evidence_id,
                            source_observation_id=ref.source_observation_id,
                            url=ref.url,
                            title=ref.title,
                            attribution=provider.attribution if provider else None,
                            policy_url=provider.policy_url if provider else None,
                            observed_at=ref.observed_at,
                            expires_at=ref.expires_at,
                        )
                note = None
                if status == "missing":
                    note = "No sourced value is available."
                elif status == "stale":
                    note = "This observation has expired. Recheck it before relying on it."
                elif status == "conflicting":
                    note = "Sources disagree; the decision policy kept the conflict visible."
                elif field.mutable and field_claims:
                    note = "This is a time-sensitive observation."
                cells.append(ComparisonCell(
                    field=field.key,
                    label=field.label,
                    value=text,
                    status=status,
                    note=note,
                    claim_ids=tuple(item.id for item in field_claims),
                    sources=tuple(source_map[key] for key in sorted(source_map, key=lambda pair: (str(pair[0]), str(pair[1])))),
                ))
            rows.append(DomainComparisonRow(
                candidate_id=entity_id,
                name=entity.canonical_name,
                eligible=evaluation.eligibility,
                selected=decision_result.decision.selected_entity_id == entity_id,
                rank=evaluation.rank,
                score=evaluation.score,
                exclusion_reasons=evaluation.exclusion_reasons,
                cells=tuple(cells),
                features=tuple(
                    item for item in evaluation.feature_values
                    if item.name.startswith(f"{module.registration.domain_id}.")
                ),
            ))
        return tuple(rows)


def _status_priority(statuses):
    for value in ("conflicting", "stale", "unverified", "verified", "missing"):
        if any(item.status == value for item in statuses):
            return value
    return "missing"
