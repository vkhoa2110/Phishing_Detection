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
| Pilot compact v5/v6.1 | `compact_pilot_20261111`, `compact_pilot_20261111_continuation`; dùng `combined_report.md` trong continuation để giữ mọi lỗi ban đầu |
| Đối chứng dev và review tuần 4 | `week4_dev_20261111`: xem `README.md`, các ledger lỗi API và reference AI riêng; 120 reserve không suy luận |
| Verdict lõi và thinking | `focused_20261112`: pilot vận hành 32 request hoàn tất; lượt SMS dừng HTTP 429 ở 92/199, chưa công bố Accuracy/F1; RAG lọc hành vi chưa tốt hơn E5 |
| Hoàn tất verdict lõi và bổ sung nguồn | `recovery_20261113`: gộp đủ 199 request, giữ 429 cũ; audit phạm vi nhãn hành vi/toàn thông điệp; corpus 25 → 29, raw E5 Hit 5/9 → 7/9 trên dev AI |
| Kiểm chứng runtime và FR/NFR | `runtime_checks_20261113`: kết nối máy chủ, shared deadline, kiểm bản duyệt; 100 batch năm URL/model qua API in-process; audit hai cohort không trùng; không có điểm Accuracy mới |
| Kiểm tra lý do và trích dẫn | `claim_grounding_20261114`: replay 199 phản hồi; 45 phản hồi cần rà cơ chế, 48 tóm tắt được quy chiếu AI; không đổi kết luận/F1. Giữ cả lần QA đầu và lần sửa cue tiếng Việt; phiếu review chưa chấm |
| Trace RAG, parity và injection theo cặp | `evaluation_audit_20261116`: trace 36 ứng viên/300 relevance; model URL thật trên 16 ca×4 cấu hình còn 6 lượt lỗi hợp đồng thuộc 2 ca; 16 cặp injection/8 nhóm, ASR chưa chấm; không API hoặc F1 mới |
| Sửa che OTP và metadata URL | `privacy_metadata_fix_20261116`: cùng bộ 16 ca×4 cấu hình đạt 64/64 kiểm hợp đồng; 80 SMS dev có metadata 30→35; giữ score/model và replay lịch sử bằng snapshot; không API hoặc F1 mới |
| Miền trần và ranh giới trích URL | `url_intake_audit_20261117`: đối chiếu intake 2.1/2.2 trên ca tự soạn và đúng 80 SMS dev; tham chiếu IANA offline, chuỗi mơ hồ không chấm model; không nhãn phishing, API hoặc F1 mới |
| Đối chứng điểm URL và verifier | `url_score_control_20261118`: đúng 80 SMS dev, metadata không cấp/thật/hoán đổi; kiểm lại riêng các cảnh báo bằng text; xem trạng thái và giới hạn trong `README.md`, không tự tích hợp app |
| Kế hoạch SMS mới | `fresh_message_ablation_plan_v1` |

[Kết quả và giới hạn](../docs/results.md) tập hợp các số quan trọng; [phương pháp](../docs/evaluation.md) nêu mẫu số, nhãn và đối chứng. Các thư mục trên là đường dẫn cục bộ, không bảo đảm có khi clone Git. Tài liệu chi tiết nguyên trạng trước refactor có trong [mốc 479c966](https://github.com/vkhoa2110/Phishing_Detection/tree/479c96612ca79d3e1de2d37df22d82ce19e09f23/docs).

## Bảo toàn bằng chứng

- Không đổi manifest/hash, raw response hoặc checkpoint của run đã chốt.
- Mỗi thực nghiệm mới dùng `--out` mới. Cần mã gốc để kiểm hash thì dùng [worktree riêng](../docs/development.md#tai-lap-lich-su).
- Không xóa thư mục chỉ vì tên có `smoke`, `pilot`, `prepare`: chúng có thể là đầu vào đang được protocol khác tham chiếu.
- `maintenance/` chứa snapshot trước/sau refactor cục bộ; không phải kết quả đánh giá chất lượng mới.
- `make clean` dọn cache, giữ các đầu ra này. Báo cáo học thuật tiếp tục ở `docs/reports/`, không đưa lên Git.

Ảnh UI hiện hành nằm trong `ui/consumer/`; kiểm lại bằng `scripts/evaluation/check_consumer_ui.py` khi app đang mở. Ảnh và test phần mềm không thay thế đánh giá phát hiện lừa đảo.
