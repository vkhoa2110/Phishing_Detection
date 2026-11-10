# Đầu ra thực nghiệm

`evaluations/` chứa các run có protocol/manifest, dự đoán và chỉ số; `rag/` chứa index; `annotations/` chứa nhãn AI; `ui/` chứa ảnh kiểm giao diện. Tất cả đầu ra mới được giữ cục bộ. Ba snapshot lịch sử được version là `phishvn_official_v1`, `url_model_ablation_v1` và `pilot_1536_tokens`.

## Mục lục theo chủ đề

| Nhóm | Thư mục trong `evaluations/` |
|---|---|
| Baseline/nguồn/ngưỡng URL | `url_source_audit_v1`, `url_calibration_v1`, `url_char_baseline_v1` |
| Biểu diễn và source shift | `url_representation_v2`, `url_source_shift_v2`, `url_source_robust_v3`, `url_probability_audit_v2` |
| Thu mẫu URL mới | `official_url_reference_v1`, `official_url_diagnostic_v1`, `openphish_candidates_v1`, `openphish_model_diagnostic_v1` |
| Chuẩn bị test tương lai | `prospective_url_inputs_v*`, `prospective_url_registration_v*`, `prospective_url_pack_v*` |
| Bốn thành phần LLM/URL/RAG | `components_dev_live_v1`, `components_dev_results_v1` |
| URL trong ngữ cảnh | `url_context_dev_live_v1`, `url_context_dev_results_v1`, `reputation_dev_v1` |
| Prompt v4/v5 | `quality_v4_pilot_v1`, `quality_v4_pilot_results_v1`, `improvement_pilot_v1` |
| RAG chọn bằng chứng | `rag_evidence_contract_v3`, `rag_evidence_pilot_v1` |
| Hội thoại/RAG v6 | `v6_hardening_20261109`, `v6_pilot_live_20261109` |
| Hợp đồng v6.1 | `v61_contract_fix_v1` |
| Kế hoạch SMS mới | `fresh_message_ablation_plan_v1` |

[Kết quả và giới hạn](../docs/results.md) tập hợp các số quan trọng; [phương pháp](../docs/evaluation.md) nêu mẫu số, nhãn và đối chứng. Các thư mục trên là đường dẫn cục bộ, không bảo đảm có khi clone Git. Tài liệu chi tiết nguyên trạng trước refactor có trong [mốc 479c966](https://github.com/vkhoa2110/Phishing_Detection/tree/479c96612ca79d3e1de2d37df22d82ce19e09f23/docs).

## Bảo toàn bằng chứng

- Không đổi manifest/hash, raw response hoặc checkpoint của run đã chốt.
- Mỗi thực nghiệm mới dùng `--out` mới. Cần mã gốc để kiểm hash thì dùng [worktree riêng](../docs/development.md#tai-lap-lich-su).
- Không xóa thư mục chỉ vì tên có `smoke`, `pilot`, `prepare`: chúng có thể là đầu vào đang được protocol khác tham chiếu.
- `maintenance/` chứa snapshot trước/sau refactor cục bộ; không phải kết quả đánh giá chất lượng mới.
- `make clean` dọn cache, giữ các đầu ra này. Báo cáo học thuật tiếp tục ở `docs/reports/`, không đưa lên Git.

Ảnh UI hiện hành nằm trong `ui/consumer/`; kiểm lại bằng `scripts/evaluation/check_consumer_ui.py` khi app đang mở. Ảnh và test phần mềm không thay thế đánh giá phát hiện lừa đảo.
