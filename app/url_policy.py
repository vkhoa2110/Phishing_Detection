"""Conservative operating policy over unchanged URL scores and frozen cutoffs.

The old WARNING band becomes UNKNOWN, never LOW. This is abstention, not
retraining, probability calibration, or evidence of current website safety.
"""
import math

VERSION = "url-abstention-bands-1.0"


def operating_prediction(raw):
    if raw.get("status") != "ok":
        return dict(raw)
    try:
        score = float(raw["score"])
        low = float(raw.get("raw_warning_threshold", raw["warning_threshold"]))
        high = raw.get("raw_high_threshold", raw["high_threshold"])
        original_risk = raw.get("raw_risk_level", raw["risk_level"])
        high = float(high) if high is not None else None
        if original_risk not in {"HIGH", "WARNING", "LOW"}:
            raise ValueError
        if not math.isfinite(score) or not math.isfinite(low) or not 0 <= low <= 1 or not 0 <= score <= 1:
            raise ValueError
        if high is not None and (not math.isfinite(high) or not low <= high <= 1):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return {**raw, "status": "error", "risk_level": "UNKNOWN", "message": "Chưa có điểm/ngưỡng URL hợp lệ để đưa ra kết luận."}
    risk = "LOW" if score < low else "HIGH" if high is not None and score >= high else "UNKNOWN"
    return {**raw, "risk_level": risk, "raw_risk_level": original_risk,
        "raw_warning_threshold": low, "raw_high_threshold": high, "warning_threshold": high, "high_threshold": high,
        "low_threshold": low, "decision_policy": VERSION,
        "message": "Điểm URL ở vùng chưa đủ tin cậy; cần kiểm tra thêm, chưa kết luận an toàn hoặc lừa đảo."
                   if risk == "UNKNOWN" else "Kết quả theo chuỗi URL, chưa xác minh trang đích."}


class ConservativeURLModel:
    def __init__(self, model):
        self.model = model

    def load(self, reload=False):
        self.model.load(reload=reload)
        return self.status()

    def status(self):
        status = self.model.status()
        original = status.get("thresholds", {})
        high = original.get("high_threshold")
        return {**status, "decision_policy": VERSION, "training_thresholds": original,
                "thresholds": {"warning_threshold": high, "high_threshold": high,
                               "low_threshold": original.get("warning_threshold"),
                               "selected_on": "existing_training_validation_cutoffs_no_new_fit"},
                "uncertainty_policy": "Vùng giữa hai ngưỡng cũ là UNKNOWN; score chưa là xác suất đã hiệu chỉnh."}

    def predict(self, urls):
        return [operating_prediction(row) for row in self.model.predict(urls)]
