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
| Thành phần | `python -m evaluation.messages.components --help` | LLM / URL / RAG trên cùng dev |
| URL | `python -m evaluation.url.source_audit --help` | Baseline PhishVN và ảnh hưởng bronze/nguồn |
| URL | `python -m evaluation.url.character_baseline --help` | Đối chứng TF-IDF ký tự train-only |
| UI | `scripts/evaluation/check_consumer_ui.py --out NEW_DIR` | Kiểm desktop/mobile bằng replay, không gọi LLM thật |

Các runner URL khác nằm ở `evaluation/url`; pilot/ablation ở `evaluation/messages`; gán relevance/truy xuất ở `evaluation/rag`; thu mẫu và nhãn ở `evaluation/data`. Tên file không chứa phiên bản khi vai trò đã rõ; phiên bản khoa học vẫn nằm trong protocol.

## Kiểm chứng và báo cáo kỹ thuật

`scripts/evaluation/` chứa `verify_*`, `report_*`, `plot_*`, `check_v61_contract.py` và công cụ UI. Chúng có thể ghi output/phiếu/metadata; dùng bản sao hoặc thư mục mới khi cần giữ nguyên run cũ. `reproduce_phishvn_baseline.py` chạy trong môi trường tham chiếu theo protocol lịch sử.

Không chạy `run` chỉ để thử cài đặt: nhiều runner huấn luyện model hoặc gọi API. Một số yêu cầu `--live`, riêng `evaluation.messages.improvement_pilot run` gọi API trực tiếp. `--help` không thực thi thí nghiệm.

Source hash trong run cũ không tự khớp layout mới. Dùng [worktree tái lập lịch sử](../docs/development.md#tai-lap-lich-su), không sửa manifest cho hết lỗi hash. [Phương pháp đánh giá](../docs/evaluation.md), [kết quả](../docs/results.md).
