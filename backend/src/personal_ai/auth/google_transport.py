"""Bounded signing-key transport shared by user and service authentication."""

from contextlib import contextmanager

from google.auth.transport.requests import Request


class _BoundedGoogleAuthRequest(Request):
    def __call__(self, url, method="GET", body=None, headers=None, timeout=3, **kwargs):
        return super().__call__(
            url,
            method=method,
            body=body,
            headers=headers,
            timeout=min(timeout or 3, 3),
            **kwargs,
        )


@contextmanager
def signing_key_request():
    """Close the HTTP session even when key retrieval or token validation fails."""
    request = _BoundedGoogleAuthRequest()
    try:
        yield request
    finally:
        request.session.close()
