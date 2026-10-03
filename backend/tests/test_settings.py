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
