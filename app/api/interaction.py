"""Opt-in v6.1 candidate combining hardened URL intake and compact interaction.

This composes the candidate factory with interaction extraction and post-verdict
RAG. Historical runtime files are preserved in Git for locked experiment replay.
"""
from app.core.settings import ROOT as PROJECT_ROOT
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import time

import httpx
from starlette.concurrency import run_in_threadpool

import app.services.rag.evidence as rag_evidence_v3
from app.services.interaction_analysis import ExtractorAnalysisService
from app.api.candidate import create_app as create_candidate_app
from app.domain.decisions import POLICY_VERSION
from app.services.llm.client import LLMFailure
from app.services.llm.compact import CandidateMessageV61Service, PROFILE, PARSER_VERSION as MESSAGE_PARSER
from app.services.rag.explanation_v2 import PARSER_VERSION, PROFILE as EXPLANATION_PROFILE, build_retrieval_query
from app.services.rag.retrieval import RAGService
from app.core.settings import Settings
from app.domain.schemas import MessageVerdict
from app.services.url.intake import VERSION as INTAKE_VERSION, extract_urls_v2, inspect_url_intake
from app.services.url.policy import VERSION as URL_POLICY


PIPELINE = "analysis-pipeline-6.1-candidate"
CANDIDATE = "v6.1-candidate"


def runtime_manifest(settings, explanation_mode):
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None

    code_root = PROJECT_ROOT
    return {
        "scope": "v6_application", "model": settings.llm_model,
        "message_profile": PROFILE, "message_parser": MESSAGE_PARSER,
        "max_tokens": settings.max_tokens, "explanation_mode": explanation_mode,
        "corpus": settings.rag_corpus,
        "corpus_sha256": digest(settings.root / settings.rag_corpus),
        "index_dir": settings.rag_index_dir,
        "index_manifest_sha256": digest(settings.root / settings.rag_index_dir / "manifest.json"),
        "source_files_sha256": {name: digest(code_root / name) for name in (
            "app/api/interaction.py", "app/services/llm/compact.py", "app/services/llm/policy_v6.py", "app/services/llm/policy_v5.py",
            "app/services/rag/evidence.py", "app/services/rag/explanation_v2.py", "app/services/rag/explanation.py",
            "app/services/url/intake.py", "app/services/url/authority.py")},
    }


class CandidateV6Analysis(ExtractorAnalysisService):
    def __init__(self, ml, rag, llm):
        super().__init__(ml, rag, llm, url_extractor=extract_urls_v2)
        self.manifest = runtime_manifest(llm.settings, llm.explanation_mode)

    async def analyze(self, data):
        started = time.perf_counter()
        # Classification never sees RAG. Retrieval/explanation can run only
        # after the message verdict is frozen below.
        result = await self.analyze_with_extractor(data.model_copy(update={"use_rag": False}))
        execution = result["execution"]
        execution.update(version=PIPELINE, candidate=CANDIDATE, experimental=True)
        execution["runtime_manifest"] = {
            **self.manifest, "model": data.model.strip() or self.manifest["model"],
            "provider_model": result["llm"].get("provider_model"),
            "endpoint": result["llm"].get("endpoint"),
        }
        execution["requested"]["rag"] = data.use_rag
        llm_execution = execution["llm"]
        llm_execution["requested_schema_profile"] = llm_execution["requested_profile"]
        if data.mode == "text" and data.use_llm:
            llm_execution["requested_profile"] = PROFILE
        llm_execution["stage"] = "classification"
        execution["url"]["decision_policy"] = URL_POLICY

        result["post_explanation"] = self.llm.empty_explanation()
        execution["explanation"] = {
            "attempted": False, "status": "disabled", "stage": "post_classification",
            "prompt_profile": self.llm.explanation_profile, "classification_changed": False,
            "parser_version": self.llm.explanation_parser, "mode": self.llm.explanation_mode,
            "input_scope": "approved_redacted_text",
        }
        execution["retrieval"].update(
            stage="post_classification", included_in_successful_llm_call=False,
            included_in_successful_explanation_call=False,
        )
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
            text = llm["input_used"]
            # RAG's frozen contract is the base message verdict. Keep the v6
            # interaction in the result; never mutate or relax that contract.
            verdict = MessageVerdict.model_validate({
                key: value for key, value in llm["verdict"].items()
                if key in MessageVerdict.model_fields
            }, strict=True).model_dump()
            rag_started = time.perf_counter()
            execution["retrieval"]["attempted"] = True
            try:
                query = build_retrieval_query(text, verdict)
                retrieval = await run_in_threadpool(self.rag.search, query, "text")
                if (not isinstance(retrieval, dict)
                        or not isinstance(retrieval.get("sources"), list)
                        or not isinstance(retrieval.get("status"), str)):
                    raise ValueError("Invalid retrieval result.")
            except Exception:
                retrieval = {"status": "unavailable", "sources": [],
                             "reason": "Chưa truy xuất được tài liệu giải thích."}
            result["timing"]["rag_ms"] = round((time.perf_counter() - rag_started) * 1000, 1)
            result["retrieval"] = retrieval
            execution["retrieval"].update(
                status=retrieval["status"], source_count=len(retrieval["sources"])
            )
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
                result["timing"]["explanation_ms"] = round(
                    (time.perf_counter() - explanation_started) * 1000, 1
                )
            else:
                explanation = self.llm.empty_explanation("no_support")
            result["post_explanation"] = explanation
            execution["explanation"]["status"] = explanation["status"]
            execution["retrieval"]["included_in_successful_explanation_call"] = (
                execution["explanation"]["attempted"]
                and explanation["status"] in {"ok", "no_support"}
            )
            if explanation["status"] == "ok":
                result["configuration"] += " + RAG giải thích sau phân loại"

        intake = inspect_url_intake(data.text, data.mode)
        execution["url"].update(
            intake_version=intake["version"], recovered=len(intake["recovered_urls"]),
            idna_policy=intake["idna_policy"],
            recovered_requires_user_review=bool(intake["recovered_urls"]),
        )
        result["url_intake"] = {
            key: intake[key] for key in (
                "version", "idna_policy", "strict_urls", "recovered_urls", "findings",
                "interpretation_only", "notice",
            )
        }
        if intake["recovered_urls"]:
            result["notice"] += (
                " URL viết che dấu được chấm trên cách đọc hiển thị trong kết quả; "
                "hãy đối chiếu lại chuỗi gốc."
            )
        result["timing"]["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return result


def create_app(settings=None, transport=None, model_service=None, rag_service=None):
    initial = settings or Settings()
    settings = replace(initial, max_tokens=min(initial.max_tokens, 8192))
    explanation_mode = os.getenv("PHISHLENS_CANDIDATE_RAG_MODE", "free_text")
    if explanation_mode not in {"free_text", "span_selection"}:
        raise ValueError("PHISHLENS_CANDIDATE_RAG_MODE phải là free_text hoặc span_selection.")
    rag = rag_service or RAGService(settings, include_scope=True)
    # Reuse v5's model selection and HTTP/security routes, then replace only its
    # candidate services and status metadata.
    app = create_candidate_app(settings, transport, model_service, rag)
    ml = app.state.ml

    @asynccontextmanager
    async def lifespan(instance):
        async with httpx.AsyncClient(
            timeout=settings.timeout_seconds, transport=transport, trust_env=False,
        ) as client:
            instance.state.llm = CandidateMessageV61Service(
                settings, client, explanation_mode=explanation_mode,
            )
            instance.state.analysis = CandidateV6Analysis(ml, rag, instance.state.llm)
            yield

    app.router.lifespan_context = lifespan
    app.title = "PhishLens · v6.1 candidate (experimental)"
    app.version = "1.6.1-candidate"
    app.router.routes[:] = [
        route for route in app.router.routes if getattr(route, "path", None) != "/api/status"
    ]

    @app.get("/api/status")
    async def status():
        selection_only = explanation_mode == "span_selection"
        return {
            "ml": await run_in_threadpool(ml.load),
            "llm": {"endpoint": settings.endpoint, "model": settings.llm_model,
                    "has_api_key": bool(settings.api_key), "rag": False},
            "rag": await run_in_threadpool(rag.status),
            "runtime_manifest": runtime_manifest(settings, explanation_mode),
            "analysis_policy": {
                "version": POLICY_VERSION, "candidate": CANDIDATE, "experimental": True,
                "message_prompt_profile": PROFILE, "pipeline_version": PIPELINE,
                "default_include_ml": False, "headline_target": "message_actions",
                "url_decision_policy": URL_POLICY, "url_intake": INTAKE_VERSION,
                "rag_stage": "post_classification",
                "explanation_profile": rag_evidence_v3.PROFILE if selection_only else EXPLANATION_PROFILE,
                "explanation_parser_version": rag_evidence_v3.PARSER_VERSION if selection_only else PARSER_VERSION,
                "explanation_mode": explanation_mode,
            },
            "limits": {"characters": 8000, "urls": 5,
                       "llm_timeout_seconds": settings.timeout_seconds},
        }

    return app


app = create_app()
