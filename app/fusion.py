RISK_LABELS = {
    "HIGH": "Nguy cơ cao",
    "WARNING": "Cần kiểm tra thêm",
    "LOW": "Chưa phát hiện dấu hiệu rõ ràng",
    "UNKNOWN": "Chưa đủ thông tin",
}


def fuse_legacy(mode: str, urls: list[dict], llm: dict, invalid_urls: list[str]) -> dict:
    """Frozen max-alarm policy for reproducing the v1 experiments only."""
    ml_levels = [u["risk_level"] for u in urls if u.get("status") == "ok"]
    llm_level = llm.get("verdict", {}).get("risk_level") if llm.get("status") == "ok" else None
    incomplete_urls = bool(invalid_urls) or any(u.get("status") != "ok" for u in urls)
    conflict = bool(ml_levels and llm_level and (
        (max(ml_levels, key=lambda x: {"LOW": 0, "WARNING": 1, "HIGH": 2}[x]) == "LOW" and llm_level in {"HIGH", "WARNING"})
        or (any(x in {"HIGH", "WARNING"} for x in ml_levels) and llm_level == "LOW")
    ))
    if "HIGH" in ml_levels:
        level, basis = "HIGH", "Có URL đạt ngưỡng cảnh báo cao của mô hình ML."
    elif llm_level == "HIGH":
        level, basis = "HIGH", "LLM nêu dấu hiệu nguy cơ cao trong nội dung được cung cấp."
    elif "WARNING" in ml_levels:
        level, basis = "WARNING", "Có URL đạt ngưỡng cảnh báo của mô hình ML."
    elif llm_level == "WARNING":
        level, basis = "WARNING", "Nội dung có dấu hiệu cần được kiểm tra thêm."
    elif incomplete_urls:
        level, basis = "UNKNOWN", "Chưa đánh giá được đầy đủ các URL trong đầu vào."
    elif mode == "url" and ml_levels and all(x == "LOW" for x in ml_levels):
        level, basis = "LOW", "Điểm URL dưới ngưỡng cảnh báo; kết quả chỉ dựa trên các thành phần đã xử lý."
    elif llm_level == "LOW":
        level, basis = "LOW", "Chưa thấy dấu hiệu rõ ràng qua những thông tin đã phân tích."
    else:
        level, basis = "UNKNOWN", "Chưa phân tích được nội dung; kết quả URL riêng lẻ không đủ kết luận cho toàn bộ thông điệp."
    return {"risk_level": level, "label": RISK_LABELS[level], "basis": basis, "conflict": conflict}


POLICY_VERSION = "separate-assessments-2.0"
SEVERITY = {"UNKNOWN": -1, "LOW": 0, "WARNING": 1, "HIGH": 2}


def assess_urls(urls: list[dict], invalid_urls: list[str]) -> dict:
    valid = [u["risk_level"] for u in urls if u.get("status") == "ok" and u.get("risk_level") in SEVERITY]
    incomplete = bool(invalid_urls) or len(valid) != len(urls) or "UNKNOWN" in valid
    highest = max(valid, key=SEVERITY.get) if valid else "UNKNOWN"
    level = highest if highest in {"HIGH", "WARNING"} else "UNKNOWN" if incomplete else highest
    return {"risk_level": level, "label": RISK_LABELS[level], "scope": "url",
            "status": "partial" if valid and incomplete else "ok" if valid else "unavailable" if urls or invalid_urls else "not_present",
            "complete": not incomplete, "processed": len(valid), "total": len(urls) + len(invalid_urls),
            "basis": "Điểm phân loại chuỗi URL; chưa kiểm tra trang đích hoặc danh tính người gửi."}


def fuse(mode: str, urls: list[dict], llm: dict, invalid_urls: list[str]) -> dict:
    """Keep URL risk and requested message actions as distinct output targets.

    A LOW message never clears a URL alarm. A URL alarm alone never proves
    that a quoted example or an entire message is a scam. UNKNOWN is retained
    when the content component is disabled, fails, or lacks evidence.
    """
    if mode not in {"url", "text"}:
        raise ValueError("Unknown analysis mode.")
    url = assess_urls(urls, invalid_urls)
    llm_level = llm.get("verdict", {}).get("risk_level") if llm.get("status") == "ok" else "UNKNOWN"
    if llm_level not in SEVERITY:
        llm_level = "UNKNOWN"
    message_level = llm_level if mode == "text" else "UNKNOWN"
    message = {"risk_level": message_level, "label": RISK_LABELS[message_level], "scope": "message",
               "status": llm.get("status", "unavailable") if mode == "text" else "not_applicable",
               "input_scope": "approved_llm_text",
               "basis": "Nhận định về hành vi trong bản nội dung đã gửi LLM; không xác nhận danh tính người gửi."}
    conflict = mode == "text" and ((url["risk_level"] in {"HIGH", "WARNING"} and message_level == "LOW")
                                  or (url["risk_level"] == "LOW" and message_level in {"HIGH", "WARNING"}))
    url_alarm = url["risk_level"] in {"HIGH", "WARNING"}
    url_incomplete = url["status"] in {"partial", "unavailable"}
    scope = "url" if mode == "url" else "message"
    level = url["risk_level"] if mode == "url" else message_level
    if mode == "url":
        basis = url["basis"]
    elif message_level in {"HIGH", "WARNING"}:
        basis = "LLM nêu dấu hiệu trong hành vi được yêu cầu; xem bằng chứng và cảnh báo URL riêng bên dưới."
    elif message_level == "LOW":
        basis = "Chưa thấy hành vi lừa đảo rõ trong bản nội dung đã gửi LLM. Cần đối chiếu riêng các đường dẫn."
    else:
        basis = "Chưa đủ căn cứ đánh giá hành vi trong tin nhắn. Kết quả URL được giữ riêng, kể cả khi LLM chưa hoạt động."
    review_reason = ("Có URL cần cảnh giác; chưa kiểm tra trang đích hoặc danh tính chủ sở hữu."
                     if mode == "url" and url_alarm else
                     "Có URL cần cảnh giác; hành vi trong tin nhắn chưa được kết luận. Không mở hoặc điền thông tin trước khi xác minh."
                     if url_alarm and message_level == "UNKNOWN" else
                     "Có URL cần cảnh giác dù nội dung chưa cho thấy hành vi lừa đảo. Không mở hoặc điền thông tin trước khi xác minh."
                     if url_alarm and message_level == "LOW" else
                     "Nội dung có dấu hiệu dẫn dụ dù điểm URL thấp; điểm URL không bác bỏ yêu cầu nguy hiểm."
                     if conflict else "Có đường dẫn chưa được đánh giá đầy đủ." if url_incomplete else "")
    return {"risk_level": level, "label": RISK_LABELS[level], "basis": basis, "scope": scope,
            "policy_version": POLICY_VERSION, "conflict": bool(conflict),
            "requires_review": bool(conflict or url_incomplete or url_alarm or level == "UNKNOWN"),
            "review_reason": review_reason, "assessments": {"url": url, "message": message}}

