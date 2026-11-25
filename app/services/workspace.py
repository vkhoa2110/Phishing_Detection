"""SQLite accounts, sessions and private history; never store provider credentials."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
import unicodedata
import uuid

from app.core.accounts import new_token, password_hash, password_matches, token_hash
from app.core.privacy import redact
from app.core.settings import ROOT


@dataclass(frozen=True)
class WorkspaceSettings:
    database: Path = field(default_factory=lambda: ROOT / os.getenv("PHISHLENS_DATABASE", "data/application/phishlens.sqlite3"))
    session_seconds: int = 12 * 3600
    secure_cookie: bool = field(default_factory=lambda: os.getenv("PHISHLENS_COOKIE_SECURE", "0") == "1")
    daily_ai_limit: int = field(default_factory=lambda: int(os.getenv("PHISHLENS_DAILY_AI_LIMIT", "100")))


class WorkspaceError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def public_user(row):
    return {key: row[key] for key in ("id", "email", "display_name", "role", "active", "created_at")}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def search_text(value):
    return "".join(c for c in unicodedata.normalize("NFD", value.casefold()) if not unicodedata.combining(c)).replace("đ", "d")


class WorkspaceStore:
    def __init__(self, settings):
        self.settings = settings

    @contextmanager
    def connection(self, *, write=False):
        conn = sqlite3.connect(str(self.settings.database), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.create_function("search_text", 1, search_text, deterministic=True)
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        path = self.settings.database
        path.parent.mkdir(parents=True, exist_ok=True)
        # Only this application directory/database is managed here.
        if path.parent.name == "application":
            path.parent.chmod(0o700)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user','admin')),
                    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at REAL NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS rate_limits (
                    bucket TEXT PRIMARY KEY, started REAL NOT NULL, attempts INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS history (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL, title TEXT NOT NULL, mode TEXT NOT NULL,
                    risk TEXT NOT NULL, message_risk TEXT, url_risk TEXT,
                    url_count INTEGER NOT NULL, llm_status TEXT NOT NULL, profile TEXT,
                    favorite INTEGER NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', snapshot TEXT);
                CREATE INDEX IF NOT EXISTS history_owner ON history(user_id,created_at DESC);
                CREATE TABLE IF NOT EXISTS ai_usage (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    started REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS usage_owner ON ai_usage(user_id,started);
                CREATE TABLE IF NOT EXISTS extension_pairing (
                    code_hash TEXT PRIMARY KEY, session_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
                    expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS extension_devices (
                    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                    session_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
                    origin TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS remembered_devices (
                    id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    origin TEXT NOT NULL, created_at TEXT NOT NULL, expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    history_id TEXT REFERENCES history(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, comment TEXT NOT NULL, shared_snapshot TEXT,
                    status TEXT NOT NULL DEFAULT 'pending', review_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS feedback_owner ON feedback(user_id,created_at DESC);
                PRAGMA user_version=3;
            """)
        path.chmod(0o600)

    def rate_limit(self, bucket, maximum, seconds):
        now = time.time()
        with self.connection(write=True) as conn:
            conn.execute("DELETE FROM rate_limits WHERE started < ?", (now - 86400,))
            row = conn.execute("SELECT * FROM rate_limits WHERE bucket=?", (token_hash(bucket),)).fetchone()
            if row and row["started"] > now - seconds and row["attempts"] >= maximum:
                raise WorkspaceError(429, "Bạn đã thử quá nhiều lần. Vui lòng chờ rồi thử lại.")
            started, attempts = (row["started"], row["attempts"] + 1) if row and row["started"] > now - seconds else (now, 1)
            conn.execute("INSERT OR REPLACE INTO rate_limits VALUES (?,?,?)", (token_hash(bucket), started, attempts))

    def register(self, email, display_name, password):
        encoded = password_hash(password)
        try:
            with self.connection(write=True) as conn:
                first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                identity = uuid.uuid4().hex
                conn.execute("INSERT INTO users VALUES (?,?,?,?,?,1,?)",
                             (identity, email, display_name, encoded, "admin" if first else "user", stamp()))
                return public_user(conn.execute("SELECT * FROM users WHERE id=?", (identity,)).fetchone())
        except sqlite3.IntegrityError as exc:
            raise WorkspaceError(409, "Địa chỉ email này đã được đăng ký.") from exc

    def authenticate(self, email, password):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        valid = password_matches(password, row["password_hash"] if row else None)
        if not row or not valid or not row["active"]:
            raise WorkspaceError(401, "Email hoặc mật khẩu không đúng.")
        return public_user(row)

    def create_session(self, user_id):
        token = new_token()
        now = time.time()
        with self.connection(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            conn.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                         (token_hash(token), user_id, now + self.settings.session_seconds, stamp()))
        return token

    def session_user(self, token):
        if not token or len(token) > 100:
            return None
        with self.connection() as conn:
            row = conn.execute("SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id "
                "WHERE sessions.token_hash=? AND expires_at>? AND users.active=1", (token_hash(token), time.time())).fetchone()
        return public_user(row) if row else None

    def revoke_session(self, token):
        with self.connection(write=True) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))

    def update_profile(self, user_id, name):
        with self.connection(write=True) as conn:
            conn.execute("UPDATE users SET display_name=? WHERE id=?", (name, user_id))
            return public_user(conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def change_password(self, user_id, current, new):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not password_matches(current, row["password_hash"]):
            raise WorkspaceError(400, "Mật khẩu hiện tại không đúng.")
        encoded = password_hash(new)
        with self.connection(write=True) as conn:
            # Reject a concurrent password change rather than accepting stale credentials.
            result = conn.execute("UPDATE users SET password_hash=? WHERE id=? AND password_hash=?",
                                  (encoded, user_id, row["password_hash"]))
            if not result.rowcount:
                raise WorkspaceError(409, "Mật khẩu vừa thay đổi. Hãy đăng nhập lại.")
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM remembered_devices WHERE user_id=?", (user_id,))

    def reserve_ai(self, user_id):
        now = time.time()
        with self.connection(write=True) as conn:
            conn.execute("DELETE FROM ai_usage WHERE started < ?", (now - 86400 * 7,))
            count = conn.execute("SELECT COUNT(*) FROM ai_usage WHERE user_id=? AND started>?", (user_id, now - 86400)).fetchone()[0]
            if count >= self.settings.daily_ai_limit:
                raise WorkspaceError(429, "Đã hết lượt AI trong 24 giờ của tài khoản. Bạn vẫn có thể kiểm tra URL tại máy.")
            conn.execute("INSERT INTO ai_usage VALUES (?,?,?)", (uuid.uuid4().hex, user_id, now))

    def add_history(self, user_id, result, save_content, approved_text=""):
        identity = uuid.uuid4().hex
        snapshot = None
        if save_content:
            allowed = ("mode", "final", "assessments", "urls", "invalid_urls", "llm", "timing", "notice")
            forbidden = {"api_key", "endpoint", "headers", "authorization", "telemetry", "provider_quotes", "raw_response", "reasoning_content"}
            def scrub(value):
                if isinstance(value, dict):
                    return {key: scrub(item) for key, item in value.items() if key.casefold() not in forbidden}
                if isinstance(value, list):
                    return [scrub(item) for item in value]
                return redact(value)[0] if isinstance(value, str) else value
            snapshot = json.dumps(scrub({**{k: result[k] for k in allowed if k in result}, "approved_text": approved_text}), ensure_ascii=False)
            if len(snapshot.encode()) > 262144:
                raise WorkspaceError(413, "Kết quả quá lớn để lưu nội dung chi tiết.")
        llm, assessments = result["llm"], result["assessments"]
        with self.connection(write=True) as conn:
            conn.execute("INSERT INTO history (id,user_id,created_at,title,mode,risk,message_risk,url_risk,url_count,llm_status,profile,snapshot) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (identity, user_id, stamp(), "Kiểm tra URL" if result["mode"] == "url" else "Kiểm tra tin nhắn / email",
                result["mode"], result["final"]["risk_level"], assessments["message"].get("risk_level"),
                assessments["url"].get("risk_level"), len(result["urls"]), llm["status"],
                result.get("execution", {}).get("runtime", {}).get("profile"), snapshot))
        return identity

    def history(self, user_id, *, query="", risk="", favorite=False, page=1):
        clause, params = "user_id=?", [user_id]
        if query:
            clause += " AND (instr(search_text(title),search_text(?))>0 OR instr(search_text(note),search_text(?))>0)"
            params.extend([query, query])
        if risk:
            clause += " AND risk=?"; params.append(risk)
        if favorite:
            clause += " AND favorite=1"
        with self.connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM history WHERE " + clause, params).fetchone()[0]
            rows = conn.execute("SELECT id,created_at,title,mode,risk,message_risk,url_risk,url_count,llm_status,profile,favorite,note,"
                "snapshot IS NOT NULL AS content_saved FROM history WHERE " + clause + " ORDER BY created_at DESC LIMIT 20 OFFSET ?", [*params, (page - 1) * 20]).fetchall()
        return {"items": [dict(r) for r in rows], "total": count, "page": page, "page_size": 20}

    def history_item(self, user_id, identity):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM history WHERE id=? AND user_id=?", (identity, user_id)).fetchone()
        if not row:
            raise WorkspaceError(404, "Không tìm thấy kết quả này.")
        value = dict(row); value.pop("user_id")
        value["snapshot"] = json.loads(value["snapshot"]) if value["snapshot"] else None
        return value

    def update_history(self, user_id, identity, changes):
        if set(changes) - {"title", "note", "favorite"}:
            raise WorkspaceError(400, "Trường cập nhật không hợp lệ.")
        self.history_item(user_id, identity)
        if changes:
            with self.connection(write=True) as conn:
                conn.execute("UPDATE history SET " + ",".join(key + "=?" for key in changes) + " WHERE id=? AND user_id=?",
                             [*changes.values(), identity, user_id])
        return self.history_item(user_id, identity)

    def delete_history(self, user_id, identity=None):
        with self.connection(write=True) as conn:
            if identity:
                result = conn.execute("DELETE FROM history WHERE user_id=? AND id=?", (user_id, identity))
                if not result.rowcount:
                    raise WorkspaceError(404, "Không tìm thấy kết quả này.")
            else:
                conn.execute("DELETE FROM history WHERE user_id=?", (user_id,))

    def dashboard(self, user_id):
        with self.connection() as conn:
            risks = {r["risk"]: r["n"] for r in conn.execute("SELECT risk,COUNT(*) n FROM history WHERE user_id=? GROUP BY risk", (user_id,))}
            favorites = conn.execute("SELECT COUNT(*) FROM history WHERE user_id=? AND favorite=1", (user_id,)).fetchone()[0]
            used = conn.execute("SELECT COUNT(*) FROM ai_usage WHERE user_id=? AND started>?", (user_id, time.time() - 86400)).fetchone()[0]
        return {"total": sum(risks.values()), "risks": risks, "favorites": favorites,
                "ai_used_24h": used, "ai_limit_24h": self.settings.daily_ai_limit, "recent": self.history(user_id)["items"][:5]}

    def users(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT id,email,display_name,role,active,created_at FROM users ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def update_user(self, actor, identity, changes):
        if set(changes) - {"role", "active"}:
            raise WorkspaceError(400, "Trường cập nhật không hợp lệ.")
        if actor == identity:
            raise WorkspaceError(400, "Không thể đổi quyền hoặc khóa chính tài khoản quản trị đang dùng.")
        with self.connection(write=True) as conn:
            current_actor = conn.execute("SELECT active,role FROM users WHERE id=?", (actor,)).fetchone()
            if not current_actor or not current_actor["active"] or current_actor["role"] != "admin":
                raise WorkspaceError(403, "Quyền quản trị đã thay đổi. Hãy đăng nhập lại.")
            if not conn.execute("SELECT id FROM users WHERE id=?", (identity,)).fetchone():
                raise WorkspaceError(404, "Không tìm thấy tài khoản.")
            if changes:
                conn.execute("UPDATE users SET " + ",".join(key + "=?" for key in changes) + " WHERE id=?", [*changes.values(), identity])
            if changes.get("active") is False:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (identity,))
                conn.execute("DELETE FROM remembered_devices WHERE user_id=?", (identity,))
            return public_user(conn.execute("SELECT * FROM users WHERE id=?", (identity,)).fetchone())
