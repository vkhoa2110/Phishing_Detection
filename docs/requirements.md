# Yêu cầu chức năng và minh chứng

Phạm vi triển khai là các profile chạy qua `run.py` và `app.api.runtime`. Stable vẫn dùng XGBoost/v4; candidate và focused dùng URL ký tự, chưa được chọn thay mặc định chỉ từ điểm dev. `verifier-shadow` là nhánh quan sát thử nghiệm, không đổi kết luận. Các journal nghiên cứu cần source đúng phiên bản để replay; source snapshot/commit cũ giữ cục bộ hoặc trong Git. Đối chiếu cập nhật ngày 21/11/2026; trạng thái chức năng khác với chất lượng phát hiện.

## FR-01–FR-08

| Mã | Hành vi và mã nguồn | Kiểm chứng | Trạng thái/giới hạn |
|---|---|---|---|
| FR-01 | Giới hạn input, rỗng/sai/quá dài: `app/domain/schemas.py`, `app/api/legacy.py` | `tests/api/test_baseline.py`; `tests/api/test_runtime.py` | Có validation và thông báo chung không echo body/key |
| FR-02 | Tách/gộp URL, phân biệt email: `app/services/url/parsing.py`; candidate thêm `intake.py`, `authority.py` | `tests/url/test_url_intake_v2.py`, `tests/api/test_baseline.py`, `tests/api/test_url_capacity.py` | Tab URL nhận một URL; văn bản/email nhận tối đa 50 URL khác nhau từ 25/11; không cắt ngầm khi vượt giới hạn |
| FR-03 | Model đã lưu và policy: `app/services/url/features.py`, `character.py`, `policy.py` | `tests/url/test_url_char_service.py`, `test_phishvn.py`; benchmark model thật | Có suy luận cục bộ, không xác minh website đang hoạt động |
| FR-04 | LLM trên nội dung đã duyệt: `app/services/analysis.py`, `llm/message.py`, `llm/core.py` | `tests/api/test_runtime.py`, `test_focused_app.py`; các lượt API dev có journal | Có luồng AI với xác nhận; URL-only cục bộ là chế độ bổ sung, không tự gửi dữ liệu khi người dùng từ chối |
| FR-05 | Retrieval và dẫn nguồn: `app/services/rag/retrieval.py`, `evidence.py`, `app/api/interaction.py` | `tests/rag/`; `tests/api/test_focused_app.py` | Có nguồn hoặc trạng thái không tìm được. Relevance/claim vẫn thiếu chấm người; không tuyên bố chất lượng chỉ từ quote/schema đúng |
| FR-06 | Nhận định nội dung và URL, bất đồng và bất định: `app/domain/decisions.py` | `tests/messages/test_fusion_matrix.py` có đủ 25/25 tổ hợp với assertion toàn bộ kết quả; `tests/api/test_analysis_service.py`, `test_quality_app.py` | Có hiển thị riêng; đã bổ sung test các ô còn thiếu sau audit 20/11. Cần nhãn rủi ro toàn thông điệp để đánh giá chất lượng tổng hợp |
| FR-07 | Xem/sửa/xác nhận, che lại sau sửa: `app/static/app.js`, `/api/preview`, `app/core/privacy.py` | `tests/api/test_runtime.py`; browser `check_runtime_ui.py`, `check_focused_ui.py` | Thay đổi do chuẩn hóa/che thêm được hiển thị và yêu cầu xác nhận lại. URL đã xóa không được đưa trở lại metadata AI |
| FR-08 | Thiếu/sai JSON, cắt output, timeout/API lỗi: `llm/core.py`, `llm/telemetry.py`, `app/api/runtime.py`; verifier shadow tách trạng thái bổ sung | `tests/api/test_runtime.py`, `test_focused_app.py`, `test_verifier_shadow.py`, `test_runtime_deep_json.py`; journal lỗi dev | Giữ kết quả URL khi AI lỗi; giữ verdict khi giải thích/verifier lỗi; lỗi kỹ thuật không biến thành LOW hoặc câu hỏi thiếu ngữ cảnh |

## FR-09–FR-18 — lớp phần mềm cục bộ ngày 24/11

| Mã | Đã triển khai | Kiểm chứng và phạm vi |
|---|---|---|
| FR-09 — tài khoản | Đăng ký, đăng nhập/đăng xuất, cookie session có hạn, sửa tên và đổi mật khẩu; admin đầu tiên | `app/api/workspace.py`, `app/core/accounts.py`, `tests/api/test_workspace.py`; đổi mật khẩu thu hồi các phiên cũ; chưa xác minh email/SSO/MFA |
| FR-10 — lịch sử riêng | Lưu metadata mặc định, snapshot đã che theo lựa chọn; tìm có/không dấu, lọc, đánh dấu, ghi chú, JSON và xóa | Truy vấn bắt buộc chủ sở hữu; người khác đọc/sửa/xóa trả 404; không khôi phục nội dung nếu người dùng không chọn lưu |
| FR-11 — dashboard/quản trị | Thống kê riêng, quota AI 24 giờ; admin đổi quyền/khóa/mở khóa, không xem lịch sử người khác | Backend kiểm quyền và thu hồi session; bảo vệ tự hạ quyền/khóa; giới hạn đồng thời một lượt/tài khoản và bốn/tiến trình |
| FR-12 — lưu trữ/vận hành | SQLite WAL, schema, file cục bộ ngoài Git; backup nhất quán và đặt lại mật khẩu bằng lệnh nhập ẩn | `app/services/workspace.py`, `scripts/maintenance/workspace.py`; backup không ghi đè; nhắm localhost/demo, chưa là cấu hình dịch vụ công khai |
| FR-13 — extension trình duyệt | Menu link/đoạn chọn và URL tab; ghép nối một lần, preview/consent, hai nhận định và lịch sử | `extensions/chromium`, `app/api/browser_extension.py`; bearer phạm vi hẹp, quota chung; phiên cũ hoặc ghi nhớ 30 ngày có thu hồi; cần backend cục bộ; chưa phát hành store |
| FR-14 — phản hồi | Người dùng gửi/xóa/theo dõi; admin lọc/phân trang/xử lý và trả lời | `app/services/product_features.py`, `app/static/product.js`, `tests/api/test_product_features.py`; chia sẻ nội dung opt-in, không tự tạo gold/training |
| FR-15 — mở demo | Kiểm cài đặt, khởi động/mở lại ứng dụng, shortcut Linux, gói ZIP extension | `launch.py`, `start_phishlens.*`, `scripts/maintenance/package_extension.py`; cần môi trường/model đã cài; Windows launcher chưa kiểm trên máy Windows |
| FR-16 — ảnh và khoanh vùng extension 0.3 | Side panel, sáng/tối, khoanh trực tiếp trên trang tự crop/OCR/preview; file/drop/paste riêng; nút nổi tùy chọn và ghi nhớ 30 ngày | `region*.js`, `floating.js`, `images.js`, `image_text.py`, test API và `check_extension_region_ui.py`; OCR tại máy, AI luôn consent; Chrome headless kiểm capture với bản manifest test cấp trước quyền tùy chọn; chưa tự động native permission dialog/toolbar/shortcut hoặc vision/QR |

| FR-17 — trợ lý trình duyệt 0.4 | Điều hướng Kiểm tra/Trợ lý/Kết nối, nút nổi kéo/bám mép, menu, tạm nghỉ/ẩn site; opt-in tự kiểm URL cục bộ khi đóng bảng | `assistant.js`, `floating.js`, `check_extension_assistant_ui.py`; mặc định tắt, không đọc DOM/gọi AI/lưu lịch sử nền; badge và cảnh báo sau điều hướng, không chặn truy cập; cần backend đang chạy |

| FR-18 — dùng khách, không nhập mã | Web/extension có URL, preview/consent AI, OCR mà không đăng nhập; extension tự kết nối localhost; ZIP public | `test_guest_access.py`, `check_guest_ui.py`; không tạo user/history, quota chung theo client, dữ liệu riêng vẫn cần tài khoản. API mã/token cũ giữ tương thích, UI không còn bước lấy/nhập mã |

Luồng trình duyệt hai tài khoản và model URL thật đạt ở [workspace trial](../artifacts/ui/workspace_trial_20261124_02/browser/checks.json), không gọi provider trong lượt đó. Lượt riêng sau đăng nhập có **một provider call thật, HTTP200/stop, 1.012 token**, giữ consent và chỉ lưu metadata: [live UI](../artifacts/evaluations/workspace_completion_20261124/live_ui/checks.json). Đây là kiểm tích hợp phần mềm, không phải F1 mới. [Bộ kiểm phần mềm mới](../artifacts/evaluations/workspace_completion_20261124/validation_final/checks.json) lưu source/test hiện hành; không gộp node test với số tin đánh giá.

Mốc extension/feedback tiếp theo có **1.603 test đạt**, [6 luồng Chromium với extension thật/provider giả](../artifacts/ui/extension_20261124_02/checks.json) và [1 smoke provider thật qua extension, HTTP200/stop/988 token](../artifacts/ui/extension_live_20261124/checks.json). [Snapshot nguồn và kiểm phần mềm](../artifacts/evaluations/extension_completion_20261124/validation_final/checks.json). Các mốc được giữ riêng; kiểm browser không phải bằng chứng về Recall/F1.

## NFR và trạng thái đánh giá

| Mã | Minh chứng hiện tại | Phần còn thiếu/giới hạn |
|---|---|---|
| NFR-01: năm URL trong một giây ở ít nhất 95% lượt, model đã nạp, CPU 4 lõi/RAM 8 GB; chờ LLM 45 giây | Benchmark cũ 100 batch × 5 URL/profile; bổ sung ngày 21/11 có 100 quan sát **một URL**/model/phạm vi, gồm intake/đặc trưng/predict và API in-process; runtime dùng chung budget tối đa 45 giây | Máy đo có 14,84 GiB RAM, không giới hạn ở 8 GiB; chưa gồm mạng HTTP vật lý hoặc tải đồng thời. Timeout kiểm bằng transport mô phỏng và thời hạn rút ngắn, không phải đo provider thật chờ 45 giây |
| NFR-02: dữ liệu đã duyệt, không tự lưu nội dung người dùng | Request gửi đúng bản cuối, kiểm che lại khi sửa; logger không ghi body. Workspace chỉ lưu metadata mặc định, snapshot đã che phải được chọn riêng | Che bằng quy tắc chưa bảo đảm hết PII; database/backup chứa dữ liệu tài khoản riêng và được giữ ngoài Git |
| NFR-03: key phía máy chủ, HTTPS | Runtime từ chối key/endpoint/model client; giao diện triển khai chỉ đọc dịch vụ; test không echo key trong status/lỗi/log | ASGI nghiên cứu vẫn có hợp đồng cũ, phải dùng launcher/factory runtime cho triển khai |
| NFR-04: kiểm phản hồi | Parser strict, kiểm quote, finish reason, giữ lỗi; focused runtime kiểm cue của cơ chế và diễn giải có quy chiếu AI (`claim_grounding.py`, `test_claim_grounding.py`, `test_reason_presentation.py`) | Kiểm cue không xác minh ý nghĩa; chưa sửa được phân loại sai. Thiếu cue chỉ đổi cách diễn giải, không biến thành LOW/UNKNOWN |
| NFR-05: tái lập | Manifest, hash, journal, scorer, phiên bản model/corpus; snapshot cho mã cũ | Các run đã xem chỉ là hồi cứu/dev; cần source đúng lúc đăng ký |
| NFR-06: giới hạn sử dụng | 8.000 ký tự/50 URL khác nhau; token cap; shared deadline; không tự retry. Workspace có quota 100 yêu cầu AI/24 giờ/tài khoản theo cấu hình và giới hạn đồng thời | Quota theo lượt phân tích, chưa phải tính tiền/token provider; chưa có service SLA hoặc quản lý tải phân tán. Benchmark NFR-01 giữ workload lịch sử 5 URL, chưa chứng minh latency cho 50 URL |
| NFR-07: desktop/mobile | Browser replay kiểm tràn ngang, xác nhận, trường kết nối ẩn và thiếu key máy chủ | Chưa thử nghiệm khả dụng với người dùng thật |
| NFR-08: injection | Stress tự soạn và test hợp đồng; input/nguồn là dữ liệu không tin cậy, LLM không mở URL/thực thi | Cần bộ cặp gốc/chèn được chấm độc lập và trường hợp nguồn RAG bị chèn rộng hơn; không tuyên bố chống injection đầy đủ |

## Dữ liệu và cách đọc các test

`objective_v1` và `fresh_messages_v1` là các cohort khác nhau, không phải thay nhãn cùng 80 SMS. Tool `evaluation.data.cohort_audit` xuất bảng ID với N/A khi mẫu không tồn tại ở một cohort; không bịa lý do chuyển 9 dương thành 4. Phiếu `whole_message_review.csv` giữ hành vi, nhãn toàn thông điệp và bằng chứng URL riêng; chưa có gold mới.

Suite offline bao gồm nhóm `tests/api`, `messages`, `url`, `rag`, `data`, `evaluation`. Nhiều test API dùng `httpx.MockTransport`, FakeML hoặc retriever giả để tạo lỗi/schema/timeout/consent có kiểm soát. Một số test kiểm hợp đồng/array hoặc replay dữ liệu đã khóa. Số test đạt không phải số SMS dự đoán đúng hoặc số lượt provider thật. Benchmark URL riêng dùng model thật; browser check replay phản hồi AI, không gọi provider.

Benchmark batch và danh sách phần chưa hoàn tất ở mốc 13/11 nằm tại [runtime_checks_20261113](../artifacts/evaluations/runtime_checks_20261113/README.md); cập nhật 21/11 ở [improvements_20261121](../artifacts/evaluations/improvements_20261121/README.md). Ưu tiên nhãn độc lập, mẫu dương có URL và đánh giá nguồn/giải thích trước khi mở test hoặc thay model vận hành.

[Benchmark từng URL ngày 21/11](../artifacts/evaluations/url_single_latency_20261121/README.md) đo hai phạm vi độc lập, không chia thời gian batch cho năm. Kết quả chính phục hồi từ 400 quan sát đầu tiên; lỗi xuất metadata thư viện và lượt kiểm export sau sửa được giữ riêng. Các con số chỉ mô tả snapshot/workload đã đăng ký; không phải SLA của profile verifier-shadow hoặc chất lượng phát hiện.

Rà soát đầu ngày 16/11 phát hiện hai lỗi: metadata URL bị bỏ khi hostname được chuẩn hóa hoa/thường; regex che mã OTP có thể che nhầm scheme `https`. Sau sửa, cùng 16 ca × 4 cấu hình đạt 64/64 kiểm hợp đồng qua focused, dùng model URL thật và phản hồi AI/retrieval giả lập. Metadata chỉ ghép với URL còn trong bản đã duyệt; giữ đúng cách viết đã duyệt, không khôi phục URL đã xóa và bỏ trường hợp nhiều URL bị nhập nhằng sau che dữ liệu. Quy tắc che thông tin đăng nhập URL cũng được sửa để có thể che lại mà không làm hỏng URL. Đây là sửa chức năng, không phải điểm chất lượng phát hiện hoặc bảo đảm che hết PII. [Audit trước sửa](../artifacts/evaluations/evaluation_audit_20261116/README.md) và [kiểm chứng sau sửa](../artifacts/evaluations/privacy_metadata_fix_20261116/README.md). Trace retrieval và báo cáo injection đã xuất offline; chấm relevance/tuân chỉ dẫn vẫn còn thiếu.

Ngày 17/11 bổ sung tham chiếu IANA offline cho miền trần trong text ở candidate/focused. Chuỗi có hậu tố chưa đủ căn cứ nằm riêng ở `unscored_candidates`, giữ nguyên trong bản nội dung được duyệt, không gửi score và không bị coi là URL lỗi. Giao diện yêu cầu đối chiếu lại chuỗi chưa chấm; giới hạn URL áp dụng sau lọc (từ 25/11 tăng lên 50 URL khác nhau; snapshot 17/11 vẫn là năm URL). Tên miền có hậu tố trong danh sách vẫn có thể là viết tắt/tên tệp, và URL có scheme không được xác minh tồn tại hoặc an toàn. [Protocol, regression và chẩn đoán dev](../artifacts/evaluations/url_intake_audit_20261117/README.md).
