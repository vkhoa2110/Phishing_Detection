# Đọc chữ và mã QR từ ảnh trong extension

Extension 0.3 có hai cách riêng: **Khoanh vùng trên trang** (hoặc Alt+Shift+S/menu chuột phải/nút nổi tùy chọn) và **Tải ảnh từ máy** trong thẻ Hình ảnh (chọn/kéo thả PNG, JPEG, WebP hoặc Ctrl+V). Khi khoanh trên trang, thả chuột là tự cắt/đọc chữ và mở bản duyệt; không cần tải ảnh lên hay bấm Đọc chữ. Esc hủy. Mở extension trên chính tab web để cấp quyền `activeTab`; nút nổi cần quyền toàn trang tùy chọn.

Ảnh tải/dán có xem trước: kéo trên ảnh để cắt, **Toàn ảnh** để bỏ vùng cắt, rồi **Đọc chữ và mã QR**. Chỉ vùng đã chọn đến backend localhost. Kiểm tra/sửa dấu, số và URL; chỉ chữ đã đồng ý mới gửi AI. Ảnh gốc không đến LLM. Backend cần đang chạy; OCR thiếu chữ không tự đưa ra kết luận về toàn ảnh.

## Đọc QR

Từ extension 0.19, backend giải mã QR bằng **ZXing-C++ 3.2.0.post1**, nhận Pillow image trong một tiến trình riêng. URL HTTP/HTTPS hiện ở thẻ **Mã QR trong ảnh**; chọn **Kiểm tra đường dẫn này** để chấm URL tại máy. Không mở liên kết, không thêm payload QR vào bản gửi AI, không diễn giải VietQR thành kết luận về giao dịch. QR khác URL chỉ có phần xem dữ liệu thu gọn; byte không giải mã được UTF-8 được báo dữ liệu nhị phân.

Tối đa 8 nội dung QR khác nhau mỗi lượt, gộp mã trùng; vượt trần có thông báo để cắt vùng nhỏ hơn. Đọc QR tối đa 5 giây; nếu OCR cũng bật thì tiếp theo OCR có ngân sách riêng 20 giây. Hai bước không có SLA thời gian tổng. Lỗi một bước được nêu rõ và giữ kết quả bước còn lại khi có. QR hoạt động khi không có Tesseract; OCR vẫn hoạt động khi không có ZXing.

Vùng QR giải mã được được che trắng trước OCR để tránh chữ nhiễu từ các ô mã. Khi khoanh vùng có QR, tiện ích dừng ở màn hình mã/chữ để chọn bước tiếp theo, không tự gửi chữ sang AI kể cả khi đã chọn chế độ gửi ngay. Kết quả QR không có trong lịch sử Gần đây cho tới khi người dùng chủ động kiểm tra URL; ảnh/payload chỉ ở bộ nhớ. Thành công giải mã không chứng minh độ an toàn của dữ liệu.

Nguồn triển khai: [ZXing-C++ Python bindings](https://github.com/zxing-cpp/zxing-cpp/blob/master/wrappers/python/README.md), [giấy phép Apache-2.0](https://github.com/zxing-cpp/zxing-cpp/blob/master/LICENSE). Kiểm thử biến đổi ảnh và luồng chức năng không thay thế đánh giá chất lượng trên ảnh thực tế có nhãn độc lập.

## Cài OCR tùy chọn

Ứng dụng URL/văn bản vẫn chạy nếu thiếu bộ đọc ảnh. Cài Pillow và ZXing-C++:

```bash
.venv/bin/python -m pip install -r requirements/ocr.txt
```

Tesseract cần cả `vie` và `eng`. Trên Ubuntu 26.04 x86_64 của demo, đã tải/extract gói apt vào `models/ocr/` theo người dùng, không đổi gói hệ thống hoặc cần sudo. Thiết lập cho môi trường tương ứng:

```bash
.venv/bin/python scripts/maintenance/install_ocr.py
```

Công cụ tải từ apt index của máy; thư viện chia sẻ khác của hệ thống vẫn phải tương thích. Binary/data bị Git ignore. `models/ocr/installation.json` ghi SHA các gói. Script giữ nguyên runtime đang có. Trên hệ điều hành khác, cài Tesseract cùng tiếng Việt/Anh theo [tài liệu Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html); chưa kiểm Windows/macOS trong lượt này.

Tự phát hiện `models/ocr/usr/bin/tesseract`, sau đó executable trong PATH. Có thể đặt `PHISHLENS_OCR_BIN` / `PHISHLENS_OCR_TESSDATA` từ môi trường máy chủ, không nhận đường dẫn từ request. Khởi động lại backend sau cài và kiểm:

```bash
.venv/bin/python launch.py --check
```

## Phạm vi

- Ảnh tĩnh PNG/JPEG/WebP, tối đa 5 MiB, 12 triệu điểm ảnh, ít nhất 20 px mỗi chiều. Chưa hỗ trợ PDF, SVG, GIF hoặc ảnh động.
- QR tối đa 5 giây, OCR tối đa 20 giây; hai tác vụ đọc ảnh đồng thời, 30 yêu cầu/giờ/tài khoản hoặc địa chỉ khách. Không dùng lượt AI hoặc tự tạo lịch sử.
- Không tự lấy ảnh từ URL. Backend chuẩn hóa byte trong bộ nhớ, đưa qua stdin Tesseract, không tạo file ảnh. Ảnh/crop chỉ ở bộ nhớ cửa sổ; chọn Xóa ảnh hoặc đóng/reload cửa sổ để bỏ.
- Chỉ chữ được người dùng duyệt mới gửi AI/lưu theo lựa chọn. Không lưu ảnh/kết quả vào storage extension; địa chỉ/theme/token theo README.
- OCR và QR có thể bỏ sót; chưa đánh giá độ chính xác bằng nhãn người. Chưa xác thực logo/giấy tờ, suy luận thị giác, đọc chữ viết tay hoặc xác minh tài khoản nhận tiền trong QR.

Tham khảo: [Tesseract CLI](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html), [sidePanel](https://developer.chrome.com/docs/extensions/reference/api/sidePanel), [captureVisibleTab](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab).
