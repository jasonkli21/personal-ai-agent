"""Conservative URL, literal-snippet extraction and transparent planning policy."""

import ipaddress
import re
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from personal_ai.agents.research.contracts import ResearchError


def canonical_url(value: str) -> str:
    if len(value) > 2048 or re.search(r"[\x00-\x20\x7f\\]", value):
        raise ValueError("unsafe URL")
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or not host
        or parsed.port not in {None, 80, 443}
        or "%" in host
    ):
        raise ValueError("unsafe URL")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if (
            "." not in host
            or host.endswith((".local", ".localhost", ".internal", ".invalid"))
            or re.fullmatch(r"[0-9.xa-f]+", host)
            or not re.fullmatch(r"[a-z0-9.-]+", host)
            or any(
                not part or part.startswith("-") or part.endswith("-") for part in host.split(".")
            )
        ):
            raise ValueError("unsafe URL")
    else:
        if not address.is_global:
            raise ValueError("unsafe URL")
        host = f"[{host}]" if address.version == 6 else host
    port = (
        f":{parsed.port}"
        if parsed.port and parsed.port != (443 if parsed.scheme == "https" else 80)
        else ""
    )
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit((parsed.scheme, host + port, parsed.path or "/", urlencode(query), ""))


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


class SnippetExtractor:
    def extract(self, text: str) -> str:
        if len(text) > 10000:
            raise ResearchError("extraction_oversized")
        parser = _TextParser()
        parser.feed(text)
        passage = " ".join(unescape(" ".join(parser.parts)).split())
        if len(passage) > 1200 or any(ord(c) < 32 for c in passage):
            raise ResearchError("extraction_oversized")
        return passage


def content_fingerprint(passage: str) -> str:
    # Preserve case, punctuation, numbers and negation; only whitespace is normalized.
    return sha256(" ".join(passage.split()).encode()).hexdigest()


class DeterministicPlanner:
    def plan(self, question: str, max_queries: int):
        return (" ".join(question.split()),) if question.strip() and max_queries else ()


def planned_queries(planner, question: str, max_queries: int) -> tuple[str, ...]:
    try:
        values = planner.plan(question, max_queries)
        if not isinstance(values, (list, tuple)) or len(values) > max_queries:
            raise ValueError("invalid plan")
        result = []
        for value in values:
            if not isinstance(value, str) or len(value) > 500 or not value.strip():
                raise ValueError("invalid query")
            value = " ".join(value.split())
            # Custom planners must preserve all explicit question terms; no tool syntax.
            if not set(question.lower().split()) <= set(value.lower().split()):
                raise ValueError("query dropped constraints")
            if value not in result:
                result.append(value)
        return tuple(result)
    except Exception:  # noqa: BLE001 - optional planners fail to the deterministic baseline
        return tuple(DeterministicPlanner().plan(question, max_queries))
