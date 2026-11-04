"""Application workflow, independent of HTTP routes and provider transport.

URL classification targets the original input; message analysis and retrieval
target only the redacted text approved by the user. Their conclusions stay
separate. Component execution is reported even when a requested step fails.
"""
from datetime import datetime, timezone
import time

from starlette.concurrency import run_in_threadpool

from .fusion import fuse
from .llm_service import LLMFailure
from .privacy import redact
from .schemas import AnalyzeInput
from .urls import extract_urls


PIPELINE_VERSION = "analysis-pipeline-3.0"
MESSAGE_PROFILE = "message-v3"


class AnalysisInputError(ValueError):
    """A request cannot be processed; no external call has been made."""


class AnalysisService:
    def __init__(self, ml, rag, llm):
        self.ml, self.rag, self.llm = ml, rag, llm

    async def analyze(self, data: AnalyzeInput) -> dict:
        started = time.perf_counter()
        if data.use_llm and not data.consent:
            raise AnalysisInputError("Cần xem bản nội dung gửi ra ngoài và xác nhận trước khi gọi LLM.")
        try:
            urls, invalid = extract_urls(data.text, data.mode)
        except ValueError as exc:
            raise AnalysisInputError(str(exc)) from exc
        text, fields = "", []
        if data.use_llm:
            text, fields = redact(data.llm_text if data.llm_text is not None else data.text)
            if not text.strip():
                raise AnalysisInputError("Bản gửi tới LLM không được để trống.")
            try:
                extract_urls(text, "text")
            except ValueError as exc:
                raise AnalysisInputError(str(exc)) from exc

        ml_started = time.perf_counter()
        url_results = await run_in_threadpool(self.ml.predict, urls) if urls else []
        ml_ms = round((time.perf_counter() - ml_started) * 1000, 1)
        llm = {"status": "disabled", "message": "Chưa bật phân tích bằng LLM.", "rag": False}
        retrieval = {"status": "disabled", "sources": [], "reason": "Chưa bật tham khảo tài liệu RAG."}
        rag_ms = llm_ms = 0.0
        prompt_profile = MESSAGE_PROFILE if data.mode == "text" else "legacy"
        retrieval_attempted = data.use_llm and data.use_rag and data.mode == "text"
        if data.use_rag and not data.use_llm:
            retrieval["reason"] = "AI đang tắt nên chưa truy xuất tài liệu để giải thích nội dung."
        if data.use_llm:
            if retrieval_attempted:
                rag_started = time.perf_counter()
                retrieval = await run_in_threadpool(self.rag.search, text, data.mode)
                rag_ms = round((time.perf_counter() - rag_started) * 1000, 1)
            elif data.use_rag:
                retrieval = {"status": "empty", "sources": [],
                             "reason": "Tài liệu về thủ đoạn không xác nhận uy tín của một URL; không truy xuất ở chế độ đường dẫn."}
            llm_started = time.perf_counter()
            try:
                llm = await self.llm.analyze(
                    text=text, mode=data.mode, urls=url_results, include_ml=data.include_ml,
                    endpoint=data.endpoint, model=data.model, api_key=data.api_key.get_secret_value(),
                    rag_sources=retrieval["sources"],
                    prompt_profile=prompt_profile,
                )
                llm["masked_fields"] = fields
                llm["input_modified"] = text != redact(data.text)[0]
            except LLMFailure as exc:
                llm = {"status": "error", "code": exc.code, "message": exc.message, "rag": False}
            llm_ms = round((time.perf_counter() - llm_started) * 1000, 1)

        decision = fuse(data.mode, url_results, llm, invalid)
        return {
            "created_at": datetime.now(timezone.utc).isoformat(), "mode": data.mode,
            "configuration": ("ML + LLM" if data.use_llm and data.include_ml else "ML / LLM độc lập" if data.use_llm else "ML") + (" + RAG" if llm.get("rag") else ""),
            "final": decision, "assessments": decision["assessments"], "urls": url_results,
            "invalid_urls": invalid, "llm": llm, "ml": self.ml.status(), "retrieval": retrieval,
            "execution": {
                "version": PIPELINE_VERSION,
                "requested": {"llm": data.use_llm, "rag": data.use_rag, "url_context": data.include_ml},
                "url": {"status": decision["assessments"]["url"]["status"],
                        "processed": decision["assessments"]["url"]["processed"], "input_scope": "original_input"},
                "retrieval": {"attempted": retrieval_attempted, "status": retrieval["status"],
                              "source_count": len(retrieval["sources"]),
                              "included_in_successful_llm_call": bool(llm.get("rag")),
                              "input_scope": "approved_redacted_text"},
                "llm": {"status": llm["status"], "prompt_profile": llm.get("prompt_profile"),
                        "requested_profile": prompt_profile if data.use_llm else None,
                        "included_url_context": bool(llm.get("included_ml")),
                        "input_scope": "approved_redacted_text"},
            },
            "timing": {"ml_ms": ml_ms, "rag_ms": rag_ms, "llm_ms": llm_ms,
                       "total_ms": round((time.perf_counter() - started) * 1000, 1)},
            "notice": "Nhận định hành vi áp dụng cho bản nội dung đã gửi LLM. Cảnh báo URL được đánh giá riêng tại máy. Mức thấp không bảo đảm an toàn; ứng dụng không mở trang đích.",
        }
