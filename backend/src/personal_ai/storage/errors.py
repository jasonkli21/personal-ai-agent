"""Application-level persistence errors.

These errors deliberately contain no Firestore exception objects so callers can
map them to stable HTTP responses without exposing infrastructure details.
"""


class StorageError(Exception):
    """Base class for errors raised by persistence implementations."""


class ResourceNotFoundError(StorageError):
    """The resource is absent or does not belong to the requested owner."""


class ConversationConflictError(StorageError):
    """The active branch changed or an in-flight turn blocks the mutation."""


class StorageUnavailableError(StorageError):
    """The backing store could not complete an operation."""


# Short aliases make the boundary pleasant to consume while retaining explicit
# names for HTTP/API adapters.
NotFoundError = ResourceNotFoundError
RepositoryError = StorageError
