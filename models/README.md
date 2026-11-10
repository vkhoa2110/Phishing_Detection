# Gói suy luận cục bộ

| Thư mục | Dùng cho |
|---|---|
| `inference_XGBoost_d6_s42/` | Profile stable v4; 21 đặc trưng URL |
| `url_character/` | Candidate v5/v6.1; TF-IDF ký tự + Logistic Regression |
| `embeddings/multilingual-e5-small/` | Encoder RAG E5-small |

## XGBoost

Giải nén export vào `models/inference_XGBoost_d6_s42/` với `model.ubj`, `config.json`, `predict_url.py`, `url_features.py`, `url_preprocessing.py`. `MODEL_DIR` có thể là đường dẫn tuyệt đối hoặc tương đối với root. App lấy run ID, feature và ngưỡng từ gói thật; không giả lập dự đoán khi thiếu gói.

Chỉ nạp gói đã tin cậy vì mã Python trong export được import. Trọng số và mã xuất đi kèm không đưa lên Git; notebook huấn luyện được giữ riêng.

## URL ký tự

`models/url_character/` gồm `export.json`, `vocabulary.json`, `weights.npz`. Bộ nạp kiểm hash source, chuẩn hóa, trọng số và phiên bản NumPy/SciPy/scikit-learn; không dùng pickle. Export lịch sử ở `artifacts/evaluations/url_char_baseline_v1/deployment/` giữ nguyên để làm bằng chứng.

Sau refactor dùng gói đã chuyển có provenance và kiểm score tương đương; [hướng dẫn chuyển gói](../docs/development.md). Không thay source hash thủ công để bỏ qua kiểm chứng. Gói candidate không thay XGBoost mặc định.

## Embedding

[Cài E5 và dựng index](../docs/guides/RAG.md). Model revision được khóa trong metadata; runtime chỉ đọc file cục bộ. Model và index không được đưa vào Git.
