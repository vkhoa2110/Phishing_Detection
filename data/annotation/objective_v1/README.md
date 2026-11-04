# Bộ đánh giá khách quan — bản chuẩn bị v1

Protocol được khóa trước lượt so sánh mới. 200 SMS bên ngoài và 72 ca mô phỏng
được đánh giá, báo cáo riêng. 72 ca thuộc 12 nhóm, mỗi nhóm có yêu cầu rủi ro,
quy trình thông thường, thiếu ngữ cảnh, hai kiểu prompt injection và trích dẫn giáo dục.
Các vai trò do tác giả thiết kế không phải nhãn chuẩn; vẫn cần review.

- `protocol.json`: điều kiện chạy, ánh xạ nhãn, mẫu số, lỗi, bộ đối chứng, giới hạn.
- `classification/sms/`: 200 SMS, 80 dev/120 test; giữ nguyên split và nội dung đã che.
- `classification/challenge/`: 72 ca, 48 dev/24 test, tách theo 12 nhóm tình huống.
- `reviewer_a.zip`, `reviewer_b.zip`: gói mù để gửi riêng từng người; không có nhãn AI,
  nhãn nguồn, split, vai trò ca, điểm model, thứ hạng retrieval hoặc phiếu của người kia.
- `retrieval/`: 24 truy vấn, 25 tài liệu, 600 cặp/người; chấm toàn corpus để tránh ưu ái retriever.
- `explanation_selection.jsonl`: 32 mẫu chốt trước kết quả (8 mỗi dataset/split), chấm cùng mẫu ở bốn arm.
- `provisional_reference/`: nhãn tham chiếu AI cho 272 mẫu, gồm UNKNOWN, lý do
  và căn cứ. SMS được trợ lý đọc theo rubric mà không xem nhãn AI cũ/điểm model;
  nhãn mô phỏng theo thiết kế của tác giả. Không phải gold/thẩm định độc lập.

Hai phiếu classification dùng cùng định dạng `evaluation.review`. Không tự tạo
mã người gán nhãn để biến nhãn AI thành reviewed-gold. Nếu chỉ có AI, nhãn được
đặt riêng với trạng thái provisional; chỉ dùng cho diagnostic ghi rõ giới hạn.
Đồng thuận AI không thay việc thẩm định độc lập. 200 SMS đã có nhãn AI sơ bộ từ trước;
không mô tả đây là test chưa từng bị xem. Chỉ có SMS, chưa có email thực.

Chạy từ thư mục gốc:

```bash
.venv/bin/python -m evaluation.benchmark_pack verify --out data/annotation/objective_v1
.venv/bin/python -m evaluation.review status --workspace data/annotation/objective_v1/classification/sms
.venv/bin/python -m evaluation.review adjudicate --workspace data/annotation/objective_v1/classification/sms
.venv/bin/python -m evaluation.review finalize --workspace data/annotation/objective_v1/classification/sms --out data/evaluation/objective_sms_gold_v1
.venv/bin/python -m evaluation.relevance_review status --workspace data/annotation/objective_v1/retrieval
```

Lặp quy trình với `classification/challenge`, xuất sang thư mục khác. Nhãn UNKNOWN
được giữ riêng. Chỉ dùng dev để chọn prompt; không thay nhãn vì mô hình dự đoán khác.
Nếu test có rất ít ca một lớp hoặc nhiều UNKNOWN, báo đúng số lượng và độ bất định;
không tự bù mẫu theo kết quả. Bộ này không ước lượng tỷ lệ phishing ngoài thực tế.
Nguồn SMS và giấy phép: xem `data/annotation/vn_sms_v2/ATTRIBUTION.md`.
