"""Application composition for the accepted v4 policy; v3 remains reproducible.

Reuses existing HTTP routes/security and workflow, selecting versioned services
through a new factory instead of rewriting registered baseline source files.
"""
from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
from starlette.concurrency import run_in_threadpool

from .analysis_service import AnalysisService
from .fusion import POLICY_VERSION
from .main import create_app as create_baseline_app
from .message_service import MessageService, PROFILE
from .ml_service import ModelService
from .rag_service import RAGService
from .settings import Settings
from .url_policy import ConservativeURLModel, VERSION as URL_POLICY

PIPELINE = "analysis-pipeline-4.0"


class QualityAnalysis(AnalysisService):
    async def analyze(self, data):
        result = await super().analyze(data)
        result["execution"]["version"] = PIPELINE
        llm = result["execution"]["llm"]
        llm["requested_schema_profile"] = llm["requested_profile"]
        llm["requested_profile"] = PROFILE if data.mode == "text" and data.use_llm else llm["requested_profile"]
        result["execution"]["url"]["decision_policy"] = URL_POLICY
        return result


def create_app(settings=None, transport=None, model_service=None, rag_service=None):
    settings = settings or Settings()
    settings = replace(settings, max_tokens=min(settings.max_tokens, 8192))
    ml = ConservativeURLModel(model_service or ModelService(settings))
    rag = rag_service or RAGService(settings, include_scope=True)
    app = create_baseline_app(settings, transport, ml, rag)

    @asynccontextmanager
    async def lifespan(instance):
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, transport=transport, trust_env=False) as client:
            instance.state.llm = MessageService(settings, client)
            instance.state.analysis = QualityAnalysis(ml, rag, instance.state.llm)
            yield

    app.router.lifespan_context = lifespan
    app.version = "1.4.0"
    # Replace only the service-status endpoint; all validation/privacy routes stay identical.
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/api/status"]

    @app.get("/api/status")
    async def status():
        return {"ml": await run_in_threadpool(ml.load), "llm": {"endpoint": settings.endpoint,
            "model": settings.llm_model, "has_api_key": bool(settings.api_key), "rag": False},
            "rag": await run_in_threadpool(rag.status),
            "analysis_policy": {"version": POLICY_VERSION, "default_include_ml": False,
                "message_prompt_profile": PROFILE, "pipeline_version": PIPELINE, "headline_target": "message_actions",
                "url_decision_policy": URL_POLICY},
            "limits": {"characters": 8000, "urls": 5, "llm_timeout_seconds": settings.timeout_seconds}}

    return app


app = create_app()
