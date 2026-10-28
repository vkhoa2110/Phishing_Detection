# Dữ liệu

- [evaluation/](evaluation/): bộ 60 thông điệp mô phỏng v1; bộ so sánh RAG 100 mẫu (60 mẫu cũ có URL, 40 mẫu mới không URL); truy vấn truy xuất riêng (40 dev, 12 test). Xem [phương pháp baseline](../docs/evaluation/METHODS.md) và [so sánh RAG](../docs/evaluation/RAG_ABLATION.md).
- [knowledge/](knowledge/README.md): 25 bản tóm lược có nguồn để chuẩn bị RAG; các snapshot có metadata và hash.
- [raw/](raw/README.md): nơi đặt archive bộ dữ liệu gốc trên máy cục bộ.
- [annotation/vn_sms_v2/](annotation/vn_sms_v2/README.md): 200 SMS từ nguồn ngoài, 80 dev/120 test, đang chờ hai người gán nhãn; nhãn spam nguồn không phải phishing gold.

Mã xử lý dữ liệu nằm ở `evaluation/` và `scripts/`; dự đoán và chỉ số nằm ở `artifacts/evaluations/`. Không đưa nội dung người dùng hoặc mẫu test vào kho RAG.

`rag_retrieval_*_v1.jsonl` là truy vấn và ID nguồn liên quan do trợ lý soạn, chưa được người thứ hai thẩm định. Nhãn ở đây là relevance tài liệu, không phải phishing/benign. Test không dùng để chọn ngưỡng; chủ đề nguồn vẫn trùng với dev nên đây chỉ là kiểm tra bước đầu.
