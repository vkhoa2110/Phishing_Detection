# Sử dụng PhishLens

## Cài đặt

Dùng Python 3.11/3.12, mở terminal tại thư mục có `run.py`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python run.py
```

Mở **http://127.0.0.1:8000**. Windows dùng `.venv\Scripts\python.exe` và `Copy-Item .env.example .env`. Không cần npm, GPU hoặc cài dịch vụ cơ sở dữ liệu riêng; tài khoản dùng SQLite cục bộ.

Đặt XGBoost export có `model.ubj`, `config.json`, `predict_url.py`, `url_features.py`, `url_preprocessing.py` trong `models/inference_XGBoost_d6_s42/`. Có thể đổi `MODEL_DIR` trong `.env`. Chỉ nạp gói đã kiểm tra vì mã Python trong gói được import. [Các gói model](../../models/README.md).

Người triển khai cấu hình `FPT_ENDPOINT`, `FPT_MODEL`, `FPT_API_KEY` trong môi trường máy chủ. Khi chạy bằng `run.py`, người dùng không phải nhập key và không được thay endpoint/model từ trình duyệt. Thiết lập chỉ hiển thị nơi nhận dữ liệu. Endpoint mặc định nằm trong `.env.example`; đổi host cần cập nhật `LLM_ALLOWED_HOSTS` và khởi động lại. Không ghi key vào Git.

`PORT` mặc định 8000, chỉ bind máy cục bộ. Runtime giới hạn `LLM_TIMEOUT_SECONDS` tối đa 45 giây dùng chung từ lời gọi AI đầu tiên đến giải thích tùy chọn; không cấp lại 45 giây riêng cho mỗi bước. Thời gian nạp model/truy xuất cục bộ không được bảo đảm bởi giới hạn này. `LLM_MAX_TOKENS` bị chặn tối đa 8.192; focused mặc định tối đa 2.048. Không tự retry khi lỗi; key máy chủ không trả về giao diện.

## Kiểm tra nội dung

Sau khi đã cài phụ thuộc và model, có thể dùng `make demo` hoặc mở `start_phishlens.sh` trên Linux / `start_phishlens.bat` trên Windows. Launcher tự mở trang `/check` để dùng ngay, mặc định **8001**, không đổi mặc định 8000 của `run.py`. Giữ terminal mở trong khi sử dụng; Ctrl+C để dừng tiến trình do launcher khởi động. Nếu ứng dụng đã chạy đúng phiên bản trên cổng đó, launcher mở lại trang và không tạo tiến trình thứ hai. Tiến trình đang chạy giữ profile hiện tại; `--profile` áp dụng khi khởi động mới.

`make shortcut` cài shortcut PhishLens vào menu ứng dụng Linux của tài khoản hiện tại; chưa là bộ cài độc lập và vẫn phụ thuộc vị trí repository. Kiểm môi trường mà không chạy server/AI: `.venv/bin/python launch.py --check --profile focused`. Đổi cổng/profile: `.venv/bin/python launch.py --port 8002 --profile focused`. Launcher kiểm hiện diện asset, không thay thế kiểm hash của model khi ứng dụng nạp. Windows cần tự cài Python, phụ thuộc và asset như phần Cài đặt; kiểm trình duyệt của lượt này thực hiện trên Linux/Chromium.

1. Chọn tin nhắn/email hoặc URL. Nội dung nhận tối đa 8.000 ký tự và **50 URL khác nhau**; URL trùng chỉ tính một lần. Tab URL nhận một đường dẫn. Vượt giới hạn sẽ được yêu cầu tách nội dung, không tự bỏ bớt URL.
2. Bật AI nếu muốn phân tích hành vi; bật đối chiếu tài liệu nếu đã [chuẩn bị RAG](RAG.md). Metadata URL cho AI là tùy chọn, mặc định tắt.
3. Trước khi gọi AI, kiểm tra/sửa bản xem trước đã che thông tin và xác nhận đồng ý gửi tới máy chủ hiển thị. Che tự động có thể chưa hết dữ liệu cá nhân.
4. Đọc khung **Phân tích nội dung bằng AI** ngay dưới kết luận: nhận định, lý do, ngữ cảnh và các đoạn trích AI dùng làm căn cứ. Câu hỏi bổ sung xuất hiện tại đây khi thiếu ngữ cảnh. Cảnh báo URL được giữ riêng. LOW chỉ nói chưa thấy dấu hiệu rõ theo phép kiểm tra, không bảo đảm an toàn. UNKNOWN là chưa đủ căn cứ.
5. **Tải kết quả (.json)** nằm ngay dưới kết quả; **In / PDF** ở đầu khung mở hộp thoại in của trình duyệt. Chọn Lưu dưới dạng PDF để giữ bản báo cáo. Model/token/cấu hình nằm trong **Thông tin kỹ thuật**; URL nghi vấn chỉ hiển thị như văn bản.

Bên cạnh ô nhập có hai ví dụ tự soạn để thử nhanh; bấm ví dụ chỉ điền nội dung, chưa phân tích. **Cài extension** mở hướng dẫn ngay trên trang. Tab URL mặc định tắt AI; tab tin nhắn/email chọn sẵn AI và nhớ lựa chọn riêng trong phiên.

Tắt AI để chỉ suy luận URL tại máy. Nội dung không có URL và không dùng AI sẽ không có đủ thông tin để kết luận. Dịch vụ AI lỗi vẫn giữ kết quả URL nếu có; không tạo nhận định giả.

Khung AI hiển thị trực tiếp, không cần mở “Chi tiết phân tích và tải kết quả”. Khi không có trích dẫn, ứng dụng nói rõ điều đó; không tự viết thêm căn cứ. Focused diễn giải từ mã kết luận và trích dẫn, không phải một bài phân tích tự do dài. Trong tab URL, khung mang tên “Nhận xét đường dẫn bằng AI” để giữ đúng phạm vi. Nếu vẫn thấy giao diện cũ sau cập nhật, tải lại bằng Ctrl+F5 rồi thực hiện lượt kiểm tra mới.

## Tài khoản và lịch sử cục bộ

Mở ứng dụng dùng ngay ở **chế độ khách**, không cần tạo tài khoản. Có thể kiểm URL, xem trước/đồng ý gửi AI và dùng extension/OCR. Khách không lưu lịch sử, không chuyển kết quả cũ vào tài khoản sau khi đăng nhập. Nút Đăng nhập chỉ cần khi muốn lịch sử/dashboard/hồ sơ.


`run.py` mặc định mở lớp ứng dụng có tài khoản. Tạo tài khoản bằng tên hiển thị, email và mật khẩu 12–128 ký tự. Email là tên đăng nhập, chưa được xác minh qua email. Tài khoản đầu tiên trên database mới là quản trị viên; các tài khoản sau là thành viên. Không có mật khẩu mặc định. Đăng xuất kết thúc phiên hiện tại; đổi mật khẩu kết thúc toàn bộ phiên cũ và cấp phiên mới cho trình duyệt đang dùng.

- **Tổng quan:** thống kê lịch sử riêng, các lượt cần chú ý, kết quả đã đánh dấu và số yêu cầu AI trong 24 giờ. Số cảnh báo là nhận định hệ thống, không phải độ chính xác hoặc số vụ lừa đảo được xác nhận.
- **Kiểm tra:** giữ luồng preview/xác nhận trước khi gọi AI. Có thể tắt lưu lịch sử. Mặc định chỉ lưu thời điểm/loại/mức nhận định; chỉ khi chọn “Kèm nội dung đã che và kết quả chi tiết” mới lưu thêm bản đã che và kết quả. Quy tắc che vẫn có thể bỏ sót dữ liệu riêng tư; kiểm tra trước khi chọn lưu/gửi.
- **Lịch sử:** tìm theo tên/ghi chú có hoặc không dấu, lọc mức/đánh dấu, xem chi tiết, đặt tên, viết ghi chú, tải bản đã lưu dạng JSON và xóa. Lượt chỉ lưu thông tin tổng quát không thể khôi phục nội dung đã bỏ qua.
- **Tài khoản:** sửa tên hiển thị, đổi mật khẩu; tải extension và thu hồi các kết nối tài khoản cũ. Email đăng nhập giữ nguyên trong bản cục bộ này.
- **Phản hồi:** xem/xóa góp ý đã gửi và đọc trả lời của quản trị viên. Gửi từ khung kết quả hoặc chi tiết lịch sử. Nhận định tổng quát và mô tả góp ý được chia sẻ mặc định; chỉ chia sẻ nội dung/snapshot đã lưu khi chọn rõ. Góp ý không phải nhãn chuẩn tự động.
- **Quản trị:** xem danh sách tài khoản, đổi quyền, khóa/mở khóa. Không truy cập lịch sử riêng của người khác. Không tự khóa hoặc hạ quyền tài khoản quản trị đang dùng. Người bị khóa hết hiệu lực các phiên cũ.

Database mặc định `data/application/phishlens.sqlite3`; có thể đặt `PHISHLENS_DATABASE` trước khi khởi động. Dữ liệu này nằm ngoài Git. Mỗi tài khoản có tối đa `PHISHLENS_DAILY_AI_LIMIT=100` yêu cầu phân tích AI trong 24 giờ, gồm các yêu cầu đã nhận nhưng kết thúc lỗi; một yêu cầu có thể gồm nhiều lượt provider nếu bật giải thích/verifier. Tối đa một lượt phân tích đang chạy trên mỗi tài khoản và bốn trên một tiến trình. Kiểm tra chỉ URL cục bộ không dùng hạn mức AI.

Sao lưu nhất quán cả dữ liệu đang nằm trong SQLite WAL vào file mới:

```bash
.venv/bin/python scripts/maintenance/workspace.py backup \
  --out artifacts/maintenance/phishlens_backup_20261124.sqlite3
```

Không ghi đè file backup cũ. Backup chứa dữ liệu tài khoản và lịch sử; giữ riêng như database. Nếu quên mật khẩu, người vận hành có quyền vào máy có thể đặt lại bằng lệnh sau; mật khẩu được nhập ẩn, không truyền trên command line:

```bash
.venv/bin/python scripts/maintenance/workspace.py reset-password --email ban@example.com
```

Chưa tích hợp SMTP, xác minh email, đăng nhập Google hoặc MFA. Bản này phục vụ máy cá nhân/demo tại localhost. Chế độ không tài khoản chỉ dành kiểm nghiên cứu: `PHISHLENS_ACCOUNTS=0 PORT=8003 make run-focused`; API của các script nghiên cứu vẫn giữ hợp đồng cũ. Không coi việc hoàn tất đăng nhập/lịch sử là đã đánh giá chất lượng model hoặc sẵn sàng mở dịch vụ công cộng.

## Extension và phản hồi

Bản extension **0.7** có bảng **Kiểm tra / Trợ lý / Kết nối**, sáng/tối, nút khoanh vùng lớn và hai lối tắt kiểm trang/dán tin. **Khoanh vùng trên trang**: bấm nút hoặc Alt+Shift+S/menu chuột phải → kéo chọn → thả để tự OCR → sửa chữ/đồng ý phân tích. Esc hủy. **Tải ảnh từ máy** vẫn riêng trong thẻ Hình ảnh: chọn/drop/Ctrl+V → cắt nếu cần → Đọc chữ. Chỉ chữ đã duyệt tới LLM; ảnh chỉ OCR tại máy. [OCR](OCR.md).

**Email và chụp nhanh (0.7):** mở email trên Gmail/Outlook → mở PhishLens → **Đọc email đang mở**. Bật **Trợ lý Gmail / Outlook** nếu muốn đổi thư là chuẩn bị bản duyệt mới; consent luôn hủy khi thay thư và AI chờ xác nhận. Email dạng ảnh/tệp đính kèm chưa được đọc qua DOM. Khoanh vùng từ menu/nút nổi hiện ngay trước bản đọc ảnh; nút **Chụp toàn vùng hiển thị** lấy phần website đang nhìn thấy. Phần Dấu hiệu có thêm giải thích AI sau phân loại ở focused/shadow; có thể tắt trong tùy chọn, không đổi verdict và dùng chung hạn chờ 45 giây.

Trong **Trợ lý**, bật riêng **Hiện nút PhishLens trên trang** và/hoặc **Tự kiểm URL khi mở trang**; Chrome hỏi quyền trang khi bật. Nút nổi kéo được, menu có tạm nghỉ một giờ và ẩn website. Tự kiểm URL hoạt động khi đóng bảng, chỉ gửi chuỗi URL tới ứng dụng localhost; không đọc trang/gọi AI/lưu lịch sử nền. HIGH/WARNING có badge `!`, UNKNOWN có `?`; nếu có nút nổi thì HIGH có thông báo nhẹ. Mất kết nối là chưa kiểm được, không phải an toàn. Cả hai tùy chọn mặc định tắt; backend phải chạy. Tự kiểm không chặn trang đích.

Sau cập nhật bấm **Reload** trong trang extensions, đóng bảng cũ và tải lại tab web. Alt+Shift+P mở bảng; Ctrl+Enter thao tác chính, phím có thể bị OS chiếm. Cần Chrome 116+, chưa kiểm Edge/Windows/macOS.

Thẻ tin nhắn/ảnh chọn sẵn AI, nhưng chưa gửi dữ liệu cho đến khi bạn duyệt và đồng ý. Kết quả có mức riêng cho URL/nội dung, căn cứ và hướng xử lý; chi tiết URL/nguồn thu gọn. Có tải JSON và sao chép tóm tắt không kèm nội dung gốc/URL. Đóng/reload bảng mất bản nháp, ảnh và kết quả chưa lưu; lịch sử đã chọn lưu vẫn ở tài khoản.

Xem [hướng dẫn cài extension](../../extensions/chromium/README.md). Tải ZIP ngay ở trang kiểm tra khách hoặc trong Tài khoản, giải nén và **Load unpacked** thư mục có `manifest.json`. Mở extension để tự kết nối địa chỉ đã lưu/cổng 8001 hoặc 8000; không lấy/nhập mã hoặc đăng nhập. Cổng riêng nhập trong Kết nối. Khách có URL/AI/OCR, không lưu lịch sử; đăng nhập trên web cho các lượt tiếp theo muốn lưu. Tạm ngừng kết nối được nhớ qua reload. Backend cần chạy; khởi động lại để nạp API khách sau cập nhật. Kết nối tài khoản cũ vẫn có thể thu hồi trong Tài khoản.

Extension không yêu cầu mật khẩu/API key, không tự đọc toàn trang. Chuột phải link để lấy URL đích mà không mở link; bôi đen rồi chuột phải để lấy văn bản; bấm biểu tượng để kiểm URL tab HTTP/HTTPS. URL mặc định AI tắt; thẻ Tin nhắn/ảnh chọn sẵn AI. Trước khi gửi, phải duyệt bản đã che và đồng ý trước khi gửi. Nội dung sau sửa được che lại, thay đổi bản duyệt yêu cầu xác nhận lại. Điểm URL và nguồn RAG là các lựa chọn riêng. Mở lịch sử đầy đủ để xem phần đã chọn lưu và gửi phản hồi.

Quản trị viên xem phản hồi ở cuối trang **Quản trị**, có bộ lọc trạng thái, phân trang và ghi chú trả lời. Quản trị viên chỉ xem nội dung được người gửi cho phép chia sẻ trong phản hồi; không có quyền đọc lịch sử riêng. Người gửi có thể xóa phản hồi; xóa kết quả hoặc toàn bộ lịch sử cũng xóa phản hồi gắn với kết quả cùng snapshot chia sẻ. Quy tắc che có thể bỏ sót PII; tự kiểm tra trước khi đồng ý chia sẻ.

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

Ví dụ chỉ chạy URL cục bộ, không gọi LLM, dành cho runtime nghiên cứu không tài khoản mở riêng bằng `PHISHLENS_ACCOUNTS=0 PORT=8003 make run-focused`. Bản phần mềm có tài khoản nên dùng giao diện để giữ session và CSRF token:

```bash
curl -s http://127.0.0.1:8003/api/analyze \
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

Ứng dụng hiện có tài khoản, lịch sử và hạn mức lượt AI theo tài khoản, phục vụ thử nghiệm cục bộ; chưa có tính tiền theo usage hoặc cấu hình triển khai công khai. [Kết quả và hạn chế](../results.md).
