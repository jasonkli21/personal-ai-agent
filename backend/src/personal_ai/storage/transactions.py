"""Bounded Firestore transactions with explicit RPC deadlines and no hidden retries."""

import logging
from time import monotonic


def bounded_transaction(client, operation, seconds=5):
    deadline = monotonic() + seconds

    def timeout():
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("storage deadline")
        return remaining

    transaction = client.transaction(max_attempts=1)
    api = client._firestore_api
    response = api.begin_transaction(
        request={"database": client._database_string},
        metadata=client._rpc_metadata,
        retry=None,
        timeout=timeout(),
    )
    transaction._id = response.transaction
    try:
        result = operation(transaction, timeout)
        api.commit(
            request={
                "database": client._database_string,
                "transaction": transaction.id,
                "writes": transaction._write_pbs,
            },
            metadata=client._rpc_metadata,
            retry=None,
            timeout=timeout(),
        )
        return result
    except BaseException:
        try:
            api.rollback(
                request={"database": client._database_string, "transaction": transaction.id},
                metadata=client._rpc_metadata,
                retry=None,
                timeout=1,
            )
        except Exception:  # noqa: BLE001 - retain the original failure
            logging.getLogger(__name__).info("Research transaction rollback failed")
        raise
    finally:
        transaction._clean_up()
