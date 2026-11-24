"""Opt-in observation of a blind second opinion; never revise an app verdict.

Compose the preserved focused profile rather than changing its registered
classification or explanation implementation. Launch through managed runtime;
the raw factory explicitly skips verification without its shared request budget.
"""
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import time

from app.api.focused import create_app as create_focused_app
from app.core.settings import ROOT
from app.services.llm.client import LLMFailure
from app.services.llm.verifier import ALARM_LEVELS, VerifierFacade, protocol_manifest, revision, verification_error

PROFILE = "verifier-shadow"
STAGE = "post_classification_and_optional_explanation"


def shadow_manifest():
    files = ("app/api/verifier_shadow.py", "app/services/llm/verifier.py", "app/api/runtime.py")
    return {**protocol_manifest(), "mode": "shadow", "stage": STAGE,
        "source_files_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}}


class ShadowAnalysis:
    def __init__(self, service, manifest):
        self.service = service
        self.verification_manifest = manifest

    def __getattr__(self, name):
        return getattr(self.service, name)

    @property
    def llm(self):
        return self.service.llm

    @llm.setter
    def llm(self, value):
        # The managed runtime must wrap all three stages, not a stale facade.
        self.service.llm = value

    async def analyze(self, data):
        analysis_started = time.perf_counter()
        result = await self.service.analyze(data)
        llm = result["llm"]
        level = llm.get("verdict", {}).get("risk_level") if llm.get("status") == "ok" else None
        verification = {"mode": "shadow", "status": "skipped", "attempted": False,
            "stage": STAGE, "profile": protocol_manifest()["profile"], "verdict_changed": False,
            "applied": False, "semantic_support_verified": False,
            "original_level": level, "suggested_level": level,
            "usage": {}, "usage_available": False}
        result["verification"] = verification
        if data.mode != "text":
            verification["skip_reason"] = "not_message_mode"
        elif not data.use_llm:
            verification["skip_reason"] = "llm_disabled"
        elif llm.get("status") != "ok":
            verification["skip_reason"] = "classification_not_completed"
        elif level not in ALARM_LEVELS:
            verification["skip_reason"] = "not_completed_alarm"
        else:
            from app.api.runtime import ACTIVE_BUDGET
            budget = ACTIVE_BUDGET.get()
            if budget is None:
                verification["skip_reason"] = "managed_budget_required"
            else:
                # Only a successful primary result can supply approved text.
                # Never fall back to data.text or even data.llm_text here.
                started, before_calls = time.perf_counter(), budget.calls
                try:
                    parsed = await self.llm.verify(text=llm["input_used"])
                except LLMFailure as exc:
                    parsed = verification_error(exc.code)
                except (ValueError, TypeError, KeyError):
                    parsed = verification_error("INPUT_INVALID")
                # The frozen revision parser expects only protocol fields;
                # transport observations remain separate from its schema.
                proposed = revision(level, {key: parsed[key] for key in (
                    "status", "code", "assessment", "reason_code", "quotes") if key in parsed})
                verification.update(parsed)
                verification.update(attempted=budget.calls > before_calls,
                    original_level=level, suggested_level=proposed["level"],
                    revision_status=proposed["status"], needs_review=proposed["needs_review"],
                    elapsed_ms=round(1000 * (time.perf_counter() - started), 2))
        result["execution"]["verification"] = {
            "mode": "shadow", "status": verification["status"], "attempted": verification["attempted"],
            "stage": STAGE, "input_scope": "approved_llm_input_only",
            "verdict_changed": False, "applied": False,
        }
        result["execution"]["runtime_manifest"]["verification"] = deepcopy(self.verification_manifest)
        result["timing"]["verification_ms"] = verification.get("elapsed_ms", 0.0)
        result["timing"]["total_ms"] = round(1000 * (time.perf_counter() - analysis_started), 1)
        return result


def create_app(settings=None, transport=None, model_service=None, rag_service=None):
    app = create_focused_app(settings, transport, model_service, rag_service)
    manifest = shadow_manifest()
    original_lifespan = app.router.lifespan_context
    original_status = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/api/status")

    @asynccontextmanager
    async def lifespan(instance):
        async with original_lifespan(instance):
            facade = VerifierFacade(instance.state.llm)
            instance.state.analysis.llm = instance.state.llm = facade
            instance.state.analysis = ShadowAnalysis(instance.state.analysis, manifest)
            yield

    app.router.lifespan_context = lifespan
    app.title = "PhishLens · verifier shadow (experimental)"
    app.router.routes[:] = [route for route in app.router.routes if getattr(route, "path", None) != "/api/status"]

    @app.get("/api/status")
    async def status():
        data = await original_status()
        data["analysis_policy"].update(verifier_mode="shadow", verifier_applies_revision=False)
        data["runtime_manifest"]["verification"] = deepcopy(manifest)
        return data

    return app
