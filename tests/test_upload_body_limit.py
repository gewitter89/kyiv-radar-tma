# -*- coding: utf-8 -*-
"""Regression tests for pre-multipart upload request size enforcement."""
import os
import sys

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("BOT_TOKEN", "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.testclient import TestClient
from server.kyiv_radar_api import (
    UploadBodyLimitMiddleware, MAX_UPLOAD_REQUEST_BYTES, app as production_app,
)

UPLOAD_PATH = "/api/landlords/upload_photos"


def mini_client(max_bytes=1024):
    app = FastAPI()
    app.add_middleware(UploadBodyLimitMiddleware, max_body_bytes=max_bytes)

    @app.post(UPLOAD_PATH)
    async def upload(photos: list[UploadFile] = File(...), initData: str = Form(...)):
        return {"count": len(photos)}

    @app.post("/api/unrelated")
    async def unrelated():
        return {"ok": True}

    return TestClient(app)


def test_small_multipart_upload_is_not_blocked():
    client = mini_client()
    response = client.post(
        UPLOAD_PATH, data={"initData": "test"},
        files=[("photos", ("demo.jpg", b"x" * 120, "image/jpeg"))],
    )
    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_declared_large_body_rejected_before_form_parsing():
    client = mini_client()
    response = client.post(
        UPLOAD_PATH,
        content=b"short",
        headers={"Content-Length": "2048", "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert "request body" in response.json()["detail"]


def test_chunked_large_multipart_rejected_without_content_length():
    client = mini_client()
    boundary = "upload-probe"
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="initData"\r\n\r\n'
        "test\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="photos"; filename="demo.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode("ascii")
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    response = client.post(
        UPLOAD_PATH,
        content=iter([prefix, b"x" * 1536, suffix]),
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Transfer-Encoding": "chunked",
        },
    )
    assert response.status_code == 413
    assert "request body" in response.json()["detail"]


def test_unrelated_endpoint_is_not_size_limited():
    response = mini_client().post("/api/unrelated", content=b"x" * 5000)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_production_app_registers_gate_and_preserves_cors():
    assert any(
        middleware.cls is UploadBodyLimitMiddleware
        for middleware in production_app.user_middleware
    )
    assert MAX_UPLOAD_REQUEST_BYTES == 33 * 1024 * 1024
    response = TestClient(production_app).post(
        UPLOAD_PATH,
        content=b"x",
        headers={
            "Content-Length": str(MAX_UPLOAD_REQUEST_BYTES + 1),
            "Content-Type": "application/octet-stream",
            "Origin": "https://gewitter89.github.io",
        },
    )
    assert response.status_code == 413
    assert response.headers.get("access-control-allow-origin") == "https://gewitter89.github.io"
