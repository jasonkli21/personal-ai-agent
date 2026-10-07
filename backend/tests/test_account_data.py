"""Portable account-export encoding and inventory contracts."""

from datetime import UTC, datetime
from decimal import Decimal

from personal_ai.auth.account_data import (
    EXPORT_COLLECTIONS,
    _portable,
)
from personal_ai.auth.owner_data import OWNER_DATA_COLLECTIONS


def test_portable_export_encodes_nested_values_without_provider_types():
    value = {
        "timestamp": datetime(2026, 10, 6, tzinfo=UTC),
        "amount": Decimal("1.25"),
        "blob": b"abc",
        "non_finite": float("inf"),
        "nested": ("value", 2),
    }

    assert _portable(value) == {
        "timestamp": "2026-10-06T00:00:00+00:00",
        "amount": "1.25",
        "blob": {"$type": "base64", "value": "YWJj"},
        "non_finite": {"$type": "float", "value": "inf"},
        "nested": ["value", 2],
    }


def test_account_export_inventory_covers_private_families_and_control_records():
    assert set(OWNER_DATA_COLLECTIONS) <= set(EXPORT_COLLECTIONS)
    assert "audit_events" in EXPORT_COLLECTIONS
    assert "account_lifecycle_requests" in EXPORT_COLLECTIONS
