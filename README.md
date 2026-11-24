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

`make run-focused` chạy bản verdict lõi thử nghiệm. Các profile qua `run.py` dùng kết nối AI do máy chủ quản lý, một ngân sách chờ tối đa 45 giây cho phân loại và giải thích; người dùng xem và xác nhận nội dung trước khi gửi. [Yêu cầu và minh chứng FR/NFR](docs/requirements.md).

Focused hiện dùng `message-core-1.1`: đối chiếu quote chỉ khác định dạng về đúng đoạn gốc và báo rõ nguyên nhân đầu ra không hợp lệ. Preview đã sửa trường hợp marker số trong URL bị thay đổi ở lượt che tiếp theo. [Hướng dẫn demo](docs/guides/USAGE.md#demo-bản-focused-đã-sửa-lỗi-ngày-2411) và [minh chứng 24/11](artifacts/evaluations/submission_hardening_20261124/README.md) tách riêng kiểm lỗi của bản mới với số liệu core 1.0 lịch sử.

Bản focused qua launcher kiểm tra thêm dấu hiệu tối thiểu giữa mã lý do và từng trích dẫn. Khi thiếu dấu hiệu, ứng dụng diễn giải thận trọng và yêu cầu kiểm tra lại; giữ nguyên mức cảnh báo của AI và kết quả URL. Đây chưa phải kiểm chứng ngữ nghĩa hoặc cải thiện F1. [Phạm vi và kết quả](docs/results.md#kiem-tra-ly-do).

`make run-verifier-shadow` thử focused với một lượt LLM kiểm tra lại các kết luận HIGH/WARNING. Chế độ này chỉ ghi đề xuất vào trường `verification` của API, giữ nguyên kết luận hiển thị, cảnh báo URL và RAG. Lượt bổ sung dùng nội dung đã duyệt và chung ngân sách chờ 45 giây; có thể tăng token/chi phí khi sử dụng thật. Stable và focused thông thường không tự bật verifier. [Cấu hình và giới hạn](docs/architecture.md#verifier-shadow).

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

Luồng [chốt nhãn người và đánh giá qua API ứng dụng](docs/evaluation.md#chốt-nhãn-người-và-đánh-giá-đúng-ứng-dụng-ngày-2111) kiểm cùng bốn cấu hình trên dev, tách UNKNOWN/lỗi và giữ từng attempt. Nhãn chưa hoàn tất sẽ chặn đánh giá theo reference người. Lượt [full-dev ngày 22/11](artifacts/evaluations/expanded_dev_full_20261122/README.md) đã hoàn tất 1.228 ô trên 307 ca dev có nhãn AI; 93 holdout và nhãn người còn chờ. [Kết quả mới nhất và giới hạn](docs/results.md) phân biệt kiểm phần mềm, chẩn đoán API và chất lượng phát hiện độc lập.
