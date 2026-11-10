# Dữ liệu

| Thư mục | Nội dung |
|---|---|
| `evaluation/` | Thông điệp mô phỏng, tập hồi quy và truy vấn retrieval phiên bản hóa |
| [knowledge/](knowledge/README.md) | Corpus v1 25 nguồn, v2 37 nguồn và metadata/provenance |
| [raw/](raw/README.md) | Archive dữ liệu và snapshot bên thứ ba cài cục bộ |
| [annotation/vn_sms_v2/](annotation/vn_sms_v2/README.md) | 200 SMS nguồn ngoài, phiếu review |
| [annotation/objective_v1/](annotation/objective_v1/README.md) | Gói SMS/challenge/relevance có protocol và hash |
| [annotation/url_context_v1/](annotation/url_context_v1/README.md) | URL nguồn thực và ngữ cảnh đánh giá riêng |
| [annotation/fresh_messages_v1/](annotation/fresh_messages_v1/README.md) | SMS review bổ sung và stress do trợ lý soạn |
| [annotation/official_url_reference_v1/](annotation/official_url_reference_v1/README.md) | Tham chiếu tuyến chính thức, không tự là nhãn benign |

Mã chuẩn bị/nhãn nằm ở `evaluation/data`, `evaluation/rag` và `scripts/data`; output nằm ở `artifacts`. [Phương pháp đánh giá](../docs/evaluation.md), [kết quả và giới hạn](../docs/results.md).

Không đưa input người dùng, nhãn hoặc đáp án test vào corpus RAG. Nhãn spam nguồn chỉ dùng lấy mẫu, không phải phishing gold. Nhãn AI phải để riêng với nhãn người; dữ liệu tự soạn và nguồn ngoài không gộp thành một điểm chung.

README nằm trong snapshot đã khóa hash được giữ nguyên, có thể mô tả module/đường dẫn cũ. Đọc chúng cùng [source lịch sử](../docs/development.md#tai-lap-lich-su); hướng dẫn chạy hiện hành nằm trong `docs`. Không sửa README/manifest của snapshot chỉ để cập nhật đường dẫn.
