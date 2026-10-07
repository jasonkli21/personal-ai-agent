"""Federated AWS DynamoDB client for Cloud Run; never consults AWS key chains."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC
from typing import Any
from urllib.parse import urlsplit

from personal_ai.persistence.dynamodb import DynamoDBRuntimeTable

_REGION = re.compile(r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$", re.ASCII)
_ROLE_ARN = re.compile(r"^arn:(aws|aws-us-gov|aws-cn):iam::\d{12}:role/[A-Za-z0-9+=,.@_/-]{1,512}$")


@dataclass(frozen=True)
class FederatedDynamoDBConfig:
    region: str
    table_name: str
    role_arn: str
    identity_token_audience: str
    role_session_name: str = "personal-ai-cloud-run"

    def validate(self) -> None:
        if not _REGION.fullmatch(self.region):
            raise ValueError("dynamodb_region_invalid")
        if not self.table_name or len(self.table_name) > 255:
            raise ValueError("dynamodb_table_name_invalid")
        if not _ROLE_ARN.fullmatch(self.role_arn):
            raise ValueError("dynamodb_role_arn_invalid")
        parsed = urlsplit(self.identity_token_audience)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("dynamodb_identity_audience_invalid")
        if not re.fullmatch(r"[A-Za-z0-9+=,.@_-]{2,64}", self.role_session_name):
            raise ValueError("dynamodb_role_session_name_invalid")


def google_oidc_aws_condition_claims(claims: dict[str, Any]) -> dict[str, str]:
    """Return AWS's mapped Google OIDC `aud`, `oaud`, and `sub` condition values."""
    audience = claims.get("aud")
    subject = claims.get("sub")
    authorized_party = claims.get("azp")
    if not isinstance(audience, str) or not audience or not isinstance(subject, str) or not subject:
        raise ValueError("google_oidc_claims_invalid")
    mapped = {"accounts.google.com:oaud": audience, "accounts.google.com:sub": subject}
    mapped["accounts.google.com:aud"] = authorized_party if isinstance(authorized_party, str) and authorized_party else audience
    return mapped


def _unverified_claims(token: str) -> dict[str, Any]:
    """Decode claims only to validate request shape; AWS verifies the signed token."""
    try:
        encoded = token.split(".")[1]
        encoded += "=" * (-len(encoded) % 4)
        value = json.loads(base64.urlsafe_b64decode(encoded))
    except (IndexError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("google_identity_token_invalid") from error
    if not isinstance(value, dict):
        raise TypeError("google_identity_token_invalid")
    return value


def _assume_federated_role(config: FederatedDynamoDBConfig) -> dict[str, str]:
    """Exchange a Cloud Run service-account ID token for bounded STS credentials."""
    from boto3 import client as boto_client
    from botocore import UNSIGNED
    from botocore.config import Config
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    config.validate()
    if not os.environ.get("K_SERVICE") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise RuntimeError("cloud_run_service_account_identity_required")
    identity_token = id_token.fetch_id_token(Request(timeout=5), config.identity_token_audience)
    claims = _unverified_claims(identity_token)
    if claims.get("aud") != config.identity_token_audience or not claims.get("sub"):
        raise RuntimeError("google_identity_token_audience_invalid")
    # The ID token itself carries no user input. STS enforces the role's exact
    # audience/azp/subject trust conditions and returns at most a 1-hour session.
    sts = boto_client(
        "sts",
        region_name=config.region,
        aws_access_key_id="unsigned-oidc-exchange",
        aws_secret_access_key="unsigned-oidc-exchange",
        config=Config(
            signature_version=UNSIGNED,
            connect_timeout=3,
            read_timeout=5,
            retries={"mode": "standard", "max_attempts": 2},
            tcp_keepalive=True,
        ),
    )
    response = sts.assume_role_with_web_identity(
        RoleArn=config.role_arn,
        RoleSessionName=config.role_session_name,
        WebIdentityToken=identity_token,
        DurationSeconds=3600,
    )
    credentials = response["Credentials"]
    expiration = credentials["Expiration"]
    return {
        "access_key": credentials["AccessKeyId"],
        "secret_key": credentials["SecretAccessKey"],
        "token": credentials["SessionToken"],
        "expiry_time": expiration.astimezone(UTC).isoformat(),
    }


def federated_dynamodb_client(config: FederatedDynamoDBConfig):
    """Create a TLS-verified client with refreshable, short-lived STS credentials."""
    import boto3
    import botocore.session
    from botocore.config import Config
    from botocore.credentials import RefreshableCredentials

    config.validate()
    credentials = RefreshableCredentials.create_from_metadata(
        metadata=_assume_federated_role(config),
        refresh_using=lambda: _assume_federated_role(config),
        method="google-oidc-sts",
    )
    session = botocore.session.get_session()
    session._credentials = credentials
    session.set_config_variable("region", config.region)
    client = boto3.Session(botocore_session=session).client(
        "dynamodb",
        region_name=config.region,
        verify=True,
        config=Config(
            connect_timeout=3,
            read_timeout=5,
            retries={"mode": "standard", "max_attempts": 2},
            tcp_keepalive=True,
        ),
    )
    endpoint = urlsplit(client.meta.endpoint_url)
    if endpoint.scheme != "https" or endpoint.hostname is None:
        raise RuntimeError("dynamodb_tls_endpoint_required")
    return client


class FederatedDynamoDBRuntimeTable(DynamoDBRuntimeTable):
    """Runtime table wrapper that cannot bootstrap or use DynamoDB Local."""

    def __init__(self, config: FederatedDynamoDBConfig, *, client=None) -> None:
        config.validate()
        self.local = None
        self.client = client if client is not None else federated_dynamodb_client(config)
        self.table_name = config.table_name
        endpoint = urlsplit(self.client.meta.endpoint_url)
        if endpoint.scheme != "https" or endpoint.hostname is None:
            raise ValueError("dynamodb_tls_endpoint_required")

    def bootstrap(self) -> None:
        raise RuntimeError("cloud_dynamodb_runtime_cannot_bootstrap")

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close is not None:
            close()


__all__ = [
    "FederatedDynamoDBConfig",
    "FederatedDynamoDBRuntimeTable",
    "federated_dynamodb_client",
    "google_oidc_aws_condition_claims",
]
