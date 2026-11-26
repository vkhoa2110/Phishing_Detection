"""Narrow extension API: public guest analysis and legacy scoped account bearers."""
import inspect
import re
import hashlib
from contextlib import asynccontextmanager

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.domain.schemas import InputData
from app.services.workspace import WorkspaceError
from app.services.image_text import ImageTextService, MAX_BYTES, MIMES
from app.services.analysis_jobs import AnalysisJobs


class PairInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(pattern=r"^[a-f0-9]{64}$")
    remember: bool = False


class ExtensionAnalyze(InputData):
    model_config = ConfigDict(extra="forbid", strict=True)
    use_llm: bool = False
    include_ml: bool = False
    use_rag: bool = False
    consent: bool = False
    llm_text: str | None = Field(default=None, max_length=8000)
    save_history: bool = True
    save_content: bool = False
    explain_evidence: bool = False


class JobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    id: str = Field(pattern=r"^[a-f0-9-]{36}$")


class JobStart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    client_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_key: str = Field(pattern=r"^[a-f0-9-]{36}$")
    payload: ExtensionAnalyze


async def extension_access(request, call_next, products):
    identity = request.headers.get("x-phishlens-extension", "")
    origin = request.headers.get("origin", "")
    if not identity and request.method == "OPTIONS" and re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
        identity = origin.rsplit("/", 1)[-1]
    expected = "chrome-extension://" + identity
    allowed = {"/api/extension/connect", "/api/extension/session", "/api/extension/preview", "/api/extension/analyze", "/api/extension/disconnect", "/api/extension/image-text", "/api/extension/jobs/start", "/api/extension/jobs/status"}

    def response(message, status):
        return JSONResponse({"detail": message}, status_code=status)

    if not re.fullmatch(r"[a-p]{32}", identity) or (origin and origin != expected):
        return response("Nguồn kết nối extension không hợp lệ.", 403)
    if request.url.path not in allowed:
        result = response("Không tìm thấy chức năng extension.", 404)
    elif request.method == "OPTIONS":
        requested = {v.strip().lower() for v in request.headers.get("access-control-request-headers", "").split(",") if v.strip()}
        if request.headers.get("access-control-request-method") != "POST" or requested - {"authorization", "content-type", "x-phishlens-extension"}:
            result = response("Yêu cầu kết nối không hợp lệ.", 403)
        else:
            result = JSONResponse({"ok": True})
    elif request.method != "POST":
        result = response("Chỉ hỗ trợ POST.", 405)
    else:
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError:
            declared = MAX_BYTES + 1
        image_request = request.url.path == "/api/extension/image-text"
        if declared > (MAX_BYTES if image_request else 65536):
            result = response("Yêu cầu quá lớn.", 413)
        elif image_request:
            # Handle bounded binary images here, outside the frozen JSON runtime.
            raw = request.headers.get("authorization", "")
            user = await run_in_threadpool(products.extension_user, raw[7:] if raw.startswith("Bearer ") else "", expected)
            if raw and not user:
                result = response("Kết nối tài khoản đã hết hạn hoặc bị thu hồi. Hãy kết nối lại ở chế độ khách.", 401)
            else:
                try:
                    mime = request.headers.get("content-type", "").split(";")[0].strip().lower()
                    if mime not in MIMES:
                        raise WorkspaceError(415, "Chỉ nhận ảnh PNG, JPEG hoặc WebP.")
                    identity = user["id"] if user else "guest:" + (request.client.host if request.client else "unknown")
                    await run_in_threadpool(products.workspace.rate_limit, "ocr:" + identity, 30, 3600)
                    payload = bytearray()
                    async for chunk in request.stream():
                        if len(payload) + len(chunk) > MAX_BYTES:
                            raise WorkspaceError(413, "Ảnh tối đa 5 MB. Hãy cắt ảnh nhỏ hơn.")
                        payload.extend(chunk)
                    data = await run_in_threadpool(request.app.state.extension_ocr.extract, bytes(payload), mime)
                    result = JSONResponse(data)
                except WorkspaceError as exc:
                    result = response(exc.message, exc.status)
        elif len(await request.body()) > 65536:
            result = response("Yêu cầu quá lớn.", 413)
        else:
            raw = request.headers.get("authorization", "")
            user = await run_in_threadpool(products.extension_user, raw[7:] if raw.startswith("Bearer ") else "", expected)
            request.state.account = user
            request.state.extension_origin = expected
            if raw and not user and request.url.path != "/api/extension/connect":
                result = response("Kết nối tài khoản đã hết hạn hoặc bị thu hồi. Hãy kết nối lại ở chế độ khách.", 401)
            else:
                # The frozen inner runtime accepts same-origin web requests only.
                # Origin is checked above; an explicit bearer must be valid.
                # Adapt only this scoped API without broadening global CORS.
                original_headers = request.scope["headers"]
                request.scope["headers"] = [(key, value) for key, value in original_headers if key.lower() != b"origin"]
                try:
                    result = await call_next(request)
                finally:
                    request.scope["headers"] = original_headers
    result.headers.update({"Access-Control-Allow-Origin": expected, "Vary": "Origin",
        "Access-Control-Allow-Methods": "POST", "Access-Control-Allow-Headers": "Authorization, Content-Type, X-PhishLens-Extension",
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
    return result


def install_extension(app, products, analyze, analyze_type):
    app.state.extension_ocr = ImageTextService()
    jobs = app.state.extension_jobs = AnalysisJobs()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with original_lifespan(instance):
            try:
                yield
            finally:
                await jobs.close()

    app.router.lifespan_context = lifespan
    preview = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/preview")
    status = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/status")

    @app.post("/api/extension/connect")
    def connect(data: PairInput, request: Request):
        products.workspace.rate_limit("extension-connect:" + request.client.host, 20, 900)
        return products.connect(data.code, request.state.extension_origin, data.remember)

    @app.post("/api/extension/session")
    async def session(request: Request):
        data = await status() if inspect.iscoroutinefunction(status) else await run_in_threadpool(status)
        user = request.state.account
        return {"guest": user is None, "user": {"display_name": user["display_name"] if user else "Chế độ khách"}, "ml_ready": data["ml"]["ready"],
            "llm_ready": data["llm"]["has_api_key"], "model": data["llm"]["model"], "rag_ready": data.get("rag", {}).get("ready", False),
            "evidence_explanation_available": data.get("runtime", {}).get("evidence_explanation_available", False), "analysis_jobs": True,
            "limits": data["limits"],
            "ocr": await run_in_threadpool(app.state.extension_ocr.status)}

    @app.post("/api/extension/preview")
    async def preview_input(data: InputData):
        return await preview(data) if inspect.iscoroutinefunction(preview) else await run_in_threadpool(preview, data)

    @app.post("/api/extension/analyze")
    async def analyze_input(data: ExtensionAnalyze, request: Request):
        if data.use_llm and (not data.consent or not data.llm_text or not data.llm_text.strip()):
            raise WorkspaceError(422, "Hãy xem trước và xác nhận bản nội dung gửi AI.")
        return await analyze(analyze_type.model_validate(data.model_dump()), request)

    def owner(request, key):
        user = request.state.account
        identity = user["id"] if user else "guest:" + (request.client.host if request.client else "unknown")
        return hashlib.sha256((identity + "|" + request.state.extension_origin + "|" + key).encode()).hexdigest()

    @app.post("/api/extension/jobs/start")
    async def start_job(data: JobStart, request: Request):
        payload = data.payload
        if payload.use_llm and (not payload.consent or not payload.llm_text or not payload.llm_text.strip()):
            raise WorkspaceError(422, "Hãy xem trước và xác nhận bản nội dung gửi AI.")
        validated = analyze_type.model_validate(payload.model_dump())
        # Retain only the scope needed by analysis, not a connection/receive task.
        scope = dict(request.scope)
        scope["state"] = dict(request.scope.get("state", {}))
        detached = Request(scope)
        return jobs.start(owner(request, data.client_key), data.request_key, payload.model_dump(),
                          lambda: analyze(validated, detached))

    @app.post("/api/extension/jobs/status")
    async def job_status(data: JobStatus, request: Request):
        return jobs.get(owner(request, data.client_key), data.id)

    @app.post("/api/extension/disconnect")
    def disconnect(request: Request):
        if not request.state.account:
            return {"ok": True}
        from app.core.accounts import token_hash
        with products.workspace.connection(write=True) as conn:
            conn.execute("DELETE FROM extension_devices WHERE token_hash=? AND origin=?",
                         (token_hash(request.headers["authorization"][7:]), request.state.extension_origin))
            conn.execute("DELETE FROM remembered_devices WHERE token_hash=? AND origin=?",
                         (token_hash(request.headers["authorization"][7:]), request.state.extension_origin))
        return {"ok": True}
