"""Explicit no-provisioning cloud contract smoke for reviewed existing resources."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4

import pytest

pytestmark = pytest.mark.cloud_smoke


def _reviewed_opt_in() -> bool:
    return (
        os.environ.get("P10_CLOUD_SMOKE") == "1"
        and os.environ.get("K_SERVICE", "").strip() != ""
        and os.environ.get("P10_CLOUD_SMOKE_APPROVAL_REF", "").strip() != ""
        and os.environ.get("P10_STRICT_ZERO_REPORT", "").strip() != ""
        and os.environ.get("P10_STRICT_ZERO_MAXIMUM_AGE_DAYS", "").isdigit()
        and os.environ.get("P10_NEON_RUNTIME_DSN", "").strip() != ""
        and os.environ.get("P10_DYNAMODB_ROLE_ARN", "").strip() != ""
        and os.environ.get("P10_AWS_OIDC_AUDIENCE", "").strip() != ""
    )


def _gate_validator():
    root = Path(__file__).resolve().parents[3]
    module_path = root / "infrastructure/phase10/strict_zero_release_gate.py"
    spec = importlib.util.spec_from_file_location("p10_strict_zero_gate", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("strict_zero_release_gate_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.validate_report


@pytest.mark.skipif(not _reviewed_opt_in(), reason="explicit reviewed cloud smoke opt-in is absent")
def test_reviewed_neon_and_dynamodb_smoke_without_provisioning():
    report_path = Path(os.environ["P10_STRICT_ZERO_REPORT"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    maximum_age = int(os.environ["P10_STRICT_ZERO_MAXIMUM_AGE_DAYS"])
    failures = _gate_validator()(report, maximum_age_days=maximum_age)
    assert not failures, "strict-$0 evidence blocks cloud smoke: " + ",".join(failures)

    from personal_ai.persistence.dynamodb import _marshal
    from personal_ai.persistence.dynamodb_cloud import (
        FederatedDynamoDBConfig,
        FederatedDynamoDBRuntimeTable,
    )
    from personal_ai.persistence.neon import NeonRuntimeDatabase

    database = NeonRuntimeDatabase(
        os.environ["P10_NEON_RUNTIME_DSN"],
        environment=os.environ.get("APP_ENVIRONMENT", "production"),
    )
    table = FederatedDynamoDBRuntimeTable(FederatedDynamoDBConfig(
        region=os.environ.get("P10_DYNAMODB_REGION", "us-east-1"),
        table_name=os.environ["P10_DYNAMODB_TABLE_NAME"],
        role_arn=os.environ["P10_DYNAMODB_ROLE_ARN"],
        identity_token_audience=os.environ["P10_AWS_OIDC_AUDIENCE"],
        role_session_name="personal-ai-smoke",
    ))
    try:
        with database.connection() as connection:
            connection.execute(
                "CREATE TEMP TABLE p10_vector_smoke (embedding vector(3)) ON COMMIT DROP"
            )
            connection.execute(
                "INSERT INTO p10_vector_smoke VALUES ('[1,0,0]'::vector)"
            )
            distance = connection.execute(
                "SELECT embedding <=> '[1,0,0]'::vector FROM p10_vector_smoke"
            ).fetchone()[0]
            assert float(distance) == 0

        partition = f"P10SMOKE#{uuid4()}"
        key = {"PK": partition, "SK": "SMOKE#control"}
        nonce = str(uuid4())
        item = {
            **key,
            "kind": "p10-cloud-smoke",
            "smoke_nonce": nonce,
            "PUBPK": f"P10SMOKE#{nonce}",
            "PUBSK": f"JOB#{nonce}",
        }
        try:
            table.transact([{"Put": {
                "Item": _marshal(item),
                "ConditionExpression": "attribute_not_exists(PK)",
            }}])
            assert table.get(key, consistent=True) == item
            table.transact([{"Update": {
                "Key": _marshal(key),
                "UpdateExpression": "SET smoke_updated=:updated",
                "ConditionExpression": "smoke_nonce=:nonce",
                "ExpressionAttributeValues": _marshal({
                    ":updated": True, ":nonce": item["smoke_nonce"],
                }),
            }}])
            item["smoke_updated"] = True
            assert table.get(key, consistent=True) == item
            rows = table.query(
                partition=partition,
                sort_prefix="SMOKE#",
                consistent=True,
                deadline=monotonic() + 5,
                limit=5,
            )
            assert rows == [item]
            deadline = monotonic() + 5
            indexed = []
            while monotonic() < deadline:
                response = table.client.query(
                    TableName=table.table_name,
                    IndexName="job-publication-v1",
                    KeyConditionExpression="#pk=:pk AND begins_with(#sk,:prefix)",
                    ExpressionAttributeNames={"#pk": "PUBPK", "#sk": "PUBSK"},
                    ExpressionAttributeValues=_marshal({
                        ":pk": item["PUBPK"], ":prefix": "JOB#",
                    }),
                    Limit=2,
                )
                indexed = response.get("Items", [])
                if indexed:
                    break
                sleep(0.1)
            assert len(indexed) == 1
        finally:
            table.transact([{"Delete": {"Key": _marshal(key)}}])
            assert table.get(key, consistent=True) is None
    finally:
        database.close()
        table.close()
