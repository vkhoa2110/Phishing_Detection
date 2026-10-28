# Baseline tham chiếu: ML + LLM

> Đây là mốc tham chiếu v1. Từ 28/10/2026, ứng dụng dùng [hai đánh giá riêng và prompt message-v2](../evaluation/CONTEXT_V2.md). `fuse_legacy`, `baseline-1.0` và `rag-1.0` vẫn được giữ cho các công cụ thực nghiệm cũ. Xem [RAG](../guides/RAG.md) cho phần truy xuất.

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

- Giao diện quản trị/cập nhật tự động kho RAG. Hiện đã có embedding, chỉ mục cục bộ và truy xuất tùy chọn; snapshot mới vẫn được dựng và chọn ngưỡng bằng công cụ dòng lệnh.
- Nhãn độc lập và đánh giá trên test set ngoài thực tế. Đã chuẩn bị [200 SMS nguồn công khai chờ hai người review](../../data/annotation/vn_sms_v2/README.md); chưa có nhãn phishing chuẩn cho các mẫu này. Bộ 60/100 mẫu tự soạn trước đó chỉ dùng chẩn đoán.
- Đánh giá prompt injection có hệ thống và chấm độ đúng của lập luận. Kiểm tra quote chỉ xác nhận trích đoạn có thật, không xác nhận suy luận của LLM đúng.
- Huấn luyện, chọn lại ngưỡng hoặc so sánh với baseline PhishVN trong ứng dụng.
- Tài khoản, triển khai công khai, ngân sách API theo người dùng, cơ sở dữ liệu.

## Cách dùng cho thực nghiệm v1

Giữ cùng model ID, prompt (`baseline-1.0`), tham số và bộ kiểm tra. Khi tắt tùy chọn cung cấp ML, nhận định ở `llm.verdict` tương ứng LLM chỉ đọc nội dung; khi bật, LLM nhận thêm phân loại URL. Cả hai vẫn chạy ML cục bộ và tổng hợp cảnh báo để phục vụ giao diện. Vì vậy, **không gọi toàn bộ đầu ra `final` của chế độ tắt cung cấp ML là cấu hình “chỉ LLM”**; khi so sánh tác động thông tin ML cần chấm `llm.verdict` trước quy tắc kết hợp.

Đoạn trên mô tả chính sách v1. Với v2, headline text là hành vi, còn cảnh báo URL nằm trong `assessments.url`; vẫn chấm bốn arm theo cùng prompt profile và báo riêng các phạm vi thay vì coi đổi ý nghĩa headline là tăng độ chính xác.

File JSON xuất lưu cấu hình, model/run ID, ngưỡng, prompt version, thời gian, token nếu API trả về và kết quả thành phần. Công cụ `python -m evaluation.run` đã bổ sung đánh giá lô, so sánh LLM độc lập, LLM nhận điểm URL và hai cách fusion; xem `docs/evaluation/METHODS.md`. Kết quả mẫu nhỏ chỉ dùng chẩn đoán, chưa chứng minh khả năng tổng quát.

Các thử nghiệm giao diện và mô phỏng API không chứng minh chất lượng nhận diện lừa đảo. Kết quả cuối cần được đo với trọng số thật, dữ liệu gán nhãn và API của bạn.

