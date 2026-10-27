# Dữ liệu

- [evaluation/](evaluation/): 60 thông điệp mô phỏng có nhãn để chẩn đoán ngữ cảnh; phương pháp ở [METHODS.md](../docs/evaluation/METHODS.md).
- [knowledge/](knowledge/README.md): 25 bản tóm lược có nguồn để chuẩn bị RAG; các snapshot có metadata và hash.
- [raw/](raw/README.md): nơi đặt archive bộ dữ liệu gốc trên máy cục bộ.

Mã xử lý dữ liệu nằm ở `evaluation/` và `scripts/`; dự đoán và chỉ số nằm ở `artifacts/evaluations/`. Không đưa nội dung người dùng hoặc mẫu test vào kho RAG.
