# Tài liệu dự án

Bắt đầu với các tài liệu hiện hành dưới đây. Các nghiên cứu trước được giữ để đối chiếu phương pháp và tái lập kết quả.

## Sử dụng và phát triển

| Nội dung | Tài liệu |
|---|---|
| Cài đặt, cấu hình, API và cách dùng | [USAGE.md](guides/USAGE.md) |
| Chuẩn bị embedding, chỉ mục và nguồn RAG | [RAG.md](guides/RAG.md) |
| Kiến trúc hiện hành, kiểm chứng v4 và giới hạn | [QUALITY_V4.md](architecture/QUALITY_V4.md) |
| Profile v5 thử nghiệm: URL ký tự, phân biệt injection và RAG sau phân loại | [QUALITY_V5_TRIAL.md](architecture/QUALITY_V5_TRIAL.md) |
| Candidate v6: URL che dấu, cấu trúc hội thoại và kiểm tra RAG có kiểm soát | [QUALITY_V6_TRIAL.md](architecture/QUALITY_V6_TRIAL.md) |
| Nghiên cứu tiếp: đối chứng URL, RAG chọn bằng chứng, dữ liệu tương lai | [RESEARCH_NEXT_V1.md](architecture/RESEARCH_NEXT_V1.md) |
| Lượt mới: chuyển nguồn, 229 ứng viên/tham chiếu và trang review | [SOURCE_AND_DATA_V2.md](architecture/SOURCE_AND_DATA_V2.md) |
| Cấu trúc thư mục và dọn cache | [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) |
| Lệnh thu thập, kiểm tra và đánh giá | [scripts/README.md](../scripts/README.md) |
| Kết quả và ảnh kiểm tra giao diện | [artifacts/README.md](../artifacts/README.md) |

## Đánh giá và dữ liệu

| Nội dung | Tài liệu |
|---|---|
| Phương pháp và lệnh đánh giá | [METHODS.md](evaluation/METHODS.md) |
| Tái lập baseline PhishVN, kiểm tra bronze/nguồn và độ nhạy ngưỡng | [URL_SOURCE_AUDIT_V1.md](evaluation/URL_SOURCE_AUDIT_V1.md) |
| Báo nhầm theo ngưỡng, cross-fit theo miền và kế hoạch validation mới | [URL_CALIBRATION_V1.md](evaluation/URL_CALIBRATION_V1.md) |
| Thử TF-IDF ký tự + LR so với XGBoost trên cùng dữ liệu | [URL_CHAR_BASELINE_V1.md](evaluation/URL_CHAR_BASELINE_V1.md) |
| Đối chứng bỏ marker: kết quả âm và dấu vết nguồn | [URL_REPRESENTATION_V2.md](evaluation/URL_REPRESENTATION_V2.md) |
| Nhận diện nguồn và bỏ nguồn ngoài train | [URL_SOURCE_SHIFT_V2.md](evaluation/URL_SOURCE_SHIFT_V2.md) |
| Đối chứng bỏ www/cân bằng nguồn, ba model giữ nguyên kết quả bất lợi | [URL_SOURCE_ROBUST_V3.md](evaluation/URL_SOURCE_ROBUST_V3.md) |
| Hiệu chỉnh score theo thành phần calibration | [URL_PROBABILITY_AUDIT_V2.md](evaluation/URL_PROBABILITY_AUDIT_V2.md) |
| 29 tuyến nguồn chính thức và phiếu review | [OFFICIAL_URL_REFERENCES_V1.md](evaluation/OFFICIAL_URL_REFERENCES_V1.md) |
| Cảnh báo trên 29 tuyến chưa có nhãn rủi ro | [OFFICIAL_URL_DIAGNOSTIC_V1.md](evaluation/OFFICIAL_URL_DIAGNOSTIC_V1.md) |
| 200 ứng viên OpenPhish mới thu, nhãn nguồn sơ bộ | [OPENPHISH_CANDIDATES_V1.md](evaluation/OPENPHISH_CANDIDATES_V1.md) |
| Năm model trên toàn bộ 200 ứng viên nguồn dương | [OPENPHISH_MODEL_DIAGNOSTIC_V1.md](evaluation/OPENPHISH_MODEL_DIAGNOSTIC_V1.md) |
| Khóa nguồn, nhãn và thời gian trước bộ URL mới | [PROSPECTIVE_URL_V1.md](evaluation/PROSPECTIVE_URL_V1.md) |
| So sánh LLM / URL / RAG trên dev | [COMPONENTS_DEV_V1.md](evaluation/COMPONENTS_DEV_V1.md) |
| Pilot v6: RAG, lịch sử hội thoại và bộ SMS bổ sung | [V6_PILOT_V1.md](evaluation/V6_PILOT_V1.md) |
| Bộ đánh giá cố định và giới hạn nhãn AI | [OBJECTIVE_V1.md](evaluation/OBJECTIVE_V1.md) |
| Kết quả 364 lượt dev SMS/ngữ cảnh | [OBJECTIVE_DEV_RESULTS_V1.md](evaluation/OBJECTIVE_DEV_RESULTS_V1.md) |
| 160 URL nguồn thực, 200 ca ngữ cảnh | [URL_CONTEXT_V1.md](evaluation/URL_CONTEXT_V1.md) |
| Kết quả 720 lượt dev URL/ngữ cảnh | [URL_CONTEXT_DEV_RESULTS_V1.md](evaluation/URL_CONTEXT_DEV_RESULTS_V1.md) |
| Thử nghiệm kho uy tín URL | [REPUTATION_V1.md](evaluation/REPUTATION_V1.md) |
| Kho RAG v2 và so sánh BM25/E5/Hybrid | [RAG_RETRIEVAL_V2.md](evaluation/RAG_RETRIEVAL_V2.md) |
| Truy xuất tiếng Việt không dấu | [RETRIEVAL_ROBUSTNESS.md](evaluation/RETRIEVAL_ROBUSTNESS.md) |
| Phiếu gán nhãn 200 SMS | [vn_sms_v2/](../data/annotation/vn_sms_v2/README.md) |
| Nhãn AI sơ bộ và cách rà soát | [AI_PRELABELS.md](evaluation/AI_PRELABELS.md) |
| Nguồn và snapshot tài liệu RAG | [data/knowledge/](../data/knowledge/README.md) |

## Các mốc thiết kế và thực nghiệm trước

| Phạm vi | Tài liệu |
|---|---|
| Baseline ứng dụng ban đầu | [BASELINE.md](architecture/BASELINE.md) |
| Thiết kế v3 và kiểm tra bằng chứng | [QUALITY_V3.md](architecture/QUALITY_V3.md) |
| Hai phạm vi kết luận và đánh giá v2 | [CONTEXT_V2.md](evaluation/CONTEXT_V2.md) |
| Đề xuất mở rộng nguồn RAG | [RAG_V2_PROPOSAL.md](architecture/RAG_V2_PROPOSAL.md) |
| URL trên PhishVN | [PHISHVN.md](evaluation/PHISHVN.md) |
| Chẩn đoán thông điệp mô phỏng | [SYNTHETIC.md](evaluation/SYNTHETIC.md) |
| So sánh các thành phần và truy xuất v1 | [RAG_ABLATION.md](evaluation/RAG_ABLATION.md) |
| Biên bản kiểm tra ngày 24/10/2026 | [VERIFICATION.md](evaluation/VERIFICATION.md) |

Các tài liệu ghi rõ thời điểm và phạm vi. Kết quả lịch sử không tự mô tả chất lượng của phiên bản ứng dụng hiện hành. Báo cáo học thuật trong `reports/` chỉ giữ trên máy cục bộ.
