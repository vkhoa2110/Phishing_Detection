import importlib.util
import json
import math
import sys
from pathlib import Path
from threading import RLock

from .settings import Settings


class ModelService:
    """Nạp gói do notebook xuất. Chỉ dùng mã/mô hình do chính bạn tạo."""
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = RLock()
        self.predictor = None
        self.spec = {}
        self.path: Path | None = None
        self.error = "Chưa tìm thấy gói mô hình."

    def _resolve(self) -> Path | None:
        configured = Path(self.settings.model_dir).expanduser()
        if not configured.is_absolute():
            configured = self.settings.root / configured
        candidates = [configured]
        if configured.is_dir():
            candidates.extend(sorted(configured.glob("inference_*")))
        candidates.extend(sorted(self.settings.root.glob("inference_*")))
        candidates.extend(sorted((self.settings.root / "models").glob("inference_*")))
        for path in dict.fromkeys(candidates):
            if (path / "predict_url.py").is_file() and any((path / f).is_file() for f in ["config.json", "run.json"]):
                return path.resolve()
        return None

    def load(self, reload: bool = False) -> dict:
        with self.lock:
            if self.predictor is not None and not reload:
                return self.status()
            self.predictor, self.spec, self.path = None, {}, self._resolve()
            if not self.path:
                self.error = "Đặt thư mục models/inference_XGBoost_d6_s42 vào thư mục dự án rồi bấm Nạp lại."
                return self.status()
            try:
                config_path = self.path / "config.json"
                if not config_path.exists():
                    config_path = self.path / "run.json"
                self.spec = json.loads(config_path.read_text(encoding="utf-8"))
                if self.spec.get("kind") not in {"xgboost", "lightgbm", "rf", "logreg"}:
                    raise ValueError("Chỉ hỗ trợ gói ML từ notebook; không nạp BERT ở bản này.")
                if self.spec.get("smoke_test"):
                    raise ValueError("Gói này được tạo ở chế độ SMOKE_TEST.")
                names = self.spec["feature_names"]
                tw = float(self.spec["thresholds"]["warning_threshold"])
                th = self.spec["thresholds"]["high_threshold"]
                if not names or len(names) != len(set(names)) or not math.isfinite(tw) or not 0 <= tw <= 1:
                    raise ValueError("Cấu hình feature/ngưỡng không hợp lệ.")
                if th is not None and (not math.isfinite(float(th)) or not tw <= float(th) <= 1):
                    raise ValueError("Ngưỡng cao phải lớn hơn hoặc bằng ngưỡng cảnh báo.")
                # Import đúng các module trong gói, tránh cache của gói khác.
                for name in ["url_features", "url_preprocessing", "phishlens_export_predictor"]:
                    sys.modules.pop(name, None)
                for name, filename in [("url_features", "url_features.py"), ("url_preprocessing", "url_preprocessing.py"), ("phishlens_export_predictor", "predict_url.py")]:
                    spec = importlib.util.spec_from_file_location(name, self.path / filename)
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[name] = module
                    spec.loader.exec_module(module)
                cls = sys.modules["phishlens_export_predictor"].URLRiskPredictor
                self.predictor = cls(self.path)
                if list(self.predictor.features) != names:
                    raise ValueError("Thứ tự feature của config và bộ suy luận không khớp.")
                # Gói xuất từ notebook đã đặt XGBoost chạy CPU khi nạp.
                self.error = ""
            except Exception as exc:
                self.predictor = None
                known = str(exc) if isinstance(exc, (ValueError, ModuleNotFoundError, FileNotFoundError, KeyError)) else type(exc).__name__
                self.error = f"Không nạp được model: {known[:240]}. Xem README để kiểm tra gói và thư viện."
            return self.status()

    def status(self) -> dict:
        return {
            "ready": self.predictor is not None,
            "run_id": self.spec.get("run_id"),
            "kind": self.spec.get("kind"),
            "folder": self.path.name if self.path else None,
            "feature_count": len(self.spec.get("feature_names", [])),
            "thresholds": self.spec.get("thresholds", {}),
            "message": self.error or "Mô hình ML đã sẵn sàng.",
        }

    def predict(self, urls: list[str]) -> list[dict]:
        with self.lock:
            self.load()
            result = []
            for i, url in enumerate(urls, 1):
                item = {"id": f"URL-{i:02}", "url": url}
                if self.predictor is None:
                    result.append({**item, "status": "unavailable", "message": self.error})
                    continue
                try:
                    output = self.predictor.predict([url])[0]
                    score = float(output["score"])
                    if not math.isfinite(score) or not 0 <= score <= 1 or output["risk_level"] not in {"HIGH", "WARNING", "LOW"}:
                        raise ValueError("Điểm dự đoán không hợp lệ.")
                    result.append({**item, "status": "ok", "score": score,
                        "risk_level": output["risk_level"],
                        "warning_threshold": self.spec["thresholds"]["warning_threshold"],
                        "high_threshold": self.spec["thresholds"]["high_threshold"]})
                except Exception:
                    result.append({**item, "status": "error", "message": "Không xử lý được URL này; không coi đây là kết quả ít nguy cơ."})
            return result

