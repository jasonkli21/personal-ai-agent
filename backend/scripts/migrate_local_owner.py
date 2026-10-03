#!/usr/bin/env python3
"""Dry-run-first reassignment of legacy ``local`` owner fields to one OIDC owner."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime

from google.cloud import firestore

from personal_ai.auth.owner_data import OWNER_DATA_COLLECTIONS


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--project", required=True, help="Firestore project id")
    result.add_argument(
        "--owner-id", required=True, help="Active usr_<32 lowercase hex> mapping id"
    )
    result.add_argument(
        "--apply", action="store_true", help="Write changes; otherwise only count matching records"
    )
    result.add_argument(
        "--confirm-owner-id", help="Repeat the target owner id to authorize --apply"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not re.fullmatch(r"usr_[0-9a-f]{32}", args.owner_id):
        parser().error("--owner-id must use the stable usr_<32 lowercase hex> format")
    if args.apply and args.confirm_owner_id != args.owner_id:
        parser().error("--apply requires --confirm-owner-id to match --owner-id")

    client = firestore.Client(project=args.project)
    mapping = client.collection("identity_mappings").document(args.owner_id).get()
    mapping_data = mapping.to_dict() or {} if mapping.exists else {}
    if (
        not mapping.exists
        or mapping_data.get("status") != "active"
        or mapping_data.get("owner_id") != args.owner_id
    ):
        print(
            "Target owner mapping is missing or inactive; no records were changed.", file=sys.stderr
        )
        return 2

    total = 0
    now = datetime.now(UTC)
    for collection_name in OWNER_DATA_COLLECTIONS:
        base_query = (
            client.collection(collection_name)
            .where(filter=firestore.FieldFilter("owner_id", "==", "local"))
            .order_by("__name__")
        )
        last = None
        collection_count = 0
        while True:
            query = base_query.limit(200)
            if last is not None:
                query = query.start_after(last)
            records = tuple(query.stream())
            if not records:
                break
            collection_count += len(records)
            total += len(records)
            if args.apply:
                batch = client.batch()
                for snapshot in records:
                    batch.update(
                        snapshot.reference,
                        {
                            "owner_id": args.owner_id,
                            "owner_migration_version": "phase9-owner-v1",
                            "owner_migrated_at": now,
                        },
                        option=firestore.LastUpdateOption(snapshot.update_time),
                    )
                batch.commit()
            last = records[-1]
        print(f"{collection_name}: {collection_count} legacy records")
    mode = "updated" if args.apply else "would update"
    print(f"{total} owner fields {mode}. No document content was printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
