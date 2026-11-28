"""Deployment policy around preserved research profiles and service contracts."""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
import hashlib
import math
import time

from fastapi import HTTPException, Request

from app.core.settings import ROOT, Settings
from app.domain.claim_grounding import VERSION as PRESENTATION_VERSION, guard_presentation
from app.domain.schemas import AnalyzeInput
from app.services.llm.client import LLMFailure
from app.services.llm import decision_explanation
from app.services.llm import conversation

VERSION = "server-managed-runtime-1.0"
PRESENTATION_SHA256 = hashlib.sha256((ROOT / "app/domain/claim_grounding.py").read_bytes()).hexdigest()
FOCUSED_PROFILES = {"focused", "verifier-shadow"}
DEFAULT_BUDGET_SCOPE = "shared_from_first_provider_call_including_optional_explanation"
SHADOW_BUDGET_SCOPE = "shared_from_first_provider_call_including_optional_explanation_and_verification"


def budget_scope(profile):
    return SHADOW_BUDGET_SCOPE if profile == "verifier-shadow" else DEFAULT_BUDGET_SCOPE


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
                if stage == "analyze" and conversation.TARGET.get() == "conversation":
                    result = await conversation.analyze(self.service, **kwargs)
                else:
                    result = (await decision_explanation.describe(self.service, **kwargs) if stage == "describe_evidence"
                              else await getattr(self.service, stage)(**kwargs))
                if stage == "analyze" and self.guard_reasons:
                    result = guard_presentation(result)
                if isinstance(result, dict) and result.get("code") == "TIMEOUT":
                    budget.timed_out_stage = stage
                return result
        except TimeoutError as exc:
            budget.timed_out_stage = stage
            raise LLMFailure("TIMEOUT", "Đã hết thời gian chờ AI cho lượt kiểm tra này.") from exc
        except RecursionError as exc:
            # Excessively nested provider JSON is invalid input, including when
            # a frozen parser raises before returning its normal error record.
            raise LLMFailure("RESPONSE_INVALID", "Phản hồi AI không hợp lệ; kết quả đã hoàn tất được giữ riêng.") from exc
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

    async def verify(self, **kwargs):
        try:
            return await self.invoke("verify", **kwargs)
        except LLMFailure as exc:
            # A failed shadow opinion cannot invalidate a completed analysis.
            return {"status": "error", "code": exc.code, "usage": {}, "usage_available": False}

    async def describe_evidence(self, **kwargs):
        try:
            return await self.invoke("describe_evidence", **kwargs)
        except LLMFailure as exc:
            return {"status": "error", "code": exc.code, "classification_changed": False}


class ManagedAnalysis:
    def __init__(self, service, seconds, profile):
        self.service, self.seconds, self.profile = service, seconds, profile

    async def analyze(self, data):
        budget = RequestBudget(self.seconds)
        token = ACTIVE_BUDGET.set(budget)
        target_token = conversation.TARGET.set(data.analysis_target)
        try:
            result = await self.service.analyze(data)
            llm = result["llm"]
            if (decision_explanation.REQUESTED.get() and data.mode == "text" and llm.get("status") == "ok"
                    and llm.get("core_decision") and llm["verdict"].get("evidence")):
                explanation_started = time.perf_counter()
                llm["evidence_explanation"] = await self.service.llm.describe_evidence(llm=llm)
                elapsed = round((time.perf_counter() - explanation_started) * 1000, 1)
                result["timing"]["evidence_explanation_ms"] = elapsed
                result["timing"]["total_ms"] += elapsed
            result["execution"]["runtime"] = {"version": VERSION, "profile": self.profile,
                "connection_mode": "server_managed", "provider_budget_seconds": self.seconds,
                "budget_scope": budget_scope(self.profile),
                "calls_attempted": budget.calls, "timed_out_stage": budget.timed_out_stage}
            result["execution"]["runtime"]["reason_presentation_sha256"] = PRESENTATION_SHA256 if self.profile in FOCUSED_PROFILES else None
            if data.analysis_target == "conversation":
                result["analysis_target"] = "conversation"
                result["execution"]["llm"]["requested_profile"] = conversation.PROFILE
                result["execution"]["llm"]["assessment_scope"] = "selected_conversation"
            grounding = result.get("llm", {}).get("claim_grounding")
            if grounding:
                result["execution"]["llm"]["reason_presentation"] = grounding["version"]
                if grounding["status"] == "needs_review":
                    result["final"]["requires_review"] = True
            return result
        finally:
            conversation.TARGET.reset(target_token)
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
    elif profile == "verifier-shadow":
        from app.api.verifier_shadow import create_app as factory
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
            wrapped = BudgetedLLM(inner.llm, guard_reasons=profile in FOCUSED_PROFILES)
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
        data["runtime"]["reason_presentation"] = PRESENTATION_VERSION if profile in FOCUSED_PROFILES else None
        data["runtime"]["evidence_explanation_available"] = profile in FOCUSED_PROFILES
        data["runtime"]["reason_presentation_sha256"] = PRESENTATION_SHA256 if profile in FOCUSED_PROFILES else None
        # Read loaded settings after each preserved factory applies its cap.
        # Explicit allowlist: no endpoint, headers, keys, input or raw response.
        service = app.state.llm
        actual = service.settings
        data["runtime"]["effective_llm"] = {
            "model": actual.llm_model,
            "prompt_profile": data.get("analysis_policy", {}).get("message_prompt_profile") or getattr(service, "profile", "legacy"),
            "max_tokens": actual.max_tokens,
            "thinking_requested": getattr(service, "thinking", "default"),
            "rag_stage": data.get("analysis_policy", {}).get("rag_stage", "pre_classification"),
        }
        data["limits"].update(llm_timeout_seconds=settings.timeout_seconds,
            llm_request_budget_seconds=settings.timeout_seconds,
            llm_budget_scope=budget_scope(profile))
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
def create_verifier_shadow_app(): return create_app("verifier-shadow")
def create_v5_app(): return create_app("candidate-v5")
def create_legacy_app(): return create_app("legacy")
