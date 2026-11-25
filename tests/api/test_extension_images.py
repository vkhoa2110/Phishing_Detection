"""Authenticated binary boundary and image decoding. No real provider calls."""
from io import BytesIO
from unittest.mock import Mock
import subprocess

from fastapi.testclient import TestClient
import pytest

from app.services.image_text import ImageTextService, MAX_BYTES
from app.services.workspace import WorkspaceError
from tests.api.test_workspace import application, register, headers
from tests.api.test_product_features import connect, EXTENSION, ORIGIN


def png(size=(200, 90), format="PNG"):
    from PIL import Image
    buffer = BytesIO(); Image.new("RGB", size, "white").save(buffer, format=format)
    return buffer.getvalue()


@pytest.fixture
def ocr(monkeypatch):
    service = ImageTextService(); service.binary = "test-ocr"
    service._status = {"ready": True, "languages": ["vie", "eng"]}
    monkeypatch.setattr(subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0, stdout="Hãy gửi mã OTP".encode(), stderr=b"")))
    return service


def test_binary_image_endpoint_requires_scoped_bearer_before_decoding(application):
    with TestClient(application) as web, TestClient(application) as ext:
        register(web)
        # A web cookie cannot rescue an invalid account bearer; guests omit it.
        assert web.post("/api/extension/image-text", headers={"X-PhishLens-Extension": EXTENSION, "Authorization": "Bearer invalid", "Content-Type": "image/png"}, content=png()).status_code == 401
        assert ext.post("/api/extension/image-text", headers={"Origin": "https://foreign.example", "X-PhishLens-Extension": EXTENSION}, content=png()).status_code == 403
        assert ext.post("/api/extension/image-text", headers={"X-PhishLens-Extension": EXTENSION, "Authorization": "Bearer invalid"}, content=png()).status_code == 401


def test_binary_image_endpoint_accepts_bounded_image_without_AI_usage_or_history(application, ocr):
    application.state.extension_ocr = ocr
    with TestClient(application) as web, TestClient(application) as ext:
        register(web); auth = connect(web, ext)
        response = ext.post("/api/extension/image-text", headers={**auth, "Content-Type": "image/png"}, content=png())
        assert response.status_code == 200, response.text
        assert response.json()["text"] == "Hãy gửi mã OTP" and response.json()["provider_calls"] == 0
        assert response.json()["image_saved"] is False and response.headers["access-control-allow-origin"] == ORIGIN
        assert web.get("/api/dashboard").json()["ai_used_24h"] == 0
        assert web.get("/api/history").json()["total"] == 0


def test_binary_image_rejects_non_images_corruption_and_oversized_requests(application, ocr):
    application.state.extension_ocr = ocr
    with TestClient(application) as web, TestClient(application) as ext:
        register(web); auth = connect(web, ext)
        assert ext.post("/api/extension/image-text", headers={**auth, "Content-Type": "image/svg+xml"}, content=b"<svg/>").status_code == 415
        assert ext.post("/api/extension/image-text", headers={**auth, "Content-Type": "image/png"}, content=b"not-a-png").status_code == 415
        assert ext.post("/api/extension/image-text", headers={**auth, "Content-Type": "image/png"}, content=b"x" * (MAX_BYTES + 1)).status_code == 413
        # Existing JSON endpoints retain the much smaller bound.
        assert ext.post("/api/extension/preview", headers={**auth, "Content-Type": "application/json"}, content=b"x" * 70000).status_code == 413


@pytest.mark.parametrize("payload,mime,status", [(lambda: png((4001, 3000)), "image/png", 413), (lambda: png((10, 10)), "image/png", 413), (lambda: png(), "image/jpeg", 415)])
def test_decoder_enforces_dimensions_and_content_type_before_ocr(ocr, payload, mime, status):
    with pytest.raises(WorkspaceError) as error: ocr.extract(payload(), mime)
    assert error.value.status == status
    subprocess.run.assert_not_called()


def test_ocr_uses_stdin_and_timeout_and_never_opens_an_image_url(ocr):
    response = ocr.extract(png(), "image/png")
    args, options = subprocess.run.call_args
    assert "stdin" in args[0] and "stdout" in args[0] and "vie+eng" in args[0]
    assert options["timeout"] == 20 and options["input"].startswith(b"\x89PNG")
    assert "shell" not in options and response["local_only"]
    assert ocr.slots.acquire(blocking=False); ocr.slots.release()


def test_ocr_timeout_releases_slot_and_does_not_expose_stderr(ocr):
    subprocess.run.side_effect = subprocess.TimeoutExpired("private-file-path", 20)
    with pytest.raises(WorkspaceError) as error: ocr.extract(png(), "image/png")
    assert error.value.status == 504 and "private-file-path" not in error.value.message
    assert ocr.slots.acquire(blocking=False); ocr.slots.release()


def test_ocr_never_silently_truncates_long_text_or_hides_empty_result(ocr):
    subprocess.run.return_value.stdout = b"x" * 8001
    with pytest.raises(WorkspaceError) as error: ocr.extract(png(), "image/png")
    assert error.value.status == 413
    subprocess.run.return_value.stdout = b" \n"
    assert ocr.extract(png(), "image/png")["status"] == "empty"


def test_missing_optional_engine_is_actionable_and_cannot_invoke_a_process(ocr):
    ocr._status = {"ready": False}
    with pytest.raises(WorkspaceError) as error: ocr.extract(png(), "image/png")
    assert error.value.status == 503 and "Tesseract" in error.value.message
    subprocess.run.assert_not_called()


def test_ocr_bound_limits_parallel_work_and_releases_after_failure(ocr):
    assert ocr.slots.acquire(blocking=False) and ocr.slots.acquire(blocking=False)
    with pytest.raises(WorkspaceError) as error: ocr.extract(png(), "image/png")
    assert error.value.status == 429
    subprocess.run.assert_not_called()
    ocr.slots.release(); ocr.slots.release()
