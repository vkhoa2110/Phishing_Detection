# Huấn luyện mô hình URL

[Train_URL_Phishing_GPU.ipynb](Train_URL_Phishing_GPU.ipynb) là bản nguồn notebook dùng để tạo gói mô hình và khôi phục fingerprint trong đánh giá PhishVN. Bản đưa vào Git không chứa output cell hay API key.

Notebook giữ nguyên mã và cấu hình của bản gốc ở thư mục BCTT để giữ SHA-256 đã ghi trong hồ sơ thực nghiệm. Các đường dẫn Google Colab trong notebook thuộc môi trường huấn luyện; không tự sửa notebook lịch sử chỉ để khớp bố cục ứng dụng.

Khi chạy thử cấu hình khác, lưu bản notebook/lượt chạy mới và ghi rõ thay đổi. Dữ liệu gốc đặt tại `data/raw/` khi đánh giá cục bộ; gói model dùng cho ứng dụng đặt tại `models/`. Chỉ khởi chạy notebook sau khi xem cấu hình `RUN_TREES`, `RUN_BERT`, tài nguyên và đầu ra của lần chạy.

Dữ liệu PhishVN có nguồn và giấy phép trong [data/raw/README.md](../data/raw/README.md). Mã đặc trưng tham chiếu giữ thông tin ghi công và giấy phép trong notebook/gói xuất.
