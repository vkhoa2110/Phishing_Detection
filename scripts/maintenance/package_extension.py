"""Create the unpackable browser extension ZIP from an explicit source allowlist."""
from io import BytesIO
from pathlib import Path
import argparse
import os
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
FILES = ("manifest.json", "background.js", "workspace.js", "analysis-jobs.js", "assistant.js", "mail.js", "mail-reader.js", "mail-annotations.js", "region-capture.js", "region.js", "floating.js", "check.html", "check.js", "images.js", "check.css", "README.md",
         "icons/16.png", "icons/48.png", "icons/128.png")


def extension_zip():
    source = ROOT / "extensions/chromium"
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            path = source / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("Thiếu file extension: " + name)
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 24, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/distributions/phishlens-extension.zip")
    parser.add_argument("--force", action="store_true", help="Replace an existing generated ZIP")
    args = parser.parse_args()
    payload = extension_zip()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.force:
        with tempfile.NamedTemporaryFile(dir=args.out.parent, delete=False) as target:
            temporary = Path(target.name)
            target.write(payload)
        try:
            os.replace(temporary, args.out)
        finally:
            temporary.unlink(missing_ok=True)
    else:
        with args.out.open("xb") as target:
            target.write(payload)
    print("Đã tạo gói extension:", args.out)


if __name__ == "__main__":
    main()
