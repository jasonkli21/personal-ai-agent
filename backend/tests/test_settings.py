"""Tests for environment-backed application settings."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from personal_ai.settings import Settings


def test_settings_load_from_example_file() -> None:
    """The committed example file is complete enough for local startup."""
    example_file = Path(__file__).parents[1] / ".env.example"

    settings = Settings(_env_file=example_file)

    assert settings.ai_provider == "gemini"
    assert settings.ai_model == "gemini-2.5-flash"
    assert settings.ai_api_key.get_secret_value() == ""
    assert settings.firestore_project_id == "example-personal-ai"
    assert settings.firestore_emulator_host == "localhost:8080"
    assert settings.request_timeout_seconds == 30
    assert settings.max_context_tokens == 32768
    assert not settings.context_inspection_enabled
    assert settings.allowed_web_origins == ["http://localhost:3000"]


def test_production_refuses_development_authentication() -> None:
    with pytest.raises(ValidationError, match="authentication_configuration_invalid"):
        Settings(
            ai_provider="gemini",
            ai_model="gemini-2.5-flash",
            app_environment="production",
            allowed_origins=("https://personal.example",),
        )


def test_oidc_production_requires_one_allowlisted_verified_account() -> None:
    settings = Settings(
        ai_provider="gemini",
        ai_model="gemini-2.5-flash",
        app_environment="production",
        auth_mode="google_oidc",
        auth_required=True,
        auth_audience="client-id.apps.googleusercontent.com",
        auth_allowed_emails=("owner@gmail.com",),
        allowed_origins=("https://personal.example",),
    )

    assert settings.auth_required
    assert settings.auth_allowed_emails == ("owner@gmail.com",)


@pytest.mark.parametrize("origin", [
    "http://personal.example", "https://personal.example/path", "https://personal.example/?query=1",
    "https://personal.example/#fragment", "https://user:password@personal.example", "https://*.example",
])
def test_deployed_origins_must_be_exact_https_origins(origin) -> None:
    with pytest.raises(ValidationError, match="authentication_configuration_invalid"):
        Settings(
            _env_file=None, ai_provider="gemini", ai_model="synthetic",
            app_environment="production", auth_mode="google_oidc", auth_required=True,
            auth_audience="client", auth_allowed_emails=("owner@gmail.com",),
            allowed_origins=(origin,),
        )


def test_deployed_environment_rejects_inherited_firestore_emulator() -> None:
    with pytest.raises(ValidationError, match="deployed_firestore_emulator_forbidden"):
        Settings(
            _env_file=None, ai_provider="gemini", ai_model="synthetic",
            app_environment="staging", auth_mode="google_oidc", auth_required=True,
            auth_audience="client", auth_allowed_emails=("owner@gmail.com",),
            allowed_origins=("https://personal.example",), firestore_emulator_host="localhost:8080",
        )


def test_required_authentication_cannot_silently_use_development_identity() -> None:
    with pytest.raises(ValidationError, match="authentication_configuration_invalid"):
        Settings(_env_file=None, ai_provider="fake", ai_model="test", auth_required=True)
