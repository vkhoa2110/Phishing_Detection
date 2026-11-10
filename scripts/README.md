# Công cụ dòng lệnh

Chạy từ thư mục gốc repository bằng `.venv/bin/python`.

| Nhóm | Script | Chức năng |
|---|---|---|
| Đánh giá | `evaluation/verify_evaluation.py RUN_DIR` | Đối chiếu chỉ số bằng scikit-learn; ghi biên bản kiểm chứng vào thư mục được chọn |
| Đánh giá | `evaluation/plot_evaluation.py RUN_DIR` | Tạo biểu đồ từ lần chạy hoàn chỉnh |
| Đánh giá RAG | `evaluation/verify_rag_ablation.py RUN_DIR` | Kiểm chứng độc lập bốn arm, fusion, checkpoint và nguồn dẫn |
| Đánh giá RAG | `evaluation/plot_rag_ablation.py RUN_DIR` | Biểu đồ toàn bộ và nhóm có/không URL |
| Bảo trì | `maintenance/clean.py` | Xem trước cache có thể xóa; thêm `--apply` để dọn. Không xóa môi trường, model, dữ liệu hoặc kết quả |
| Giao diện người dùng | `evaluation/check_consumer_ui.py --out NEW_DIR` | Kiểm tra bốn cỡ màn hình 320–1440 px, dán nội dung, tiến trình, đồng ý gửi API, cảnh báo mâu thuẫn, lỗi và XSS; replay AI, URL chạy thật cục bộ; lưu ảnh và biên bản kiểm tra |
| Dữ liệu SMS | `data/prepare_vn_sms.py --out NEW_DIR` | Tải revision nguồn cố định, khử trùng/nhóm/chọn 200 SMS chờ review |
| RAG | `rag/prepare_index.py --download` | Tải model E5-small đã ghim revision và dựng chỉ mục mới |
| RAG | `rag/collect_rag_sources.py --out NEW_DIR` | Tải các nguồn đã duyệt vào snapshot mới |
| RAG | `rag/assemble_corpus.py --snapshot SNAPSHOT --catalog CATALOG --out NEW_DIR --catalog-out NEW_CATALOG` | Ghép snapshot đã kiểm tra hash; có thể lặp cặp snapshot/catalog; giữ nguyên tài liệu cũ |
| RAG | `rag/validate_rag_corpus.py CORPUS --catalog CATALOG` | Kiểm tra và chốt lại manifest nội dung biên tập |
| Đánh giá retrieval | `evaluation/verify_retrieval_comparison.py RUN --corpus FILE --index DIR --dev FILE --test FILE` | Kiểm chứng số học, hash và chọn ngưỡng dev, không gọi API |
| Nhãn AI | `evaluation/render_prelabels.py ANNOTATION_RUN` | Tạo HTML xem/lọc nhãn AI sơ bộ, không sửa phiếu người đánh giá |

`verify_evaluation.py`, `plot_evaluation.py` và validator có ghi tệp kết quả/metadata, nên dùng bản sao hoặc thư mục chạy mới nếu cần bảo toàn snapshot lịch sử. Bộ test kiểm tra corpus đã bàn giao mà không ghi đè manifest.

Package chạy thí nghiệm nằm riêng ở `evaluation/`: `python -m evaluation.run` cho bộ thông điệp mô phỏng và `python -m evaluation.phishvn` cho PhishVN. Mặc định các công cụ này không gọi LLM; `--live` mới phát sinh gọi API. [Phương pháp đánh giá](../docs/evaluation/METHODS.md).

`python -m evaluation.url_source_audit prepare|run|report|verify --out RUN` khóa/chạy/kiểm tra baseline PhishVN và ba nhóm train core/all/bronze cùng cỡ mẫu. `evaluation/reproduce_phishvn_baseline.py --out RUN` chạy riêng LR/RF trong môi trường tham chiếu đã ghim thư viện. Không gọi API, không thay model ứng dụng. [Kết quả, đầu vào và lệnh tái lập](../docs/evaluation/URL_SOURCE_AUDIT_V1.md).

`python -m evaluation.url_calibration run|verify --out RUN` kiểm tra 7 chính sách cảnh báo trên score validation của model hiện hành, chọn ngưỡng bằng URL âm và giữ ngoài từng nhóm miền. Không đọc dự đoán test, huấn luyện, gọi API hoặc thay ngưỡng app. [Kết quả, giới hạn và kế hoạch validation mới](../docs/evaluation/URL_CALIBRATION_V1.md).

`python -m evaluation.url_char_baseline prepare|run|verify --out RUN` thử một cấu hình TF-IDF ký tự + Logistic Regression, chỉ fit train và chọn ngưỡng bằng validation. `python -m app.url_char_service export --audit-dir RUN` đóng gói JSON/NPZ sau khi kiểm tra phát lại đúng hash/score; không thay gói XGBoost. [Kết quả và giới hạn](../docs/evaluation/URL_CHAR_BASELINE_V1.md).

`python -m evaluation.improvement_pilot prepare|run|report|verify --out RUN` chuẩn bị/chạy pilot v4/v5 cùng schema và chẩn đoán RAG trước/sau phân loại. **`run` gọi API**, tối đa 280 yêu cầu theo protocol; `prepare`, `report`, `verify` không gọi. [Profile thử nghiệm và điều kiện](../docs/architecture/QUALITY_V5_TRIAL.md).

`python -m evaluation.url_representation_v2 prepare|run|verify --out RUN` đối chứng chỉ bỏ marker URL, giữ cấu hình học. Một fit train-only, chỉ chấm validation; [kết quả âm](../docs/evaluation/URL_REPRESENTATION_V2.md) được giữ, không thay model.

`python -m evaluation.rag_evidence_audit --out NEW_DIR` kiểm tra phép chiếu contract trên raw cũ, không gọi API. `python -m evaluation.rag_evidence_pilot prepare|run|verify|report --out RUN` so sánh hai hợp đồng RAG sau verdict đã khóa. **Chỉ `run --live` gọi API**, tối đa 32 yêu cầu; `verify` đối chiếu raw/hash, `report` giữ phiếu review đã có. [Phương pháp và kết quả](../docs/architecture/RESEARCH_NEXT_V1.md).

`python -m evaluation.url_representation_audit_v3 run|verify --out NEW_DIR` kiểm tra collision và các bất biến host/path trên train/validation lịch sử, không fit hoặc mở test. `python -m evaluation.rag_summary_audit_v1 prepare --out NEW_DIR` tạo phiếu review 148 claim; `python -m evaluation.rag_controlled_v1 prepare --out NEW_DIR` khóa 30 request protocol 1.2 với manifest và hash; scorer yêu cầu metadata HTTP/finish/model/usage và hash từng request; `python -m evaluation.conversation_structure_v1 prepare --out NEW_DIR` khóa 6 hội thoại dev và phiếu mù. Dùng `python -m evaluation.conversation_structure_v1 prepare-paired --out NEW_DIR --model MODEL_ID` để khóa 72 request v5/v6 theo tiền tố và lịch sử; nhãn từng tiền tố để trống chờ review. Các lệnh này không gọi API. [Thiết kế v6 và giới hạn](../docs/architecture/QUALITY_V6_TRIAL.md).

`python -m evaluation.v6_pilot prepare --out NEW_RUN` sao chép và khóa hai gói 30/72 yêu cầu; `run --out NEW_RUN --live` gọi đúng một lần cho mỗi yêu cầu và ghi journal trước khi gửi. `verify --out NEW_RUN` phát lại kiểm tra offline; `python -m evaluation.v6_pilot_report --out NEW_RUN` xuất báo cáo và phiếu review, không tự gán nhãn người. Không có `--live` thì không gọi provider.

`python -m evaluation.fresh_message_pack --out NEW_REVIEW_PACK` chọn thêm 200 SMS từ snapshot nguồn hiện có, loại toàn bộ nhóm giao với 200 mẫu trước, và tạo riêng 40 ca stress tự soạn. Nhãn spam nguồn chỉ dùng lấy mẫu; nhãn phishing SMS để trống. [Kết quả pilot và trạng thái dữ liệu](../docs/evaluation/V6_PILOT_V1.md).

`python -m evaluation.prospective_url_benchmark register|prepare|verify|report ...` khóa dữ liệu/model/chính sách trước test tương lai; kiểm tra bằng chứng, nguồn, miền/campaign, thời gian và nhãn. Không tải URL, chạy model hoặc tự tạo nhãn người. [Schema và lệnh đầy đủ](../docs/evaluation/PROSPECTIVE_URL_V1.md).

`python -m evaluation.url_source_shift_v2 prepare|run|verify --out RUN` kiểm tra source classifier/leave-one-source-out; `python -m evaluation.url_source_robust_v3 prepare|run|verify --out RUN` đối chứng ba can thiệp nguồn/www; `python -m evaluation.url_probability_audit_v2 prepare|run|verify --out RUN` chẩn đoán calibration. Chỉ validation lịch sử, không API, không tự thay app. Dùng `verify` cho snapshot đã hoàn tất; không chạy lại `run` trong cùng thư mục.

`python -m evaluation.official_url_references ...` thu các tuyến chính thức đã khóa trước, không gán benign; `python scripts/data/render_official_review.py --out NEW.html` tạo trang review từ metadata đã verify. `python -m evaluation.official_url_diagnostic_v1 prepare|run|verify --out RUN` chấm toàn bộ tham chiếu, chỉ báo số cảnh báo.

`python -m evaluation.openphish_candidates_v1 ...` thu snapshot theo điều kiện nguồn đã kiểm tra; raw/URL chỉ giữ cục bộ. `python -m evaluation.openphish_model_diagnostic_v1 prepare|run|verify --out RUN` chấm 5 model trên đúng 200 ứng viên nguồn dương, không fit hoặc HTTP/API. [Kết quả và giới hạn](../docs/architecture/SOURCE_AND_DATA_V2.md).

`python -m evaluation.url_context_pack prepare|verify --out PACK` dựng/kiểm tra bộ 160 URL nguồn thực và 200 ca ngữ cảnh, không đọc dự đoán để chọn mẫu. `python -m evaluation.url_context_score` chấm dự đoán nhập theo ba mục tiêu, giữ kết quả chưa đủ ở trạng thái pending; không gọi API và không xác thực nguồn gốc provider của file dự đoán. [Schema, phương pháp và giới hạn](../docs/evaluation/URL_CONTEXT_V1.md).

`python -m evaluation.url_context_run --split dev --repetitions 3 --out NEW_RUN` đăng ký lượt chạy và tính URL cục bộ; thêm `--live` mới gọi API (720 yêu cầu trên 120 ca dev nếu chạy đủ ba lượt). Journal ngăn gửi lại yêu cầu đã thử, lỗi được giữ trong kết quả. `scripts/evaluation/report_url_context.py --run RUN --out NEW_REPORT` kiểm chứng số học và payload rồi tạo báo cáo/biểu đồ khi đã đủ lượt.

`python -m evaluation.reputation prepare --out NEW_RUN` dựng kho từ PhishVN train và khóa cấu hình; `python -m evaluation.reputation run --out NEW_RUN` so sánh tra cứu/model/kết hợp trên URL truy cập lại và 40 URL dev chưa biết, có kịch bản hết hạn. Chỉ suy luận URL cục bộ, không gọi API hoặc chọn lại ngưỡng. [Kết quả và giới hạn](../docs/evaluation/REPUTATION_V1.md).

`python -m evaluation.component_ablation --out NEW_RUN` khóa và chuẩn bị 80 SMS + 80 ngữ cảnh dev cho bốn cấu hình LLM/URL/RAG; thêm `--live` để chạy 640 lần thử API. `scripts/evaluation/report_components.py --run RUN --out NEW_REPORT` kiểm chứng và tạo bảng/biểu đồ sau khi đủ lượt. [Phương pháp và kết quả](../docs/evaluation/COMPONENTS_DEV_V1.md).

`python -m evaluation.quality_pilot --out NEW_RUN` đăng ký đối chiếu v3/v4 trên toàn bộ 80 SMS dev và 40 ca hồi quy chọn theo miền; thêm `--live` để chạy 240 lần thử API. `scripts/evaluation/report_quality_pilot.py --run RUN --out NEW_REPORT` kiểm chứng độc lập. `python -m evaluation.url_operating_policy --out NEW_REPORT` chấm chính sách URL thận trọng trên score dev/validation đã lưu, không gọi API hoặc học ngưỡng mới. [Kết quả, điều kiện chấp nhận và giới hạn](../docs/architecture/QUALITY_V4.md).

Chọn ngưỡng và kiểm tra retrieval bằng `python -m evaluation.retrieval`. Không gọi LLM, không đưa nhãn hay score ML vào truy vấn. [Hướng dẫn RAG](../docs/guides/RAG.md).

`python -m evaluation.ablation` chuẩn bị so sánh bốn cấu hình LLM/URL/RAG; thêm `--live` để gọi API. `python -m evaluation.retrieval_comparison` đối chiếu BM25, E5 và Hybrid chỉ trên máy, không đổi cấu hình truy xuất ứng dụng. [Phương pháp, lệnh và giới hạn](../docs/evaluation/RAG_ABLATION.md).

Với corpus/truy vấn v2, truyền `--corpus`, `--index`, `--dev`, `--test`, `--out` riêng. [Lệnh tái lập và kết quả 100 truy vấn](../docs/evaluation/RAG_RETRIEVAL_V2.md). Validator kiểm tra hash snapshot trước khi chốt; muốn thay tóm lược phải tạo snapshot và catalog mới tương ứng.

`python -m evaluation.review status|adjudicate|finalize` kiểm tra hai phiếu, chuẩn bị phân xử, xuất bộ nhãn chuẩn bất biến. Chạy v2 bằng `--prompt-profile message-v2 --fusion-policy separate --reviewed-manifest GOLD_MANIFEST`; thiếu nhãn đã review thì bị chặn trước API. [Hướng dẫn v2](../docs/evaluation/CONTEXT_V2.md).

`python -m evaluation.prelabel --live --out NEW_DIR` tạo nhãn AI sơ bộ bằng prompt riêng, không dùng nhãn nguồn/ML/RAG. Mặc định 4 SMS/lượt, trần 16.384 token, tối đa 50 lượt; bỏ `--live` thì chỉ chuẩn bị offline. Không điền hai phiếu người đánh giá. `python -m evaluation.prelabel_repair --base BASE_RUN --out NEW_DIR --live` chỉ chạy lại các mẫu chưa có phản hồi hợp lệ, giữ nguyên nhãn AI đã có kể cả UNKNOWN. Kết quả không được dùng làm gold để đánh giá chính mô hình gán nhãn.

`python -m evaluation.retrieval_robustness --out NEW_DIR` thử E5/BM25 gốc và bỏ dấu trên dev tăng cường, sau đó kiểm tra bộ hồi quy đã xem. Không thay ứng dụng. [Phương pháp và giới hạn](../docs/evaluation/RETRIEVAL_ROBUSTNESS.md).

`python scripts/evaluation/check_v61_contract.py --out NEW_DIR` kiểm chứng pilot cũ, phát lại riêng quy tắc đếm lượt và so kích thước request v6/v6.1. Lệnh không gọi provider hoặc tạo điểm Accuracy/F1 mới. [Bản sửa v6.1](../docs/architecture/QUALITY_V6_TRIAL.md).
