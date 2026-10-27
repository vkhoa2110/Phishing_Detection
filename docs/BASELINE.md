# Baseline 01: ML + LLM, chưa dùng RAG

## Mục đích

Nối mô hình URL đã có với luồng phân tích văn bản và giao diện sử dụng được, làm mốc triển khai trước khi bổ sung RAG và đánh giá trên bộ dữ liệu tiếng Việt.

## Đã triển khai trong mã nguồn

- Nạp gói ML từ notebook, giữ nguyên hàm sinh feature, thứ tự cột và ngưỡng.
- URL riêng lẻ; email/tin nhắn có, nhiều hoặc không có URL.
- LLM qua endpoint FPT, thông số cấu hình và API key nhập được từ giao diện hoặc môi trường.
- Bản xem trước, che dữ liệu theo quy tắc và xác nhận gửi API.
- Đầu ra LLM có cấu trúc; kiểm tra quote có xuất hiện trong đầu vào.
- Cảnh báo tổng hợp theo quy tắc; không biến lỗi API thành kết luận ít nguy cơ.
- Không lưu lịch sử, không đưa API key xuống cấu hình frontend, xuất JSON theo thao tác người dùng.

## Chưa triển khai

- Truy xuất RAG trong luồng ứng dụng và cập nhật chỉ mục. Đã chuẩn bị kho 25 nguồn tiếng Việt có bản tóm lược và provenance trong `knowledge/`; bước tạo embedding/chỉ mục chưa triển khai.
- Bộ email/tin nhắn thực được gán nhãn độc lập, rubric và đánh giá trên test set ngoài thực tế. Đã bổ sung bộ chẩn đoán mô phỏng 60 mẫu có URL trong `evaluation/`, không thay thế tập thực tế.
- Đánh giá prompt injection có hệ thống và chấm độ đúng của lập luận. Kiểm tra quote chỉ xác nhận trích đoạn có thật, không xác nhận suy luận của LLM đúng.
- Huấn luyện, chọn lại ngưỡng hoặc so sánh với baseline PhishVN trong ứng dụng.
- Tài khoản, triển khai công khai, ngân sách API theo người dùng, cơ sở dữ liệu.

## Cách dùng cho thực nghiệm tiếp theo

Giữ cùng model ID, prompt (`baseline-1.0`), tham số và bộ kiểm tra. Khi tắt tùy chọn cung cấp ML, nhận định ở `llm.verdict` tương ứng LLM chỉ đọc nội dung; khi bật, LLM nhận thêm phân loại URL. Cả hai vẫn chạy ML cục bộ và tổng hợp cảnh báo để phục vụ giao diện. Vì vậy, **không gọi toàn bộ đầu ra `final` của chế độ tắt cung cấp ML là cấu hình “chỉ LLM”**; khi so sánh tác động thông tin ML cần chấm `llm.verdict` trước quy tắc kết hợp.

File JSON xuất lưu cấu hình, model/run ID, ngưỡng, prompt version, thời gian, token nếu API trả về và kết quả thành phần. Công cụ `python -m evaluation.run` đã bổ sung đánh giá lô, so sánh LLM độc lập, LLM nhận điểm URL và hai cách fusion; xem `evaluation/README.md`. Kết quả mẫu nhỏ chỉ dùng chẩn đoán, chưa chứng minh khả năng tổng quát.

Các thử nghiệm giao diện và mô phỏng API không chứng minh chất lượng nhận diện lừa đảo. Kết quả cuối cần được đo với trọng số thật, dữ liệu gán nhãn và API của bạn.

