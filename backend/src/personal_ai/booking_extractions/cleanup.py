"""Bounded cleanup for expired booking extraction results.

Run with ``uv run python -m personal_ai.booking_extractions.cleanup --limit 100``.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from personal_ai.booking_extractions.repositories import FirestoreBookingExtractionRepository
from personal_ai.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")
    settings = get_settings()
    repository = FirestoreBookingExtractionRepository(
        project_id=settings.firestore_project_id,
        emulator_host=settings.firestore_emulator_host,
    )
    print(repository.purge_expired(datetime.now(UTC), limit=args.limit))


if __name__ == "__main__":
    main()
