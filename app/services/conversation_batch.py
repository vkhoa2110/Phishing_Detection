"""Bounded sequential conversation windows, preserving partial coverage explicitly."""
import copy
import re
import time

from fastapi import HTTPException
from app.core.privacy import redact
from app.domain.decisions import fuse
from app.services.workspace import WorkspaceError

MAX_TEXT = 200_000
MAX_PARTS = 64
WINDOW = 7600


def windows(text):
    """Every approved character is assessed, with overlap at turn boundaries.

    Long individual turns also overlap, so a sentence crossing a window is
    not silently lost. No generated summary replaces the original turns.
    """
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + WINDOW)
        if end < len(text):
            boundary = text.rfind("\n[Tin ", start + WINDOW // 2, end)
            if boundary > start:
                end = boundary
        parts.append(text[start:end])
        if len(parts) > MAX_PARTS:
            raise WorkspaceError(422, "Phạm vi quá dài. Chọn ít tin hơn hoặc chia theo ngày.")
        if end == len(text):
            break
        boundaries = [m.start() for m in re.finditer(r"\n\[Tin ", text[start:end])]
        # Up to 1,200 chars of original preceding conversation, never a whole
        # huge turn that could prevent forward progress.
        overlap = boundaries[-2] + start if len(boundaries) >= 2 else end - 600
        start = max(start + 1, end - 1200, min(overlap, end - 1))
    return parts


def preview(text):
    approved, masked = redact(text)
    parts = windows(approved)
    return {"text": approved, "masked_fields": masked, "parts": len(parts),
            "characters": len(approved), "max_characters": MAX_TEXT}


def aggregate(results, total, scope, stopped=None):
    if not results:
        raise WorkspaceError(422, "Chưa phân tích được phần nào. Hãy kiểm tra lại kết nối hoặc hạn mức.")
    result = copy.deepcopy(results[0])
    rows = []
    for index, part in enumerate(results):
        llm = part["llm"]
        risk = llm.get("verdict", {}).get("risk_level", "UNKNOWN") if llm.get("status") == "ok" else "UNKNOWN"
        rows.append({"part": index + 1, "risk_level": risk, "status": llm.get("status"), "result": part})
    risks = [row["risk_level"] for row in rows]
    complete = len(rows) == total and all(row["status"] == "ok" for row in rows)
    risk = "HIGH" if "HIGH" in risks else "WARNING" if "WARNING" in risks else "UNKNOWN" if not complete or "UNKNOWN" in risks else "LOW"
    labels = {"HIGH": "Có dấu hiệu nguy cơ cao", "WARNING": "Có phần cần kiểm tra", "UNKNOWN": "Chưa đủ kết quả cho toàn phạm vi", "LOW": "Chưa phát hiện dấu hiệu rõ ràng"}
    evidence, seen, urls = [], set(), {}
    for row in sorted(rows, key=lambda row: {"HIGH": 0, "WARNING": 1, "UNKNOWN": 2, "LOW": 3}[row["risk_level"]]):
        for item in row["result"]["llm"].get("verdict", {}).get("evidence", []):
            if item["quote"] not in seen:
                evidence.append({**item, "part": row["part"]}); seen.add(item["quote"])
    for part in results:
        for url in part.get("urls", []):
            urls.setdefault(url["url"], url)
    message = f"Đã xử lý {len(rows)}/{total} phần của phạm vi đã chọn. "
    message += "Có dấu hiệu cần đối chiếu trong hội thoại." if risk in {"HIGH", "WARNING"} else "Chưa hoàn tất hoặc còn phần chưa đủ ngữ cảnh." if risk == "UNKNOWN" else "Các phần đã phân tích chưa cho thấy yêu cầu lừa đảo rõ ràng."
    result["llm"] = {"status": "ok", "verdict": {"risk_level": risk, "summary": message,
        "evidence": evidence[:20], "recommended_actions": ["Đối chiếu các tin được trích và xác minh yêu cầu qua kênh đã biết."]},
        "model": results[0]["llm"].get("model"), "prompt_version": "conversation-batch-1.0", "input_used": "",
        "evidence_explanation": {"status": "disabled"}}
    if all(part["llm"].get("status") == "disabled" for part in results):
        result["llm"]["status"] = "disabled"
    elif not any(part["llm"].get("status") == "ok" for part in results):
        result["llm"].update(status="error", message="Chưa hoàn tất phân tích AI; kết quả URL được giữ riêng.")
    result["final"] = {**result.get("final", {}), "risk_level": risk, "label": labels[risk], "requires_review": risk != "LOW"}
    result["urls"] = list(urls.values())
    result["invalid_urls"] = [url for part in results for url in part.get("invalid_urls", [])]
    decision = fuse("text", result["urls"], result["llm"], result["invalid_urls"])
    result["final"] = {**decision, "label": labels[risk], "policy_version": "conversation-windows-1.0"}
    result["assessments"] = decision["assessments"]
    result["analysis_target"] = "conversation"
    result["conversation_batch"] = {"total_parts": total, "completed_parts": len(rows), "complete": complete,
        "stopped": stopped, "scope": scope, "aggregation": "highest_warning_else_unknown_if_incomplete", "parts": rows,
        "limitation": "Từng cửa sổ được phân tích với phần ngữ cảnh chồng lấn; không phải một lượt đọc đồng thời toàn bộ lịch sử."}
    result["history"] = {"status": "disabled", "reason": "conversation_batch"}
    result["timing"] = {key: round(sum(part.get("timing", {}).get(key, 0) for part in results), 2)
        for key, value in results[0].get("timing", {}).items() if isinstance(value, (int, float))}
    result["execution"] = {"aggregation": "conversation-windows-1.0", "parts": [part.get("execution") for part in results]}
    return result


async def run(job, data, analyze, analyze_type, request):
    approved = redact(data.llm_text)[0] if data.use_llm else data.text
    parts = windows(approved)
    results, stopped, started = [], None, time.monotonic()
    job.progress = {"completed": 0, "total": len(parts), "stage": "analyzing"}
    for index, text in enumerate(parts):
        if job.cancel_requested or time.monotonic() - started > 900:
            stopped = "user_cancelled" if job.cancel_requested else "time_limit"; break
        job.progress.update(current=index + 1)
        # Score only URLs still present in the approved window. Removed text
        # cannot re-enter LLM metadata; original transcript never becomes a
        # separate hidden channel to the provider.
        payload = analyze_type.model_validate({"mode": "text", "text": text, "llm_text": text,
            "analysis_target": "conversation", "use_llm": data.use_llm, "consent": data.consent,
            "include_ml": data.include_ml, "use_rag": False, "explain_evidence": data.explain_evidence,
            "save_history": False, "save_content": False})
        try:
            part = await analyze(payload, request)
        except (HTTPException, WorkspaceError) as error:
            if not results:
                raise
            stopped = {"status": getattr(error, "status_code", getattr(error, "status", 500)), "message": str(getattr(error, "detail", getattr(error, "message", "")))}
            break
        results.append(part); job.progress["completed"] = len(results)
        # Do not hammer a failing provider or turn missing responses into LOW.
        if data.use_llm and part["llm"].get("status") == "error":
            stopped = "provider_error"; break
    job.progress["stage"] = "finished"
    return aggregate(results, len(parts), data.scope.model_dump(), stopped)
