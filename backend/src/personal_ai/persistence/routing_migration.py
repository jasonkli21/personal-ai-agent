"""Compatibility import for the frozen migration 022 transformation.

The runner invokes the versioned migration module directly. This name remains
available to focused migration tests and must never own mutable migration logic.
"""

from importlib import import_module

_migration_022 = import_module("personal_ai.persistence.migrations_py.022_routing_authorities")
migrate_routing_authorities = _migration_022.migrate_routing_authorities
retain_definition = _migration_022.retain_definition

__all__ = ["migrate_routing_authorities", "retain_definition"]
