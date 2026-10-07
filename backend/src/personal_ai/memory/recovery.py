"""Explicit bounded recovery of durable jobs whose Pub/Sub notification was lost."""

import argparse
import json

from personal_ai.memory.lifecycle_jobs import MemoryLifecycleCoordinator, PubSubMemoryJobPublisher
from personal_ai.persistence.factory import persistence_factory
from personal_ai.settings import get_settings


def recover_pending(settings, *, limit=50, coordinator=None):
    if not 1 <= limit <= 100:
        raise ValueError("job_limit_invalid")
    if not settings.memory_enabled or not settings.memory_lifecycle_worker_enabled:
        return {"status": "disabled", "published": 0}
    if coordinator is None:
        factory = persistence_factory(settings)
        memories = factory.memory_repository()
        messages = factory.message_repository()
        lifecycle = factory.memory_lifecycle_repository(memories, messages)
        coordinator = MemoryLifecycleCoordinator(
            settings, lifecycle, memories, publisher=PubSubMemoryJobPublisher(settings)
        )
    return {"status": "completed", "published": coordinator.republish_pending(limit=limit)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args()
    print(json.dumps(recover_pending(get_settings(), limit=args.limit)))


if __name__ == "__main__":
    main()
