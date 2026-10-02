"""Conservative extractive policy, applied before embedding and again on reads."""

import re

from personal_ai.memory.contracts import normalize

# Defense in depth, not a claim to classify every possible sensitive statement.
DENIED = re.compile(
    r"\b(password|passwd|secret|api.?key|token|credential|private.?key|"
    r"account|iban|ssn|social security|credit card|medical|health|diagnos\w*|"
    r"medication|therapy|legal|lawsuit|attorney|passport|address|email|phone|"
    r"prices?|costs?|availability|inventory|opening hours|recommend\w*|"
    r"according to|website|https?)\b|[\w.+-]+@[\w.-]+|\d{6,}|"
    r"\b\d{3}[- .]\d{2,3}[- .]\d{4}\b",
    re.IGNORECASE,
)
TYPE_MARKERS = {
    "preference": ("i prefer", "i like", "i dislike", "i always choose"),
    "episodic_observation": ("i visited", "i tried", "i attended", "i experienced"),
    "semantic_summary": ("i usually", "i tend to", "in general, i"),
    "explicit_correction": ("correction:", "actually, i", "i no longer", "i now prefer"),
}
RATIONALES = dict(
    zip(
        TYPE_MARKERS,
        ("user_preference", "user_experience", "user_generalization", "user_correction"),
        strict=True,
    )
)


def content_reason(content, settings):
    if DENIED.search(content) or any(
        normalize(term) in normalize(content)
        for term in settings.memory_sensitive_terms
        if term.strip()
    ):
        return "sensitive_or_external"
    return None


def _standalone_assertion(candidate: str, source: str) -> bool:
    """Require an unquoted, complete sentence rather than a prompt fragment."""
    start = source.find(candidate)
    while start >= 0:
        end = start + len(candidate)
        before = source[:start].rstrip()
        after = source[end:]
        after_text = after.lstrip()
        starts_sentence = not before or before[-1] in ".!?"
        ends_sentence = (
            not after_text
            or after_text[0] in ".!?"
            or (candidate[-1] in ".!?" and after[:1].isspace())
        )
        # Quotes around the candidate or a trailing quote after its punctuation
        # make it reported text, not an attributable user assertion.
        quoted = (before and before[-1] in "\"'“‘") or (
            after_text and after_text[0] in "\"'”’"
        )
        if starts_sentence and ends_sentence and not quoted:
            return True
        start = source.find(candidate, start + 1)
    return False


def candidate_reason(candidate, source, settings):
    users = [m for m in source if m.role.value == "user" and m.status.value == "completed"]
    selected = [m for m in users if m.id in candidate.source_message_ids]
    if len(selected) != len(candidate.source_message_ids):
        return "source_mismatch"
    if not any(candidate.content in m.content for m in selected):
        return "not_source_grounded"
    if not any(_standalone_assertion(candidate.content, m.content) for m in selected):
        return "unsupported_assertion"
    # Reject even a harmless excerpt when the supplied user statement contains sensitive data.
    if any(content_reason(m.content, settings) for m in selected):
        return "sensitive_or_external"
    if candidate.confidence < 0.8:
        return "low_confidence"
    if candidate.rationale_code != RATIONALES[candidate.memory_type] or not any(
        normalize(candidate.content).startswith(marker)
        for marker in TYPE_MARKERS[candidate.memory_type]
    ):
        return "unsupported_type"
    # An asserted date must belong to the exact statement being retained.
    if candidate.effective_at and candidate.effective_at.date().isoformat() not in candidate.content:
        return "unsupported_effective_time"
    return content_reason(candidate.content, settings)
