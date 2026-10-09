"""Private GCS JSON API adapter, explicit generations, bounded IO and no retries."""

from __future__ import annotations

import re
from time import monotonic
from urllib.parse import quote

import httpx

from personal_ai.artifacts.contracts import (
    MAX_COMPRESSED_BYTES,
    ArtifactConflict,
    ArtifactUnavailable,
)

_KEY = re.compile(r"^artifacts/v1/[0-9a-f]{64}/[0-9a-f-]{36}\.jsonl?\.gz$")


class PrivateGCSArtifactStore:
    """No public URLs, ACL writes, signed URLs, arbitrary endpoints or client keys.

    An operator attestation covers inherited IAM, total account free-tier usage,
    eligible project/region and billing. Live metadata separately enforces PAP,
    uniform access, STANDARD regional storage, no versions/soft delete/retention.
    Credentials are obtained from workload ADC, never stored in references.
    """

    def __init__(
        self, bucket, *, region, preflight_verified=False, token=None, client=None, timeout=10
    ):
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]", bucket):
            raise ValueError("artifact_bucket_invalid")
        if not preflight_verified or region not in {"us-west1", "us-central1", "us-east1"}:
            raise ArtifactUnavailable("artifact_gcs_preflight_required")
        if not 0 < timeout <= 10:
            raise ValueError("artifact_gcs_timeout_invalid")
        self.bucket, self.region = bucket, region
        self.store_id = f"gcs:{bucket}"
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)
        self.timeout = timeout
        self.token = token or self._adc_token
        self.verified = False

    @staticmethod
    def _adc_token():
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/devstorage.read_write"]
        )
        transport = Request()
        credentials.refresh(lambda **kwargs: transport(**{**kwargs, "timeout": 10}))
        return credentials.token

    def _request(self, method, path, *, params=None, body=None, ceiling=65536):
        deadline = monotonic() + self.timeout
        headers = {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/octet-stream",
            "Accept-Encoding": "identity",
        }
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise ArtifactUnavailable("artifact_gcs_deadline")
        with self.client.stream(
            method,
            "https://storage.googleapis.com/" + path,
            params=params,
            content=body,
            headers=headers,
            timeout=remaining,
        ) as response:
            data = bytearray()
            for chunk in response.iter_bytes():
                if monotonic() >= deadline:
                    raise ArtifactUnavailable("artifact_gcs_deadline")
                data.extend(chunk)
                if len(data) > ceiling:
                    raise ArtifactUnavailable("artifact_gcs_response_oversized")
            return response.status_code, bytes(data)

    @staticmethod
    def _json(data):
        import json

        try:
            value = json.loads(data)
        except ValueError as error:
            raise ArtifactUnavailable("artifact_gcs_protocol") from error
        if not isinstance(value, dict):
            raise ArtifactUnavailable("artifact_gcs_protocol")
        return value

    def verify_private_bucket(self):
        status, body = self._request("GET", f"storage/v1/b/{self.bucket}")
        if status != 200:
            raise ArtifactUnavailable("artifact_bucket_unavailable")
        facts = self._json(body)
        iam = facts.get("iamConfiguration", {})
        if (
            iam.get("publicAccessPrevention") != "enforced"
            or not iam.get("uniformBucketLevelAccess", {}).get("enabled")
            or facts.get("location", "").lower() != self.region
            or facts.get("storageClass") != "STANDARD"
            or facts.get("versioning", {}).get("enabled")
            or str(facts.get("softDeletePolicy", {}).get("retentionDurationSeconds")) != "0"
            or facts.get("retentionPolicy")
            or facts.get("encryption")
            or facts.get("billing", {}).get("requesterPays")
        ):
            raise ArtifactUnavailable("artifact_bucket_policy_unsafe")
        self.verified = True

    def _key(self, key):
        if not self.verified:
            raise ArtifactUnavailable("artifact_bucket_not_verified")
        if not _KEY.fullmatch(key):
            raise ArtifactUnavailable("artifact_key_invalid")
        return f"storage/v1/b/{self.bucket}/o/{quote(key, safe='')}"

    def generation(self, key):
        status, body = self._request("GET", self._key(key))
        if status == 404:
            return None
        if status != 200:
            raise ArtifactUnavailable("artifact_gcs_stat_failed")
        value = self._json(body).get("generation", "")
        if not re.fullmatch(r"[1-9][0-9]{0,29}", str(value)):
            raise ArtifactUnavailable("artifact_generation_invalid")
        return str(value)

    def put(self, key, body):
        self._key(key)
        if not 0 < len(body) <= MAX_COMPRESSED_BYTES:
            raise ArtifactUnavailable("artifact_upload_size")
        status, data = self._request(
            "POST",
            f"upload/storage/v1/b/{self.bucket}/o",
            params={"uploadType": "media", "name": key, "ifGenerationMatch": "0"},
            body=body,
        )
        if status == 412:
            generation = self.generation(key)
            if generation is None or self.read(key, generation, max_bytes=len(body)) != body:
                raise ArtifactConflict("artifact_object_conflict")
            return generation
        if status not in {200, 201}:
            raise ArtifactUnavailable("artifact_gcs_upload_failed")
        generation = self._json(data).get("generation", "")
        if not re.fullmatch(r"[1-9][0-9]{0,29}", str(generation)):
            raise ArtifactUnavailable("artifact_generation_invalid")
        return str(generation)

    def read(self, key, generation, *, max_bytes):
        if not re.fullmatch(r"[1-9][0-9]{0,29}", generation):
            raise ArtifactUnavailable("artifact_generation_invalid")
        if not 0 < max_bytes <= MAX_COMPRESSED_BYTES:
            raise ArtifactUnavailable("artifact_read_size")
        status, body = self._request(
            "GET",
            self._key(key),
            params={
                "alt": "media",
                "generation": generation,
                "ifGenerationMatch": generation,
            },
            ceiling=max_bytes,
        )
        if status != 200:
            raise ArtifactUnavailable("artifact_gcs_read_failed")
        return body

    def delete(self, key, generation):
        if not re.fullmatch(r"[1-9][0-9]{0,29}", generation):
            raise ArtifactUnavailable("artifact_generation_invalid")
        status, _ = self._request(
            "DELETE",
            self._key(key),
            params={
                "generation": generation,
                "ifGenerationMatch": generation,
            },
        )
        if status not in {204, 404}:
            raise ArtifactUnavailable("artifact_gcs_delete_failed")

    def close(self):
        self.client.close()
