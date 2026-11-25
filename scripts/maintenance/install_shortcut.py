"""Install a per-user Linux application shortcut; no startup service or root access."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def desktop_quote(path):
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path.home() / ".local/share/applications/phishlens-local.desktop")
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        raise SystemExit("Linux dùng shortcut này; Windows mở start_phishlens.bat.")
    target = args.out.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SystemExit("Shortcut đã tồn tại; giữ file cũ: " + str(target))
    text = ("[Desktop Entry]\nType=Application\nName=PhishLens\nComment=Kiểm tra dấu hiệu lừa đảo trong URL và thông điệp\n"
        + "Exec=" + desktop_quote(ROOT / "start_phishlens.sh") + "\n"
        + "Path=" + str(ROOT) + "\nIcon=" + str(ROOT / "app/static/shield.svg")
        + "\nTerminal=true\nCategories=Utility;Security;\nStartupNotify=false\n")
    with target.open("x", encoding="utf-8") as handle:
        handle.write(text)
    target.chmod(0o755)
    print("Đã tạo shortcut PhishLens:", target)
    print("Mở PhishLens trong menu ứng dụng. Shortcut phụ thuộc vị trí repository hiện tại.")


if __name__ == "__main__":
    main()
