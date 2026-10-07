"""Shared wall-clock deadline for bounded memory service operations."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

_OPERATION_DEADLINE = ContextVar("memory_lifecycle_deadline", default=None)


@contextmanager
def lifecycle_deadline(seconds: float):
    """Share one wall-clock allowance across a retrieval or worker operation."""
    previous = _OPERATION_DEADLINE.get()
    deadline = monotonic() + seconds
    token = _OPERATION_DEADLINE.set(min(previous, deadline) if previous else deadline)
    try:
        yield
    finally:
        _OPERATION_DEADLINE.reset(token)


def rpc_timeout() -> float:
    """Return the remaining bounded operation allowance, capped at five seconds."""
    deadline = _OPERATION_DEADLINE.get()
    left = 5 if deadline is None else min(5, deadline - monotonic())
    if left <= 0:
        raise TimeoutError("memory_lifecycle_timeout")
    return left
