"""One-click local launcher: preflight, reuse a healthy instance, open browser."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parent


def health(base):
    try:
        with build_opener(ProxyHandler({})).open(base + "/api/health", timeout=1) as response:
            data = json.load(response)
            return data.get("application") == "PhishLens" and data.get("ready") is True and {"browser_extension", "image_text"}.issubset(data.get("features", []))
    except (URLError, OSError, ValueError):
        return False


def diagnostics(profile):
    required = {"fastapi": "fastapi", "uvicorn": "uvicorn", "httpx": "httpx", "dotenv": "python-dotenv", "numpy": "numpy", "sklearn": "scikit-learn", "xgboost": "xgboost"}
    missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
    if missing:
        print("Thiếu thư viện:", ", ".join(missing))
        print("Cài phụ thuộc theo README.md: .venv/bin/python -m pip install -r requirements.txt")
        return False
    from app.core.settings import Settings
    config = Settings()
    # Check installed assets, never train/download a replacement or print credentials.
    character = profile in {"focused", "verifier-shadow", "candidate"} and os.getenv("PHISHLENS_CANDIDATE_URL_MODEL", "char") != "xgboost"
    model = ROOT / "models/url_character" if character else ROOT / config.model_dir
    available = (model / "export.json").is_file() and (model / "weights.npz").is_file() if character else (model / "predict_url.py").is_file()
    print("Model URL:", "đã có asset" if available else "thiếu asset; xem models/README.md")
    print("Dịch vụ AI:", "đã có cấu hình key; chưa gọi nhà cung cấp" if config.api_key else "chưa có key; vẫn kiểm tra URL tại máy được")
    rag = (ROOT / config.rag_model_dir).is_dir() and (ROOT / config.rag_index_dir).is_dir()
    print("Tài liệu RAG:", "đã có thư mục model/index; ứng dụng sẽ kiểm tra khi nạp" if rag else "chưa đủ asset; vẫn có thể kiểm tra URL / AI không RAG")
    from app.services.image_text import ImageTextService
    image_status = ImageTextService().status()
    print("Đọc ảnh OCR:", "sẵn sàng tiếng Việt/Anh tại máy" if image_status["ready"] else "chưa cài; xem docs/guides/OCR.md")
    print("Giải mã QR:", "sẵn sàng tại máy" if image_status.get("qr_ready") else "chưa cài; cài requirements/ocr.txt rồi khởi động lại")
    return available


def port_available(port):
    with socket.socket() as sock:
        # A recently stopped server may leave TIME_WAIT connections. Uvicorn
        # reuses these addresses too; they must not look like a live listener.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def main():
    os.chdir(ROOT)
    virtual = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    if Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        if not virtual.is_file():
            raise SystemExit("Chưa có .venv. Làm theo bước cài đặt trong README.md rồi mở lại PhishLens.")
        os.execv(str(virtual), [str(virtual), str(Path(__file__).resolve()), *sys.argv[1:]])
    if importlib.util.find_spec("dotenv"):
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8001")))
    parser.add_argument("--profile", choices=["stable", "focused", "verifier-shadow"], default=os.getenv("PHISHLENS_PROFILE", "stable"))
    parser.add_argument("--check", action="store_true", help="Kiểm tra cài đặt, không chạy server hoặc gọi AI")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Cổng cần trong khoảng 1024–65535.")
    base = f"http://127.0.0.1:{args.port}"
    if not args.check and health(base):
        print("PhishLens đang chạy:", base)
        if not args.no_browser:
            webbrowser.open(base + "/check")
        return
    if not diagnostics(args.profile):
        raise SystemExit(1)
    if args.check:
        return
    if not port_available(args.port):
        raise SystemExit(f"Cổng {args.port} đang được dùng bởi tiến trình khác hoặc PhishLens phiên bản cũ. Đóng cửa sổ chạy cũ, hoặc dùng --port 8002.")
    env = {**os.environ, "PORT": str(args.port), "PHISHLENS_PROFILE": args.profile, "PHISHLENS_ACCOUNTS": "1"}
    process = subprocess.Popen([sys.executable, str(ROOT / "run.py")], cwd=ROOT, env=env)
    try:
        deadline = time.monotonic() + 75
        while not health(base):
            if process.poll() is not None:
                raise SystemExit("Ứng dụng chưa khởi động được. Xem thông báo phía trên và kiểm tra README.md.")
            if time.monotonic() > deadline:
                raise SystemExit("Ứng dụng khởi động quá lâu. Kiểm tra asset và thông báo phía trên.")
            time.sleep(.4)
        print("\nPhishLens sẵn sàng:", base + "/check", flush=True)
        print("Mở trang kiểm tra để dùng ngay. Không cần tạo tài khoản.", flush=True)
        print("Giữ cửa sổ này mở khi dùng ứng dụng. Nhấn Ctrl+C để dừng.", flush=True)
        if not args.no_browser:
            webbrowser.open(base + "/check")
        process.wait()
    except KeyboardInterrupt:
        print("\nĐang dừng PhishLens…")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()


if __name__ == "__main__":
    main()
