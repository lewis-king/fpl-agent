from types import SimpleNamespace

from fastapi.testclient import TestClient

import pytest

import fplagent_web.app as module


@pytest.fixture(autouse=True)
def no_top_manager_sampling(monkeypatch):
    sampled = []
    monkeypatch.setattr(module, "latest_finished_event", lambda: 10)
    monkeypatch.setattr(module, "ensure_elite_sample", sampled.append)
    return sampled


def test_review_requires_manager_id_without_contacting_any_service(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network/service work must not be performed without an entry ID")

    monkeypatch.setattr(module, "refresh_gameweek_review", forbidden)
    app = module.create_app(
        profile_factory=lambda: SimpleNamespace(get=lambda: SimpleNamespace(fpl_entry_id=None))
    )
    client = TestClient(app)
    assert client.get("/api/v1/review").json()["status"] == "manager_required"
    assert client.post("/api/v1/review/refresh").status_code == 400


def test_review_endpoint_is_separate_from_decision_refresh(monkeypatch, no_top_manager_sampling):
    calls = []

    def refresh(entry_id):
        calls.append(entry_id)
        return {"status": "ready", "events": []}

    monkeypatch.setattr(module, "refresh_gameweek_review", refresh)
    monkeypatch.setattr(
        module, "read_gameweek_review", lambda entry: {"status": "cached", "entry_id": entry}
    )
    app = module.create_app(
        profile_factory=lambda: SimpleNamespace(get=lambda: SimpleNamespace(fpl_entry_id=42))
    )
    client = TestClient(app)
    assert client.get("/api/v1/review").json()["status"] == "cached"
    assert calls == []
    assert client.post("/api/v1/review/refresh").json()["status"] == "ready"
    assert no_top_manager_sampling == [10]
    assert calls == [42]


def test_review_error_does_not_leak_private_paths(monkeypatch):
    def fail(_):
        raise ValueError("sensitive internal details")

    monkeypatch.setattr(module, "refresh_gameweek_review", fail)
    app = module.create_app(
        profile_factory=lambda: SimpleNamespace(get=lambda: SimpleNamespace(fpl_entry_id=42))
    )
    response = TestClient(app).post("/api/v1/review/refresh")
    assert response.status_code == 503
    assert "sensitive" not in response.text
