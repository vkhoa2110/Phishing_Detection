# Sử dụng PhishLens

## Cài đặt

Dùng Python 3.11/3.12, mở terminal tại thư mục có `run.py`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python run.py
```

Mở **http://127.0.0.1:8000**. Windows dùng `.venv\Scripts\python.exe` và `Copy-Item .env.example .env`. Không cần npm, GPU hoặc cơ sở dữ liệu.

Đặt XGBoost export có `model.ubj`, `config.json`, `predict_url.py`, `url_features.py`, `url_preprocessing.py` trong `models/inference_XGBoost_d6_s42/`. Có thể đổi `MODEL_DIR` trong `.env`. Chỉ nạp gói đã kiểm tra vì mã Python trong gói được import. [Các gói model](../../models/README.md).

LLM dùng `FPT_ENDPOINT`, `FPT_MODEL`, `FPT_API_KEY`; có thể nhập kết nối trong thiết lập giao diện. Endpoint mặc định được khai báo trong `.env.example`; dùng model mà tài khoản thực sự có quyền truy cập. Đổi host cần cập nhật `LLM_ALLOWED_HOSTS` và khởi động lại. Không ghi key vào Git.

`PORT` mặc định 8000, chỉ bind máy cục bộ. `LLM_TIMEOUT_SECONDS` và `LLM_MAX_TOKENS` kiểm soát ngân sách, app chặn cap vượt 8.192; không tự retry khi lỗi. `FPT_API_KEY` được đọc phía server, không hiển thị ngược lên giao diện.

## Kiểm tra nội dung

1. Chọn tin nhắn/email hoặc URL, dán tối đa 8.000 ký tự và năm URL khác nhau.
2. Bật AI nếu muốn phân tích hành vi; bật đối chiếu tài liệu nếu đã [chuẩn bị RAG](RAG.md). Metadata URL cho AI là tùy chọn, mặc định tắt.
3. Trước khi gọi AI, kiểm tra/sửa bản xem trước đã che thông tin và xác nhận đồng ý gửi tới máy chủ hiển thị. Che tự động có thể chưa hết dữ liệu cá nhân.
4. Đọc nhận định nội dung, cảnh báo URL, dấu hiệu, bước xử lý và giới hạn. LOW chỉ nói chưa thấy dấu hiệu rõ theo phép kiểm tra, không bảo đảm an toàn. UNKNOWN là chưa đủ căn cứ.
5. Chi tiết có score và thông tin thực thi; có thể tải kết quả JSON. URL nghi vấn được hiển thị như văn bản.

Tắt AI để chỉ suy luận URL tại máy. Nội dung không có URL và không dùng AI sẽ không có đủ thông tin để kết luận. Dịch vụ AI lỗi vẫn giữ kết quả URL nếu có; không tạo nhận định giả.

## Profile thử nghiệm

```bash
# v4 ổn định
.venv/bin/python run.py

# v6.1: URL ký tự, cấu trúc tương tác, RAG sau phân loại
PHISHLENS_PROFILE=candidate .venv/bin/python run.py

# v6.1 với giải thích bằng lựa chọn đoạn
PHISHLENS_PROFILE=candidate PHISHLENS_CANDIDATE_RAG_MODE=span_selection .venv/bin/python run.py
```

Có thể dùng `make run-candidate`. Candidate cần `models/url_character/`, chưa được thay bản mặc định. Các profile đối chứng `candidate-v5` và `legacy` xem [kiến trúc](../architecture.md). Khi chạy uvicorn trực tiếp, dùng `app.main:app` cho stable và `app.api.interaction:app` cho v6.1.

## API cục bộ

`GET /api/status` xem trạng thái; `POST /api/model/reload` nạp lại model; `POST /api/preview` tạo bản che; `POST /api/analyze` phân tích. Schema đầy đủ ở **http://127.0.0.1:8000/docs**.

Ví dụ chỉ chạy URL cục bộ, không gọi LLM:

```bash
curl -s http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{"mode":"url","text":"https://example.org/","use_llm":false}'
```

`example.org` là ví dụ đầu vào, không phải khẳng định model sẽ kết luận LOW. API dùng AI cần đúng `llm_text` đã duyệt và `consent=true`; nên thử qua giao diện để giữ luồng xác nhận.

## Xử lý lỗi

| Hiện tượng | Kiểm tra |
|---|---|
| Model unavailable | Vị trí export, phụ thuộc và hash; không đổi tên file trong gói |
| Candidate URL unavailable | Gói `models/url_character/` phải tương thích mã/phiên bản thư viện; [chuyển gói sau refactor](../development.md) |
| RAG unavailable | Corpus/index/embedding/calibration cùng phiên bản; [hướng dẫn RAG](RAG.md) |
| 401/403 hoặc 404 | Quyền key, endpoint và model được cấp |
| 429 / output bị cắt | Kiểm hạn mức/budget trên dev, giữ lỗi trong kết quả đánh giá |
| Cổng bận | Đổi `PORT`, khởi động lại và mở đúng URL |
| Mạng bắt buộc proxy | Transport nằm trong `app/api`, mặc định `trust_env=False`; cấu hình phù hợp, không tắt HTTPS |

Ứng dụng hiện phục vụ thử nghiệm cục bộ; chưa có tài khoản, quản lý chi phí nhiều người hoặc cấu hình triển khai công khai. [Kết quả và hạn chế](../results.md).
