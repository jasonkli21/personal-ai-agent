"""Verified request identity carried from authentication to owner-scoped services."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    issuer: str
    subject: str
    owner_id: str
    email: str | None
    issued_at: int
    authenticated: bool

    @classmethod
    def development(cls) -> "AuthenticatedPrincipal":
        """Return the explicit local/test principal, never a deployed identity."""
        return cls(
            issuer="local-development",
            subject="local-development",
            owner_id="local",
            email=None,
            issued_at=0,
            authenticated=False,
        )
