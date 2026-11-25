"""Install an optional user-local Tesseract runtime on Ubuntu without sudo.

Downloads apt-indexed packages and extracts into ignored models/ocr. Does not
modify OS packages. Other platforms should install Tesseract normally.
"""
import argparse
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ("tesseract-ocr", "libtesseract5", "libleptonica6", "tesseract-ocr-eng", "tesseract-ocr-vie")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if platform.system() != "Linux" or platform.machine() != "x86_64" or not shutil.which("apt-get") or not shutil.which("dpkg-deb"):
        raise SystemExit("Cài Tesseract + dữ liệu vie/eng theo docs/guides/OCR.md trên hệ điều hành này.")
    destination = ROOT / "models/ocr"
    if (destination / "usr/bin/tesseract").exists():
        raise SystemExit("Đã có runtime models/ocr; giữ nguyên. Kiểm bằng launch.py --check và khởi động lại ứng dụng.")
    packages = destination / "packages"; packages.mkdir(parents=True, exist_ok=True)
    subprocess.run(["apt-get", "download", *PACKAGES], cwd=packages, check=True)
    files = sorted(packages.glob("*.deb"))
    for path in files:
        subprocess.run(["dpkg-deb", "-x", str(path), str(destination)], check=True)
    (destination / "installation.json").write_text(json.dumps({"source": "Ubuntu apt packages, user-local extraction",
        "packages": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}, indent=2) + "\n")
    import sys
    sys.path.insert(0, str(ROOT))
    from app.services.image_text import ImageTextService
    ready = ImageTextService().status()["ready"]
    print("OCR tiếng Việt/Anh:", "sẵn sàng. Khởi động lại PhishLens." if ready else "thiếu thư viện hệ thống. Xem docs/guides/OCR.md.")
    if not ready: raise SystemExit(1)


if __name__ == "__main__":
    main()
