"""Scoped browser connections and opt-in, reviewable user feedback."""
import json
import secrets
import time
import uuid

from app.core.accounts import new_token, token_hash
from app.core.privacy import redact
from app.services.workspace import WorkspaceError, stamp


class ProductStore:
    def __init__(self, workspace):
        self.workspace = workspace

    def pairing_code(self, session):
        code, now = secrets.token_hex(32), time.time()
        with self.workspace.connection(write=True) as conn:
            session_hash = token_hash(session)
            if not conn.execute("SELECT 1 FROM sessions WHERE token_hash=? AND expires_at>?", (session_hash, now)).fetchone():
                raise WorkspaceError(401, "Hãy đăng nhập lại để ghép nối.")
            conn.execute("DELETE FROM extension_pairing WHERE session_hash=? OR expires_at<?", (session_hash, now))
            conn.execute("INSERT INTO extension_pairing VALUES (?,?,?)", (token_hash(code), session_hash, now + 300))
        return {"code": code, "expires_in": 300}

    def connect(self, code, origin, remember=False):
        token, identity, now = new_token(), uuid.uuid4().hex, time.time()
        with self.workspace.connection(write=True) as conn:
            row = conn.execute("SELECT p.session_hash,s.expires_at,s.user_id FROM extension_pairing p JOIN sessions s ON s.token_hash=p.session_hash "
                "JOIN users u ON u.id=s.user_id WHERE p.code_hash=? AND p.expires_at>? AND s.expires_at>? AND u.active=1",
                (token_hash(code), now, now)).fetchone()
            if not row:
                raise WorkspaceError(401, "Mã ghép nối không đúng, đã dùng hoặc hết hạn. Tạo mã mới trong Tài khoản.")
            expires = now + 30 * 86400 if remember else row["expires_at"]
            if remember:
                conn.execute("DELETE FROM remembered_devices WHERE expires_at<?", (now,))
                count = conn.execute("SELECT COUNT(*) FROM remembered_devices WHERE user_id=?", (row["user_id"],)).fetchone()[0]
                if count >= 10:
                    raise WorkspaceError(409, "Đã đủ 10 kết nối ghi nhớ. Thu hồi một kết nối cũ trong Tài khoản.")
                conn.execute("INSERT INTO remembered_devices VALUES (?,?,?,?,?,?)", (identity, token_hash(token), row["user_id"], origin, stamp(), expires))
            else:
                count = conn.execute("SELECT COUNT(*) FROM extension_devices WHERE session_hash=?", (row["session_hash"],)).fetchone()[0]
                if count >= 10:
                    raise WorkspaceError(409, "Đã đủ 10 kết nối của phiên này. Hãy thu hồi một kết nối cũ.")
                conn.execute("INSERT INTO extension_devices VALUES (?,?,?,?,?)", (identity, token_hash(token), row["session_hash"], origin, stamp()))
            conn.execute("DELETE FROM extension_pairing WHERE code_hash=?", (token_hash(code),))
        return {"token": token, "id": identity, "expires_at": expires, "remember": remember}

    def extension_user(self, token, origin):
        if not token or len(token) > 100:
            return None
        with self.workspace.connection() as conn:
            remembered = conn.execute("SELECT u.id,u.email,u.display_name,u.role,u.active,u.created_at FROM remembered_devices d JOIN users u ON u.id=d.user_id "
                "WHERE d.token_hash=? AND d.origin=? AND d.expires_at>? AND u.active=1", (token_hash(token), origin, time.time())).fetchone()
            if remembered:
                return dict(remembered)
            row = conn.execute("SELECT u.id,u.email,u.display_name,u.role,u.active,u.created_at FROM extension_devices d "
                "JOIN sessions s ON s.token_hash=d.session_hash JOIN users u ON u.id=s.user_id "
                "WHERE d.token_hash=? AND d.origin=? AND s.expires_at>? AND u.active=1", (token_hash(token), origin, time.time())).fetchone()
        return dict(row) if row else None

    def devices(self, user_id):
        with self.workspace.connection() as conn:
            rows = conn.execute("SELECT d.id,d.origin,d.created_at,s.expires_at,0 AS remembered FROM extension_devices d "
                "JOIN sessions s ON s.token_hash=d.session_hash WHERE s.user_id=? AND s.expires_at>? ORDER BY d.created_at DESC",
                (user_id, time.time())).fetchall()
            persistent = conn.execute("SELECT id,origin,created_at,expires_at,1 AS remembered FROM remembered_devices WHERE user_id=? AND expires_at>? ORDER BY created_at DESC", (user_id, time.time())).fetchall()
        return {"items": sorted([dict(row) for row in [*rows, *persistent]], key=lambda row: row["created_at"], reverse=True)}

    def revoke_device(self, user_id, identity):
        with self.workspace.connection(write=True) as conn:
            result = conn.execute("DELETE FROM extension_devices WHERE id=? AND session_hash IN (SELECT token_hash FROM sessions WHERE user_id=?)", (identity, user_id))
            persistent = conn.execute("DELETE FROM remembered_devices WHERE id=? AND user_id=?", (identity, user_id))
            if not result.rowcount and not persistent.rowcount:
                raise WorkspaceError(404, "Không tìm thấy kết nối này.")

    def feedback(self, user_id, history_id, kind, comment, share):
        # Look up ownership inside the insertion transaction. Never trust a client-supplied result.
        with self.workspace.connection(write=True) as conn:
            record = conn.execute("SELECT * FROM history WHERE id=? AND user_id=?", (history_id, user_id)).fetchone()
            if not record:
                raise WorkspaceError(404, "Không tìm thấy kết quả này trong lịch sử của bạn.")
            if share and not record["snapshot"]:
                raise WorkspaceError(400, "Lượt này không lưu nội dung. Bạn có thể gửi phản hồi không kèm nội dung.")
            if conn.execute("SELECT 1 FROM feedback WHERE user_id=? AND history_id=? AND status='pending'", (user_id, history_id)).fetchone():
                raise WorkspaceError(409, "Kết quả này đã có phản hồi đang chờ xử lý.")
            # Only classification metadata is shared by default. Titles and private notes are excluded.
            shared = {key: record[key] for key in ("mode", "risk", "message_risk", "url_risk", "url_count", "llm_status", "profile")}
            if share:
                shared["result"] = json.loads(record["snapshot"])
            identity, now = uuid.uuid4().hex, stamp()
            conn.execute("INSERT INTO feedback (id,user_id,history_id,kind,comment,shared_snapshot,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (identity, user_id, history_id, kind, redact(comment)[0], json.dumps(shared, ensure_ascii=False), now, now))
        return {"id": identity, "status": "pending"}

    def feedback_list(self, user_id, *, admin=False, page=1, status=""):
        clause, params = ("1=1", []) if admin else ("user_id=?", [user_id])
        if status:
            clause += " AND status=?"; params.append(status)
        with self.workspace.connection() as conn:
            total = conn.execute("SELECT COUNT(*) FROM feedback WHERE " + clause, params).fetchone()[0]
            rows = conn.execute("SELECT * FROM feedback WHERE " + clause + " ORDER BY created_at DESC LIMIT 20 OFFSET ?", [*params, (page - 1) * 20]).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item.pop("user_id")
            item["shared_snapshot"] = json.loads(item["shared_snapshot"])
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": 20}

    def delete_feedback(self, user_id, identity):
        with self.workspace.connection(write=True) as conn:
            if not conn.execute("DELETE FROM feedback WHERE user_id=? AND id=?", (user_id, identity)).rowcount:
                raise WorkspaceError(404, "Không tìm thấy phản hồi này.")

    def review_feedback(self, actor, identity, status, note):
        with self.workspace.connection(write=True) as conn:
            admin = conn.execute("SELECT 1 FROM users WHERE id=? AND active=1 AND role='admin'", (actor,)).fetchone()
            if not admin:
                raise WorkspaceError(403, "Quyền quản trị đã thay đổi.")
            if not conn.execute("UPDATE feedback SET status=?,review_note=?,updated_at=? WHERE id=?", (status, redact(note)[0], stamp(), identity)).rowcount:
                raise WorkspaceError(404, "Không tìm thấy phản hồi này.")
        return {"ok": True}
