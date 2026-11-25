"""Local OCR for user-selected raster images; no files, URLs or provider calls."""
from io import BytesIO
import os
from pathlib import Path
import shutil
import subprocess
import threading
import warnings

from app.core.settings import ROOT
from app.services.workspace import WorkspaceError

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
MIMES = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


class ImageTextService:
    def __init__(self):
        local = ROOT / "models/ocr/usr/bin/tesseract"
        self.binary = os.getenv("PHISHLENS_OCR_BIN") or (str(local) if local.is_file() else shutil.which("tesseract"))
        self.data = os.getenv("PHISHLENS_OCR_TESSDATA") or (str(ROOT / "models/ocr/usr/share/tesseract-ocr/5/tessdata") if local.is_file() else None)
        self.env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        library = ROOT / "models/ocr/usr/lib/x86_64-linux-gnu"
        if local.is_file() and library.is_dir():
            self.env["LD_LIBRARY_PATH"] = str(library) + (":" + self.env["LD_LIBRARY_PATH"] if self.env.get("LD_LIBRARY_PATH") else "")
        self.slots = threading.BoundedSemaphore(2)
        self._status = None

    def command(self):
        return [self.binary, *(["--tessdata-dir", self.data] if self.data else [])]

    def status(self):
        if self._status is None:
            available = False
            try:
                import PIL  # Optional dependency; the rest of the app works without OCR.
                if self.binary:
                    result = subprocess.run([*self.command(), "--list-langs"], capture_output=True, timeout=5, env=self.env)
                    languages = result.stdout.decode("utf-8", "replace").splitlines()
                    available = result.returncode == 0 and {"vie", "eng"}.issubset(languages)
            except (ImportError, OSError, subprocess.TimeoutExpired):
                pass
            self._status = {"ready": available, "languages": ["vie", "eng"] if available else [], "local_only": True,
                "max_bytes": MAX_BYTES, "max_pixels": MAX_PIXELS,
                "message": "Đọc chữ tiếng Việt/Anh tại máy" if available else "Chưa cài OCR tiếng Việt/Anh. Xem hướng dẫn OCR; bạn vẫn có thể dán văn bản."}
        return dict(self._status)

    def extract(self, payload, mime):
        if not self.status()["ready"]:
            raise WorkspaceError(503, "Chưa có OCR cục bộ. Cài Tesseract tiếng Việt/Anh theo hướng dẫn rồi khởi động lại PhishLens.")
        if mime not in MIMES or not payload:
            raise WorkspaceError(415, "Chọn ảnh PNG, JPEG hoặc WebP.")
        if len(payload) > MAX_BYTES:
            raise WorkspaceError(413, "Ảnh tối đa 5 MB. Hãy cắt vùng nội dung cần kiểm tra.")
        if not self.slots.acquire(blocking=False):
            raise WorkspaceError(429, "Máy đang đọc ảnh khác. Hãy chờ một chút rồi thử lại.")
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(BytesIO(payload)) as original:
                        if original.format != MIMES[mime] or getattr(original, "n_frames", 1) != 1:
                            raise WorkspaceError(415, "Cần ảnh tĩnh PNG, JPEG hoặc WebP đúng định dạng.")
                        if original.width * original.height > MAX_PIXELS or min(original.size) < 20:
                            raise WorkspaceError(413, "Ảnh cần từ 20 px mỗi chiều và không quá 12 triệu điểm ảnh. Hãy cắt vùng chứa chữ.")
                        image = ImageOps.exif_transpose(original).convert("RGBA")
                        background = Image.new("RGBA", image.size, "white")
                        background.alpha_composite(image)
                        image = ImageOps.autocontrast(background.convert("L"))
                        width, height = image.size
                        normalized = BytesIO(); image.save(normalized, format="PNG")
            except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise WorkspaceError(415, "Không đọc được ảnh. Hãy xuất lại thành PNG hoặc JPEG và thử lại.") from exc
            try:
                result = subprocess.run([*self.command(), "stdin", "stdout", "-l", "vie+eng", "--psm", "6"],
                    input=normalized.getvalue(), capture_output=True, timeout=20, env=self.env)
            except subprocess.TimeoutExpired as exc:
                raise WorkspaceError(504, "Đọc ảnh quá lâu. Hãy cắt ảnh nhỏ hơn hoặc dán văn bản.") from exc
            except OSError as exc:
                raise WorkspaceError(503, "OCR chưa sẵn sàng. Kiểm tra cài đặt Tesseract.") from exc
            if result.returncode:
                raise WorkspaceError(422, "Không trích được chữ từ ảnh này. Thử ảnh rõ hơn hoặc cắt sát nội dung.")
            text = "".join(c for c in result.stdout.decode("utf-8", "replace") if c.isprintable() or c in "\n\t").strip()
            if len(text) > 8000:
                raise WorkspaceError(413, "Ảnh có hơn 8.000 ký tự. Hãy cắt thành từng vùng; ứng dụng không tự cắt mất nội dung.")
            return {"text": text, "status": "ok" if text else "empty", "width": width, "height": height,
                "local_only": True, "image_saved": False, "provider_calls": 0,
                "notice": "Hãy sửa lỗi nhận dạng, đặc biệt dấu tiếng Việt, số và URL, trước khi phân tích. OCR chỉ đọc chữ, chưa phân tích hình ảnh hoặc giải mã QR."}
        finally:
            self.slots.release()
