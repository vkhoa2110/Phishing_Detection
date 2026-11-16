# Công cụ dòng lệnh

Chạy từ root bằng `.venv/bin/python`. Mã thí nghiệm nằm trong package `evaluation`; script ở đây phục vụ tác vụ thu thập, kiểm chứng, xuất biểu đồ và bảo trì. Xem `--help` của từng lệnh để biết tham số.

## Các entry point chính

| Nhóm | Lệnh / module | Mục đích |
|---|---|---|
| Bảo trì | `scripts/maintenance/clean.py [--apply]` | Dọn cache, mặc định xem trước |
| Bảo trì | `scripts/maintenance/repackage_character.py --help` | Chuyển gói URL ký tự sau refactor với kiểm score chính xác |
| Dữ liệu | `scripts/data/prepare_vn_sms.py --out NEW_DIR` | Lấy mẫu SMS nguồn cố định, tạo phiếu |
| Dữ liệu | `python -m evaluation.data.fresh_messages --out NEW_DIR` | Gói review mới và stress tự soạn |
| Nhãn | `python -m evaluation.data.review --help` | Kiểm phiếu, phân xử, khóa nhãn |
| URL tương lai | `python -m evaluation.data.prospective_urls --help` | Đăng ký trước, kiểm evidence và domain/campaign |
| RAG | `scripts/rag/prepare_index.py --download` | Tải E5 revision cố định và tạo chỉ mục |
| Corpus | `scripts/rag/collect_rag_sources.py --out NEW_DIR` | Thu snapshot nguồn đã duyệt |
| Corpus | `scripts/rag/assemble_corpus.py --help` | Ghép snapshot, giữ provenance |
| Corpus | `scripts/rag/validate_rag_corpus.py --help` | Kiểm hash và metadata |
| Retrieval | `python -m evaluation.rag.metrics --help` | Chọn ngưỡng dev, chấm truy vấn test |
| RAG có kiểm soát | `python -m evaluation.rag.controlled --help` | Chuẩn bị/chấm can thiệp nguồn và injection |
| Claim | `python -m evaluation.rag.summary_audit --help` | Phiếu kiểm raw → tóm lược → claim |
| Hội thoại | `python -m evaluation.messages.conversation --help` | Đối chứng theo prefix và lịch sử |
| Pilot | `python -m evaluation.messages.interaction_pilot --help` | Khóa và chạy request một lần, kiểm journal |
| Pilot compact | `python -m evaluation.messages.compact_pilot --help` | Đối chiếu v5/v6.1, 24 request trên 12 input cũ; chỉ đo lỗi/usage, không Accuracy/F1 |
| Tiếp tục khi lỗi mạng | `scripts/evaluation/continue_compact_pilot.py --help` | Khóa phần chưa gửi, giữ lỗi parent và xuất báo cáo gộp; không vượt chặn HTTP |
| Thành phần | `python -m evaluation.messages.components --help` | LLM / URL / RAG trên cùng dev |
| Dev mới | `python -m evaluation.data.fresh_dev --help` | Trích riêng dev, tạo phiếu người/nhãn AI có hash; giữ reserve ngoài suy luận |
| Bốn cấu hình cố định | `python -m evaluation.messages.fresh_ablation --help` | Cùng prompt/schema; dùng chung response khi payload giống nhau; giữ mọi lỗi |
| Diễn giải ablation | `python -m evaluation.messages.ablation_interpretation --out COMPLETE_RUN` | Tách sửa đúng cảnh báo nhầm khỏi mất quyết định do lỗi/UNKNOWN; kèm Accuracy và coverage |
| Pilot verdict lõi | `python -m evaluation.messages.core_pilot --help` | Probe provider và factorial schema/thinking, không công bố Accuracy/F1 |
| Chất lượng verdict lõi | `python -m evaluation.messages.core_quality --help` | Ba pipeline trên cùng dev/reference AI; chỉ xuất so sánh khi inventory đầy đủ |
| Phục hồi sau 429 | `scripts/evaluation/recover_core_quality.py --help` | Amendment có probe thành công: chỉ request chưa gửi, một worker/cách bốn giây; giữ lỗi cũ trong kết quả gộp |
| Mở rộng corpus | `python -m evaluation.rag.corpus_comparison --help` | Kiểm đủ ma trận relevance, giữ nguồn cũ nguyên vẹn và dùng chung mẫu số khi đo raw E5 top-3 |
| Điều kiện cải tiến | `python -m evaluation.messages.readiness --help` | Kiểm giảm FP thực sự, Accuracy/Recall/coverage và khoảng trống nhãn/dữ liệu |
| Phạm vi nhãn | `python -m evaluation.messages.label_scope --help` | Phân biệt reference hành vi AI với rủi ro toàn thông điệp; tạo phiếu 80 dev chưa có nhãn người |
| Đối chiếu cohort | `python -m evaluation.data.cohort_audit --help` | Phân biệt đổi tập mẫu với đổi nhãn, xuất bảng ID và N/A phù hợp |
| Hiệu năng URL | `scripts/evaluation/benchmark_url_runtime.py --help` | 100 batch năm URL, model thật qua API in-process, không gọi provider; ghi máy/affinity và giới hạn |
| Truy xuất theo hành vi | `python -m evaluation.rag.action_comparison --help` | Chấm lại E5 và lọc BM25/RRF/hành vi trên dev đã xem |
| Review RAG | `python -m evaluation.rag.dev_review --help` | Toàn bộ cặp query/tài liệu và rubric giải thích, tách phiếu AI/người |
| URL | `python -m evaluation.url.source_audit --help` | Baseline PhishVN và ảnh hưởng bronze/nguồn |
| URL | `python -m evaluation.url.character_baseline --help` | Đối chứng TF-IDF ký tự train-only |
| UI | `scripts/evaluation/check_consumer_ui.py --out NEW_DIR` | Kiểm desktop/mobile bằng replay, không gọi LLM thật |
| UI bổ sung ngữ cảnh | `scripts/evaluation/check_focused_ui.py --base-url http://127.0.0.1:8001 --out NEW_DIR` | Kiểm đồng ý lại, không khôi phục URL đã xóa, XSS và mobile bằng replay |
| UI triển khai | `scripts/evaluation/check_runtime_ui.py --out NEW_DIR` | Kiểm kết nối máy chủ, không gửi key/override và xác nhận lại khi bản sửa được che thêm; replay, không provider |

Các runner URL khác nằm ở `evaluation/url`; pilot/ablation ở `evaluation/messages`; gán relevance/truy xuất ở `evaluation/rag`; thu mẫu và nhãn ở `evaluation/data`. Tên file không chứa phiên bản khi vai trò đã rõ; phiên bản khoa học vẫn nằm trong protocol.

## Kiểm chứng và báo cáo kỹ thuật

`scripts/evaluation/` chứa `verify_*`, `report_*`, `plot_*`, `check_v61_contract.py` và công cụ UI. Chúng có thể ghi output/phiếu/metadata; dùng bản sao hoặc thư mục mới khi cần giữ nguyên run cũ. `reproduce_phishvn_baseline.py` chạy trong môi trường tham chiếu theo protocol lịch sử.

Không chạy `run` chỉ để thử cài đặt: nhiều runner huấn luyện model hoặc gọi API. Một số yêu cầu `--live`, riêng `evaluation.messages.improvement_pilot run` gọi API trực tiếp. `--help` không thực thi thí nghiệm.

Source hash trong run cũ không tự khớp layout mới. Dùng [worktree tái lập lịch sử](../docs/development.md#tai-lap-lich-su), không sửa manifest cho hết lỗi hash. [Phương pháp đánh giá](../docs/evaluation.md), [kết quả](../docs/results.md).
