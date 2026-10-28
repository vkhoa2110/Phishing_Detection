# Nhãn AI sơ bộ cho 200 SMS

Theo lựa chọn của người dùng ngày 28/10/2026, tạo nhãn AI trước để hỗ trợ rà soát. **Không phải bộ nhãn chuẩn do con người đánh giá và không phải kết quả đo độ chính xác.**

## Mục tiêu và đầu ra

Dùng 200 SMS đã chuẩn bị ở `data/annotation/vn_sms_v2/`, gồm 80 dev và 120 test, đã tách nhóm/domain. Dữ liệu nguồn gộp spam với scam; không chuyển trực tiếp nhãn đó thành phishing. Không truy cập URL có trong SMS.

Prompt riêng chỉ nhận ID và văn bản đã che, không nhận nhãn nguồn, split, dự đoán ML hay RAG. Mỗi SMS có nhãn, nhóm nội dung, lý do tiếng Việt, đoạn dẫn và mức tự đánh giá high/medium/low. Mức này không phải xác suất đã hiệu chỉnh.

- `1`: có dấu hiệu cụ thể của lừa đảo/chiếm thông tin hoặc tiền; cần đoạn dẫn nguyên văn.
- `0`: chưa thấy hành vi lừa đảo rõ; quảng cáo, OTP hoặc thanh toán không tự là phishing. Không xác nhận người gửi, URL hay giao dịch an toàn.
- `UNKNOWN`: thiếu ngữ cảnh quyết định hoặc thông tin quan trọng bị che. Không đổi thành bình thường.

Gói cục bộ: `artifacts/annotations/vn_sms_ai_complete_v1/`.

**Đã hoàn tất 200/200 phản hồi AI hợp lệ:** 64 nhãn 1, 120 nhãn 0, 16 UNKNOWN; 110 mẫu ưu tiên rà soát. 16 UNKNOWN là nhận định thiếu ngữ cảnh của AI, không phải lỗi API còn bỏ dở. Có 55 request qua ba lượt (25 + 26 + 4), 41 request tạo đủ 200 nhãn và 14 request lỗi được giữ làm audit. Hai phiếu người đánh giá vẫn trống. Toàn bộ 135 test tự động đạt; các kiểm chứng dữ liệu không thay thế việc kiểm tra nhãn bằng người.

Trang xem cục bộ đang phục vụ ở `http://127.0.0.1:8010/`. Khởi động lại khi cần:

```bash
.venv/bin/python -m http.server 8010 --bind 127.0.0.1 \
  --directory artifacts/annotations/vn_sms_ai_complete_v1
```

- `index.html`: xem/tìm/lọc nhãn, không gọi mạng bên ngoài hoặc sửa tệp.
- `review_all.csv`: toàn bộ SMS và nhãn AI, mở bằng Excel/LibreOffice.
- `priority_review.csv`: UNKNOWN, nhãn dương hoặc mức tự đánh giá chưa cao. Mọi nhãn AI đều cần kiểm tra; mẫu ngoài danh sách không mặc nhiên đúng.
- `labels.jsonl`, `summary.json`, `manifest.json`: dữ liệu, phân bố nhãn và provenance.
- `verification.json`: kiểm tra đủ ID, nội dung, đoạn dẫn, CSV, hash và cổng từ chối nhãn AI làm gold.

Số lượng cụ thể xem summary và README trong gói. Đây là phân bố nhãn AI, không phải tỷ lệ lừa đảo thực được xác minh. Hai phiếu người đánh giá giữ nguyên hash và không được điền bằng AI. Muốn gán nhãn mù độc lập, người gán nhãn không xem gợi ý AI trước. Nếu đã dùng gợi ý, phải ghi là AI-assisted review.

## API, lỗi và khả năng tiếp tục

Lưu checkpoint trước/sau request, tối đa hai request đồng thời và có trần số lượt mới. Lỗi hoặc bị cắt không tính là nhãn hợp lệ. Không tự retry checkpoint đã gọi. Các lượt bổ sung chỉ chọn mẫu chưa có phản hồi hợp lệ, không chọn theo giá trị nhãn; giữ nguyên mọi nhãn AI đã có, kể cả UNKNOWN.

Lượt đầu dùng 8 SMS/nhóm và trần 8.192 token, nhiều phản hồi bị cắt. Lượt bổ sung dùng nhóm nhỏ hơn, trần 16.384 token. Usage ghi nhận là phần API cung cấp và công cụ lưu được; usage thiếu ở các lỗi lượt đầu không được coi bằng 0 hoặc dùng để khẳng định tổng chi phí đầy đủ.

Chuẩn bị offline, thêm `--live` để gọi API đã cấu hình:

```bash
.venv/bin/python -m evaluation.prelabel --out artifacts/annotations/vn_sms_ai_new
```

Mặc định hiện tại: 4 SMS/nhóm, tối đa 50 request mới và trần 16.384 token. Resume cùng thư mục không gọi lại checkpoint đã có. Xử lý mẫu chưa có nhãn hợp lệ ở lượt riêng:

```bash
.venv/bin/python -m evaluation.prelabel_repair --live \
  --base artifacts/annotations/vn_sms_ai_new \
  --out artifacts/annotations/vn_sms_ai_new_repair
```

## Giới hạn khi đánh giá

Mô hình gán nhãn dùng cùng dịch vụ/tên mô hình với bộ phân loại hiện tại, dù prompt khác. So sánh dự đoán với nhãn này có tính phụ thuộc, không chứng minh độ chính xác độc lập. Vì vậy chưa chạy bốn cấu hình để công bố F1 trên nhãn AI và không dùng nhãn này để chọn prompt, ngưỡng hoặc retriever.

`evaluation.review.validate_gold` từ chối manifest `ai_preliminary`; không tạo trạng thái reviewed_frozen hoặc phiếu đồng thuận giả. Tập test người đánh giá cần được khóa trước lượt đánh giá chính thức. Chấm lời giải thích và mức hỗ trợ của nguồn cần quy trình riêng; trích đúng chuỗi chưa chứng minh nhận định đúng.
