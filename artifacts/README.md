# Kết quả thực nghiệm

Các snapshot đã chốt:

| Thư mục | Phạm vi |
|---|---|
| [evaluations/phishvn_official_v1/](evaluations/phishvn_official_v1/) | Model trên 8.941 URL test; hai nhánh LLM trên cùng 100 URL |
| [evaluations/url_model_ablation_v1/](evaluations/url_model_ablation_v1/) | Chẩn đoán 60 thông điệp mô phỏng, hai nhánh LLM |
| [evaluations/pilot_1536_tokens/](evaluations/pilot_1536_tokens/) | Lượt pilot chưa hoàn tất; không gộp với kết quả chính |

Mỗi snapshot giữ nguyên CSV/JSONL, manifest, checkpoint, chỉ số và hình đã tạo. Không chỉnh tên đường dẫn hay hash bên trong file lịch sử. Xem [bảng chuyển đổi](../docs/PROJECT_STRUCTURE.md#đối-chiếu-đường-dẫn-cũmới) khi đối chiếu đường dẫn trước ngày tổ chức lại.

Kết quả chạy mới và `report-builds/` bị Git bỏ qua mặc định. Chọn thư mục `--out` mới cho cấu hình mới; không ghi đè snapshot đã chốt. Báo cáo Word/PDF được giữ cục bộ và không theo dõi trên Git.
