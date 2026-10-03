#!/usr/bin/env python3
"""Inventory legacy owner data; safely migrate chat-only databases to one OIDC owner."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import UTC, datetime

from google.cloud import firestore

from personal_ai.auth.owner_data import OWNER_DATA_COLLECTIONS

# Later phases embed owners or derive IDs/idempotency keys from them. A generic
# field update corrupts those records, so refuse the whole apply before writes.
SUPPORTED_COLLECTIONS = {"conversations", "messages", "conversation_summaries"}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project", required=True, help="Firestore project id")
    result.add_argument(
        "--owner-id", required=True, help="Active usr_<32 lowercase hex> mapping id"
    )
    result.add_argument(
        "--apply", action="store_true", help="Migrate a chat-only database; default is inventory"
    )
    result.add_argument(
        "--confirm-owner-id", help="Repeat the target owner id to authorize --apply"
    )
    return result


def legacy_batches(client, collection_name):
    query = (
        client.collection(collection_name)
        .where(filter=firestore.FieldFilter("owner_id", "==", "local"))
        .order_by("__name__")
    )
    last = None
    while True:
        page = query.limit(200)
        if last is not None:
            page = page.start_after(last)
        records = tuple(page.stream())
        if not records:
            return
        yield records
        last = records[-1]


def migrate(client, *, owner_id, apply):
    mapping = client.collection("identity_mappings").document(owner_id).get()
    mapping_data = (mapping.to_dict() or {}) if mapping.exists else {}
    if (
        not mapping.exists
        or mapping_data.get("status") != "active"
        or mapping_data.get("owner_id") != owner_id
    ):
        print(
            "Target owner mapping is missing or inactive; no records were changed.", file=sys.stderr
        )
        return 2

    counts = {}
    for collection_name in OWNER_DATA_COLLECTIONS:
        counts[collection_name] = sum(
            len(records) for records in legacy_batches(client, collection_name)
        )
        print(f"{collection_name}: {counts[collection_name]} legacy records")
    total = sum(counts.values())
    if not apply:
        print(f"{total} legacy records found. No records were changed.")
        return 0
    if any(count and name not in SUPPORTED_COLLECTIONS for name, count in counts.items()):
        print(
            "Apply supports chat and working summaries only. Other legacy collections require "
            "a collection-aware migration of embedded owners and derived keys; "
            "no records were changed.",
            file=sys.stderr,
        )
        return 2

    for collection_name in sorted(SUPPORTED_COLLECTIONS):
        for records in legacy_batches(client, collection_name):
            batch = client.batch()
            for snapshot in records:
                # Strict record schemas reject migration metadata. Keep the
                # schema intact and store provenance in a separate audit event.
                batch.update(
                    snapshot.reference,
                    {"owner_id": owner_id},
                    option=firestore.LastUpdateOption(snapshot.update_time),
                )
            audit_id = hashlib.sha256(
                f"owner-migration-v2:{owner_id}:{collection_name}:".encode()
                + ":".join(snapshot.id for snapshot in records).encode()
            ).hexdigest()
            batch.create(
                client.collection("audit_events").document(audit_id),
                {
                    "id": audit_id,
                    "actor_subject": owner_id,
                    "owner_id": owner_id,
                    "action": "owner.migrate",
                    "target_type": collection_name,
                    "target_id": None,
                    "result": "migrated",
                    "record_count": len(records),
                    "correlation_id": audit_id,
                    "occurred_at": datetime.now(UTC),
                    "migration_version": "phase9-chat-owner-v2",
                },
            )
            batch.commit()
    print(f"{total} owner fields updated. No document content was printed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not re.fullmatch(r"usr_[0-9a-f]{32}", args.owner_id):
        parser().error("--owner-id must use the stable usr_<32 lowercase hex> format")
    if args.apply and args.confirm_owner_id != args.owner_id:
        parser().error("--apply requires --confirm-owner-id to match --owner-id")

    client = firestore.Client(project=args.project)
    try:
        return migrate(client, owner_id=args.owner_id, apply=args.apply)
    except Exception as error:  # noqa: BLE001 - redact SDK details at the operator boundary
        # SDK messages may include document identifiers. Report only the class;
        # interrupted batches can be reviewed and safely resumed with writes paused.
        print(f"Migration stopped ({type(error).__name__}); review before retry.", file=sys.stderr)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
