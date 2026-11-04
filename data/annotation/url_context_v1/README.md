# Bộ đối chiếu URL và ngữ cảnh v1

**Đã tạo 160 URL thực và 360 đầu vào; chưa gọi LLM, chưa có F1 so sánh.**

- `urls.jsonl`: 160 URL / 160 miền, chọn theo quota nguồn/tier/lớp, không dùng điểm model. Dev 40, test 120; mỗi split cân bằng hai lớp.
- `dev.jsonl`, `test.jsonl`: 160 ca URL riêng + 200 thông điệp tự soạn trên 40 URL trong số đó, năm ngữ cảnh cho mỗi URL. Các ca dùng lại URL không độc lập thống kê.
- `reference_review.csv`: xem nội dung và ba nhãn riêng. 1=rủi ro theo chiều đang chấm; 0=không có điều kiện rủi ro đã định; UNKNOWN=không đủ căn cứ/không áp dụng. Không coi 0 là website được xác minh an toàn hiện tại.
- `reviewer_a.csv`, `reviewer_b.csv`: phiếu mù còn trống, không giả nhãn người. `reference_review.csv` dành cho điều phối, không gửi cùng phiếu mù.
- `system_prompt.txt`: cùng prompt/schema cho LLM và LLM + URL. Hai cấu hình đều thấy URL. Chỉ thêm điểm model ở `url_model`; metadata nguồn/nhãn không gửi cho LLM.
- `*_inputs.jsonl`: payload chưa có nhãn; `id` bên ngoài `input` chỉ là khóa cục bộ, không gửi API.

## Ba chiều đánh giá

| Chiều | Ý nghĩa nhãn |
|---|---|
| url_risk | Nhãn URL lịch sử của PhishVN, giữ nguyên nguồn/tier |
| message_behavior | Hành vi lấy mật khẩu/OTP hoặc ngữ cảnh giáo dục theo thiết kế; lời mời mở URL trung tính là UNKNOWN |
| action_risk | Yêu cầu lấy bí mật hoặc yêu cầu mở URL có nhãn rủi ro; URL chỉ trích trong bài học không tự làm chiều này thành 1 |

Phần URL có benign từ cả Tín nhiệm mạng, Tranco Việt Nam và Tranco toàn cầu. Phần ngữ cảnh có URL benign kèm yêu cầu lấy mật khẩu, URL rủi ro chỉ được trích để cảnh báo, và injection ép cả LOW lẫn HIGH. Không được chọn lại mẫu để LLM + URL thắng.

## Nguồn và giới hạn

Thai Nguyen Vu, PhishVN v3.1.0, DOI `10.17632/b97hxbxtpd.4`, CC BY 4.0; nguồn upstream NCSC/Tín nhiệm mạng và Tranco. [Nguồn phát hành](https://data.mendeley.com/datasets/b97hxbxtpd/4). Phần thích nghi giữ URL/nhãn, lấy mẫu theo miền và thêm văn bản do trợ lý soạn. Đọc `DATA_LICENSE.txt` và `SOURCE_DATASHEET.md`.

Gold/silver là tier của nguồn, không phải nhãn do dự án tự kiểm chứng lại. Nhãn positive có phạm vi lừa đảo/lạm dụng rộng hơn lấy thông tin đăng nhập. Dev dương chỉ có silver vì split nguồn không có gold dương. Nguồn lớp dương và âm khác nhau nên vẫn còn lệch nguồn.

Đã kiểm tra không trùng miền train/dev/test và loại 80 miền thuộc các danh sách đã chọn cho lượt LLM PhishVN trước. Tuy nhiên, toàn bộ val/test đã từng được đánh giá ML: **đây là bộ chẩn đoán tái sử dụng holdout, không phải external test mới**. Các thông điệp ghép URL là mô phỏng, không phải SMS thật. Tỷ lệ 50/50 của phần URL phục vụ so sánh, không đại diện tỷ lệ lừa đảo trong sử dụng thực tế.

## Chạy đánh giá

Đầu tiên `python -m evaluation.url_context_pack verify --out <thư_mục_này>`. Dùng môi trường `.venv` của dự án.

Trước gọi API phải đăng ký model, tham số, ngưỡng, số lượt lặp, hash runner và chính sách lỗi thành execution manifest riêng. Pack hiện khóa dữ liệu/prompt, chưa khóa một lượt API. Khuyến nghị ba lượt/cấu hình, giữ mọi kết quả; không chọn lượt tốt nhất. Không dùng trực tiếp runner `message-v3`: mục tiêu và schema khác.

Công cụ `evaluation.url_context_score` chấm file dự đoán đã lưu theo từng split, task và chiều; thiếu dự đoán thì chưa xuất metrics. File chỉ số không được dùng làm bằng chứng đã chạy model nếu dự đoán là fixture. Không truy cập website trong bộ dữ liệu để dựng pack này.
