"""Opt-in core decision, observed transport, action retrieval and clarification.

Run with ``uvicorn app.api.focused:app``. This composes frozen services without
rewriting the code hashes required by previous registered evaluations.
"""
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import os

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.interaction import CandidateV6Analysis, create_app as create_interaction_app, runtime_manifest
from app.core.settings import ROOT, Settings
from app.domain import clarification
from app.services.llm.core import CoreMessageService, PROFILE
from app.services.llm.telemetry import LAST_CLASSIFIER_CALL
from app.services.rag.action_retrieval import ActionAwareRAG, POLICY as RETRIEVAL_POLICY
from app.services.rag.retrieval import RAGService
import app.services.rag.evidence as evidence_selection

PIPELINE = "focused-core-1.0-candidate"


def manifest(settings, thinking, hybrid):
    inherited = runtime_manifest(settings, "span_selection")
    files = ("app/api/focused.py", "app/services/llm/core.py", "app/services/llm/telemetry.py",
             "app/domain/clarification.py", "app/services/rag/action_retrieval.py")
    return {"url_intake_version": inherited["url_intake_version"],
        "bare_domain_reference": inherited["bare_domain_reference"],
        "message_profile": PROFILE, "thinking_requested": thinking,
        "thinking_support_verified_by_runtime": False, "max_tokens": settings.max_tokens,
        "model": settings.llm_model, "explanation_mode": "span_selection", "rag_stage": "post_classification",
        "retrieval_policy": RETRIEVAL_POLICY if hybrid else "existing_e5",
        "source_files_sha256": {**inherited["source_files_sha256"],
            **{name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}},
        "corpus": settings.rag_corpus, "index_dir": settings.rag_index_dir}


class FocusedAnalysis(CandidateV6Analysis):
    def __init__(self, ml, rag, llm, *, hybrid):
        super().__init__(ml, rag, llm)
        self.manifest = manifest(llm.settings, llm.thinking, hybrid)

    async def analyze(self, data):
        token = LAST_CLASSIFIER_CALL.set(None)
        try:
            result = await super().analyze(data)
            result["execution"].update(version=PIPELINE, candidate=PIPELINE, experimental=True)
            if data.mode == "text" and data.use_llm:
                result["execution"]["llm"]["requested_profile"] = PROFILE
                observation = LAST_CLASSIFIER_CALL.get()
                if observation:
                    result["llm"]["telemetry"] = observation
                    result["llm"].setdefault("usage", observation["usage"])
                result["execution"]["llm"]["technical_status"] = result["llm"]["status"]
                result["execution"]["llm"]["semantic_uncertainty"] = (
                    result["llm"]["status"] == "ok" and result["llm"]["verdict"]["risk_level"] == "UNKNOWN")
            result["clarification"] = clarification.plan(result["llm"]) if data.mode == "text" else {"status": "not_needed", "questions": []}
            return result
        finally:
            LAST_CLASSIFIER_CALL.reset(token)


class ClarificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)
    answers: list[dict[str, str]] = Field(min_length=1, max_length=2)


def create_app(settings=None, transport=None, model_service=None, rag_service=None):
    initial = settings or Settings()
    budget = int(os.getenv("PHISHLENS_CORE_MAX_TOKENS", "2048"))
    if not 256 <= budget <= 8192: raise ValueError("Core token budget must be between 256 and 8192.")
    settings = replace(initial, max_tokens=min(initial.max_tokens, budget))
    thinking = os.getenv("PHISHLENS_CORE_THINKING", "disabled")
    if thinking not in {"default", "enabled", "disabled"}: raise ValueError("Invalid thinking request.")
    # The action filter lost a supported query in the registered dev comparison.
    # Keep it opt-in instead of promoting its higher rejection rate alone.
    retrieval = os.getenv("PHISHLENS_FOCUSED_RETRIEVAL", "e5")
    if retrieval not in {"e5", "action_hybrid"}: raise ValueError("Invalid focused retrieval policy.")
    hybrid = retrieval == "action_hybrid"
    rag = rag_service or RAGService(settings, include_scope=True)
    if hybrid and rag_service is None: rag = ActionAwareRAG(rag)
    app = create_interaction_app(settings, transport, model_service, rag)
    ml = app.state.ml
    original_status = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/api/status")

    @asynccontextmanager
    async def lifespan(instance):
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, transport=transport, trust_env=False) as client:
            instance.state.llm = CoreMessageService(settings, client, thinking=thinking, explanation_mode="span_selection")
            instance.state.analysis = FocusedAnalysis(ml, rag, instance.state.llm, hybrid=hybrid)
            yield

    app.router.lifespan_context = lifespan
    app.title = "PhishLens · focused core (experimental)"
    app.version = "1.7.0-candidate"
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/api/status"]

    @app.get("/api/status")
    async def status():
        data = await original_status()
        data["runtime_manifest"] = manifest(settings, thinking, hybrid)
        data["analysis_policy"].update(candidate=PIPELINE, pipeline_version=PIPELINE,
            message_prompt_profile=PROFILE, interaction_required=False, clarification_available=True,
            thinking_requested=thinking, retrieval_policy=RETRIEVAL_POLICY if hybrid else "existing_e5",
            explanation_mode="span_selection", explanation_profile=evidence_selection.PROFILE,
            explanation_parser_version=evidence_selection.PARSER_VERSION)
        data["limits"]["core_max_tokens"] = settings.max_tokens
        return data

    @app.post("/api/clarify/preview")
    async def clarify(data: ClarificationRequest):
        try:
            return clarification.preview(data.text, data.answers)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


app = create_app()
