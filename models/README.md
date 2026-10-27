# Gói mô hình cục bộ

Giải nén model đã xuất từ notebook vào:

```text
models/inference_XGBoost_d6_s42/
├── model.ubj
├── config.json
├── predict_url.py
├── url_features.py
└── url_preprocessing.py
```

`MODEL_DIR` mặc định là `models/inference_XGBoost_d6_s42`. Đường dẫn tương đối được tính từ thư mục gốc repository; có thể dùng đường dẫn tuyệt đối trong `.env`.

Ứng dụng đọc run ID, thứ tự đặc trưng và ngưỡng từ gói, suy luận trên CPU. Chỉ nạp gói đã tin cậy vì các tệp Python trong gói được import. Trọng số, mã xuất đi kèm và checkpoint cục bộ không được đưa vào Git; notebook huấn luyện và các bằng chứng thí nghiệm được quản lý riêng.
