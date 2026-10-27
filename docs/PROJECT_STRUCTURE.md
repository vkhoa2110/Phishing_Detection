# Cấu trúc và quy ước dự án

Tổ chức lại ngày **27/10/2026**. Git repository và môi trường `.venv` nằm trực tiếp trong `/home/khoa/BCTT/Phishing_Baseline_ML_LLM/`. Chạy các lệnh từ thư mục có `run.py`.

## Trách nhiệm từng nhóm

| Thư mục | Nội dung | Quy ước |
|---|---|---|
| `app/` | Backend và frontend của ứng dụng | Logic triển khai; không chứa dữ liệu thực nghiệm |
| `evaluation/` | Package chạy `python -m evaluation...` | Chỉ chứa mã đánh giá |
| `data/evaluation/` | Mẫu đánh giá có nhãn | Nhãn/provenance đi cùng mẫu |
| `data/knowledge/` | Danh mục nguồn và corpus RAG | Snapshot có phiên bản, hash và nguồn |
| `data/raw/` | Archive dữ liệu gốc | Cài cục bộ; không commit archive |
| `models/` | Gói model xuất từ notebook | Cài cục bộ; không commit trọng số |
| `notebooks/` | Huấn luyện và xuất model | Nguồn có thể kiểm tra, không chứa khóa bí mật |
| `artifacts/evaluations/` | Dự đoán, checkpoint, chỉ số và biểu đồ | Mỗi thí nghiệm một thư mục; không sửa snapshot đã chốt |
| `artifacts/report-builds/` | Bản dựng báo cáo mới | Đầu ra cục bộ, được Git bỏ qua |
| `docs/` | Hướng dẫn và báo cáo đã phát hành | Tách thiết kế, hướng dẫn, đánh giá và báo cáo |
| `scripts/` | Công cụ dòng lệnh theo nhóm | `evaluation/`, `rag/`, `reporting/` |
| `requirements/` | Profile phụ thuộc | `base`, `dev`, `evaluation`, `rag-collection`, `reporting` |
| `tests/` | Test tự động | Chạy từ gốc bằng `python -m pytest` |

`requirements.txt` ở gốc giữ lệnh cài ứng dụng quen thuộc và dẫn tới `requirements/base.txt`. Trạng thái thuật toán, prompt và ngưỡng không được đổi để tổ chức thư mục.

## Đối chiếu đường dẫn cũ–mới

| Đường dẫn cũ tính từ Git root trước đây | Đường dẫn hiện tại |
|---|---|
| `knowledge/` | `data/knowledge/` |
| `evaluation/data/` | `data/evaluation/` |
| `reports/` | `artifacts/evaluations/` |
| `deliverables/bao_cao_phishing_2026_10_26/` | `docs/reports/2026-10-26/` |
| Các script Python trong thư mục báo cáo | `scripts/reporting/` |
| `scripts/collect_rag_sources.py` | `scripts/rag/collect_rag_sources.py` |
| `scripts/validate_rag_corpus.py` | `scripts/rag/validate_rag_corpus.py` |
| `scripts/plot_evaluation.py` | `scripts/evaluation/plot_evaluation.py` |
| `scripts/verify_evaluation.py` | `scripts/evaluation/verify_evaluation.py` |
| `docs/BASELINE.md` | `docs/architecture/BASELINE.md` |
| `docs/PHISHVN_EVALUATION.md` | `docs/evaluation/PHISHVN.md` |
| `docs/EVALUATION.md` | `docs/evaluation/SYNTHETIC.md` |
| `docs/VERIFICATION.md` | `docs/evaluation/VERIFICATION.md` |
| `evaluation/README.md` | `docs/evaluation/METHODS.md` |
| Hướng dẫn chi tiết trước đây trong README gốc | `docs/guides/USAGE.md` |
| `requirements.txt` chứa toàn bộ dependency app | `requirements/base.txt` |
| `requirements-dev.txt` | `requirements/dev.txt` |
| `requirements-eval.txt` | `requirements/evaluation.txt` |
| `requirements-rag-collect.txt` | `requirements/rag-collection.txt` |
| `inference_XGBoost_d6_s42/` cạnh `run.py` | `models/inference_XGBoost_d6_s42/` |
| Notebook huấn luyện ở thư mục BCTT | `notebooks/Train_URL_Phishing_GPU.ipynb` |
| Archive PhishVN ở thư mục BCTT | `data/raw/PhishVN_v3.1.0_open.zip` trên máy hiện tại |

Hai bản `Bao_cao_Phishing.docx/pdf` ở ngoài Git root trước đây là bản sao giống hệt bản đã commit; đã gộp về `docs/reports/2026-10-26/`. Các bản gốc khác trong `/home/khoa/BCTT/` được giữ nguyên.

## Bảo toàn kết quả thực nghiệm

Các file bên trong `artifacts/evaluations/`, `data/knowledge/corpus_v1/` và các tài sản báo cáo đã xuất được chuyển nguyên byte. Hash, ngày tạo, đường dẫn trong manifest và nội dung báo cáo mô tả hiện trạng lúc tạo; không ghi đè chúng để làm khớp tên thư mục mới.

Hash mã nguồn hiện tại thay đổi do chuyển đường dẫn. Khi chạy lại thực nghiệm, chọn `--out` mới; không resume vào snapshot lịch sử bằng cấu hình đã đổi. Công cụ dựng báo cáo xuất sang `artifacts/report-builds/` và đọc minh chứng đã chốt trong `docs/reports/2026-10-26/`.

## Dữ liệu cục bộ và Git

Git theo dõi mã nguồn, tài liệu, bộ mẫu, corpus đã rà soát và ba snapshot thí nghiệm đã chốt. `.env`, `.venv`, trọng số, archive gốc, kết quả chạy mới và bản dựng báo cáo mới được bỏ qua. Muốn phát hành một thí nghiệm mới, rà soát nội dung và bổ sung ngoại lệ `.gitignore` có chủ đích.

## Kiểm tra sau khi chuyển thư mục

- Bộ kiểm thử tự động: 60/60 đạt, không gọi API.
- Nạp model từ `models/` và phân tích URL thật bằng ML: đạt.
- Đánh giá PhishVN offline: tái lập fingerprint `d3d1ee19f42b` và số đo trên 8.941 URL test.
- Dựng Word sang thư mục build mới: đạt.
- Đối chiếu 57 tệp minh chứng lịch sử: giữ nguyên SHA-256.
- Các liên kết Markdown trong tài liệu hiện hành được kiểm tra tới đích tồn tại; tài liệu snapshot giữ đường dẫn lịch sử theo bảng chuyển đổi.
