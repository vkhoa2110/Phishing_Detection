# Công cụ dòng lệnh

Chạy từ thư mục gốc repository bằng `.venv/bin/python`.

| Nhóm | Script | Chức năng |
|---|---|---|
| Đánh giá | `evaluation/verify_evaluation.py RUN_DIR` | Đối chiếu chỉ số bằng scikit-learn; ghi biên bản kiểm chứng vào thư mục được chọn |
| Đánh giá | `evaluation/plot_evaluation.py RUN_DIR` | Tạo biểu đồ từ lần chạy hoàn chỉnh |
| Đánh giá RAG | `evaluation/verify_rag_ablation.py RUN_DIR` | Kiểm chứng độc lập bốn arm, fusion, checkpoint và nguồn dẫn |
| Đánh giá RAG | `evaluation/plot_rag_ablation.py RUN_DIR` | Biểu đồ toàn bộ và nhóm có/không URL |
| Giao diện v2 | `evaluation/check_context_ui.py` | Replay phản hồi diagnostic tại desktop/mobile; không gọi thêm LLM |
| Giao diện người dùng | `evaluation/check_consumer_ui.py` | Kiểm tra desktop/tablet/mobile, đồng ý gửi API, cảnh báo mâu thuẫn, lỗi và XSS; replay AI, URL chạy thật cục bộ; kết quả ở thư mục mới |
| Dữ liệu SMS | `data/prepare_vn_sms.py --out NEW_DIR` | Tải revision nguồn cố định, khử trùng/nhóm/chọn 200 SMS chờ review |
| RAG | `rag/prepare_index.py --download` | Tải model E5-small đã ghim revision và dựng chỉ mục mới |
| RAG | `rag/collect_rag_sources.py --out NEW_DIR` | Tải các nguồn đã duyệt vào snapshot mới |
| RAG | `rag/assemble_corpus.py --snapshot SNAPSHOT --catalog CATALOG --out NEW_DIR --catalog-out NEW_CATALOG` | Ghép snapshot đã kiểm tra hash; có thể lặp cặp snapshot/catalog; giữ nguyên tài liệu cũ |
| RAG | `rag/validate_rag_corpus.py CORPUS --catalog CATALOG` | Kiểm tra và chốt lại manifest nội dung biên tập |
| Đánh giá retrieval | `evaluation/verify_retrieval_comparison.py RUN --corpus FILE --index DIR --dev FILE --test FILE` | Kiểm chứng số học, hash và chọn ngưỡng dev, không gọi API |
| Nhãn AI | `evaluation/render_prelabels.py ANNOTATION_RUN` | Tạo HTML xem/lọc nhãn AI sơ bộ, không sửa phiếu người đánh giá |

`verify_evaluation.py`, `plot_evaluation.py` và validator có ghi tệp kết quả/metadata, nên dùng bản sao hoặc thư mục chạy mới nếu cần bảo toàn snapshot lịch sử. Bộ test kiểm tra corpus đã bàn giao mà không ghi đè manifest.

Package chạy thí nghiệm nằm riêng ở `evaluation/`: `python -m evaluation.run` cho bộ thông điệp mô phỏng và `python -m evaluation.phishvn` cho PhishVN. Mặc định các công cụ này không gọi LLM; `--live` mới phát sinh gọi API. [Phương pháp đánh giá](../docs/evaluation/METHODS.md).

Chọn ngưỡng và kiểm tra retrieval bằng `python -m evaluation.retrieval`. Không gọi LLM, không đưa nhãn hay score ML vào truy vấn. [Hướng dẫn RAG](../docs/guides/RAG.md).

`python -m evaluation.ablation` chuẩn bị so sánh bốn cấu hình LLM/URL/RAG; thêm `--live` để gọi API. `python -m evaluation.retrieval_comparison` đối chiếu BM25, E5 và Hybrid chỉ trên máy, không đổi cấu hình truy xuất ứng dụng. [Phương pháp, lệnh và giới hạn](../docs/evaluation/RAG_ABLATION.md).

Với corpus/truy vấn v2, truyền `--corpus`, `--index`, `--dev`, `--test`, `--out` riêng. [Lệnh tái lập và kết quả 100 truy vấn](../docs/evaluation/RAG_RETRIEVAL_V2.md). Validator kiểm tra hash snapshot trước khi chốt; muốn thay tóm lược phải tạo snapshot và catalog mới tương ứng.

`python -m evaluation.review status|adjudicate|finalize` kiểm tra hai phiếu, chuẩn bị phân xử, xuất bộ nhãn chuẩn bất biến. Chạy v2 bằng `--prompt-profile message-v2 --fusion-policy separate --reviewed-manifest GOLD_MANIFEST`; thiếu nhãn đã review thì bị chặn trước API. [Hướng dẫn v2](../docs/evaluation/CONTEXT_V2.md).

`python -m evaluation.prelabel --live --out NEW_DIR` tạo nhãn AI sơ bộ bằng prompt riêng, không dùng nhãn nguồn/ML/RAG. Mặc định 4 SMS/lượt, trần 16.384 token, tối đa 50 lượt; bỏ `--live` thì chỉ chuẩn bị offline. Không điền hai phiếu người đánh giá. `python -m evaluation.prelabel_repair --base BASE_RUN --out NEW_DIR --live` chỉ chạy lại các mẫu chưa có phản hồi hợp lệ, giữ nguyên nhãn AI đã có kể cả UNKNOWN. Kết quả không được dùng làm gold để đánh giá chính mô hình gán nhãn.

`python -m evaluation.retrieval_robustness --out NEW_DIR` thử E5/BM25 gốc và bỏ dấu trên dev tăng cường, sau đó kiểm tra bộ hồi quy đã xem. Không thay ứng dụng. [Phương pháp và giới hạn](../docs/evaluation/RETRIEVAL_ROBUSTNESS.md).
