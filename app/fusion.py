RISK_LABELS = {
    "HIGH": "Nguy cơ cao",
    "WARNING": "Cần kiểm tra thêm",
    "LOW": "Chưa phát hiện dấu hiệu rõ ràng",
    "UNKNOWN": "Chưa đủ thông tin",
}


def fuse(mode: str, urls: list[dict], llm: dict, invalid_urls: list[str]) -> dict:
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

