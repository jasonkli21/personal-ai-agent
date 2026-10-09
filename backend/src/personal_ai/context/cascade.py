"""Frozen source preparation through the existing shared context builder."""

from personal_ai.context.builder import ContextBuilder, ContextBuildPolicy
from personal_ai.context.tokens import EstimatedTokenCounter
from personal_ai.validation.tasks import ValidationInput


class FrozenContextAssembler:
    """Rebuild from the same authorized records under each endpoint's ceiling.

    Local estimates fit source blocks; the runtime separately admits one exact
    endpoint count. Base history never shrinks. Optional source omissions require
    the P21 source-narrowing policy and receive a different prepared-input digest.
    No summaries, retrieval, or other hidden auxiliary calls occur here.
    """

    def __init__(self, *, messages, entries, policy, validation, permission_revalidator=None):
        self.messages = tuple(messages)
        self.entries = tuple(type(entry).model_validate(entry.model_dump()) for entry in entries)
        self.policy = ContextBuildPolicy.model_validate(policy.model_dump())
        self.validation = ValidationInput.model_validate(validation.model_dump())
        self.permission_revalidator = permission_revalidator
        sources = {source.source_id: source for source in self.validation.sources}
        if (len({entry.source_id for entry in self.entries}) != len(self.entries)
            or set(sources) != {entry.source_id for entry in self.entries}
            or any(sources[entry.source_id].text != entry.content for entry in self.entries)):
            raise ValueError("cascade_source_input_mapping_invalid")

    def __call__(self, profile, decision):
        cap = min(self.policy.global_input_tokens, decision.request.requirements.input_tokens,
                  profile.context_limit_tokens - decision.request.requirements.output_tokens)
        policy = ContextBuildPolicy(
            global_input_tokens=cap,
            source_max_tokens={key: min(value, cap) for key, value in self.policy.source_max_tokens.items()},
            source_priorities=self.policy.source_priorities,
        )
        context = ContextBuilder(
            EstimatedTokenCounter(), permission_revalidator=self.permission_revalidator
        ).build(self.messages, self.entries, policy,
                base_sensitivity=decision.request.requirements.sensitivity)
        injected = {item.source_id for item in context.manifest.items if item.injected}
        inputs = ValidationInput.model_validate({
            **self.validation.model_dump(),
            "sources": tuple(source for source in self.validation.sources if source.source_id in injected),
        })
        return context, inputs
