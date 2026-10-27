# PhishLens — Phishing Detection & Analysis

Ứng dụng web tiếng Việt kiểm tra URL, email và tin nhắn, kết hợp XGBoost với DeepSeek-V4-Flash qua API FPT. Chạy cục bộ bằng FastAPI và HTML/CSS/JavaScript. RAG hiện đã có kho tài liệu; truy xuất trong ứng dụng chưa triển khai.

## Chạy nhanh

Dùng Python 3.11 hoặc 3.12, mở terminal tại thư mục có `run.py`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python run.py
```

Mở **http://127.0.0.1:8000**. Trên Windows, thay `.venv/bin/python` bằng `.venv\Scripts\python.exe` và sao chép `.env.example` bằng trình quản lý tệp hoặc `Copy-Item`.

Đặt gói mô hình tại **`models/inference_XGBoost_d6_s42/`**, gồm `model.ubj`, `config.json`, `predict_url.py`, `url_features.py` và `url_preprocessing.py`. Xem [hướng dẫn model](models/README.md). Trọng số được cài riêng; thiếu model sẽ được báo rõ.

Khi bật LLM, cấu hình `FPT_API_KEY` trong `.env` hoặc nhập ở giao diện. Ứng dụng có bản xem trước và bước xác nhận gửi API. Hướng dẫn đầy đủ ở [Cài đặt và sử dụng](docs/guides/USAGE.md).

## Cấu trúc dự án

```text
.
├── app/                    # FastAPI, xử lý ML/LLM và giao diện
├── data/
│   ├── evaluation/         # Mẫu thông điệp có nhãn
│   ├── knowledge/          # Danh mục và snapshot tài liệu RAG
│   └── raw/                # Dữ liệu gốc cài cục bộ, không đưa lên Git
├── models/                 # Gói mô hình suy luận cài cục bộ
├── notebooks/              # Notebook huấn luyện và xuất model
├── artifacts/evaluations/  # Kết quả thực nghiệm đã chốt
├── docs/                   # Hướng dẫn, thiết kế, đánh giá và báo cáo
├── scripts/                # Công cụ evaluation / rag / reporting
├── tests/                  # Kiểm thử tự động
├── requirements/           # Phụ thuộc theo mục đích sử dụng
├── requirements.txt        # Điểm cài đặt cho ứng dụng
├── Makefile                # Lệnh thao tác thường dùng
└── run.py                  # Điểm khởi động ứng dụng
```

Xem [quy ước thư mục và bảng đường dẫn cũ–mới](docs/PROJECT_STRUCTURE.md). Repository nằm ngay tại thư mục đang mở; không còn tầng thư mục `phishing_baseline/` ở máy cục bộ.

## Báo cáo và tài liệu

- [Báo cáo Word](docs/reports/2026-10-26/Bao_cao_Phishing_ML_LLM_RAG_Le_Van_Khoa.docx) · [Báo cáo PDF](docs/reports/2026-10-26/Bao_cao_Phishing_ML_LLM_RAG_Le_Van_Khoa.pdf).
- [Mục lục tài liệu](docs/README.md) · [Kiến trúc baseline](docs/architecture/BASELINE.md).
- [Kết quả URL trên PhishVN](docs/evaluation/PHISHVN.md) · [Chẩn đoán thông điệp mô phỏng](docs/evaluation/SYNTHETIC.md).
- [Phương pháp và lệnh đánh giá](docs/evaluation/METHODS.md) · [Kết quả theo lần chạy](artifacts/README.md).
- [Kho 25 nguồn RAG](data/knowledge/README.md) · [Danh mục nguồn kèm URL](data/knowledge/corpus_v1/sources.csv).

Các báo cáo ngày 26/10/2026 giữ nguyên nội dung và số liệu. Đường dẫn bên trong snapshot theo cấu trúc tại thời điểm tạo; đối chiếu vị trí hiện tại trong [bảng chuyển đổi](docs/PROJECT_STRUCTURE.md#đối-chiếu-đường-dẫn-cũmới).

## Phát triển và kiểm thử

```bash
.venv/bin/python -m pip install -r requirements/dev.txt
.venv/bin/python -m pytest -q
```

Các test chạy offline, không gọi FPT. Có thể dùng `make run`, `make test` hoặc `make help` trên môi trường có Make. [Các profile phụ thuộc](requirements/README.md) và [các công cụ](scripts/README.md) mô tả lệnh đánh giá, thu thập và dựng báo cáo.

Kết quả hiện có gồm đánh giá model trên 8.941 URL test PhishVN, phép so sánh LLM trên cùng 100 URL và bộ chẩn đoán 60 thông điệp mô phỏng. Chúng có nhiệm vụ khác nhau; giới hạn diễn giải được trình bày trong từng báo cáo. Phần RAG chưa có kết quả phân loại để so sánh.
