# PhishLens

Ứng dụng web tiếng Việt giúp kiểm tra dấu hiệu lừa đảo trong tin nhắn, email và đường dẫn. FastAPI phục vụ giao diện HTML/CSS/JavaScript; XGBoost kiểm tra URL cục bộ, LLM giải thích nội dung và RAG cung cấp tài liệu tham khảo khi được bật.

Ứng dụng hiện dùng **chính sách v4**: đánh giá riêng hành vi trong nội dung và rủi ro URL, giữ mức “chưa đủ thông tin” khi thiếu căn cứ. [Thiết kế và giới hạn chất lượng](docs/architecture/QUALITY_V4.md).

## Chạy ứng dụng

Dùng Python 3.11 hoặc 3.12 tại thư mục có `run.py`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python run.py
```

Mở **http://127.0.0.1:8000**. Trên Windows, dùng `.venv\Scripts\python.exe` và `Copy-Item .env.example .env`.

- Đặt gói XGBoost trong `models/inference_XGBoost_d6_s42/` theo [hướng dẫn model](models/README.md).
- Cấu hình `FPT_API_KEY` trong `.env` hoặc nhập trong thiết lập giao diện để dùng AI. Bạn được xem, sửa và xác nhận nội dung trước khi gửi tới dịch vụ bên ngoài.
- Muốn dùng RAG, chuẩn bị embedding E5-small và chỉ mục theo [hướng dẫn RAG](docs/guides/RAG.md), rồi bật **Đối chiếu với tài liệu có nguồn**. RAG mặc định tắt.

[Cài đặt, API và xử lý lỗi](docs/guides/USAGE.md). Khi cần đối chiếu ứng dụng baseline v3: `PHISHLENS_PROFILE=legacy .venv/bin/python run.py`.

## Các thư mục chính

| Thư mục | Dùng để làm gì? |
|---|---|
| `app/` | API, xử lý nội dung/URL và giao diện trong `static/` |
| `evaluation/` | Các phép đánh giá và công cụ chuẩn bị nhãn |
| `data/` | Bộ đánh giá, phiếu gán nhãn và kho tài liệu RAG |
| `models/` | Trọng số và gói suy luận cài cục bộ |
| `artifacts/` | Kết quả thực nghiệm; ảnh kiểm tra giao diện ở `ui/` |
| `docs/` | Hướng dẫn, thiết kế và phương pháp đánh giá |
| `scripts/` | Công cụ chạy từ dòng lệnh, gồm dọn cache |
| `tests/`, `notebooks/` | Kiểm thử tự động và notebook huấn luyện |

[Quy ước thư mục](docs/PROJECT_STRUCTURE.md) · [Các lệnh công cụ](scripts/README.md) · [Mục lục kết quả](artifacts/README.md).

## Phát triển

```bash
.venv/bin/python -m pip install -r requirements/dev.txt
make test
make clean
```

`make clean` chỉ xóa cache phát sinh. Không xóa dữ liệu, model, kết quả thực nghiệm hoặc báo cáo. Có thể xem trước bằng `.venv/bin/python -B scripts/maintenance/clean.py`.

Bộ test chạy offline. Các phép đánh giá LLM chỉ gọi API khi chạy với `--live`; xem [phương pháp và lệnh đánh giá](docs/evaluation/METHODS.md). Nhãn AI sơ bộ và các bộ mô phỏng chưa thay thế tập có nhãn người độc lập.

## Tài liệu nên đọc

- [Sử dụng ứng dụng](docs/guides/USAGE.md) và [thiết lập RAG](docs/guides/RAG.md).
- [Chất lượng v4](docs/architecture/QUALITY_V4.md): thay đổi hiện hành, kiểm chứng và đánh đổi Recall/coverage.
- [So sánh LLM / URL / RAG](docs/evaluation/COMPONENTS_DEV_V1.md) và [bộ đánh giá cố định](docs/evaluation/OBJECTIVE_V1.md).
- [Toàn bộ tài liệu, gồm các phiên bản trước](docs/README.md).

`.env`, môi trường Python, trọng số, dữ liệu gốc và kết quả chạy mới không được đưa lên Git. Báo cáo học thuật cùng tài sản biên soạn ở `docs/reports/` và `scripts/reporting/` chỉ giữ cục bộ.
