# Demo PhishLens cho buổi trình bày

## Mở bản demo

Tại thư mục gốc dự án, sau khi đã cài phụ thuộc và model:

```bash
.venv/bin/python launch.py --profile focused --port 8001
```

Mở **http://127.0.0.1:8001/static/demo.html**. Không cần đăng nhập. Nếu launcher tái sử dụng tiến trình đã chạy, profile của tiến trình đó được giữ nguyên; xem Thiết lập → Trạng thái kỹ thuật để kiểm tra. Cấu hình key AI nằm tại máy chủ, không cần trình chiếu file `.env`.

Cài hoặc Reload extension tại `chrome://extensions` từ thư mục `extensions/chromium` rồi tải lại trang. Nếu muốn dùng nút nổi hoặc phím tắt khoanh vùng trên mọi trang, mở extension → Trợ lý → bật nút PhishLens và chấp nhận quyền trang web. Không cần bật tự kiểm URL nền để thực hiện demo. Trình duyệt có thể chiếm phím tắt; dùng menu chuột phải nếu cần.

## Kịch bản khoảng 5 phút

| Thời gian | Thao tác | Điểm cần trình bày |
|---|---|---|
| 0:00–0:30 | Mở không gian demo, giới thiệu ba loại đầu vào | “PhishLens hỗ trợ xem dấu hiệu trong URL, thông điệp và phần chữ trong ảnh.” |
| 0:30–2:00 | Chọn **Ưu đãi mua sắm cuối năm**, sao chép vào tab Tin nhắn của extension; bật AI, bấm Kiểm tra, duyệt nội dung đã che rồi xác nhận | Chỉ ra yêu cầu nhập CVV, trả phí trước và gửi OTP. Đợi kết quả thật, đọc trích dẫn và giải thích thay vì chỉ nhìn màu cảnh báo. |
| 2:00–2:45 | Mở chi tiết URL và hướng xử lý | Điểm mô hình URL và nhận định hành vi được giữ riêng. Phần trăm URL chưa phải xác suất lừa đảo đã hiệu chỉnh. |
| 2:45–3:45 | Chọn **Lịch hội thảo**, bấm **Dùng mẫu này để kiểm tra**, xác nhận trên web | Có ví dụ đối chứng. Mở mẫu chỉ điền nội dung; phải chủ động gửi mới gọi AI. Kết quả mỗi lượt có thể khác. |
| 3:45–4:45 | Chọn **Ưu đãi trong ảnh**, dùng **Alt+Shift+S** hoặc chuột phải → **Khoanh vùng trên trang để kiểm tra**, kéo sát ảnh | Sau khi thả chuột, OCR tại máy tạo bản chữ để kiểm tra. Đọc lại chữ rồi xác nhận gửi AI. Có thể tải PNG để thử chức năng tải ảnh riêng. |
| 4:45–5:00 | Kết thúc bằng phạm vi đã thực hiện | “Demo này dùng mẫu tự soạn. Ứng dụng hỗ trợ kiểm tra; cần đối chiếu người gửi qua kênh đã biết.” |

Thông báo ngắn thứ ba dành cho câu hỏi về thiếu ngữ cảnh; không có kết luận điền sẵn. Không gọi một kết quả LOW là chứng nhận an toàn.

## Nếu muốn trình diễn trực tiếp trên Gmail / Outlook

Trang demo là nội dung giả định, không mô phỏng việc truy cập hộp thư. Với một thư thử nghiệm đã có trong tài khoản của bạn:

1. Bật Trợ lý Gmail / Outlook trong extension và tải lại tab hộp thư sau khi Reload extension.
2. Mở một email cụ thể, bấm **Kiểm tra email này**. Chế độ mặc định vẫn yêu cầu duyệt và đồng ý gửi; chế độ Gửi ngay cần bạn chọn trước trong Cài đặt.
3. Chờ trạng thái ngay trên thư, bấm **Chi tiết** để mở kết quả bên cạnh. Bấm **Xem dấu hiệu trên thư** để đối chiếu trích dẫn và liên kết.
4. Không đưa thư có thông tin cá nhân của người khác lên màn hình trình chiếu hoặc gửi AI khi chưa được phép.

Không cần gửi email thật để dùng các tình huống ở trang demo. Gmail/Outlook còn phụ thuộc bố cục và quyền của trình duyệt; bản chạy thử tự động dưới đây không xác minh hộp thư thật hoặc giao diện Brave trên máy của bạn.

## Tự kiểm tra trước buổi trình bày

Kiểm tra trang demo, chuyển mẫu, tải PNG và bố cục; lệnh này không gọi AI:

```bash
.venv/bin/python scripts/evaluation/rehearse_teacher_demo.py \
  --out artifacts/ui/demo_preflight
```

Nếu muốn chạy ba đầu vào bằng dịch vụ AI thật và ghi video:

```bash
.venv/bin/python scripts/evaluation/rehearse_teacher_demo.py \
  --out artifacts/ui/demo_live --live-provider
```

Mỗi thư mục đầu ra phải mới. Lượt đầy đủ gửi **ba phân loại và tối đa hai giải thích bổ sung**; có thể phát sinh phí theo nhà cung cấp, không tự retry và không gửi email. Cần cài Playwright/Chromium theo hướng dẫn kiểm UI của dự án. Browser profile riêng, chế độ khách không lưu lịch sử. Quyền website tùy chọn được cấp sẵn trong bản sao extension dùng cho diễn tập headless; JavaScript sản phẩm không sửa. Đây không phải kiểm thử hộp thoại cấp quyền của hệ điều hành/trình duyệt.

Đầu ra gồm `checks.json`, JSON phản hồi, ảnh màn hình, PNG mẫu và hai video WebM. Video ghi lại các thao tác tự động với mẫu giả định và phản hồi provider thật; không phải kết quả khảo sát người dùng hay đánh giá độ chính xác độc lập. Giữ file ghi lại ở `artifacts/ui/` cục bộ, không đưa browser profile lên Git.

## Khi có trục trặc

- **Chưa kết nối:** giữ cửa sổ chạy server mở, kiểm cổng 8001 và địa chỉ trong Cài đặt extension.
- **AI lỗi hoặc chậm:** giữ nguyên lỗi, chuyển sang kiểm URL tại máy hoặc giải thích bằng video của lượt đã ghi; nói rõ đang xem lại, không giới thiệu là phản hồi trực tiếp.
- **Khoanh vùng chưa được:** bấm biểu tượng extension trên đúng tab hoặc bật nút nổi/cấp quyền. Vùng chọn phải thuộc trang HTTP/HTTPS; các trang `chrome://` bị giới hạn.
- **Chữ OCR sai:** sửa bản chữ trước khi gửi. “Toàn vùng hiển thị” chỉ chụp viewport trang, không chụp toàn màn hình hệ điều hành hoặc tự cuộn cả trang dài.
