"""Real local QR decoding and partial OCR failure; no external service calls."""
from io import BytesIO
import subprocess

from fastapi.testclient import TestClient
import pytest

from app.services import qr_codes
from app.services.image_text import ImageTextService
from app.services.workspace import WorkspaceError
from tests.api.test_workspace import application, register
from tests.api.test_product_features import connect, ORIGIN


def qr_image(text="https://example.org/promotion?coupon=DEMO"):
    from PIL import Image
    zxingcpp = pytest.importorskip("zxingcpp")
    return Image.fromarray(zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.QRCode).to_image(scale=6))


def png(image):
    output = BytesIO(); image.save(output, format="PNG")
    return output.getvalue()


def qr_only():
    pytest.importorskip("zxingcpp")
    service = ImageTextService()
    service._status = {"ready": False, "qr_ready": True}
    return service


@pytest.mark.parametrize("variation", ["normal", "rotated", "inverted", "screenshot"])
def test_local_qr_decoder_reads_exact_url_under_image_transforms(variation):
    from PIL import Image, ImageOps
    image = qr_image()
    if variation == "rotated": image = image.rotate(90, expand=True)
    if variation == "inverted": image = ImageOps.invert(image.convert("L"))
    if variation == "screenshot":
        canvas = Image.new("RGB", (800, 600), "#eef1f9"); canvas.paste(image, (420, 210)); image = canvas
    result = qr_only().extract(png(image), "image/png")
    assert result["qr"]["codes"][0]["text"] == "https://example.org/promotion?coupon=DEMO"
    assert result["qr"]["codes"][0]["kind"] == "url"
    assert result["ocr_status"] == "unavailable" and result["text"] == ""
    assert result["provider_calls"] == 0 and result["image_saved"] is False


def test_multiple_qr_codes_deduplicate_and_keep_non_url_payload_separate():
    from PIL import Image
    texts = ["https://example.org/a", "WIFI:T:WPA;S:demo;P:private-example;;", "https://example.org/a"]
    canvas = Image.new("RGB", (1000, 320), "white")
    for index, text in enumerate(texts): canvas.paste(qr_image(text), (20 + 320 * index, 30))
    result = qr_only().extract(png(canvas), "image/png")
    codes = result["qr"]["codes"]
    assert [c["text"] for c in codes] == texts[:2]
    assert [c["kind"] for c in codes] == ["url", "text"]
    assert len(codes[0]["positions"]) == 2 and result["text"] == ""


def test_qr_limit_is_explicit_not_silent_truncation():
    from PIL import Image
    canvas = Image.new("RGB", (1000, 1000), "white")
    for index in range(9): canvas.paste(qr_image(f"https://example.org/{index}"), (15 + index % 3 * 330, 15 + index // 3 * 330))
    result = qr_only().extract(png(canvas), "image/png")["qr"]
    assert result["truncated"] is True and len(result["codes"]) == 8 and result["detected"] == 9


def test_qr_pixels_do_not_become_spurious_ocr_text(monkeypatch):
    from PIL import Image
    service = qr_only(); service._status["ready"] = True
    def recognize(payload):
        image = Image.open(BytesIO(payload))
        assert image.getextrema() == (255, 255), "QR pattern must be masked before OCR"
        return ""
    monkeypatch.setattr(service, "_read_text", recognize)
    result = service.extract(png(qr_image()), "image/png")
    assert result["text"] == "" and result["qr"]["status"] == "ok"


def test_qr_result_survives_ocr_timeout_without_claiming_text_was_read(monkeypatch):
    service = qr_only(); service._status["ready"] = True
    def timeout(payload): raise WorkspaceError(504, "OCR quá lâu.")
    monkeypatch.setattr(service, "_read_text", timeout)
    result = service.extract(png(qr_image()), "image/png")
    assert result["qr"]["status"] == "ok" and result["ocr_status"] == "error"
    assert result["ocr_error"] == "OCR quá lâu." and result["text"] == ""


@pytest.mark.parametrize("error,expected", [(subprocess.TimeoutExpired("private-data", 5), "timeout"), (OSError("private-path"), "error")])
def test_qr_process_failure_is_bounded_and_does_not_echo_private_details(monkeypatch, error, expected):
    monkeypatch.setattr(qr_codes, "available", lambda: True)
    def fail(*args, **kwargs):
        assert kwargs["timeout"] == 5 and "shell" not in kwargs
        assert args[0][-2:] == ["-m", "app.services.qr_codes"]
        raise error
    monkeypatch.setattr(subprocess, "run", fail)
    result = qr_codes.extract(b"validated-normalized-png")
    assert result == {"status": expected, "codes": [], "truncated": False}


def test_missing_optional_qr_decoder_does_not_start_a_process(monkeypatch):
    monkeypatch.setattr(qr_codes, "available", lambda: False)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("Unexpected process"))
    assert qr_codes.extract(b"unused")["status"] == "unavailable"


@pytest.mark.parametrize("text", ["javascript:alert(1)", "file:///etc/passwd", "https://", "WIFI:S:demo;;", "https://example.org/\nOTP", "https://example.org/\u202ebad", "https://example.org:bad/", "https://example.org\x00"])
def test_other_payloads_do_not_gain_a_check_url_action(text):
    assert qr_codes.is_web_url(text) is False


def test_authenticated_qr_endpoint_reuses_image_boundary_without_ai_or_history(application):
    application.state.extension_ocr = qr_only()
    with TestClient(application) as web, TestClient(application) as ext:
        register(web); auth = connect(web, ext)
        response = ext.post("/api/extension/image-text", headers={**auth, "Content-Type": "image/png"}, content=png(qr_image()))
        assert response.status_code == 200 and response.headers["access-control-allow-origin"] == ORIGIN
        assert response.json()["qr"]["codes"][0]["kind"] == "url"
        assert web.get("/api/dashboard").json()["ai_used_24h"] == 0
        assert web.get("/api/history").json()["total"] == 0
