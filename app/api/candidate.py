"""Opt-in v5 candidate: freeze the verdict, then optionally explain with RAG.

Run with ``uvicorn app.api.candidate:app`` for manual evaluation. The normal app
entry point stays on v4. This is experimental: the live pilot may reject v5;
offline contract tests establish workflow boundaries, not detection quality.
"""
from contextlib import asynccontextmanager
from dataclasses import replace
import os
import time

import httpx
from starlette.concurrency import run_in_threadpool

from app.domain.decisions import POLICY_VERSION
from app.services.llm.client import LLMFailure, normalize_endpoint
from app.services.llm.policy_v5 import MessageV5Service, PROFILE
from app.services.url.features import ModelService
from app.api.stable import QualityAnalysis, create_app as create_quality_app
from app.services.rag.explanation_v2 import PROFILE as EXPLANATION_PROFILE, PARSER_VERSION, build_explanation_payload, build_retrieval_query, call_explanation_v2 as call_explanation
import app.services.rag.evidence as rag_evidence_v3
from app.services.rag.retrieval import RAGService
from app.core.settings import Settings
from app.services.url.character import CharURLService
from app.services.url.policy import VERSION as URL_POLICY


PIPELINE = "analysis-pipeline-5.0-candidate"
CANDIDATE = "v5-candidate"


def explanation_state(status="disabled", code=None, *, profile=EXPLANATION_PROFILE, parser_version=PARSER_VERSION):
    result = {
        "status": status, "prompt_profile": profile,
        "stage": "post_classification", "usage": {},
        "explanation": {"support": [], "actions": []},
        "validation": {"classification_changed": False, "structural_only": True,
                       "semantic_support_verified": False, "semantic_review_required": True,
                       "source_text_kind": "editorial_summary_not_verbatim", "parser_version": parser_version},
    }
    if code:
        result["code"] = code
    return result


class CandidateMessageService(MessageV5Service):
    def __init__(self, settings, client, *, explanation_mode="free_text"):
        super().__init__(settings, client)
        self.explanation_mode = explanation_mode
        self.selection_only = explanation_mode == "span_selection"
        self.explanation_profile = rag_evidence_v3.PROFILE if self.selection_only else EXPLANATION_PROFILE
        self.explanation_parser = rag_evidence_v3.PARSER_VERSION if self.selection_only else PARSER_VERSION

    def empty_explanation(self, status="disabled", code=None):
        result = explanation_state(status, code, profile=self.explanation_profile,
                                   parser_version=self.explanation_parser)
        result["validation"]["selection_only"] = self.selection_only
        return result

    async def explain(self, *, text, verdict, sources, endpoint, model, api_key):
        """Share the classifier's transport limits, without returning a verdict."""
        endpoint = normalize_endpoint(endpoint or self.settings.endpoint, self.settings)
        key = api_key.strip() or self.settings.api_key
        if not key or any(character in key for character in "\r\n"):
            raise LLMFailure("API_KEY_MISSING" if not key else "API_KEY_INVALID", "Chưa có API key hợp lệ.")
        model = model.strip() or self.settings.llm_model
        try:
            builder = rag_evidence_v3.build_evidence_payload if self.selection_only else build_explanation_payload
            payload = builder(
                approved_text=text, verdict=verdict, sources=sources, model=model,
                max_tokens=self.settings.max_tokens,
            )
        except (ValueError, TypeError):
            return self.empty_explanation("error", "INPUT_INVALID")
        async with self.slots:
            call = rag_evidence_v3.call_evidence if self.selection_only else call_explanation
            result = await call(
                self.client, endpoint=endpoint, api_key=key, payload=payload,
                approved_text=text, verdict=verdict, sources=sources,
                timeout=self.settings.timeout_seconds,
            )
        result["stage"] = "post_classification"
        # Provider content is never exposed; explanation usage stays separate.
        result.pop("http_status", None)
        result.pop("finish_reason", None)
        return result


class CandidateAnalysis(QualityAnalysis):
    async def analyze(self, data):
        started = time.perf_counter()
        # Reuse all input validation/redaction and ordinary classifier error
        # handling, but do not retrieve or send RAG in the classification call.
        result = await super().analyze(data.model_copy(update={"use_rag": False}))
        execution = result["execution"]
        execution.update(version=PIPELINE, candidate=CANDIDATE, experimental=True)
        execution["requested"]["rag"] = data.use_rag
        if data.mode == "text" and data.use_llm:
            execution["llm"]["requested_profile"] = PROFILE
        execution["llm"]["stage"] = "classification"
        result["post_explanation"] = self.llm.empty_explanation()
        execution["explanation"] = {
            "attempted": False, "status": "disabled", "stage": "post_classification",
            "prompt_profile": self.llm.explanation_profile, "classification_changed": False,
            "parser_version": self.llm.explanation_parser,
            "mode": self.llm.explanation_mode,
            "input_scope": "approved_redacted_text",
        }
        execution["retrieval"].update(stage="post_classification", included_in_successful_llm_call=False,
                                       included_in_successful_explanation_call=False)
        result["timing"]["explanation_ms"] = 0.0

        requested = data.use_rag and data.use_llm and data.mode == "text"
        if not data.use_rag:
            reason = "Chưa bật tài liệu giải thích sau phân loại."
        elif not data.use_llm:
            reason = "AI đang tắt nên chưa truy xuất tài liệu để giải thích nội dung."
        elif data.mode != "text":
            reason = "Tài liệu giải thích hành vi không xác nhận uy tín của một URL."
        else:
            reason = "Chưa có kết quả phân loại thành công để bổ sung tài liệu."
        result["retrieval"]["reason"] = reason
        if requested and result["llm"]["status"] == "ok":
            llm = result["llm"]
            # input_used is produced by the inherited workflow only after the
            # user's edited text has been redacted and consent checked.
            text, verdict = llm["input_used"], llm["verdict"]
            rag_started = time.perf_counter()
            execution["retrieval"]["attempted"] = True
            try:
                query = build_retrieval_query(text, verdict)
                retrieval = await run_in_threadpool(self.rag.search, query, "text")
                # Source validation also happens before any explanation call.
                if (not isinstance(retrieval, dict) or not isinstance(retrieval.get("sources"), list)
                        or not isinstance(retrieval.get("status"), str)):
                    raise ValueError("Invalid retrieval result.")
            except Exception:
                # Retrieval is optional; an unavailable index must not erase a
                # successful classifier. Never expose raw exception content.
                retrieval = {"status": "unavailable", "sources": [],
                             "reason": "Chưa truy xuất được tài liệu giải thích."}
            result["timing"]["rag_ms"] = round((time.perf_counter() - rag_started) * 1000, 1)
            result["retrieval"] = retrieval
            execution["retrieval"].update(status=retrieval["status"], source_count=len(retrieval["sources"]))
            if retrieval["sources"]:
                execution["explanation"]["attempted"] = True
                explanation_started = time.perf_counter()
                try:
                    explanation = await self.llm.explain(
                        text=text, verdict=verdict, sources=retrieval["sources"],
                        endpoint=llm["endpoint"], model=llm["model"],
                        api_key=data.api_key.get_secret_value(),
                    )
                except (LLMFailure, ValueError, TypeError):
                    explanation = self.llm.empty_explanation("error", "EXPLANATION_UNAVAILABLE")
                result["timing"]["explanation_ms"] = round((time.perf_counter() - explanation_started) * 1000, 1)
            else:
                explanation = self.llm.empty_explanation("no_support")
            result["post_explanation"] = explanation
            execution["explanation"]["status"] = explanation["status"]
            execution["retrieval"]["included_in_successful_explanation_call"] = (
                execution["explanation"]["attempted"] and explanation["status"] in {"ok", "no_support"}
            )
            if explanation["status"] == "ok":
                result["configuration"] += " + RAG giải thích sau phân loại"
        result["timing"]["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return result


def create_app(settings=None, transport=None, model_service=None, rag_service=None):
    settings = settings or Settings()
    settings = replace(settings, max_tokens=min(settings.max_tokens, 8192))
    explanation_mode = os.getenv("PHISHLENS_CANDIDATE_RAG_MODE", "free_text")
    if explanation_mode not in {"free_text", "span_selection"}:
        raise ValueError("PHISHLENS_CANDIDATE_RAG_MODE phải là free_text hoặc span_selection.")
    rag = rag_service or RAGService(settings, include_scope=True)
    if model_service is None:
        model_name = os.getenv("PHISHLENS_CANDIDATE_URL_MODEL", "char")
        if model_name not in {"char", "xgboost"}:
            raise ValueError("PHISHLENS_CANDIDATE_URL_MODEL phải là char hoặc xgboost.")
        model_service = CharURLService() if model_name == "char" else ModelService(settings)
    # Both opt-in URL candidates use the existing uncertainty wrapper. The normal
    # run.py entry point still uses its original XGBoost model and v4 prompt.
    app = create_quality_app(settings, transport, model_service, rag)
    ml = app.state.ml

    @asynccontextmanager
    async def lifespan(instance):
        async with httpx.AsyncClient(timeout=settings.timeout_seconds, transport=transport, trust_env=False) as client:
            instance.state.llm = CandidateMessageService(settings, client, explanation_mode=explanation_mode)
            instance.state.analysis = CandidateAnalysis(ml, rag, instance.state.llm)
            yield

    app.router.lifespan_context = lifespan
    app.title = "PhishLens · v5 candidate (experimental)"
    app.version = "1.5.0-candidate"
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != "/api/status"]

    @app.get("/api/status")
    async def status():
        return {
            "ml": await run_in_threadpool(ml.load),
            "llm": {"endpoint": settings.endpoint, "model": settings.llm_model,
                    "has_api_key": bool(settings.api_key), "rag": False},
            "rag": await run_in_threadpool(rag.status),
            "analysis_policy": {"version": POLICY_VERSION, "candidate": CANDIDATE, "experimental": True,
                                "message_prompt_profile": PROFILE, "pipeline_version": PIPELINE,
                                "default_include_ml": False, "headline_target": "message_actions",
                                "url_decision_policy": URL_POLICY, "rag_stage": "post_classification",
                                "explanation_profile": rag_evidence_v3.PROFILE if explanation_mode == "span_selection" else EXPLANATION_PROFILE,
                                "explanation_parser_version": rag_evidence_v3.PARSER_VERSION if explanation_mode == "span_selection" else PARSER_VERSION,
                                "explanation_mode": explanation_mode},
            "limits": {"characters": 8000, "urls": 5, "llm_timeout_seconds": settings.timeout_seconds},
        }

    return app


app = create_app()
