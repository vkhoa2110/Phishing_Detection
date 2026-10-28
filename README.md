# PhishLens — Phishing Detection & Analysis

Ứng dụng web tiếng Việt kiểm tra URL, email và tin nhắn, kết hợp XGBoost với DeepSeek-V4-Flash qua API FPT. Chạy cục bộ bằng FastAPI và HTML/CSS/JavaScript. RAG v1 dùng embedding E5-small chạy cục bộ, truy xuất kho 25 tóm lược và hiển thị URL nguồn tham khảo.

Từ v2, **hành vi trong tin nhắn và rủi ro URL được hiển thị riêng**. Mặc định LLM không nhận điểm ML; model URL vẫn chạy tại máy và giữ cảnh báo riêng. [Thiết kế, quy trình đánh giá v2](docs/evaluation/CONTEXT_V2.md). Đã chuẩn bị [200 SMS từ nguồn công khai chờ gán nhãn độc lập](data/annotation/vn_sms_v2/README.md); chưa dùng nhãn spam nguồn làm nhãn phishing.

Đã dựng riêng [kho RAG v2 gồm 37 nguồn và đánh giá retrieval](docs/evaluation/RAG_RETRIEVAL_V2.md), có [thử nghiệm tiếng Việt không dấu](docs/evaluation/RETRIEVAL_ROBUSTNESS.md). [Nhãn AI sơ bộ cho 200 SMS](docs/evaluation/AI_PRELABELS.md) được lưu riêng để rà soát, không thay nhãn người đánh giá hoặc dùng làm gold tính F1.

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

Để dùng RAG, làm theo [thiết lập E5-small và chỉ mục](docs/guides/RAG.md). Trên máy hiện tại đã chuẩn bị model, chỉ mục và ngưỡng; giao diện có tùy chọn **Tham khảo tài liệu có nguồn (RAG)** cho email/tin nhắn. Cài ứng dụng cơ bản không tự tải model embedding.

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
├── docs/                   # Hướng dẫn, thiết kế và đánh giá
├── scripts/                # Công cụ evaluation / rag
├── tests/                  # Kiểm thử tự động
├── requirements/           # Phụ thuộc theo mục đích sử dụng
├── requirements.txt        # Điểm cài đặt cho ứng dụng
├── Makefile                # Lệnh thao tác thường dùng
└── run.py                  # Điểm khởi động ứng dụng
```

Xem [quy ước thư mục và bảng đường dẫn cũ–mới](docs/PROJECT_STRUCTURE.md). Repository nằm ngay tại thư mục đang mở; không còn tầng thư mục `phishing_baseline/` ở máy cục bộ.

## Tài liệu

- [Thiết lập và sử dụng RAG](docs/guides/RAG.md).
- [Mục lục tài liệu](docs/README.md) · [Kiến trúc baseline](docs/architecture/BASELINE.md).
- [Kết quả URL trên PhishVN](docs/evaluation/PHISHVN.md) · [Chẩn đoán thông điệp mô phỏng](docs/evaluation/SYNTHETIC.md).
- [So sánh LLM / URL / RAG và BM25 / E5 / Hybrid](docs/evaluation/RAG_ABLATION.md).
- [Hai phạm vi đánh giá và bộ SMS chờ review](docs/evaluation/CONTEXT_V2.md).
- [Nhãn AI sơ bộ và cách rà soát](docs/evaluation/AI_PRELABELS.md) · [Thử nghiệm retrieval không dấu](docs/evaluation/RETRIEVAL_ROBUSTNESS.md).
- [Phương pháp và lệnh đánh giá](docs/evaluation/METHODS.md) · [Kết quả theo lần chạy](artifacts/README.md).
- [Kho 25 nguồn RAG](data/knowledge/README.md) · [Danh mục nguồn kèm URL](data/knowledge/corpus_v1/sources.csv).

Báo cáo Word/PDF và các tệp phục vụ biên soạn được giữ cục bộ trong `docs/reports/`, không theo dõi trên Git. Đường dẫn lịch sử của dữ liệu thực nghiệm được đối chiếu trong [bảng chuyển đổi](docs/PROJECT_STRUCTURE.md#đối-chiếu-đường-dẫn-cũmới).

## Phát triển và kiểm thử

```bash
.venv/bin/python -m pip install -r requirements/dev.txt
.venv/bin/python -m pytest -q
```

Các test chạy offline, không gọi FPT. Có thể dùng `make run`, `make test` hoặc `make help` trên môi trường có Make. [Các profile phụ thuộc](requirements/README.md) và [các công cụ](scripts/README.md) mô tả lệnh đánh giá và thu thập.

Kết quả hiện có gồm đánh giá model trên 8.941 URL test PhishVN, so sánh LLM trên cùng 100 URL, bộ chẩn đoán 60 thông điệp v1 và lượt so sánh bốn cấu hình LLM/URL/RAG trên 100 thông điệp mô phỏng (60 mẫu cũ có URL, 40 mẫu mới không URL). Đã đối chiếu BM25, E5 và Hybrid trên 40 câu dev, 12 câu test truy xuất. Các bộ này có nhiệm vụ khác nhau; giới hạn được trình bày trong từng tài liệu. Nhãn tin nhắn và relevance do trợ lý soạn, chưa có tập tin nhắn thực được gán nhãn độc lập.
