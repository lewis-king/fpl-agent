from fastapi.testclient import TestClient

import fplagent_web.app as module


def test_scouting_get_is_cached_and_post_separate_from_auth_or_decisions(monkeypatch):
    calls = []
    monkeypatch.setattr(module, "read_scouting", lambda: {"status": "cached", "players": []})
    monkeypatch.setattr(
        module, "refresh_scouting", lambda: calls.append("scouting") or {"status": "ready"}
    )
    client = TestClient(module.create_app())
    assert client.get("/api/v1/scouting").json()["status"] == "cached"
    assert calls == []
    assert client.post("/api/v1/scouting/refresh").json()["status"] == "ready"
    assert calls == ["scouting"]


def test_failed_scouting_refresh_does_not_leak_paths(monkeypatch):
    def fail():
        raise ValueError("private source path")

    monkeypatch.setattr(module, "refresh_scouting", fail)
    response = TestClient(module.create_app()).post("/api/v1/scouting/refresh")
    assert response.status_code == 503
    assert "private" not in response.text
