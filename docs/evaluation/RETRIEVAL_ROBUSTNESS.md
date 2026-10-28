# Thử nghiệm retrieval cho tiếng Việt không dấu

Ngày 28/10/2026. Đây là phát triển trên dev và kiểm tra hồi quy, không phải kết quả trên test độc lập mới. Ứng dụng vẫn dùng RAG v1; corpus, ngưỡng URL và các chỉ mục đã chốt được giữ nguyên.

## Phương pháp đã thực hiện

Từ 60 truy vấn dev v2, tạo thêm phiên bản bỏ dấu bằng Unicode NFD, loại dấu kết hợp và đổi `đ/Đ` thành `d/D`. Loại biến thể trùng câu sau chuẩn hóa, còn **117 truy vấn: 77 có nguồn, 40 không được nguồn hỗ trợ**. Các biến thể cùng câu phụ thuộc nhau, không phải 117 quan sát độc lập. Không thêm truy vấn hoặc nhãn vào corpus.

So sánh bốn phương pháp cố định:

- E5 gốc trên văn bản có sẵn.
- E5 hai phiên bản: lấy max cosine của cặp query gốc/đoạn gốc và query bỏ dấu/đoạn bỏ dấu. Không trộn chéo hai phiên bản.
- BM25 gốc.
- BM25 bỏ dấu cho cả query và đoạn.

Mỗi phương pháp chọn ngưỡng trên **cùng dev tăng cường**, với yêu cầu hit@3 ≥90%; tối đa trung bình hit@3 và tỷ lệ từ chối thiếu nguồn. Không hạ điều kiện khi mô hình không đạt. Phương pháp được chọn bằng dev trước khi tính các kết quả hồi quy: **BM25 bỏ dấu**.

## Kết quả

| Phương pháp | Dev hit@3 trước lọc | Dev hit@3 sau lọc | Từ chối dev thiếu nguồn | Hit hồi quy | Từ chối hồi quy thiếu nguồn |
|---|---:|---:|---:|---:|---:|
| E5 gốc | 63/77 (81,82%) | Không đạt điều kiện | — | — | — |
| E5 hai phiên bản | 63/77 (81,82%) | Không đạt điều kiện | — | — | — |
| BM25 gốc | 62/77 (80,52%) | Không đạt điều kiện | — | — | — |
| BM25 bỏ dấu | 71/77 (92,21%) | 71/77 (92,21%) | 15/40 | 24/24 | 8/16 |

Ngưỡng BM25 bỏ dấu: **9.250291**, top-3, k1=1.2, b=0.75. E5 dùng cùng model/revision và corpus 37 đoạn như v2, chỉ tạo thêm vector đoạn bỏ dấu trong thư mục thử nghiệm. Tối đa hai lượt encode query cho E5 hai phiên bản.

**24/24 không phải bằng chứng độ chính xác tổng quát 100%.** Đây là 24 câu có nguồn trong bộ hồi quy đã xem khi thiết kế cải tiến; còn 16 câu không được kho hỗ trợ, phương pháp vẫn trả tài liệu cho 8 câu. Đây cũng không phải F1 phân loại phishing. Relevance do trợ lý gán, chưa vét cạn nguồn cùng hỗ trợ và chưa có người thẩm định độc lập.

Kết quả gợi ý BM25 bỏ dấu là ứng viên hữu ích cho nhóm không dấu, nhưng chưa đủ cơ sở thay retriever ứng dụng. E5 hai phiên bản chưa cho thấy lợi ích trên dev này. Không so ngưỡng/kết quả mới với hiệu chỉnh trên dev gốc như cùng điều kiện.

## Những phần chưa được giải quyết

Truy xuất gần nghĩa hoặc khớp từ chưa bảo đảm nguồn hỗ trợ đúng dịch vụ, thời điểm hoặc kết luận cá nhân. Bỏ dấu còn làm nhiều từ trùng nhau. Chưa triển khai bộ kiểm tra ngữ nghĩa claim/nguồn hay bộ lọc thực thể/thời gian trong runtime; không dùng phép khớp tên thương hiệu để giả xác minh danh tính.

Trước khi triển khai cần rà relevance đầy đủ bằng người, bổ sung truy vấn thật, tạo test mới và đo khả năng từ chối kết luận không được nguồn hỗ trợ. Các câu đã xem hiện là regression, không được dùng để tuyên bố cải thiện độc lập.

## Tái lập và kiểm chứng

```bash
.venv/bin/python -m evaluation.retrieval_robustness \
  --out artifacts/rag-evaluation/accent_robustness_v2
```

Lệnh chỉ tính cục bộ, không gọi LLM. Chọn thư mục đầu ra mới. Thư mục chạy có protocol và hash trước khi chọn ngưỡng, dev tăng cường, vector đoạn bỏ dấu, calibration chốt trước hồi quy, predictions và summary. Lượt đã chạy ở `artifacts/rag-evaluation/accent_robustness_v1/`; `verification.json` kiểm chứng độc lập phép đếm, ngưỡng theo dev, lựa chọn phương pháp và hash. Kiểm tra số học không xác nhận nhãn ngữ nghĩa.
