"""Local guest and account application around the unchanged analysis runtime."""
from contextlib import asynccontextmanager
import hmac
import os
import re
import sqlite3
from typing import Literal
from urllib.parse import quote

from fastapi import HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.api.runtime import create_app as create_runtime
from app.core.accounts import csrf_token, new_token
from app.core.privacy import redact
from app.core.settings import ROOT
from app.domain.schemas import AnalyzeInput
from app.services.workspace import WorkspaceError, WorkspaceSettings, WorkspaceStore
from app.services.product_features import ProductStore
from app.api.browser_extension import extension_access, install_extension
from app.services.llm.decision_explanation import REQUESTED as EXPLANATION_REQUESTED

SESSION = "phishlens_session"
PREAUTH = "phishlens_login"
STATIC = ROOT / "app/static"


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LoginInput(StrictInput):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def email_address(cls, value):
        value = value.strip().casefold()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Invalid email")
        return value


class RegisterInput(LoginInput):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("Invalid name")
        return value


class PasswordInput(StrictInput):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class ProfileInput(StrictInput):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def name(cls, value):
        return RegisterInput.name(value)


class HistoryInput(StrictInput):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=1000)
    favorite: bool | None = None

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Empty title")
        return value.strip() if value is not None else value


class AdminInput(StrictInput):
    role: Literal["user", "admin"] | None = None
    active: bool | None = None


class WorkspaceAnalyzeInput(AnalyzeInput):
    save_history: bool = True
    save_content: bool = False
    explain_evidence: bool = False


class FeedbackInput(StrictInput):
    history_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    kind: Literal["false_alarm", "missed_risk", "unclear", "other"]
    comment: str = Field(default="", max_length=2000)
    share_content: bool = False


class FeedbackReview(StrictInput):
    status: Literal["pending", "reviewed", "dismissed"]
    review_note: str = Field(default="", max_length=2000)


def create_app(profile=None, settings=None, transport=None, model_service=None, rag_service=None, workspace_settings=None):
    profile = profile or os.getenv("PHISHLENS_PROFILE", "stable")
    if profile == "quality-v4":
        profile = "stable"
    config = workspace_settings or WorkspaceSettings()
    if not 1 <= config.daily_ai_limit <= 10000 or config.session_seconds < 60:
        raise ValueError("Invalid workspace quota or session duration")
    app = create_runtime(profile, settings, transport, model_service, rag_service)
    store = WorkspaceStore(config)
    products = ProductStore(store)
    app.state.workspace = store
    app.state.active_analyses = set()
    original_lifespan = app.router.lifespan_context
    original_analyze = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/analyze")
    original_validation = app.exception_handlers[RequestValidationError]
    app.router.routes[:] = [r for r in app.routes if getattr(r, "path", None) not in {"/", "/api/analyze"}]

    @asynccontextmanager
    async def lifespan(instance):
        await run_in_threadpool(store.initialize)
        async with original_lifespan(instance):
            yield

    app.router.lifespan_context = lifespan

    @app.exception_handler(WorkspaceError)
    async def domain_error(request, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path.startswith(("/api/extension/", "/api/feedback", "/api/browser/")):
            return JSONResponse({"detail": "Thông tin không hợp lệ. Kiểm tra nội dung và thử lại."}, status_code=422)
        if request.url.path.startswith(("/api/auth/", "/api/history", "/api/admin/")):
            return JSONResponse({"detail": "Thông tin chưa hợp lệ. Kiểm tra email, tên và độ dài mật khẩu (mật khẩu mới từ 12 đến 128 ký tự)."}, status_code=422)
        return await original_validation(request, exc)

    def cookie(response, name, token, seconds):
        response.set_cookie(name, token, httponly=True, samesite="strict", secure=config.secure_cookie,
                            max_age=seconds, path="/")

    def session_response(user, old=None):
        if old:
            store.revoke_session(old)
        token = store.create_session(user["id"])
        response = JSONResponse({"user": user, "csrf_token": csrf_token(token)})
        cookie(response, SESSION, token, config.session_seconds)
        response.delete_cookie(PREAUTH, path="/")
        return response

    @app.middleware("http")
    async def workspace_access(request: Request, call_next):
        path = request.url.path
        if path.startswith("/static/"):
            return await call_next(request)
        if path.startswith("/api/extension/"):
            return await extension_access(request, call_next, products)
        raw = request.cookies.get(SESSION, "")
        user = await run_in_threadpool(store.session_user, raw)
        request.state.account = user
        public = path in {"/", "/check", "/login", "/register", "/api/auth/session", "/api/auth/login", "/api/auth/register", "/api/health",
                          "/api/status", "/api/preview", "/api/analyze", "/api/clarify/preview", "/api/browser/download"}
        if not user and not public:
            response = JSONResponse({"detail": "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."}, status_code=401) if path.startswith("/api/") else RedirectResponse("/login?next=" + quote("/dashboard" if path == "/" else path), status_code=303)
        elif user and ((path.startswith("/api/admin/") or path in {"/admin", "/api/model/reload"}) and user["role"] != "admin"):
            response = JSONResponse({"detail": "Chức năng này dành cho quản trị viên."}, status_code=403)
        elif request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            raw_csrf = raw if user else request.cookies.get(PREAUTH, "")
            supplied = request.headers.get("x-csrf-token", "")
            if (origin and origin != str(request.base_url).rstrip("/")) or not raw_csrf or not re.fullmatch(r"[a-f0-9]{64}", supplied) or not hmac.compare_digest(supplied, csrf_token(raw_csrf)):
                response = JSONResponse({"detail": "Phiên xác nhận không hợp lệ. Tải lại trang rồi thử lại."}, status_code=403)
            else:
                try:
                    declared = int(request.headers.get("content-length", "0"))
                except ValueError:
                    declared = 65537
                if declared > 65536 or len(await request.body()) > 65536:
                    response = JSONResponse({"detail": "Yêu cầu quá lớn."}, status_code=413)
                else:
                    response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"})
        return response

    @app.get("/")
    def home(request: Request):
        return RedirectResponse("/dashboard" if request.state.account else "/check", status_code=303)

    @app.get("/api/health")
    def health():
        return {"application": "PhishLens", "workspace": True, "ready": True, "features": ["browser_extension", "feedback", "image_text", "guest_access", "extension_no_pairing"]}

    @app.get("/check")
    def check():
        return FileResponse(STATIC / "index.html")

    @app.get("/login")
    @app.get("/register")
    def auth_page(request: Request):
        return RedirectResponse("/dashboard", status_code=303) if request.state.account else FileResponse(STATIC / "account.html")

    @app.get("/dashboard")
    @app.get("/history")
    @app.get("/account")
    @app.get("/feedback")
    @app.get("/admin")
    def portal():
        return FileResponse(STATIC / "portal.html")

    @app.get("/api/auth/session")
    def session(request: Request):
        user = request.state.account
        token = request.cookies.get(SESSION if user else PREAUTH) or new_token()
        response = JSONResponse({"enabled": True, "guest_access": True, "user": user, "csrf_token": csrf_token(token),
            "first_account": not store.users(), "session_seconds": config.session_seconds})
        if not user:
            cookie(response, PREAUTH, token, 1800)
        return response

    @app.post("/api/auth/register")
    def register(data: RegisterInput, request: Request):
        store.rate_limit("register:" + request.client.host, 10, 3600)
        if len(data.password) < 12:
            raise WorkspaceError(422, "Mật khẩu cần từ 12 đến 128 ký tự.")
        user = store.register(data.email, data.display_name, data.password)
        return session_response(user, request.cookies.get(SESSION))

    @app.post("/api/auth/login")
    def login(data: LoginInput, request: Request):
        store.rate_limit("login-ip:" + request.client.host, 30, 900)
        store.rate_limit("login-email:" + data.email, 10, 900)
        user = store.authenticate(data.email, data.password)
        return session_response(user, request.cookies.get(SESSION))

    @app.post("/api/auth/logout")
    def logout(request: Request):
        store.revoke_session(request.cookies.get(SESSION, ""))
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION, path="/")
        response.delete_cookie(PREAUTH, path="/")
        return response

    @app.patch("/api/auth/profile")
    def profile_update(data: ProfileInput, request: Request):
        return {"user": store.update_profile(request.state.account["id"], data.display_name)}

    @app.post("/api/auth/password")
    def password_update(data: PasswordInput, request: Request):
        store.rate_limit("password:" + request.state.account["id"], 10, 900)
        store.change_password(request.state.account["id"], data.current_password, data.new_password)
        return session_response(request.state.account)

    @app.get("/api/dashboard")
    def dashboard(request: Request):
        return store.dashboard(request.state.account["id"])

    @app.get("/api/history")
    def history(request: Request, q: str = Query(default="", max_length=100),
                risk: Literal["", "HIGH", "WARNING", "LOW", "UNKNOWN"] = "", favorite: bool = False, page: int = Query(default=1, ge=1, le=100000)):
        return store.history(request.state.account["id"], query=q, risk=risk, favorite=favorite, page=page)

    @app.get("/api/history/{identity}")
    def history_item(identity: str, request: Request):
        return store.history_item(request.state.account["id"], identity)

    @app.patch("/api/history/{identity}")
    def history_update(identity: str, data: HistoryInput, request: Request):
        return store.update_history(request.state.account["id"], identity, data.model_dump(exclude_none=True))

    @app.delete("/api/history/{identity}")
    def history_delete(identity: str, request: Request):
        store.delete_history(request.state.account["id"], identity)
        return {"ok": True}

    @app.delete("/api/history")
    def history_clear(request: Request):
        store.delete_history(request.state.account["id"])
        return {"ok": True}

    @app.get("/api/admin/users")
    def users():
        return {"items": store.users()}

    @app.patch("/api/admin/users/{identity}")
    def user_update(identity: str, data: AdminInput, request: Request):
        return {"user": store.update_user(request.state.account["id"], identity, data.model_dump(exclude_none=True))}

    @app.post("/api/browser/pairing")
    def browser_pairing(request: Request):
        store.rate_limit("pairing:" + request.state.account["id"], 20, 900)
        return products.pairing_code(request.cookies[SESSION])

    @app.get("/api/browser/download")
    def browser_download():
        from scripts.maintenance.package_extension import extension_zip
        return Response(extension_zip(), media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="phishlens-extension.zip"'})

    @app.get("/api/browser/devices")
    def browser_devices(request: Request):
        return products.devices(request.state.account["id"])

    @app.delete("/api/browser/devices/{identity}")
    def browser_revoke(identity: str, request: Request):
        products.revoke_device(request.state.account["id"], identity)
        return {"ok": True}

    @app.post("/api/feedback")
    def feedback_create(data: FeedbackInput, request: Request):
        store.rate_limit("feedback:" + request.state.account["id"], 30, 3600)
        return products.feedback(request.state.account["id"], data.history_id, data.kind, data.comment, data.share_content)

    @app.get("/api/feedback")
    def feedback_list(request: Request, page: int = Query(default=1, ge=1, le=100000)):
        return products.feedback_list(request.state.account["id"], page=page)

    @app.delete("/api/feedback/{identity}")
    def feedback_delete(identity: str, request: Request):
        products.delete_feedback(request.state.account["id"], identity)
        return {"ok": True}

    @app.get("/api/admin/feedback")
    def feedback_queue(request: Request, page: int = Query(default=1, ge=1, le=100000), status: Literal["", "pending", "reviewed", "dismissed"] = ""):
        return products.feedback_list(request.state.account["id"], admin=True, page=page, status=status)

    @app.patch("/api/admin/feedback/{identity}")
    def feedback_review(identity: str, data: FeedbackReview, request: Request):
        return products.review_feedback(request.state.account["id"], identity, data.status, data.review_note)

    @app.post("/api/analyze")
    async def analyze(data: WorkspaceAnalyzeInput, request: Request):
        user = request.state.account
        # Guests have no user row or personal history. Share limits between web
        # and extension by socket peer, independent of cookies/extension IDs.
        identity = user["id"] if user else "guest:" + (request.client.host if request.client else "unknown")
        if identity in app.state.active_analyses:
            raise HTTPException(409, "Một lượt kiểm tra của bạn đang chạy. Hãy chờ kết quả.")
        if len(app.state.active_analyses) >= 4:
            raise HTTPException(429, "Ứng dụng đang xử lý nhiều lượt kiểm tra. Vui lòng thử lại sau.")
        app.state.active_analyses.add(identity)
        try:
            # Validate consent/connection before reserving paid usage.
            if data.use_llm and (not data.consent or data.endpoint or data.model or data.api_key.get_secret_value()):
                raise HTTPException(422, "Cần xác nhận bản gửi và dùng kết nối AI do máy chủ quản lý.")
            if data.use_llm:
                if user:
                    await run_in_threadpool(store.reserve_ai, identity)
                else:
                    await run_in_threadpool(store.rate_limit, "ai:" + identity, config.daily_ai_limit, 86400)
            core_input = AnalyzeInput.model_validate({k: getattr(data, k) for k in AnalyzeInput.model_fields})
            explanation_token = EXPLANATION_REQUESTED.set(data.explain_evidence)
            try:
                result = await original_analyze(core_input, request)
            finally:
                EXPLANATION_REQUESTED.reset(explanation_token)
            if user and data.save_history:
                try:
                    approved = result["llm"].get("input_used") or redact(data.llm_text if data.use_llm and data.llm_text is not None else data.text)[0]
                    record = await run_in_threadpool(store.add_history, identity, result, data.save_content, approved)
                    result["history"] = {"status": "saved", "id": record, "content_saved": data.save_content}
                except (sqlite3.Error, WorkspaceError):
                    result["history"] = {"status": "error", "message": "Chưa lưu được lịch sử. Bạn vẫn có thể tải kết quả JSON."}
            else:
                result["history"] = {"status": "disabled", **({"reason": "guest", "message": "Chế độ khách không lưu lịch sử. Bạn có thể tải kết quả JSON hoặc đăng nhập cho các lượt tiếp theo."} if not user else {})}
            return result
        finally:
            app.state.active_analyses.discard(identity)

    install_extension(app, products, analyze, WorkspaceAnalyzeInput)
    return app
