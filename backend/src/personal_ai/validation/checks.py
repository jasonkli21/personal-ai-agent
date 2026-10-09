"""Shared structural and hard-constraint checks for runtime and evaluation."""

import json


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_field")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("nonfinite_json_number")


def json_object(text: str) -> dict | None:
    try:
        value = json.loads(text, object_pairs_hook=_object_pairs, parse_constant=_invalid_constant)
    except (TypeError, ValueError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def type_matches(value, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "boolean":
        return isinstance(value, bool)
    return False


def _path(value, path: str):
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


def constraint_passes(output, constraint) -> bool:
    actual = _path(output, constraint.path)
    expected = constraint.value
    if actual is None:
        return False
    if constraint.operator == "lte":
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
            and actual <= expected
        )
    if constraint.operator == "gte":
        return (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and isinstance(expected, (int, float))
            and not isinstance(expected, bool)
            and actual >= expected
        )
    if constraint.operator == "equals":
        return actual == expected
    if constraint.operator == "not_equals":
        return actual != expected
    if constraint.operator == "not_contains":
        return isinstance(actual, str) and str(expected).casefold() not in actual.casefold()
    return False
