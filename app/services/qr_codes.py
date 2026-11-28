"""Decode user-selected QR images locally, with a disposable bounded process.

Payloads are data: never open a decoded URL, execute it, or contact a provider.
"""
import importlib.util
import json
import subprocess
import sys
import unicodedata
from urllib.parse import urlsplit

from app.core.settings import ROOT

MAX_CODES = 8
TIMEOUT = 5


def available():
    return importlib.util.find_spec("zxingcpp") is not None


def is_web_url(text):
    if len(text) > 8000 or any(c.isspace() or unicodedata.category(c).startswith("C") for c in text):
        return False
    try:
        value = urlsplit(text)
        return value.scheme.lower() in {"http", "https"} and bool(value.hostname) and value.port != 0
    except ValueError:
        return False


def decode_image(image):
    """Runs only in the child process; bytes are decoded losslessly as UTF-8."""
    import zxingcpp

    seen, codes = set(), []
    results = zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode)
    results.sort(key=lambda value: (value.position.top_left.y, value.position.top_left.x))
    for result in results:
        raw = result.bytes
        points = [result.position.top_left, result.position.top_right,
                  result.position.bottom_left, result.position.bottom_right]
        left, top = min(p.x for p in points), min(p.y for p in points)
        bounds = {"x": left, "y": top, "width": max(p.x for p in points) - left,
                  "height": max(p.y for p in points) - top}
        if raw in seen:
            # Keep every position for OCR masking, including repeated payloads.
            next(code for code in codes if code.get("_raw") == raw)["positions"].append(bounds)
            continue
        seen.add(raw)
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            codes.append({"kind": "binary", "text": "", "positions": [bounds], "_raw": raw})
            continue
        codes.append({"kind": "url" if is_web_url(text) else "text", "text": text, "positions": [bounds], "_raw": raw})
    for code in codes:
        code.pop("_raw")
    return {"status": "ok" if codes else "empty", "codes": codes[:MAX_CODES],
            "detected": len(codes), "truncated": len(codes) > MAX_CODES}


def extract(png):
    if not available():
        return {"status": "unavailable", "codes": [], "truncated": False}
    try:
        result = subprocess.run([sys.executable, "-m", "app.services.qr_codes"], cwd=ROOT,
            input=png, capture_output=True, timeout=TIMEOUT)
        if result.returncode or len(result.stdout) > 256_000:
            raise ValueError("Decoder failed")
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "codes": [], "truncated": False}
    except (OSError, ValueError):
        return {"status": "error", "codes": [], "truncated": False}


if __name__ == "__main__":
    from io import BytesIO
    from PIL import Image

    # Only the validated, normalized PNG from ImageTextService reaches stdin.
    with Image.open(BytesIO(sys.stdin.buffer.read(16 * 1024 * 1024 + 1))) as image:
        print(json.dumps(decode_image(image), ensure_ascii=True))
