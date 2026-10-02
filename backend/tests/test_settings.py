"""Tests for environment-backed application settings."""

from pathlib import Path

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
