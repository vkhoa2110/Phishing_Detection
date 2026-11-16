"""Deployment policy around preserved research profiles and service contracts."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import hashlib
import math

from fastapi import HTTPException, Request

from app.core.settings import ROOT, Settings
from app.domain.claim_grounding import VERSION as PRESENTATION_VERSION, guard_presentation
from app.domain.schemas import AnalyzeInput
from app.services.llm.client import LLMFailure

VERSION = "server-managed-runtime-1.0"
PRESENTATION_SHA256 = hashlib.sha256((ROOT / "app/domain/claim_grounding.py").read_bytes()).hexdigest()


@dataclass
class RequestBudget:
    seconds: float
    started_at: float | None = None
    calls: int = 0
    timed_out_stage: str | None = None

    def remaining(self):
        now = asyncio.get_running_loop().time()
        if self.started_at is None: self.started_at = now
        return max(0, self.seconds - (now - self.started_at))


ACTIVE_BUDGET = ContextVar("runtime_provider_budget", default=None)


class BudgetedLLM:
    def __init__(self, service, *, guard_reasons=False):
        self.service, self.guard_reasons = service, guard_reasons

    def __getattr__(self, name): return getattr(self.service, name)

    async def invoke(self, stage, **kwargs):
        budget = ACTIVE_BUDGET.get()
        if budget is None: raise RuntimeError("Provider calls require a request budget.")
        remaining = budget.remaining()
        if remaining <= 0:
            budget.timed_out_stage = stage
            raise LLMFailure("TIMEOUT", "Đã hết thời gian chờ AI cho lượt kiểm tra này.")
        budget.calls += 1
        try:
            async with asyncio.timeout(remaining):
                result = await getattr(self.service, stage)(**kwargs)
                if stage == "analyze" and self.guard_reasons:
                    result = guard_presentation(result)
                if isinstance(result, dict) and result.get("code") == "TIMEOUT":
                    budget.timed_out_stage = stage
                return result
        except TimeoutError as exc:
            budget.timed_out_stage = stage
            raise LLMFailure("TIMEOUT", "Đã hết thời gian chờ AI cho lượt kiểm tra này.") from exc
        except LLMFailure as exc:
            if exc.code == "TIMEOUT": budget.timed_out_stage = stage
            raise

    async def analyze(self, **kwargs): return await self.invoke("analyze", **kwargs)

    async def explain(self, **kwargs):
        try:
            return await self.invoke("explain", **kwargs)
        except LLMFailure as exc:
            # Optional explanation failure must preserve the completed verdict.
            return {**self.service.empty_explanation("error", exc.code),
                    "stage": "post_classification", "usage_available": False}


class ManagedAnalysis:
    def __init__(self, service, seconds, profile):
        self.service, self.seconds, self.profile = service, seconds, profile

    async def analyze(self, data):
        budget = RequestBudget(self.seconds)
        token = ACTIVE_BUDGET.set(budget)
        try:
            result = await self.service.analyze(data)
            result["execution"]["runtime"] = {"version": VERSION, "profile": self.profile,
                "connection_mode": "server_managed", "provider_budget_seconds": self.seconds,
                "budget_scope": "shared_from_first_provider_call_including_optional_explanation",
                "calls_attempted": budget.calls, "timed_out_stage": budget.timed_out_stage}
            result["execution"]["runtime"]["reason_presentation_sha256"] = PRESENTATION_SHA256 if self.profile == "focused" else None
            grounding = result.get("llm", {}).get("claim_grounding")
            if grounding:
                result["execution"]["llm"]["reason_presentation"] = grounding["version"]
                if grounding["status"] == "needs_review":
                    result["final"]["requires_review"] = True
            return result
        finally:
            ACTIVE_BUDGET.reset(token)


def create_app(profile="stable", settings=None, transport=None, model_service=None, rag_service=None):
    initial = settings or Settings()
    if not math.isfinite(initial.timeout_seconds) or initial.timeout_seconds <= 0:
        raise ValueError("LLM timeout must be positive and finite.")
    settings = replace(initial, timeout_seconds=min(initial.timeout_seconds, 45))
    # Lazy imports keep the launcher lightweight and preserve old ASGI factories.
    if profile == "stable":
        from app.api.stable import create_app as factory
    elif profile == "candidate":
        from app.api.interaction import create_app as factory
    elif profile == "focused":
        from app.api.focused import create_app as factory
    elif profile == "candidate-v5":
        from app.api.candidate import create_app as factory
    elif profile == "legacy":
        from app.api.legacy import create_app as factory
    else:
        raise ValueError("Unknown runtime profile.")
    app = factory(settings, transport, model_service, rag_service)
    original_status = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/status")
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(instance):
        async with original_lifespan(instance):
            inner = instance.state.analysis
            wrapped = BudgetedLLM(inner.llm, guard_reasons=profile == "focused")
            inner.llm = instance.state.llm = wrapped
            instance.state.analysis = ManagedAnalysis(inner, settings.timeout_seconds, profile)
            yield

    app.router.lifespan_context = lifespan
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) not in {"/api/status", "/api/analyze"}]

    @app.get("/api/status")
    async def status():
        data = await original_status()
        data["runtime"] = {"version": VERSION, "profile": profile, "connection_mode": "server_managed",
            "client_connection_overrides": False, "default_changed_by_this_runtime": False}
        data["runtime"]["reason_presentation"] = PRESENTATION_VERSION if profile == "focused" else None
        data["runtime"]["reason_presentation_sha256"] = PRESENTATION_SHA256 if profile == "focused" else None
        data["limits"].update(llm_timeout_seconds=settings.timeout_seconds,
            llm_request_budget_seconds=settings.timeout_seconds,
            llm_budget_scope="shared_from_first_provider_call_including_optional_explanation")
        return data

    @app.post("/api/analyze")
    async def analyze(data: AnalyzeInput, request: Request):
        if data.endpoint or data.model or data.api_key.get_secret_value():
            raise HTTPException(422, "Kết nối AI do máy chủ quản lý; yêu cầu không được kèm key, endpoint hoặc model thay thế.")
        from app.services.analysis import AnalysisInputError
        try:
            return await request.app.state.analysis.analyze(data)
        except AnalysisInputError as exc:
            raise HTTPException(422, str(exc)) from exc

    return app


def create_stable_app(): return create_app("stable")
def create_candidate_app(): return create_app("candidate")
def create_focused_app(): return create_app("focused")
def create_v5_app(): return create_app("candidate-v5")
def create_legacy_app(): return create_app("legacy")
