"""Frozen source preparation through the existing shared context builder."""

import hashlib
import json

from personal_ai.context.builder import ContextBuilder, ContextBuildPolicy
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.validation.tasks import ValidationInput


def canonical_context_reference_sha256(entry) -> str:
    """Derive a source authorization identity from the exact frozen item."""
    payload = {
        "schema": "context-item-reference-v1",
        "source_class": entry.source_class,
        "provider_id": entry.provider_id,
        "source_version": entry.source_version,
        "selected_operation": entry.selected_operation,
        "source_id": entry.source_id,
        "item_id": entry.item_id,
        "authority": entry.authority,
        "sensitivity": entry.sensitivity,
        "content_sha256": hashlib.sha256(entry.content.encode("utf-8")).hexdigest(),
        "source_refs": sorted(
            (reference.model_dump(mode="json", exclude_none=True) for reference in entry.source_refs),
            key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")),
        ),
        "permission_dependencies": sorted(
            (dependency.model_dump(mode="json", exclude_none=True)
             for dependency in entry.permission_dependencies),
            key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")),
        ),
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class FrozenContextAssembler:
    """Rebuild from the same authorized records under each endpoint's ceiling.

    Local estimates fit source blocks; the runtime separately admits one exact
    endpoint count. Base history never shrinks. Optional source omissions require
    the P21 source-narrowing policy and receive a different prepared-input digest.
    No summaries, retrieval, or other hidden auxiliary calls occur here.
    """

    def __init__(self, *, messages, entries, policy, validation, clock,
                 permission_revalidator=None):
        self.messages = tuple(messages)
        self.entries = tuple(type(entry).model_validate(entry.model_dump()) for entry in entries)
        self.policy = ContextBuildPolicy.model_validate(policy.model_dump())
        self.validation = ValidationInput.model_validate(validation.model_dump())
        if not callable(clock):
            raise TypeError("cascade_authoritative_clock_required")
        self.clock = clock
        self.permission_revalidator = permission_revalidator
        entry_by_key = {(entry.source_id, entry.item_id): entry for entry in self.entries}
        if len(entry_by_key) != len(self.entries):
            raise ValueError("cascade_source_input_mapping_invalid")
        normalized_sources = []
        mapped_keys = set()
        for source in self.validation.sources:
            if source.context_source_id is not None:
                key = (source.context_source_id, source.context_item_id)
            else:
                matches = [key for key in entry_by_key if key[0] == source.source_id]
                if len(matches) != 1:
                    raise ValueError("cascade_source_input_mapping_invalid")
                key = matches[0]
            entry = entry_by_key.get(key)
            if (entry is None or key in mapped_keys or source.text != entry.content
                or source.reference_sha256 != canonical_context_reference_sha256(entry)):
                raise ValueError("cascade_source_input_mapping_invalid")
            mapped_keys.add(key)
            normalized_sources.append(source.model_copy(update={
                "context_source_id": entry.source_id,
                "context_item_id": entry.item_id,
            }))
        if mapped_keys != set(entry_by_key):
            raise ValueError("cascade_source_input_mapping_invalid")
        self.validation = self.validation.model_copy(update={"sources": tuple(normalized_sources)})

    def __call__(self, profile, decision):
        cap = min(self.policy.global_input_tokens, decision.request.requirements.input_tokens,
                  profile.context_limit_tokens - decision.request.requirements.output_tokens)
        policy = ContextBuildPolicy(
            global_input_tokens=cap,
            source_max_tokens={key: min(value, cap) for key, value in self.policy.source_max_tokens.items()},
            source_priorities=self.policy.source_priorities,
        )
        context = ContextBuilder(
            EstimatedTokenCounter(), permission_revalidator=self.permission_revalidator,
            clock=self.clock,
        ).build(self.messages, self.entries, policy,
                base_sensitivity=decision.request.requirements.sensitivity)
        if any(
            not item.injected and item.omission_reason in {
                "permission_revoked", "permission_unverified", "expired"
            }
            for item in context.manifest.items
        ):
            raise ValueError("cascade_context_source_authority_changed")
        injected = {
            (item.source_id, item.item_id) for item in context.manifest.items if item.injected
        }
        inputs = ValidationInput.model_validate({
            **self.validation.model_dump(),
            "sources": tuple(
                source for source in self.validation.sources
                if (source.context_source_id, source.context_item_id) in injected
            ),
        })
        return context, inputs
