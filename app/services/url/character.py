"""Opt-in character URL candidate, reconstructed from JSON/NPZ without pickle.

The export command replays one locked configuration and refuses to export unless
all learned-array hashes and all historical validation/test scores match exactly.
It never tunes or replaces the production XGBoost model.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from threading import RLock

import numpy as np
import scipy
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from app.core.settings import ROOT
DEFAULT_AUDIT = ROOT / "artifacts/evaluations/url_char_baseline_v1"
DEFAULT_DEPLOYMENT = ROOT / "models/url_character"
DEFAULT_PREPROCESSING = ROOT / "models/inference_XGBoost_d6_s42/url_preprocessing.py"
SCHEMA = "char-url-export-1.0"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _versions():
    return {"numpy": np.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__}


def _learned_hashes(vectorizer, classifier):
    vocabulary = {key: int(value) for key, value in vectorizer.vocabulary_.items()}
    return {"vocabulary_sha256": hashlib.sha256(json.dumps(vocabulary, sort_keys=True).encode()).hexdigest(),
        "idf_sha256": hashlib.sha256(vectorizer.idf_.tobytes()).hexdigest(),
        "coefficient_sha256": hashlib.sha256(classifier.coef_.tobytes() + classifier.intercept_.tobytes()).hexdigest()}


class CharURLService:
    """ModelService-compatible candidate; LOW is a score band, not verification."""
    def __init__(self, artifact_dir=DEFAULT_DEPLOYMENT, preprocessing_path=DEFAULT_PREPROCESSING):
        self.path = Path(artifact_dir).expanduser().resolve()
        self.preprocessing_path = Path(preprocessing_path).expanduser().resolve()
        self.lock = RLock()
        self.vectorizer = self.classifier = self.preprocessing = None
        self.spec = {}
        self.error = "Chưa nạp model URL ký tự thử nghiệm."

    def load(self, reload=False):
        with self.lock:
            if self.classifier is not None and not reload:
                return self.status()
            self.vectorizer = self.classifier = self.preprocessing = None
            self.spec = {}
            try:
                manifest = json.loads((self.path / "export.json").read_text())
                if manifest["schema"] != SCHEMA or manifest["candidate"] is not True:
                    raise ValueError("Định dạng export candidate không hợp lệ.")
                if manifest["versions"] != _versions():
                    raise ValueError("Phiên bản numpy/scipy/scikit-learn khác bản export đã kiểm chứng.")
                if set(manifest["files"]) != {"vocabulary.json", "weights.npz"}:
                    raise ValueError("Danh sách file export không hợp lệ.")
                for name, expected in manifest["files"].items():
                    if _sha(self.path / name) != expected:
                        raise ValueError("Hash export không khớp: " + name)
                if _sha(self.preprocessing_path) != manifest["preprocessing_sha256"]:
                    raise ValueError("Mã chuẩn hóa URL khác bản đã kiểm chứng.")
                if _sha(ROOT / "evaluation/url/character_baseline.py") != manifest["source_runner_sha256"]:
                    raise ValueError("Mã baseline khác bản đã khóa khi export.")
                if _sha(Path(__file__)) != manifest["serving_source_sha256"]:
                    raise ValueError("Mã suy luận khác bản đã kiểm chứng khi export.")
                if manifest["equivalence"]["all_scores_bitwise_match"] is not True or manifest["equivalence"]["rows"] <= 0:
                    raise ValueError("Export chưa có bằng chứng khớp checkpoint.")
                thresholds = manifest["thresholds"]
                low, high = float(thresholds["warning_threshold"]), float(thresholds["high_threshold"])
                if low != .5 or not np.isfinite(high) or not low <= high <= 1:
                    raise ValueError("Ngưỡng candidate không hợp lệ; cần 0,5 ≤ HIGH ≤ 1.")
                vocabulary = json.loads((self.path / "vocabulary.json").read_text())
                if not vocabulary or any(type(value) is not int for value in vocabulary.values()) or set(vocabulary.values()) != set(range(len(vocabulary))):
                    raise ValueError("Vocabulary không hợp lệ.")
                with np.load(self.path / "weights.npz", allow_pickle=False) as saved:
                    if set(saved.files) != {"idf", "coef", "intercept", "classes"}:
                        raise ValueError("Các mảng trọng số không hợp lệ.")
                    arrays = {name: saved[name].copy() for name in saved.files}
                n = len(vocabulary)
                if arrays["idf"].shape != (n,) or arrays["coef"].shape != (1, n) or arrays["intercept"].shape != (1,) or not np.array_equal(arrays["classes"], [0, 1]):
                    raise ValueError("Kích thước trọng số không khớp vocabulary.")
                if any(array.dtype != np.float64 or not np.isfinite(array).all() for name, array in arrays.items() if name != "classes") or (arrays["idf"] <= 0).any():
                    raise ValueError("Trọng số không hữu hạn hoặc sai kiểu float64.")
                vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(3, 5), lowercase=True,
                    min_df=2, max_features=150000, sublinear_tf=True, norm="l2", dtype=np.float64,
                    vocabulary=vocabulary)
                vectorizer.idf_ = arrays["idf"]
                classifier = LogisticRegression(C=1., solver="liblinear", class_weight="balanced",
                    max_iter=1000, random_state=42)
                classifier.classes_, classifier.coef_ = arrays["classes"], arrays["coef"]
                classifier.intercept_, classifier.n_features_in_ = arrays["intercept"], n
                # transform validates fixed vocabulary, without learning from this probe.
                vectorizer.transform(["[DOMAIN] example.invalid"])
                if _learned_hashes(vectorizer, classifier) != manifest["learned_hashes"]:
                    raise ValueError("Vocabulary/IDF/hệ số không khớp bản fit đã khóa.")
                spec = importlib.util.spec_from_file_location("char_candidate_preprocessing", self.preprocessing_path)
                preprocessing = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(preprocessing)
                self.vectorizer, self.classifier, self.preprocessing = vectorizer, classifier, preprocessing
                self.spec, self.error = manifest, ""
            except Exception as exc:
                known = str(exc) if isinstance(exc, (ValueError, KeyError, FileNotFoundError)) else type(exc).__name__
                self.error = "Không nạp được model URL ký tự: " + known[:240]
            return self.status()

    def status(self):
        return {"ready": self.classifier is not None, "run_id": "char_tfidf_logreg_v1",
            "kind": "char_tfidf_logreg", "folder": self.path.name,
            "feature_count": len(self.vectorizer.vocabulary_) if self.vectorizer is not None else 0,
            "thresholds": self.spec.get("thresholds", {}), "experimental": True,
            "message": self.error or "Model URL ký tự thử nghiệm; LOW không xác minh website an toàn."}

    def _scores(self, urls):
        texts = [self.preprocessing.format_url(url) for url in urls]
        return self.classifier.predict_proba(self.vectorizer.transform(texts))[:, 1]

    def predict(self, urls):
        with self.lock:
            self.load()
            outputs = []
            for index, url in enumerate(urls, 1):
                row = {"id": f"URL-{index:02}", "url": url, "experimental": True,
                       "model": "char_tfidf_logreg_v1"}
                if self.classifier is None:
                    outputs.append({**row, "status": "unavailable", "message": self.error})
                    continue
                try:
                    score = float(self._scores([url])[0])
                    if not np.isfinite(score) or not 0 <= score <= 1:
                        raise ValueError("Invalid score")
                    low, high = (self.spec["thresholds"][key] for key in ["warning_threshold", "high_threshold"])
                    level = "HIGH" if score >= high else "WARNING" if score >= low else "LOW"
                    outputs.append({**row, "status": "ok", "score": score, "risk_level": level,
                        "warning_threshold": low, "high_threshold": high,
                        "message": "Điểm chuỗi URL từ model thử nghiệm, chưa xác minh trang đích."})
                except Exception:
                    outputs.append({**row, "status": "error", "message": "Không xử lý được URL; chưa có kết luận về độ an toàn."})
            return outputs


def export(audit_dir=DEFAULT_AUDIT):
    # Heavy evaluation imports are CLI-only; serving never fits or reads test data.
    import evaluation.url.character_baseline as audit
    audit_dir = Path(audit_dir).resolve()
    target = audit_dir / "deployment"
    if target.exists():
        raise ValueError("Export đã tồn tại; không ghi đè hoặc fit lại.")
    audit.verify(audit_dir)
    original = json.loads((audit_dir / "fit.json").read_text())
    frames, _ = audit.dataset()
    model, replay = audit.fit_training_only(frames)
    expected_hashes = {name: original[name] for name in ["vocabulary_sha256", "idf_sha256", "coefficient_sha256"]}
    if _learned_hashes(model["tfidf"], model["classifier"]) != expected_hashes:
        raise ValueError("Replay learned arrays differ; export refused, no tuning/refit retries.")
    import pandas as pd
    scores = pd.read_csv(audit_dir / "scores.csv.gz", float_precision="round_trip").set_index("id")
    rows = 0
    for split in ["val", "test"]:
        actual = model.predict_proba(frames[split].model_input)[:, 1]
        if not np.array_equal(actual, scores.loc[frames[split].id].char_score.to_numpy()):
            raise ValueError("Replay scores differ; export refused.")
        rows += len(actual)
    summary = json.loads((audit_dir / "summary.json").read_text())
    high = summary["Char_TFIDF_LogReg"]["fpr_5pct"]["full_validation_threshold"]
    if high is None or not .5 <= high <= 1:
        raise ValueError("Full-validation candidate HIGH is below predeclared 0.5 or invalid.")
    temporary = Path(tempfile.mkdtemp(prefix=".deployment-", dir=audit_dir))
    try:
        vectorizer, classifier = model["tfidf"], model["classifier"]
        _json(temporary / "vocabulary.json", {key: int(value) for key, value in vectorizer.vocabulary_.items()})
        np.savez_compressed(temporary / "weights.npz", idf=vectorizer.idf_, coef=classifier.coef_,
                            intercept=classifier.intercept_, classes=classifier.classes_)
        manifest = {"schema": SCHEMA, "candidate": True, "versions": _versions(),
            "files": {name: _sha(temporary / name) for name in ["vocabulary.json", "weights.npz"]},
            "learned_hashes": expected_hashes, "preprocessing_sha256": _sha(DEFAULT_PREPROCESSING),
            "configuration": audit.CONFIG, "source_runner_sha256": _sha(Path(audit.__file__)),
            "serving_source_sha256": _sha(Path(__file__)),
            "audit_hashes": {name: _sha(audit_dir / name) for name in ["execution.json", "fit.json", "scores.csv.gz", "summary.json"]},
            "thresholds": {"warning_threshold": .5, "high_threshold": high,
                "selected_on": "low_fixed_0.5_before_fit; HIGH_historical_validation_negative_FPR5pct"},
            "equivalence": {"all_scores_bitwise_match": True, "rows": rows,
                "vocabulary_idf_coefficients_hash_match": True},
            "export_refit": {"count": 1, "same_configuration_no_tuning": True, "train_seconds": replay["train_seconds"]},
            "limitations": "candidate only; historical diagnostic cutoffs; LOW does not verify safety; no independent new-data evidence",
            "API_calls": 0}
        _json(temporary / "export.json", manifest)
        runtime = CharURLService(temporary)
        if not runtime.load()["ready"]:
            raise ValueError("Reconstructed service refused export: " + runtime.error)
        for split in ["val", "test"]:
            actual = runtime._scores(frames[split].url.tolist())
            if not np.array_equal(actual, scores.loc[frames[split].id].char_score.to_numpy()):
                raise ValueError("Reconstructed serving scores differ; export refused.")
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    print(json.dumps({"exported": str(target), "rows_verified_exact": rows,
                      "learned_arrays_match": True, "API_calls": 0}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["export"])
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    export(args.audit_dir)


if __name__ == "__main__":
    main()
