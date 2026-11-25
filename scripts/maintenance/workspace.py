"""Local operator backup and account recovery. Never accept a password as an argument."""
import argparse
import getpass
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.accounts import password_hash
from app.services.workspace import WorkspaceSettings, WorkspaceStore


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or destination.suffix != ".sqlite3":
        raise ValueError("Cần database nguồn đã tồn tại và file đích có đuôi .sqlite3.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.touch(exist_ok=False, mode=0o600)
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as original, sqlite3.connect(destination) as copy:
            original.backup(copy)
    except Exception:
        destination.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("backup"); save.add_argument("--out", type=Path, required=True)
    reset = commands.add_parser("reset-password"); reset.add_argument("--email", required=True)
    args = parser.parse_args()
    settings = WorkspaceSettings()
    if not settings.database.is_file():
        raise SystemExit("Chưa có database ứng dụng. Hãy chạy ứng dụng và tạo tài khoản trước.")
    if args.command == "backup":
        backup(settings.database, args.out)
        print("Đã sao lưu database vào file mới.")
    else:
        store = WorkspaceStore(settings)
        with store.connection() as conn:
            row = conn.execute("SELECT id FROM users WHERE email=?", (args.email.strip().casefold(),)).fetchone()
        if not row:
            raise SystemExit("Không tìm thấy tài khoản.")
        password = getpass.getpass("Mật khẩu mới (12–128 ký tự): ")
        repeated = getpass.getpass("Nhập lại mật khẩu mới: ")
        if not 12 <= len(password) <= 128 or password != repeated:
            raise SystemExit("Mật khẩu không hợp lệ hoặc không trùng nhau.")
        encoded = password_hash(password)
        with store.connection(write=True) as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, row["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
            # Older database snapshots may predate remembered extension devices.
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='remembered_devices'").fetchone():
                conn.execute("DELETE FROM remembered_devices WHERE user_id=?", (row["id"],))
        print("Đã đặt lại mật khẩu và kết thúc mọi phiên đăng nhập của tài khoản.")


if __name__ == "__main__":
    main()
