# PhishLens

Ứng dụng tiếng Việt kiểm tra dấu hiệu lừa đảo trong tin nhắn, email và URL. FastAPI phục vụ giao diện web; model URL chạy cục bộ, LLM phân tích nội dung, RAG bổ sung tài liệu tham khảo khi được bật.

Extension **0.19.0** bổ sung đọc URL trong mã QR từ ảnh hoặc vùng khoanh, bằng ZXing-C++ tại máy. Bấm URL đã giải mã để kiểm tra cục bộ, không tự mở trang hoặc gửi dữ liệu QR tới AI. Cài nhóm phụ thuộc ảnh và khởi động lại backend; [cách dùng và giới hạn](docs/guides/OCR.md).

## Chạy nhanh

Dùng Python 3.11 hoặc 3.12 tại thư mục gốc:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
.venv/bin/python run.py
```

Mở **http://127.0.0.1:8000**. Đặt gói XGBoost trong `models/inference_XGBoost_d6_s42/` theo [hướng dẫn model](models/README.md); thêm API key trong `.env` để dùng LLM. [Cách sử dụng và xử lý lỗi](docs/guides/USAGE.md).

Ứng dụng qua `run.py` hiện có **đăng ký/đăng nhập, trang tổng quan, lịch sử riêng, đánh dấu, ghi chú, lọc/tìm kiếm, tải JSON, hồ sơ và đổi mật khẩu**. **Không cần đăng nhập để kiểm tra URL, OCR hoặc dùng AI.** Mở ứng dụng vào thẳng trang kiểm tra khách; tài khoản dùng cho lịch sử và các chức năng cá nhân. Khi cần, tạo tài khoản trên trang đăng nhập; tài khoản đầu tiên trên database mới có quyền quản trị để quản lý quyền và khóa/mở khóa thành viên. Không có tài khoản hoặc mật khẩu mặc định.

Tài khoản và lịch sử dùng SQLite tại `data/application/phishlens.sqlite3`, bị Git ignore. Lịch sử mặc định chỉ lưu thông tin tổng quát; lưu bản nội dung đã che là lựa chọn riêng trước mỗi lượt. Web khách dùng CSRF cấp tự động, không lưu lịch sử. API lịch sử/tài khoản/quản trị vẫn yêu cầu đăng nhập. Model/prompt vẫn theo profile đã chọn; lớp tài khoản không đổi kết luận lõi. [Vận hành, quyền và sao lưu](docs/guides/USAGE.md#tài-khoản-và-lịch-sử-cục-bộ).

Để mở bản demo sau khi cài môi trường/model, dùng **`make demo`**, `./start_phishlens.sh` trên Linux hoặc `start_phishlens.bat` trên Windows. Launcher kiểm asset/phụ thuộc, mở trình duyệt và tái sử dụng PhishLens nếu đã chạy; mặc định cổng **8001** (lệnh `run.py` vẫn mặc định 8000). `make shortcut` thêm mục PhishLens vào menu ứng dụng Linux của người dùng hiện tại; không tạo dịch vụ tự khởi động.

**Demo cho buổi trình bày:** mở [không gian demo cục bộ](http://127.0.0.1:8001/static/demo.html), có email khuyến mãi, thư hội thảo, thông báo thiếu ngữ cảnh và ảnh để khoanh vùng. Nút chuyển mẫu chỉ điền nội dung, không tự gửi AI. [Kịch bản 5 phút và cách chạy thử](docs/guides/DEMO.md).

**Extension trình duyệt:** chuột phải vào link hoặc đoạn bôi đen, hoặc bấm biểu tượng để lấy URL tab; kiểm URL cục bộ, duyệt/xác nhận trước khi dùng AI, giữ hai nhận định riêng. Tải ZIP ngay từ trang kiểm tra khách hoặc Tài khoản, cài bằng **Load unpacked**, rồi mở extension: tự kết nối localhost, **không cần mã hoặc đăng nhập**. Extension mới dùng khách, không lưu lịch sử. Backend phải đang chạy; chưa phát hành trên store. [Cài extension và phạm vi quyền](extensions/chromium/README.md).

**Mới ở extension 0.18:** thẻ **Gần đây** gom các lượt trong phiên; đưa lượt đang chờ chạy nền để tiếp tục dùng, mở lại kết quả mà không gửi AI thêm. Cùng phiên xử lý lần lượt, có hàng chờ và hủy trước khi gửi AI. Kết luận nêu bước nên làm ngay và giải thích bất đồng nội dung/URL; có **In / lưu PDF**. Cần khởi động lại backend khi cập nhật từ 0.17. [Cách dùng và giới hạn phiên](extensions/chromium/README.md#mới-ở-018-gần-đây-tiếp-tục-dùng-khi-chờ-và-bản-in-kết-quả).

**Sửa ở extension 0.17.1:** nút kiểm tra email tự kết nối khách khi thiếu/hết hạn kết nối; thử lại ngay trên thư sau khi mở ứng dụng. Bản 0.17 cũng sửa viewport Zalo và ID hàng Messenger để tải lịch sử qua nhiều đợt. [Chi tiết và cách cập nhật](extensions/chromium/README.md).

**Mới ở extension 0.16:** mở rộng nhận diện khung Messenger, chọn nhanh số tin và nhớ phạm vi. Cảnh báo nền tự ẩn sau 8 giây, chống nhắc lại 30 phút; không ghim nút thường trực nếu chưa chọn. Bỏ qua địa chỉ giao diện ứng dụng như Drive ở bước kiểm URL nền, giữ kiểm tra thủ công. [Cách dùng và giới hạn](extensions/chromium/README.md#mới-ở-016-nhận-diện-chat-rộng-hơn-và-cảnh-báo-yên-lặng).

**Mới ở extension 0.15:** chọn số tin gần nhất, khoảng ngày hoặc toàn bộ lịch sử tải được trên Zalo/Messenger/Telegram Web; tự cuộn và có nút dừng. Tối đa 2.000 tin/200.000 ký tự mỗi lần. Đoạn dài được phân tích từng phần có chồng lấn, báo rõ phần đã hoàn tất và giữ cảnh báo khi có lỗi/hết hạn mức. [Phạm vi, cách dùng và kiểm thử](extensions/chromium/README.md#mới-ở-015-quét-theo-số-tin-ngày-hoặc-lịch-sử-tải-được).

**Mới ở extension 0.14: hội thoại Zalo, Messenger/Facebook Tin nhắn và Telegram Web A/K.** Chọn các tin đang hiển thị, duyệt nhãn người nói và phân tích diễn biến nhiều lượt; tối đa 30 tin/8.000 ký tự. Có nút quay lại tin làm căn cứ và công tắc trợ lý riêng cho từng nền tảng. Dùng prompt riêng `conversation-core-1.0`; chưa đánh giá chất lượng độc lập hoặc xác nhận trên tài khoản chat thật. Cần backend hiện tại, Reload extension và tải lại tab chat. [Cách dùng và phạm vi kiểm thử](extensions/chromium/README.md#mới-ở-014-hội-thoại-zalo-messenger-và-telegram).

Extension **0.12** có bảng Kiểm tra / Trợ lý / Cài đặt, sáng/tối và nút nổi kéo được, menu nhanh, tạm nghỉ một giờ, ẩn theo website. **Khoanh vùng trên trang**: kéo trực tiếp → tự cắt/OCR tại máy → duyệt chữ → đồng ý phân tích theo mặc định; tải/drop/paste ảnh vẫn riêng. Có tùy chọn **tự kiểm URL cục bộ khi mở trang**, kể cả đóng bảng; mặc định tắt, không đọc nội dung trang/gọi AI/lưu lịch sử nền. Quyền toàn trang chỉ xin khi bật nút nổi hoặc tự kiểm URL. Backend cần đang chạy; mở extension là tự kết nối. AI nhận bản chữ đã che; ảnh gốc không đến provider. OCR cần Tesseract/Pillow: [hướng dẫn](docs/guides/OCR.md). Cập nhật: **Reload** extension rồi tải lại tab web. Phím **Alt+Shift+P** mở bảng, **Alt+Shift+S** khoanh vùng, **Ctrl+Enter** thao tác chính; trình duyệt/OS có thể chiếm phím.

Bản 0.12 mở Chi tiết trong bảng bên; nếu trình duyệt không hỗ trợ thì xếp mail và kết quả cạnh nhau, đóng kết quả sẽ khôi phục kích thước mail. [Bố cục hai bên](extensions/chromium/README.md#mới-ở-012-email-và-kết-quả-cạnh-nhau).

Bản 0.11 kiểm email ngay trên thư ở chế độ gửi ngay, không tự bật cửa sổ. **Chi tiết** mở bảng bên cạnh hoặc dùng lại một cửa sổ; bấm lặp dùng lượt đang chạy, **Kiểm tra lại** mới gọi lượt mới. Đóng bảng không hủy AI; backend giữ kết quả tác vụ trong RAM 15 phút sau hoàn tất. [Luồng kiểm email và thời hạn kết quả](extensions/chromium/README.md#mới-ở-011-kiểm-email-gọn-dùng-lại-cửa-sổ).

Bản 0.10 thêm **Cài đặt → Gửi nội dung tới AI**: chọn xem trước/xác nhận mỗi lượt (mặc định) hoặc đồng ý trước để gửi ngay khi chủ động yêu cầu kiểm tra. Cả hai đều che nội dung trước khi gửi; mở extension/chuyển email không tự gọi AI. [Cách gửi và lưu lựa chọn](extensions/chromium/README.md#mới-ở-010-chọn-cách-gửi-ai).

Bản 0.9 tô trích dẫn ngay trên email Gmail/Outlook sau khi phân tích, bấm để đọc giải thích; liên kết có thẻ đối chiếu chữ hiển thị với tên miền đích. Dùng lại kết quả, không gọi AI thêm; đổi thư hoặc thay đích liên kết sẽ xóa đánh dấu. [Cách dùng đánh dấu email](extensions/chromium/README.md#mới-ở-09-xem-dấu-hiệu-ngay-trên-email).

Bản 0.8 giữ nút thao tác chính ở thanh dưới, bảo toàn bản nháp/lựa chọn AI khi đổi thẻ, tách Sửa nội dung và Kiểm tra nội dung khác, đồng thời cho tìm trong danh sách URL. Tin nhắn/email nhận tối đa **50 URL khác nhau** trong 8.000 ký tự; URL trùng chỉ tính một lần. [Các luồng và phím tắt](extensions/chromium/README.md#mới-ở-08-thao-tác-liền-mạch).

Giao diện kiểm tra ưu tiên nội dung và kết quả; có ví dụ dùng thử, hướng dẫn cài extension thu gọn, tải JSON trực tiếp và **In / PDF**. Thông tin model, token và phạm vi phép kiểm nằm trong phần chi tiết. Tab URL mặc định chỉ kiểm tại máy, tab tin nhắn chọn sẵn AI nhưng luôn chờ duyệt và đồng ý gửi.

Extension 0.7 thêm giải thích AI cho từng dấu hiệu, công cụ khoanh xuất hiện trước bản đọc ảnh, chụp toàn vùng website đang hiển thị và lấy email đang mở trên Gmail/Outlook. Bật trợ lý email để tự chuẩn bị bản duyệt khi đổi thư; AI vẫn cần xác nhận. [Phạm vi và cách dùng](extensions/chromium/README.md#mới-ở-07-giải-thích-chụp-nhanh-và-email).

**Phản hồi kết quả:** gửi góp ý từ kết quả/lịch sử, theo dõi trong mục **Phản hồi**; quản trị viên xử lý tại **Quản trị**. Mặc định không gửi nội dung cho quản trị viên. Chia sẻ snapshot đã che phải được chọn riêng; xử lý góp ý không tự tạo nhãn chuẩn hoặc huấn luyện model.

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
extensions/chromium/ # Extension MV3, kết nối backend cục bộ
launch.py         # Launcher demo, kiểm cài đặt và mở trình duyệt
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

Các factory `app.api.runtime` tiếp tục phục vụ nghiên cứu và kiểm thử không có tài khoản. Nếu cần chạy các script replay UI cũ, dùng `PHISHLENS_ACCOUNTS=0 PORT=8003 make run-focused` trên cổng riêng; đây là chế độ nghiên cứu, không phải cấu hình ứng dụng có tài khoản.

- [Kiến trúc và các profile](docs/architecture.md).
- [Quy ước phát triển, đường dẫn mới và tái lập lịch sử](docs/development.md).
- [Phương pháp đánh giá](docs/evaluation.md), [kết quả và hạn chế hiện có](docs/results.md).
- [Danh sách công cụ](scripts/README.md), [dữ liệu](data/README.md), [đầu ra](artifacts/README.md).

Nhãn AI và dữ liệu tự soạn dùng để chẩn đoán, chưa thay thế đánh giá độc lập. `.env`, trọng số, raw response và kết quả mới được Git bỏ qua. Báo cáo học thuật trong `docs/reports/` tiếp tục chỉ giữ cục bộ.

Luồng [chốt nhãn người và đánh giá qua API ứng dụng](docs/evaluation.md#chốt-nhãn-người-và-đánh-giá-đúng-ứng-dụng-ngày-2111) kiểm cùng bốn cấu hình trên dev, tách UNKNOWN/lỗi và giữ từng attempt. Nhãn chưa hoàn tất sẽ chặn đánh giá theo reference người. Lượt [full-dev ngày 22/11](artifacts/evaluations/expanded_dev_full_20261122/README.md) đã hoàn tất 1.228 ô trên 307 ca dev có nhãn AI; 93 holdout và nhãn người còn chờ. [Kết quả mới nhất và giới hạn](docs/results.md) phân biệt kiểm phần mềm, chẩn đoán API và chất lượng phát hiện độc lập.
