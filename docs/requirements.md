# Yêu cầu chức năng và minh chứng

Phạm vi triển khai là các profile chạy qua `run.py` và `app.api.runtime`. Stable vẫn dùng XGBoost/v4; candidate và focused dùng URL ký tự, chưa được chọn thay mặc định chỉ từ điểm dev. Các ASGI nghiên cứu giữ nguyên cho replay, không tự có chính sách triển khai mới. Đối chiếu cập nhật ngày 16/11/2026; trạng thái chức năng khác với chất lượng phát hiện.

## FR-01–FR-08

| Mã | Hành vi và mã nguồn | Kiểm chứng | Trạng thái/giới hạn |
|---|---|---|---|
| FR-01 | Giới hạn input, rỗng/sai/quá dài: `app/domain/schemas.py`, `app/api/legacy.py` | `tests/api/test_baseline.py`; `tests/api/test_runtime.py` | Có validation và thông báo chung không echo body/key |
| FR-02 | Tách/gộp URL, phân biệt email: `app/services/url/parsing.py`; candidate thêm `intake.py`, `authority.py` | `tests/url/test_url_intake_v2.py`, `tests/api/test_baseline.py` | Tab URL nhận một URL; văn bản nhận tối đa năm URL |
| FR-03 | Model đã lưu và policy: `app/services/url/features.py`, `character.py`, `policy.py` | `tests/url/test_url_char_service.py`, `test_phishvn.py`; benchmark model thật | Có suy luận cục bộ, không xác minh website đang hoạt động |
| FR-04 | LLM trên nội dung đã duyệt: `app/services/analysis.py`, `llm/message.py`, `llm/core.py` | `tests/api/test_runtime.py`, `test_focused_app.py`; các lượt API dev có journal | Có luồng AI với xác nhận; URL-only cục bộ là chế độ bổ sung, không tự gửi dữ liệu khi người dùng từ chối |
| FR-05 | Retrieval và dẫn nguồn: `app/services/rag/retrieval.py`, `evidence.py`, `app/api/interaction.py` | `tests/rag/`; `tests/api/test_focused_app.py` | Có nguồn hoặc trạng thái không tìm được. Relevance/claim vẫn thiếu chấm người; không tuyên bố chất lượng chỉ từ quote/schema đúng |
| FR-06 | Nhận định nội dung và URL, bất đồng và bất định: `app/domain/decisions.py` | `tests/api/test_analysis_service.py`, `test_quality_app.py`; `week4_dev_20261111/url_audit/fusion_matrix.csv` | Có hiển thị riêng; cần nhãn rủi ro toàn thông điệp để đánh giá chất lượng tổng hợp |
| FR-07 | Xem/sửa/xác nhận, che lại sau sửa: `app/static/app.js`, `/api/preview`, `app/core/privacy.py` | `tests/api/test_runtime.py`; browser `check_runtime_ui.py`, `check_focused_ui.py` | Thay đổi do chuẩn hóa/che thêm được hiển thị và yêu cầu xác nhận lại. URL đã xóa không được đưa trở lại metadata AI |
| FR-08 | Thiếu/sai JSON, cắt output, timeout/API lỗi: `llm/core.py`, `llm/telemetry.py`, `app/api/runtime.py` | `tests/api/test_runtime.py`, `test_focused_app.py`; journal lỗi dev | Giữ kết quả URL khi AI lỗi; giữ verdict khi giải thích lỗi; lỗi kỹ thuật không biến thành LOW hoặc câu hỏi thiếu ngữ cảnh |

## NFR và trạng thái đánh giá

| Mã | Minh chứng hiện tại | Phần còn thiếu/giới hạn |
|---|---|---|
| NFR-01: năm URL trong một giây ở ít nhất 95% lượt, model đã nạp, CPU 4 lõi/RAM 8 GB; chờ LLM 45 giây | 100 batch × 5 URL/profile với model thật và API in-process; CPU affinity bốn lõi; runtime dùng chung budget tối đa 45 giây | Máy đo có 14,84 GiB RAM, không giới hạn ở 8 GiB; chưa gồm mạng HTTP vật lý. Timeout kiểm bằng transport mô phỏng và thời hạn rút ngắn, không phải đo provider thật chờ 45 giây |
| NFR-02: dữ liệu đã duyệt, không tự lưu nội dung người dùng | Request gửi đúng bản cuối, kiểm che lại khi sửa; test không khôi phục URL đã xóa; logger không ghi body | Che bằng quy tắc chưa bảo đảm hết PII. Artifact đánh giá chỉ giữ dữ liệu nghiên cứu, khác log ứng dụng |
| NFR-03: key phía máy chủ, HTTPS | Runtime từ chối key/endpoint/model client; giao diện triển khai chỉ đọc dịch vụ; test không echo key trong status/lỗi/log | ASGI nghiên cứu vẫn có hợp đồng cũ, phải dùng launcher/factory runtime cho triển khai |
| NFR-04: kiểm phản hồi | Parser strict, kiểm quote, finish reason, giữ lỗi; focused runtime kiểm cue của cơ chế và diễn giải có quy chiếu AI (`claim_grounding.py`, `test_claim_grounding.py`, `test_reason_presentation.py`) | Kiểm cue không xác minh ý nghĩa; chưa sửa được phân loại sai. Thiếu cue chỉ đổi cách diễn giải, không biến thành LOW/UNKNOWN |
| NFR-05: tái lập | Manifest, hash, journal, scorer, phiên bản model/corpus; snapshot cho mã cũ | Các run đã xem chỉ là hồi cứu/dev; cần source đúng lúc đăng ký |
| NFR-06: giới hạn sử dụng | 8.000 ký tự/năm URL; token cap; shared deadline; không tự retry | Không có quản lý quota/chi phí nhiều người dùng hoặc service SLA |
| NFR-07: desktop/mobile | Browser replay kiểm tràn ngang, xác nhận, trường kết nối ẩn và thiếu key máy chủ | Chưa thử nghiệm khả dụng với người dùng thật |
| NFR-08: injection | Stress tự soạn và test hợp đồng; input/nguồn là dữ liệu không tin cậy, LLM không mở URL/thực thi | Cần bộ cặp gốc/chèn được chấm độc lập và trường hợp nguồn RAG bị chèn rộng hơn; không tuyên bố chống injection đầy đủ |

## Dữ liệu và cách đọc các test

`objective_v1` và `fresh_messages_v1` là các cohort khác nhau, không phải thay nhãn cùng 80 SMS. Tool `evaluation.data.cohort_audit` xuất bảng ID với N/A khi mẫu không tồn tại ở một cohort; không bịa lý do chuyển 9 dương thành 4. Phiếu `whole_message_review.csv` giữ hành vi, nhãn toàn thông điệp và bằng chứng URL riêng; chưa có gold mới.

Suite offline bao gồm nhóm `tests/api`, `messages`, `url`, `rag`, `data`, `evaluation`. Nhiều test API dùng `httpx.MockTransport`, FakeML hoặc retriever giả để tạo lỗi/schema/timeout/consent có kiểm soát. Một số test kiểm hợp đồng/array hoặc replay dữ liệu đã khóa. Số test đạt không phải số SMS dự đoán đúng hoặc số lượt provider thật. Benchmark URL riêng dùng model thật; browser check replay phản hồi AI, không gọi provider.

Mọi số liệu NFR mới và danh sách phần chưa hoàn tất nằm tại [runtime_checks_20261113](../artifacts/evaluations/runtime_checks_20261113/README.md). Ưu tiên nhãn độc lập, mẫu dương có URL và đánh giá nguồn/giải thích trước khi mở test hoặc thay model vận hành.

Rà soát đầu ngày 16/11 phát hiện hai lỗi: metadata URL bị bỏ khi hostname được chuẩn hóa hoa/thường; regex che mã OTP có thể che nhầm scheme `https`. Sau sửa, cùng 16 ca × 4 cấu hình đạt 64/64 kiểm hợp đồng qua focused, dùng model URL thật và phản hồi AI/retrieval giả lập. Metadata chỉ ghép với URL còn trong bản đã duyệt; giữ đúng cách viết đã duyệt, không khôi phục URL đã xóa và bỏ trường hợp nhiều URL bị nhập nhằng sau che dữ liệu. Quy tắc che thông tin đăng nhập URL cũng được sửa để có thể che lại mà không làm hỏng URL. Đây là sửa chức năng, không phải điểm chất lượng phát hiện hoặc bảo đảm che hết PII. [Audit trước sửa](../artifacts/evaluations/evaluation_audit_20261116/README.md) và [kiểm chứng sau sửa](../artifacts/evaluations/privacy_metadata_fix_20261116/README.md). Trace retrieval và báo cáo injection đã xuất offline; chấm relevance/tuân chỉ dẫn vẫn còn thiếu.
