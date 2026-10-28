# Kho RAG v2 — thực nghiệm ngày 28/10/2026

37 tài liệu từ 19 đơn vị: giữ nguyên 25 tài liệu v1, thêm 12 nguồn cho 8 nhóm kịch bản. Có 20 cảnh báo, 11 quy trình hợp lệ, 2 xử lý sự cố và 4 hướng dẫn kết hợp. Đây là tóm lược tiếng Việt do trợ lý biên tập và rà soát, chưa được chuyên gia độc lập thẩm định. Không phân phối toàn bộ bài gốc.

- [documents.jsonl](documents.jsonl): nội dung và provenance, bao gồm hash nguồn tải và bản tóm lược.
- [sources.csv](sources.csv): tiêu đề, đơn vị, vai trò, ngày và URL gốc.
- [manifest.json](manifest.json), [validation.json](validation.json): hash, snapshot cha và kiểm tra kỹ thuật.
- [source_review.json](source_review.json): phạm vi rà soát của trợ lý cho nguồn mới.
- [ingestion_map.json](ingestion_map.json): 12 ID ứng viên sang `VN-RAG-101–112`; dải ID cũ được giữ nguyên.
- [Snapshot tải 12 nguồn](../collections/v2_additions_20261028/): kết quả HTTPS/robots, hash và phiên bản bộ thu thập.

Nguồn mới bao gồm Zalo QR, device code Microsoft (cả cảnh báo lẫn luồng hợp lệ), email doanh nghiệp/BEC, vé máy bay/giữ chỗ, điện lực (cảnh báo cũ và thử nghiệm app năm 2026), cô lập trực tuyến, tống tiền bằng ảnh ghép và giả hỗ trợ hoàn tiền.

22 nguồn xác minh ngày công bố, 15 nguồn chưa xác minh được ngày. `valid_from` chỉ có khi được nguồn nêu; `retrieved_at` là thời gian tải. Các nguồn v1 không được tự cập nhật nội dung/ngày khi ghép. Không dùng cảnh báo cũ làm quy định hiện hành hay kết luận tên miền, người gọi, tài khoản ngân hàng hoặc giao dịch cá nhân là thật/giả.

Đã dựng 37 đoạn E5-small và calibration riêng ở `artifacts/rag/e5-small-v2-r1/`. Trường `indexed: false` trong biên bản validator chỉ nói validator không tạo index; xem manifest index và báo cáo thực nghiệm để biết trạng thái dựng sau đó. **Ứng dụng vẫn mặc định v1**, v2 sẵn để chạy ở phiên thử nghiệm riêng.

[Phương pháp, kết quả 100 truy vấn và lệnh chạy lại](../../../docs/evaluation/RAG_RETRIEVAL_V2.md). Các truy vấn là stress test do trợ lý viết, không phải gold phishing. Không có SMS người dùng, nhãn hoặc đáp án test trong chỉ mục.
