# Kiểm tra bản bàn giao

Ngày 24/10/2026, Python 3.12, Linux x86_64.

- **31 test tự động đã qua:** trích xuất/gộp URL, giới hạn đầu vào, che dữ liệu, xác nhận gửi API, lỗi 401/402/404/429/500, timeout, JSON sai, kiểm tra quote và quy tắc tổng hợp. HTTP tới FPT được mô phỏng, không dùng key thật.
- **Bộ nạp model:** tạo một gói XGBoost nhỏ để kiểm tra kỹ thuật, dùng chính `FEATURE_SOURCE`, `PREPROCESSING_SOURCE`, `INFERENCE_SOURCE` và thứ tự 21 feature của notebook `Train_URL_Phishing.ipynb`. So sánh điểm của 40 URL trước và sau khi nạp bằng bộ adapter: khớp trong dung sai 1e-6. Đây không phải mô hình bàn giao và không có ý nghĩa đánh giá chất lượng nhận diện.
- **Giao diện Chromium:** trạng thái chưa có model; chạy URL khi tắt LLM; nhập API key; xem trước và xác nhận; hiển thị nhận định/bằng chứng/hướng dẫn với phản hồi giả lập; tải JSON. Nội dung chứa thẻ HTML được hiển thị như văn bản. Không có lỗi JavaScript trong lượt kiểm tra.
- **Bố cục:** kiểm tra màn hình 1360 px và 390 px; không tràn ngang ở chiều rộng 390 px.

Chưa kiểm tra bằng trọng số `models/inference_XGBoost_d6_s42` người dùng vừa tải từ Colab và chưa gọi endpoint FPT bằng API key thật. Cần đặt model và nhập key trên máy người dùng để kiểm tra luồng thực tế. Không bàn giao model thử, dữ liệu thử nội bộ hoặc ảnh chụp chứa kết quả giả lập.
