# Kết quả thực nghiệm

Các snapshot đã chốt:

| Thư mục | Phạm vi |
|---|---|
| [evaluations/phishvn_official_v1/](evaluations/phishvn_official_v1/) | Model trên 8.941 URL test; hai nhánh LLM trên cùng 100 URL |
| [evaluations/url_model_ablation_v1/](evaluations/url_model_ablation_v1/) | Chẩn đoán 60 thông điệp mô phỏng, hai nhánh LLM |
| [evaluations/pilot_1536_tokens/](evaluations/pilot_1536_tokens/) | Lượt pilot chưa hoàn tất; không gộp với kết quả chính |

Mỗi snapshot giữ nguyên CSV/JSONL, manifest, checkpoint, chỉ số và hình đã tạo. Không chỉnh tên đường dẫn hay hash bên trong file lịch sử. Xem [bảng chuyển đổi](../docs/PROJECT_STRUCTURE.md#đối-chiếu-đường-dẫn-cũmới) khi đối chiếu đường dẫn trước ngày tổ chức lại.

Kết quả chạy mới và `report-builds/` bị Git bỏ qua mặc định. Chọn thư mục `--out` mới cho cấu hình mới; không ghi đè snapshot đã chốt. Báo cáo Word/PDF được giữ cục bộ và không theo dõi trên Git.

Các lượt RAG cục bộ ngày 27/10/2026 (bị Git bỏ qua):

| Thư mục | Phạm vi |
|---|---|
| `evaluations/rag_ablation_v1/` | 400 lượt API, 100 tin nhắn mô phỏng, bốn arm và fusion; đã kiểm chứng, có PNG/SVG |
| `evaluations/rag_budget_diagnostic_v1/` | Bốn lượt chẩn đoán ca hết token với ngân sách lớn hơn; không gộp vào số đo chính |
| `rag-evaluation/retrieval_comparison_v1/` | BM25, E5 và Hybrid RRF; ngưỡng riêng chọn trên dev, không thay cấu hình ứng dụng |

[Phương pháp, kết quả và giới hạn](../docs/evaluation/RAG_ABLATION.md).

Các lượt cục bộ bổ sung ngày 28/10/2026, không theo dõi trên Git:

| Thư mục | Phạm vi |
|---|---|
| `rag-evaluation/retrieval_comparison_v2_r1/` | 37 nguồn, dev 60/test 40, so sánh BM25/E5/Hybrid |
| `rag-evaluation/accent_robustness_v1/` | Dev tăng cường 117 truy vấn; hồi quy 40 câu đã xem, không phải test độc lập |
| `annotations/vn_sms_ai_complete_v1/` | Gói nhãn AI sơ bộ 200 SMS, CSV, HTML để rà soát, không phải gold |
| `annotations/vn_sms_ai_v1/` và `annotations/vn_sms_ai_repair_v*/` | Checkpoint lượt đầu và các lượt bổ sung mẫu thiếu phản hồi hợp lệ |

[Nhãn AI và giới hạn](../docs/evaluation/AI_PRELABELS.md) · [Retrieval không dấu](../docs/evaluation/RETRIEVAL_ROBUSTNESS.md). Toàn bộ nhãn AI và kết quả API mới nằm ở `artifacts/`, không ghi vào hai phiếu gán nhãn mù hoặc corpus RAG.
