# Đọc chữ từ ảnh trong extension

Extension 0.3 có hai cách riêng: **Khoanh vùng trên trang** (hoặc Alt+Shift+S/menu chuột phải/nút nổi tùy chọn) và **Tải ảnh từ máy** trong thẻ Hình ảnh (chọn/kéo thả PNG, JPEG, WebP hoặc Ctrl+V). Khi khoanh trên trang, thả chuột là tự cắt/đọc chữ và mở bản duyệt; không cần tải ảnh lên hay bấm Đọc chữ. Esc hủy. Mở extension trên chính tab web để cấp quyền `activeTab`; nút nổi cần quyền toàn trang tùy chọn.

Ảnh tải/dán có xem trước: kéo trên ảnh để cắt, **Toàn ảnh** để bỏ vùng cắt, rồi **Đọc chữ từ ảnh**. Chỉ vùng đã chọn đến backend localhost để OCR. Kiểm tra/sửa dấu, số và URL; chỉ chữ đã đồng ý mới gửi AI. Ảnh gốc không đến LLM. Backend cần đang chạy; OCR thiếu chữ không tự đưa ra kết luận về toàn ảnh.

## Cài OCR tùy chọn

Ứng dụng URL/văn bản vẫn chạy nếu thiếu OCR. Cài Pillow:

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
- OCR tối đa 20 giây, hai tác vụ đồng thời; 30 yêu cầu đọc ảnh/giờ/tài khoản. Không dùng lượt AI hoặc tự tạo lịch sử.
- Không tự lấy ảnh từ URL. Backend chuẩn hóa byte trong bộ nhớ, đưa qua stdin Tesseract, không tạo file ảnh. Ảnh/crop chỉ ở bộ nhớ cửa sổ; chọn Xóa ảnh hoặc đóng/reload cửa sổ để bỏ.
- Chỉ chữ được người dùng duyệt mới gửi AI/lưu theo lựa chọn. Không lưu ảnh/kết quả vào storage extension; địa chỉ/theme/token theo README.
- OCR có thể sai; chưa đánh giá độ chính xác bằng nhãn người. Đây là đọc chữ, chưa xác thực logo/giấy tờ, suy luận thị giác, đọc chữ viết tay hoặc giải mã QR.

Tham khảo: [Tesseract CLI](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html), [sidePanel](https://developer.chrome.com/docs/extensions/reference/api/sidePanel), [captureVisibleTab](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab).
