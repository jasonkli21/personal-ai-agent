from __future__ import annotations

import pytest

from personal_ai.persistence.dynamodb_cloud import (
    FederatedDynamoDBConfig,
    google_oidc_aws_condition_claims,
)
from personal_ai.persistence.neon import NeonDirectDatabase, NeonRuntimeDatabase
from personal_ai.persistence.postgres import PostgresDatabase


def test_google_claim_mapping_uses_azp_for_aws_aud_and_aud_for_oaud():
    claims = google_oidc_aws_condition_claims({
        "aud": "https://personal-ai.example/run",
        "azp": "123456.apps.googleusercontent.com",
        "sub": "109876543210987654321",
    })
    assert claims == {
        "accounts.google.com:aud": "123456.apps.googleusercontent.com",
        "accounts.google.com:oaud": "https://personal-ai.example/run",
        "accounts.google.com:sub": "109876543210987654321",
    }


def test_federated_dynamodb_config_requires_https_audience_and_exact_role_shape():
    FederatedDynamoDBConfig(
        region="us-east-1",
        table_name="personal-ai-runtime-v1",
        role_arn="arn:aws:iam::123456789012:role/personal-ai-runtime",
        identity_token_audience="https://personal-ai.example/aws-role",
    ).validate()
    with pytest.raises(ValueError, match="dynamodb_identity_audience_invalid"):
        FederatedDynamoDBConfig(
            region="us-east-1", table_name="personal-ai-runtime-v1",
            role_arn="arn:aws:iam::123456789012:role/personal-ai-runtime",
            identity_token_audience="http://example.test/audience",
        ).validate()


def test_cloud_postgres_requires_hostname_verified_tls():
    with pytest.raises(ValueError, match="postgres_tls_verification_required"):
        PostgresDatabase(
            "postgresql://user:secret@ep-sample-pooler.us-east-1.aws.neon.tech/db?sslmode=require",
            environment="production",
        )
    with pytest.raises(ValueError, match="neon_transaction_pooler_required"):
        NeonRuntimeDatabase(
            "postgresql://user:secret@ep-sample.us-east-1.aws.neon.tech/db?sslmode=verify-full",
            environment="production",
        )
    database = NeonRuntimeDatabase(
        "postgresql://user:secret@ep-sample-pooler.us-east-1.aws.neon.tech/db?sslmode=verify-full",
        environment="production",
    )
    assert database._min_size == 0
    assert database._max_size == 4
    assert database._prepare_threshold is None
    with pytest.raises(ValueError, match="neon_runtime_pool_bound_invalid"):
        NeonRuntimeDatabase(
            "postgresql://user:secret@ep-sample-pooler.us-east-1.aws.neon.tech/db?sslmode=verify-full",
            environment="production", max_size=5,
        )
    direct = NeonDirectDatabase(
        "postgresql://user:secret@ep-sample.us-east-1.aws.neon.tech/db?sslmode=verify-full",
        environment="production",
        max_size=2,
    )
    assert direct._min_size == 0 and direct._max_size == 2
    with pytest.raises(ValueError, match="neon_direct_endpoint_required"):
        NeonDirectDatabase(
            "postgresql://user:secret@ep-sample-pooler.us-east-1.aws.neon.tech/db?sslmode=verify-full",
            environment="production",
        )
