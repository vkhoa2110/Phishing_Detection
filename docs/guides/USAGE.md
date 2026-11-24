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

Người triển khai cấu hình `FPT_ENDPOINT`, `FPT_MODEL`, `FPT_API_KEY` trong môi trường máy chủ. Khi chạy bằng `run.py`, người dùng không phải nhập key và không được thay endpoint/model từ trình duyệt. Thiết lập chỉ hiển thị nơi nhận dữ liệu. Endpoint mặc định nằm trong `.env.example`; đổi host cần cập nhật `LLM_ALLOWED_HOSTS` và khởi động lại. Không ghi key vào Git.

`PORT` mặc định 8000, chỉ bind máy cục bộ. Runtime giới hạn `LLM_TIMEOUT_SECONDS` tối đa 45 giây dùng chung từ lời gọi AI đầu tiên đến giải thích tùy chọn; không cấp lại 45 giây riêng cho mỗi bước. Thời gian nạp model/truy xuất cục bộ không được bảo đảm bởi giới hạn này. `LLM_MAX_TOKENS` bị chặn tối đa 8.192; focused mặc định tối đa 2.048. Không tự retry khi lỗi; key máy chủ không trả về giao diện.

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

Có thể dùng `make run-candidate`. Candidate cần `models/url_character/`, chưa được thay bản mặc định. Các profile đối chứng `candidate-v5` và `legacy` xem [kiến trúc](../architecture.md). Chạy trực tiếp các ASGI lõi lịch sử chỉ dành cho tái lập nghiên cứu; chúng chưa có lớp runtime mới. Nếu dùng uvicorn để triển khai, dùng factory `app.api.runtime:create_stable_app --factory` hoặc `app.api.runtime:create_focused_app --factory`.

Bản verdict lõi mới chạy riêng ở cổng 8001:

```bash
PHISHLENS_PROFILE=focused PORT=8001 .venv/bin/python run.py
```

Mở **http://127.0.0.1:8001**. Bản này mặc định yêu cầu tắt thinking, cap 2.048 token, dùng E5 và giải thích bằng lựa chọn đoạn sau kết luận. Cần cùng gói model URL ký tự của candidate. Nếu thiếu ngữ cảnh, chọn thông tin bổ sung rồi xem trước và đồng ý gửi lại; không cần nhập mã OTP, mật khẩu hoặc số tài khoản. Đầu ra JSON đầy đủ hơn không tự chứng minh phát hiện chính xác hơn. [Trạng thái đánh giá](../results.md#verdict-loi).

Biến tùy chọn: `PHISHLENS_CORE_THINKING=default|disabled|enabled`, `PHISHLENS_CORE_MAX_TOKENS=2048`, `PHISHLENS_FOCUSED_RETRIEVAL=e5|action_hybrid`. `action_hybrid` chỉ để thử nghiệm, chưa tốt hơn E5 trên lượt dev mới. Có thể dùng `make run-focused` với `PORT` phù hợp.

## Demo bản focused đã sửa lỗi ngày 24/11

Để trình bày bản lõi `message-core-1.1` trên workspace có sẵn asset và cấu hình provider:

```bash
PORT=8001 make run-focused
```

Mở **http://127.0.0.1:8001** và xem `/api/status`: profile phải là `focused`, prompt `message-core-1.1`, cap phân loại 2.048 nếu không đặt override. Stable vẫn là lựa chọn mặc định khi chạy `run.py` không chỉ định profile. Chốt lệnh và cấu hình dùng demo trong báo cáo, vì số liệu full-dev ngày 22/11 thuộc core 1.0.

1. Để hai tùy chọn RAG và cấp score URL cho AI tắt trong lượt đầu. Dán một tình huống yêu cầu gửi OTP, một quy trình người dùng tự khởi tạo và một nội dung thiếu ngữ cảnh để minh họa các nhánh; đọc kết quả thực trả, không dùng ba ví dụ làm điểm chính xác.
2. Kiểm tra bản xem trước, sửa dữ liệu cá nhân còn sót rồi xác nhận gửi. Bản đã che số trong URL phải giữ nguyên khi phân tích; các giá trị mới nhập sau chỉnh sửa vẫn được che lại.
3. Mở JSON để xem `llm.validation.quote_alignment`: nếu AI chỉ đổi hoa/thường hoặc khoảng trắng, quote hiển thị được nối về đoạn nguyên văn và có vị trí bắt đầu/kết thúc. Việc này không xác nhận ý nghĩa của trích dẫn đúng.
4. Bật RAG ở lượt riêng nếu muốn trình bày phần đối chiếu. Focused truy xuất sau verdict; việc hiện nguồn không chứng minh tăng phát hiện. Lượt phân tích mới có thể cho kết quả khác do provider sinh lại.
5. Giải thích rõ ô nội dung và URL: URL HIGH vẫn được giữ khi nội dung LOW/UNKNOWN hoặc AI lỗi. Trạng thái `OUTPUT_INVALID` có thể có mã chẩn đoán an toàn tại `llm.telemetry.output_validation`; đây là lỗi đầu ra, không phải kết luận tin bình thường.

Hai lượt chẩn đoán nhỏ và các giới hạn nằm tại [minh chứng 24/11](../../artifacts/evaluations/submission_hardening_20261124/README.md). Chưa có đánh giá độc lập bằng nhãn người cho bản core 1.1.

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
