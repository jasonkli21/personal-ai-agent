"""Owner/account lifecycle fence shared by usage, routing and artifacts."""


class OwnerFenced(RuntimeError):
    pass


def lock_owner(connection, owner_id):
    # This key predates extraction from artifacts; do not change it during upgrade.
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"artifact-owner:{owner_id}",)
    )


def assert_owner_unfenced(connection, owner_id):
    lock_owner(connection, owner_id)
    if connection.execute(
        "SELECT 1 FROM owner_lifecycle_fences WHERE owner_id=%s", (owner_id,)
    ).fetchone():
        raise OwnerFenced("owner_deletion_fenced")
