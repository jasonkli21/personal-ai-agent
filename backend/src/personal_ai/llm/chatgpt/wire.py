"""Strict provider JSON decoding; diagnostics never retain raw wire input."""

import json


def decode_json(body):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("invalid_json_constant")

    return json.loads(body, object_pairs_hook=pairs, parse_constant=invalid_constant)
