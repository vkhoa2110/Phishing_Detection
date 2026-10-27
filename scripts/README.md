# Công cụ dòng lệnh

Chạy từ thư mục gốc repository bằng `.venv/bin/python`.

| Nhóm | Script | Chức năng |
|---|---|---|
| Đánh giá | `evaluation/verify_evaluation.py RUN_DIR` | Đối chiếu chỉ số bằng scikit-learn; ghi biên bản kiểm chứng vào thư mục được chọn |
| Đánh giá | `evaluation/plot_evaluation.py RUN_DIR` | Tạo biểu đồ từ lần chạy hoàn chỉnh |
| RAG | `rag/collect_rag_sources.py --out NEW_DIR` | Tải các nguồn đã duyệt vào snapshot mới |
| RAG | `rag/validate_rag_corpus.py CORPUS --catalog CATALOG` | Kiểm tra và chốt lại manifest nội dung biên tập |

`verify_evaluation.py`, `plot_evaluation.py` và validator có ghi tệp kết quả/metadata, nên dùng bản sao hoặc thư mục chạy mới nếu cần bảo toàn snapshot lịch sử. Bộ test kiểm tra corpus đã bàn giao mà không ghi đè manifest.

Package chạy thí nghiệm nằm riêng ở `evaluation/`: `python -m evaluation.run` cho bộ thông điệp mô phỏng và `python -m evaluation.phishvn` cho PhishVN. Mặc định các công cụ này không gọi LLM; `--live` mới phát sinh gọi API. [Phương pháp đánh giá](../docs/evaluation/METHODS.md).
