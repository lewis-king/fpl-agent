from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fplagent_web.app import create_app
from fplagent_web.uploads import UploadStore

PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-body"


def test_upload_store_accepts_supported_image_and_persists_status(tmp_path: Path) -> None:
    store = UploadStore(tmp_path)

    accepted = store.create("my-team.png", PNG)
    status = store.get(accepted.upload_id)

    assert accepted.media_type == "image/png"
    assert status.status == "uploaded"
    assert status.filename == "my-team.png"
    assert status.image_sha256 == accepted.image_sha256
    assert store.image_path(accepted.upload_id).read_bytes() == PNG


def test_upload_api_rejects_non_image(tmp_path: Path) -> None:
    store = UploadStore(tmp_path)
    client = TestClient(create_app(uploads_factory=lambda: store))

    response = client.post(
        "/api/v1/uploads/team",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_image"


def test_upload_api_serves_image_and_status(tmp_path: Path) -> None:
    store = UploadStore(tmp_path)
    client = TestClient(create_app(uploads_factory=lambda: store))

    created = client.post(
        "/api/v1/uploads/team",
        files={"file": ("my-team.png", PNG, "image/png")},
    )
    upload_id = created.json()["upload_id"]
    status = client.get(f"/api/v1/uploads/{upload_id}")
    image = client.get(f"/api/v1/uploads/{upload_id}/image")

    assert created.status_code == 201
    assert status.json()["status"] == "uploaded"
    assert image.status_code == 200
    assert image.content == PNG
