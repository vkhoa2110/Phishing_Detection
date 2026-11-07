# Kết quả và đầu ra cục bộ

`evaluations/` chứa bằng chứng thực nghiệm; `ui/` chứa ảnh và biên bản kiểm tra giao diện. Các đầu ra này phục vụ hai mục đích khác nhau, không dùng ảnh UI làm số đo chất lượng mô hình.

## Kết quả hiện hành

| Thư mục | Phạm vi và tài liệu |
|---|---|
| `evaluations/url_source_audit_v1/` | 39 lượt huấn luyện; [baseline PhishVN, ảnh hưởng bronze/nguồn và calibration](../docs/evaluation/URL_SOURCE_AUDIT_V1.md) |
| `evaluations/url_calibration_v1/` | 7 chính sách trên score URL hiện hành; [cross-fit ngưỡng theo miền và đánh đổi FPR/Recall](../docs/evaluation/URL_CALIBRATION_V1.md) |
| `evaluations/url_char_baseline_v1/` | [TF-IDF ký tự + LR](../docs/evaluation/URL_CHAR_BASELINE_V1.md), điểm từng URL, biểu đồ và export candidate JSON/NPZ |
| `evaluations/improvement_pilot_v1/` | Pilot v4/v5 và RAG trước/sau phân loại; [phạm vi và trạng thái](../docs/architecture/QUALITY_V5_TRIAL.md) |
| `evaluations/url_representation_v2/` | [Đối chứng bỏ marker](../docs/evaluation/URL_REPRESENTATION_V2.md), kết quả âm, không thay model |
| `evaluations/rag_evidence_contract_v3/` và `rag_evidence_pilot_v1/` | Audit offline và 32 yêu cầu đối chứng mới; [RAG chọn đoạn trích và giới hạn](../docs/architecture/RESEARCH_NEXT_V1.md) |
| `evaluations/research_next_v1/` | Khoảng bất định và kịch bản tỷ lệ lớp, tính từ số đếm đã lưu |
| `evaluations/prospective_url_inputs_v1/`, `prospective_url_registration_v1/`, `prospective_url_pack_v1/` | [Đăng ký trước và khóa dữ liệu](../docs/evaluation/PROSPECTIVE_URL_V1.md); 0 mẫu mới, chưa có số đo test |
| `evaluations/url_source_shift_v2/`, `url_source_robust_v3/`, `url_probability_audit_v2/` | [Chuyển nguồn, ba model đối chứng và calibration](../docs/architecture/SOURCE_AND_DATA_V2.md), không thay app |
| `evaluations/official_url_reference_v1/` và `official_url_diagnostic_v1/` | Snapshot tham chiếu, [trang review cục bộ](evaluations/official_url_reference_v1/review/index.html) và score 29 URL, chưa có nhãn rủi ro |
| `evaluations/openphish_candidates_v1/` và `openphish_model_diagnostic_v1/` | Snapshot nguồn hạn chế phân phối và 200 ứng viên sơ bộ; mọi URL/raw/CSV giữ cục bộ, không đưa lên Git |
| `evaluations/prospective_url_inputs_v2/`, `prospective_url_registration_v2/`, `prospective_url_pack_v2/` | Đăng ký hiện hành bổ sung 236 dòng exposure mới, giữ v1 nguyên; pack vẫn chưa sẵn sàng |
| `evaluations/quality_v4_pilot_v1/` | 240 lần thử v3/v4; [chất lượng v4 và giới hạn](../docs/architecture/QUALITY_V4.md) |
| `evaluations/quality_v4_pilot_results_v1/` | Báo cáo, kiểm chứng và biểu đồ của pilot v4 |
| `evaluations/quality_v4_url_policy_v2/` | Chính sách URL thận trọng trên điểm dev/validation đã lưu |
| `evaluations/components_dev_live_v1/` và `components_dev_results_v1/` | Bốn cấu hình LLM/URL/RAG; [phương pháp và kết quả](../docs/evaluation/COMPONENTS_DEV_V1.md) |
| `evaluations/url_context_dev_live_v1/` và `url_context_dev_results_v1/` | 720 lượt dev URL/ngữ cảnh; [điều kiện và giới hạn](../docs/evaluation/URL_CONTEXT_DEV_RESULTS_V1.md) |
| `evaluations/reputation_dev_v1/` | [Thử nghiệm kho uy tín URL](../docs/evaluation/REPUTATION_V1.md) |

Các nhãn SMS trong các lượt này là nhãn AI sơ bộ; ngữ cảnh đối chiếu có mẫu tự soạn. Đọc giới hạn trong tài liệu trước khi sử dụng số đo.

## Kiểm tra giao diện

Ảnh mới và biên bản ở **`ui/consumer/`**:

- [Desktop](ui/consumer/desktop-initial.png), [mobile](ui/consumer/mobile-initial.png).
- [Kết quả trên desktop](ui/consumer/desktop-result-panel.png), [mobile](ui/consumer/mobile-result-panel.png).
- [Kiểm tra bốn cỡ màn hình](ui/consumer/verification.json).
- `ui/baseline-v4/verification.json`: biên bản UI trước lần thiết kế lại, giữ để đối chiếu với tài liệu v4.

Chạy lại khi ứng dụng đang mở bằng `python scripts/evaluation/check_consumer_ui.py`. Mặc định cập nhật cùng thư mục UI; dùng `--out` nếu cần lưu một lần chạy riêng. Script phát lại phản hồi AI đã ghi và chạy model URL cục bộ, không gọi provider.

## Các mốc trước và dữ liệu nghiên cứu

| Nhóm | Thư mục / tài liệu |
|---|---|
| PhishVN, 8.941 URL test và hai nhánh LLM trên cùng 100 URL | [evaluations/phishvn_official_v1/](evaluations/phishvn_official_v1/), [PHISHVN.md](../docs/evaluation/PHISHVN.md) |
| Chẩn đoán 60 thông điệp mô phỏng | [evaluations/url_model_ablation_v1/](evaluations/url_model_ablation_v1/), [SYNTHETIC.md](../docs/evaluation/SYNTHETIC.md) |
| Pilot ngân sách 1.536 token, chưa hoàn tất | [evaluations/pilot_1536_tokens/](evaluations/pilot_1536_tokens/) |
| So sánh bốn cấu hình và chẩn đoán token v1 | `evaluations/rag_ablation_v1/`, `rag_budget_diagnostic_v1/`; [RAG_ABLATION.md](../docs/evaluation/RAG_ABLATION.md) |
| Các lượt objective dev và ngữ cảnh v2 | `evaluations/objective_*`, `context_regression_v2/`; [kết quả objective](../docs/evaluation/OBJECTIVE_DEV_RESULTS_V1.md) |
| Đánh giá truy xuất | `rag-evaluation/`; [RAG v2](../docs/evaluation/RAG_RETRIEVAL_V2.md), [bỏ dấu](../docs/evaluation/RETRIEVAL_ROBUSTNESS.md) |
| Checkpoint, các lượt bổ sung và gói nhãn AI đã ghép | `annotations/`; [AI_PRELABELS.md](../docs/evaluation/AI_PRELABELS.md) |
| Chỉ mục embedding dùng trong ứng dụng | `rag/`; [cài đặt RAG](../docs/guides/RAG.md) |

Giữ nguyên manifest, checkpoint, raw response và hash trong snapshot đã chốt. `evaluations/layout_smoke/selected_ids.csv` vẫn được protocol của bộ URL/ngữ cảnh tham chiếu; tên “smoke” không có nghĩa là có thể xóa cả thư mục. Các lần chuẩn bị, bổ sung nhãn và snapshot nguồn cũng có thể là đầu vào của lần chạy sau.

## Quy ước lưu trữ

- Lần đánh giá mô hình mới dùng `--out` mới; không ghi đè kết quả đã chốt.
- UI chỉ lưu ảnh hiện hành và biên bản cần thiết, tránh giữ đồng thời `before`, `preview`, `retry` và nhiều bản chụp cùng trạng thái.
- `make clean` chỉ dọn cache, không xóa các thư mục ở đây.
- Kết quả chạy mới, `ui/`, chỉ mục và bản dựng báo cáo bị Git bỏ qua. Ba snapshot lịch sử được version là PhishVN, URL ablation và pilot 1.536 token.
- Báo cáo học thuật trong `docs/reports/` được giữ cục bộ, không đưa lên Git.
