# PhishLens

Ứng dụng tiếng Việt kiểm tra dấu hiệu lừa đảo trong tin nhắn, email và URL. FastAPI phục vụ giao diện web; model URL chạy cục bộ, LLM phân tích nội dung, RAG bổ sung tài liệu tham khảo khi được bật.

## Chạy nhanh

Dùng Python 3.11 hoặc 3.12 tại thư mục gốc:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python run.py
```

Mở **http://127.0.0.1:8000**. Đặt gói XGBoost trong `models/inference_XGBoost_d6_s42/` theo [hướng dẫn model](models/README.md); thêm API key trong `.env` để dùng LLM. [Cách sử dụng và xử lý lỗi](docs/guides/USAGE.md).

Mặc định chạy chính sách v4. Thử candidate v6.1 bằng `make run-candidate` hoặc `PHISHLENS_PROFILE=candidate .venv/bin/python run.py`. Candidate cần gói URL ký tự riêng, chưa đủ bằng chứng để thay bản mặc định. RAG mặc định tắt; xem [cài đặt RAG](docs/guides/RAG.md).

## Cấu trúc

```text
app/
  main.py         # Entry point ổn định
  api/            # HTTP, composition và các profile ứng dụng
  core/           # Cấu hình và che thông tin cá nhân
  domain/         # Schema, kiểm tra bằng chứng, quy tắc kết luận
  services/       # Luồng phân tích; llm/, rag/, url/
  static/         # HTML, CSS, JavaScript
evaluation/
  common/         # Chỉ số đánh giá dùng chung
  data/           # Chuẩn bị dữ liệu, nhãn và protocol
  messages/       # Thực nghiệm thông điệp, hội thoại và ablation
  rag/            # Truy xuất, nguồn dẫn và lời giải thích
  url/            # Baseline, nguồn dữ liệu và calibration URL
scripts/          # Tác vụ dữ liệu, RAG, báo cáo kỹ thuật và bảo trì
tests/            # Kiểm thử chia theo các nhóm chức năng
data/             # Dữ liệu, phiếu review và corpus có phiên bản
models/           # Gói suy luận cài cục bộ
artifacts/        # Đầu ra thực nghiệm cục bộ
docs/             # Tài liệu kỹ thuật hiện hành
notebooks/        # Notebook huấn luyện
requirements/     # Phụ thuộc theo nhu cầu
```

## Phát triển và tài liệu

```bash
.venv/bin/python -m pip install -r requirements/dev.txt
make test
make clean
```

`make test` chạy offline. `make clean` dọn cache, giữ dữ liệu/model/kết quả. Mỗi thực nghiệm mới dùng thư mục đầu ra mới; các snapshot đã khóa hash được giữ nguyên.

- [Kiến trúc và các profile](docs/architecture.md).
- [Quy ước phát triển, đường dẫn mới và tái lập lịch sử](docs/development.md).
- [Phương pháp đánh giá](docs/evaluation.md), [kết quả và hạn chế hiện có](docs/results.md).
- [Danh sách công cụ](scripts/README.md), [dữ liệu](data/README.md), [đầu ra](artifacts/README.md).

Nhãn AI và dữ liệu tự soạn dùng để chẩn đoán, chưa thay thế đánh giá độc lập. `.env`, trọng số, raw response và kết quả mới được Git bỏ qua. Báo cáo học thuật trong `docs/reports/` tiếp tục chỉ giữ cục bộ.
