from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.services.analysis import AnalysisInputError, AnalysisService, MESSAGE_PROFILE, PIPELINE_VERSION
from app.domain.decisions import POLICY_VERSION
from app.services.llm.client import LLMService
from app.services.url.features import ModelService
from app.core.privacy import redact
from app.services.rag.retrieval import RAGService
from app.domain.schemas import AnalyzeInput, InputData
from app.core.settings import ROOT, Settings
from app.services.url.parsing import extract_urls

STATIC = ROOT / "app/static"


def create_app(settings: Settings | None = None, transport=None, model_service=None, rag_service=None) -> FastAPI:
    settings = settings or Settings()
    ml = model_service or ModelService(settings)
    rag = rag_service or RAGService(settings, include_scope=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, transport=transport, trust_env=False) as client:
            app.state.llm = LLMService(settings, client)
            app.state.analysis = AnalysisService(ml, rag, app.state.llm)
            yield

    app = FastAPI(title="PhishLens · ML + LLM + RAG", version="1.3.0", lifespan=lifespan)
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
                                "message_prompt_profile": MESSAGE_PROFILE, "pipeline_version": PIPELINE_VERSION,
                                "headline_target": "message_actions"},
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
        try:
            return await request.app.state.analysis.analyze(data)
        except AnalysisInputError as exc:
            raise HTTPException(422, str(exc)) from exc

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
