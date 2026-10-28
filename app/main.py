from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .fusion import POLICY_VERSION, fuse
from .llm_service import LLMFailure, LLMService
from .ml_service import ModelService
from .privacy import redact
from .rag_service import RAGService
from .schemas import AnalyzeInput, InputData
from .settings import Settings
from .urls import extract_urls

STATIC = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None, transport=None, model_service=None, rag_service=None) -> FastAPI:
    settings = settings or Settings()
    ml = model_service or ModelService(settings)
    rag = rag_service or RAGService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, transport=transport, trust_env=False) as client:
            app.state.llm = LLMService(settings, client)
            yield

    app = FastAPI(title="PhishLens · ML + LLM + RAG", version="1.2.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
    app.state.ml = ml

    @app.middleware("http")
    async def local_privacy_headers(request: Request, call_next):
        if request.method == "POST" and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse({"detail": "Chỉ nhận yêu cầu từ giao diện cùng địa chỉ."}, status_code=403)
            try:
                declared = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Content-Length không hợp lệ."}, status_code=400)
            if declared > 65_536 or len(await request.body()) > 65_536:
                return JSONResponse({"detail": "Yêu cầu quá lớn."}, status_code=413)
        response = await call_next(request)
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Không trả lại body/API key trong lỗi validation.
        return JSONResponse({"detail": "Dữ liệu chưa hợp lệ. Giới hạn 8.000 ký tự, tối đa 5 URL; kiểm tra các trường nhập."}, status_code=422)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    async def status():
        return {"ml": await run_in_threadpool(ml.load), "llm": {"endpoint": settings.endpoint,
            "model": settings.llm_model, "has_api_key": bool(settings.api_key), "rag": False},
            "rag": await run_in_threadpool(rag.status),
            "analysis_policy": {"version": POLICY_VERSION, "default_include_ml": False,
                                "message_prompt_profile": "message-v2", "headline_target": "message_actions"},
            "limits": {"characters": 8000, "urls": 5, "llm_timeout_seconds": settings.timeout_seconds}}

    @app.post("/api/model/reload")
    async def reload_model():
        return await run_in_threadpool(ml.load, reload=True)

    @app.post("/api/preview")
    def preview(data: InputData):
        try:
            good, invalid = extract_urls(data.text, data.mode)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        text, fields = redact(data.text)
        return {"text": text, "masked_fields": fields, "url_count": len(good), "invalid_count": len(invalid)}

    @app.post("/api/analyze")
    async def analyze(data: AnalyzeInput, request: Request):
        if data.use_llm and not data.consent:
            raise HTTPException(422, "Cần xem bản nội dung gửi ra ngoài và xác nhận trước khi gọi LLM.")
        try:
            urls, invalid = extract_urls(data.text, data.mode)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        started = time.perf_counter()
        ml_started = time.perf_counter()
        url_results = await run_in_threadpool(ml.predict, urls) if urls else []
        ml_ms = round((time.perf_counter() - ml_started) * 1000, 1)
        llm = {"status": "disabled", "message": "Chưa bật phân tích bằng LLM.", "rag": False}
        retrieval = {"status": "disabled", "sources": [], "reason": "Chưa bật tham khảo tài liệu RAG."}
        if data.use_llm:
            text, fields = redact(data.llm_text if data.llm_text is not None else data.text)
            if not text.strip():
                raise HTTPException(422, "Bản gửi tới LLM không được để trống.")
            if data.use_rag:
                retrieval = await run_in_threadpool(rag.search, text, data.mode)
            try:
                llm = await request.app.state.llm.analyze(text=text, mode=data.mode, urls=url_results,
                    include_ml=data.include_ml, endpoint=data.endpoint, model=data.model,
                    api_key=data.api_key.get_secret_value(), rag_sources=retrieval["sources"],
                    prompt_profile="message-v2" if data.mode == "text" else "legacy")
                llm["masked_fields"] = fields
                llm["input_modified"] = text != redact(data.text)[0]
            except LLMFailure as exc:
                llm = {"status": "error", "code": exc.code, "message": exc.message, "rag": False}
        decision = fuse(data.mode, url_results, llm, invalid)
        result = {
            "created_at": datetime.now(timezone.utc).isoformat(), "mode": data.mode,
            "configuration": ("ML + LLM" if data.use_llm and data.include_ml else "ML / LLM độc lập" if data.use_llm else "ML") + (" + RAG" if llm.get("rag") else ""),
            "final": decision, "assessments": decision["assessments"], "urls": url_results,
            "invalid_urls": invalid, "llm": llm, "ml": ml.status(), "retrieval": retrieval,
            "timing": {"ml_ms": ml_ms, "total_ms": round((time.perf_counter() - started) * 1000, 1)},
            "notice": "Nhận định hành vi áp dụng cho bản nội dung đã gửi LLM. Cảnh báo URL được đánh giá riêng tại máy. Mức thấp không bảo đảm an toàn; ứng dụng không mở trang đích.",
        }
        return result

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()

