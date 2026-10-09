from __future__ import annotations

from fastapi.testclient import TestClient

from personal_ai.api.dependencies import get_request_scope
from personal_ai.auth.scope import RequestScope
from personal_ai.main import app
from personal_ai.settings import Settings, get_settings


def _scope() -> RequestScope:
    return RequestScope(
        owner_id="usr_owner_0123456789abcdef",
        application_id="travel",
        workspace_id="trip-workspace-7",
        request_id="request-7",
    )


def _settings(**updates) -> Settings:
    values = {"ai_provider": "fake", "ai_model": "synthetic", "app_environment": "test"}
    values.update(updates)
    return Settings(**values)


def test_provider_usage_inspection_is_default_off(monkeypatch):
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.update({
        get_settings: lambda: _settings(),
        get_request_scope: _scope,
    })
    monkeypatch.setattr(
        "personal_ai.api.provider_usage.persistence_factory",
        lambda _settings: (_ for _ in ()).throw(AssertionError("storage must not be opened")),
    )
    try:
        response = TestClient(app).get("/v1/developer/provider-usage")
    finally:
        app.dependency_overrides = previous

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_provider_usage_inspection_uses_validated_owner_and_workspace_scope(monkeypatch):
    calls = []

    class Accounting:
        def summary(self, **scope):
            calls.append(scope)
            return {"schema_version": "provider-usage-summary-v1", **scope}

    class Persistence:
        def provider_usage_accounting(self, configured):
            assert configured.provider_usage_inspection_enabled
            return Accounting()

    previous = app.dependency_overrides.copy()
    app.dependency_overrides.update({
        get_settings: lambda: _settings(provider_usage_inspection_enabled=True),
        get_request_scope: _scope,
    })
    monkeypatch.setattr(
        "personal_ai.api.provider_usage.persistence_factory", lambda _settings: Persistence()
    )
    try:
        response = TestClient(app).get("/v1/developer/provider-usage?days=14")
    finally:
        app.dependency_overrides = previous

    assert response.status_code == 200
    assert calls == [{
        "owner_id": "usr_owner_0123456789abcdef",
        "application_id": "travel",
        "workspace_id": "trip-workspace-7",
        "days": 14,
    }]
    assert response.json()["owner_id"] == "usr_owner_0123456789abcdef"


def test_provider_usage_inspection_bounds_requested_window():
    previous = app.dependency_overrides.copy()
    app.dependency_overrides.update({
        get_settings: lambda: _settings(provider_usage_inspection_enabled=True),
        get_request_scope: _scope,
    })
    try:
        response = TestClient(app).get("/v1/developer/provider-usage?days=91")
    finally:
        app.dependency_overrides = previous

    assert response.status_code == 422
