# Kiến trúc

## Phân chia trách nhiệm

| Package | Trách nhiệm |
|---|---|
| `app/api` | Route HTTP, lifecycle, lựa chọn dịch vụ theo profile |
| `app/core` | Đường dẫn gốc, cấu hình môi trường, che thông tin cá nhân |
| `app/domain` | Kiểu dữ liệu, kiểm bằng chứng và quy tắc kết luận |
| `app/services` | Điều phối luồng phân tích |
| `app/services/llm` | Transport API, prompt và parser phiên bản hóa |
| `app/services/url` | Trích xuất, chuẩn hóa, suy luận model và policy URL |
| `app/services/rag` | Encoder, truy xuất, lựa chọn nguồn và lời giải thích |
| `app/static` | Giao diện chạy cùng origin với API |

Các factory cho phép đưa transport/model/retriever giả vào kiểm thử offline. Mã phục vụ ứng dụng không import runner đánh giá khi khởi động; lệnh export model chỉ import phần huấn luyện khi được gọi rõ ràng.

## Các profile

| `PHISHLENS_PROFILE` | ASGI lõi để tái lập nghiên cứu | Cấu hình |
|---|---|---|
| `stable` — mặc định | `app.main:app` | v4, XGBoost, MessageService |
| `quality-v4` | `app.main:app` | Alias tương thích cho v4 |
| `candidate` | `app.api.interaction:app` | v6.1, URL ký tự, intake nâng cao và cấu trúc tương tác |
| `candidate-v5` | `app.api.candidate:app` | v5, phục vụ đối chứng |
| `legacy` | `app.api.legacy:app` | v3, phục vụ đối chứng |
| `focused` — thử nghiệm | `app.api.focused:app` | Verdict lõi, telemetry, hỏi bổ sung ngữ cảnh; RAG sau phân loại |
| `verifier-shadow` — thử nghiệm quan sát | `app.api.runtime:create_verifier_shadow_app` với `--factory` | Focused và kiểm tra ngữ nghĩa bổ sung; chỉ đề xuất, không đổi verdict |

`run.py` chạy các factory trong `app/api/runtime.py`, bọc dịch vụ lõi bằng chính sách triển khai: kết nối do máy chủ quản lý và một ngân sách chờ chung cho các lời gọi AI của mỗi request. Stable vẫn dùng XGBoost; chọn `focused` không tự thay mặc định. Các ASGI lõi trong bảng giữ nguyên để tái lập nghiên cứu, chưa có lớp chính sách triển khai mới khi gọi trực tiếp. Các module `policy_v5.py`, `policy_v6.py`, `compact.py` giữ hợp đồng prompt/parser cho đối chứng; không ghi đè lịch sử.

## Verifier shadow

<a id="verifier-shadow"></a>

Chạy `make run-verifier-shadow` hoặc `PHISHLENS_PROFILE=verifier-shadow .venv/bin/python run.py`. Nhánh này kế thừa focused, sau phân loại và giải thích tùy chọn mới gửi một yêu cầu kiểm tra lại nếu LLM có kết luận HIGH/WARNING hợp lệ. LOW, UNKNOWN, AI tắt, lỗi phân loại và chế độ chỉ URL không kích hoạt lượt này.

Verifier chỉ nhận bản văn bản đã che và được duyệt, không nhận kết luận ban đầu, score URL, nguồn RAG hoặc nhãn đánh giá. Nó dùng cùng protocol ngữ nghĩa của thử nghiệm 18/11: schema chặt, quote có thật trong input, cap 1.024 và yêu cầu thinking disabled. Mã ứng dụng có bản protocol cố định riêng và test đối chiếu với runner lịch sử; ứng dụng không import package đánh giá.

`verification` chứa kết quả kiểm tra, đề xuất mức cảnh báo, usage và telemetry tách riêng. **Chế độ shadow không sửa `final`, verdict LLM, kết quả URL hoặc lời giải thích đã hoàn tất**, kể cả khi verifier đề xuất LOW. Lỗi/thiếu ngữ cảnh cũng giữ nguyên kết quả đầu. Giao diện hiện tại tiếp tục hiển thị nhận định ban đầu; xem trường API này để rà soát trước khi cân nhắc áp dụng thực tế.

Phân loại, RAG tùy chọn và verifier dùng chung thời hạn tối đa 45 giây tính từ lời gọi AI đầu tiên; hết thời gian không bắt đầu lượt verifier mới. Không retry tự động. Đây là khả năng kiểm thử thêm, chưa chứng minh tăng F1: tham chiếu cũ vẫn là nhãn AI với ít mẫu dương. Không tự bật profile này hoặc hạ cảnh báo trên người dùng từ điểm dev.

`GET /api/status` qua runtime hiển thị cấu hình LLM hiệu lực sau các mức giới hạn của factory. Giá trị trong `.env` có thể khác cap thực sự: phải đọc status của tiến trình đang chạy. Không đưa API key, nội dung hoặc reasoning vào manifest trạng thái.

## Luồng xử lý

```mermaid
flowchart TD
    A[Người dùng nhập nội dung] --> B[Kiểm tra đầu vào và URL]
    B --> C[Model URL cục bộ]
    B --> D[Xem trước và che thông tin]
    D --> E{Đồng ý gửi AI?}
    E -->|Có| F[LLM phân tích hành vi]
    E -->|Không| G[Chưa có nhận định LLM]
    C --> H[Quy tắc kết luận và mức bất định]
    F --> H
    G --> H
    H --> I[Hiển thị nội dung và URL riêng]
    F --> J{Candidate và bật RAG?}
    J -->|Có| K[Khóa verdict rồi truy xuất nguồn]
    K --> L[Giải thích có dẫn nguồn]
    L --> I
```

Bản stable có thể đưa nguồn RAG vào lời gọi phân loại khi bật RAG. Candidate v5/v6.1 khóa verdict trước khi truy xuất và giải thích; phần nguồn không được thay kết luận. Các arm RAG trước/sau phân loại là những thí nghiệm khác nhau.

## Kết luận và rủi ro URL

Kết quả hành vi trong thông điệp và điểm URL được giữ riêng. URL điểm thấp không xác minh nội dung an toàn; cảnh báo chung từ tài liệu không xác minh một miền lừa đảo. Nội dung không có URL vẫn được LLM đánh giá. Thiếu căn cứ, lỗi parse hoặc dịch vụ lỗi được thể hiện rõ, không chuyển thành LOW.

Model XGBoost có mốc thấp `0,113843` và HIGH `0,473643` (hiển thị làm tròn). Bản stable đổi dải WARNING của model thành UNKNOWN; các mốc đầy đủ lấy từ gói model. Model ký tự dùng mốc thấp `0,5`, HIGH lấy từ export validation lịch sử. Không diễn giải các score này thành xác suất lừa đảo đã hiệu chỉnh. [Đánh đổi và giới hạn](results.md#url).

Candidate kiểm tra authority thống nhất bằng UTS #46 nontransitional/STD3. Với URL che dấu, giữ chuỗi gốc và danh sách phép đổi; URL khôi phục chỉ được chấm cục bộ và không tự thêm vào payload đã được người dùng duyệt. Intake không tải trang, phân giải DNS hoặc khẳng định URL đã được xác minh.

## Nguồn dẫn và dữ liệu người dùng

- LLM chỉ nhận nội dung đã xác nhận; URL/score đã bị xóa khỏi bản duyệt không được đưa trở lại qua metadata.
- Qua `run.py`, key/endpoint/model do máy chủ cấu hình; giao diện chỉ hiển thị dịch vụ nhận dữ liệu, API từ chối kết nối thay thế từ client. Các ASGI nghiên cứu lịch sử vẫn giữ hợp đồng cũ cho đối chứng.
- Sau khi sửa bản xem trước, giao diện kiểm che thông tin lại tại máy chủ. Nếu bản chuẩn hóa khác bản đang hiển thị thì cần xem và xác nhận bản mới; provider chưa được gọi ở bước này.
- Nguồn dẫn phải thuộc tập truy xuất và quote phải có trong tóm lược của nguồn. Candidate `span_selection` chỉ cho chọn cặp đoạn có sẵn.
- Quote tồn tại và JSON đúng schema chưa chứng minh hỗ trợ ngữ nghĩa. Cờ `interaction_semantics_verified=false` giữ giới hạn của phần suy diễn vai trò.
- Prompt injection trong nội dung/tài liệu được xử lý như dữ liệu không tin cậy; LLM không có công cụ mở URL/thực thi. Chưa có bằng chứng chống injection đủ rộng để công bố an toàn.

Candidate mặc định dùng giải thích `free_text`; đặt `PHISHLENS_CANDIDATE_RAG_MODE=span_selection` khi cần thử hợp đồng lựa chọn đoạn. Mode, prompt, token và corpus/index phải được khóa trong mỗi thí nghiệm, không suy kết quả của một cấu hình sang cấu hình khác.

## Bản thử nghiệm verdict lõi ngày 12/11

`PHISHLENS_PROFILE=focused` chọn dịch vụ lõi `app.api.focused` qua runtime triển khai. Nó dùng model URL ký tự và hợp đồng `message-core-1.1` từ 24/11: LLM chỉ sinh mức cảnh báo, loại ngữ cảnh, mã hành vi, tối đa hai đoạn trích và hai mục thiếu ngữ cảnh. Tóm tắt tiếng Việt được tạo bằng mẫu xác định từ mã hành vi. Parser yêu cầu JSON hoàn chỉnh; không vá JSON hoặc tự đổi risk/context/reason.

`app/domain/evidence_spans.py` ưu tiên quote khớp nguyên văn. Khi chỉ khác khoảng trắng hoặc hoa/thường, parser tìm đoạn tương ứng trong bản đã duyệt rồi dùng lại đúng chữ và xuống dòng gốc, giới hạn 240 ký tự. Không đổi dấu tiếng Việt, từ, dấu câu, byte URL hoặc token che dữ liệu; đoạn không tìm thấy vẫn gây lỗi. `validation.quote_alignment` giữ quote provider, offsets và số đoạn đã đối chiếu. Đây là kiểm nguồn gốc chuỗi, chưa xác nhận lập luận đúng về ngữ nghĩa. Lỗi JSON/schema/quote có mã chẩn đoán giới hạn tại `telemetry.output_validation`, không ghi giá trị sai, API key hoặc reasoning.

`app/core/privacy.py` hoàn tất việc che URL trong cùng lượt preview: marker số/PII trong hostname hoặc path được biểu diễn bằng `REDACTED` hợp lệ với URL parser. Bước che phòng vệ lúc phân tích vẫn giữ để xử lý nội dung người dùng vừa sửa. Kiểm 307 ca dev cho thấy bản preview mới không đổi ở lượt che kế tiếp; không suy tính chất này cho mọi đầu vào có thể có. Metadata vẫn chỉ được ghép với URL còn trong bản duyệt và loại ghép mơ hồ.

Từ 14/11, lớp runtime triển khai focused áp dụng `app/domain/claim_grounding.py` trước khi chuyển verdict sang nhánh RAG. Mỗi cơ chế phải có các cue tối thiểu trong một mệnh đề của một đoạn trích, không ghép từ khóa từ hai đoạn khác nhau; loại URL/token che dữ liệu khỏi phép kiểm và ghi nhận phủ định hoặc ngôn ngữ phòng tránh. Có cue chỉ cho phép diễn giải dưới dạng “AI nghi ngờ…”, không chứng minh lừa đảo. Thiếu cue thì dùng lý do trung tính, cảnh báo cần kiểm tra và `claim_grounding.status=needs_review`.

Risk, context, reason_code gốc, quote và lỗi kỹ thuật giữ nguyên qua bước kiểm cue này. Không tự hạ xuống LOW/UNKNOWN để tăng chỉ số; không thêm lời gọi AI. Nhánh RAG nhận tóm tắt đã điều chỉnh nhưng vẫn không được thay verdict. `execution.runtime` và `/api/status` lưu hash mã kiểm tra. Từ 24/11, factory focused nạp core 1.1; nguồn core 1.0 của lượt 22/11 được lưu riêng trong [snapshot lịch sử](../artifacts/evaluations/submission_hardening_20261124/historical_source_snapshot/), không dùng mã hiện hành để nhận là đã tái chạy số liệu cũ. Quy tắc từ vựng không xác minh vai người nói, lừa dối hoặc nguồn đúng; metadata luôn giữ `semantic_support_verified=false`.

Verdict hợp lệ được giữ riêng khỏi giải thích tùy chọn. RAG truy xuất sau phân loại, lời gọi giải thích chỉ chọn đoạn có sẵn (`span_selection`); lỗi ở bước này không làm mất verdict. URL và nội dung tiếp tục có nhận định riêng. Không khôi phục URL người dùng đã xóa khỏi bản duyệt để gửi qua metadata.

Khi LLM trả UNKNOWN vì thiếu ngữ cảnh, giao diện đưa ra một hoặc hai câu hỏi với lựa chọn cố định. `/api/clarify/preview` xử lý cục bộ, che thông tin lần nữa và ghi rõ câu trả lời là thông tin người nhận tự cung cấp, chưa xác minh độc lập. Người dùng xem lại và đồng ý gửi trước khi phân tích lại. Lỗi HTTP/timeout/JSON không tạo câu hỏi giả như thể chỉ thiếu ngữ cảnh.

Mặc định yêu cầu `thinking=disabled`, cap 2.048 token; có thể đổi bằng `PHISHLENS_CORE_THINKING` và `PHISHLENS_CORE_MAX_TOKENS` (256–8.192, không vượt cap cấu hình gốc). Đây là tham số yêu cầu provider, không phải bảo đảm chung về cách model hoạt động. Telemetry chỉ giữ số lượng ký tự/token, finish reason và định danh đã lọc; không lưu hoặc hiển thị văn bản reasoning. Bộ thu phản hồi giới hạn 512.000 byte sau giải nén.

Retriever mặc định vẫn là E5 hiện có. `PHISHLENS_FOCUSED_RETRIEVAL=action_hybrid` bật nhánh thử BM25/RRF và lọc hành vi; nhánh này chưa hiệu chỉnh chính sách và đã giảm Hit trên dev, nên chưa được chọn làm mặc định. [Kết quả thực đo và lượt so sánh bị dừng](results.md#verdict-loi).

## Ngân sách chờ và khả năng kiểm chứng

Runtime giới hạn timeout cấu hình tối đa 45 giây. Ngân sách dùng chung bắt đầu ở lời gọi provider đầu tiên, áp dụng cả thời gian chờ và lời giải thích tùy chọn sau đó; không khởi động lời gọi giải thích mới nếu ngân sách đã hết. `ContextVar` tách ngân sách của các request đồng thời. Lỗi phân loại vẫn trả kết quả URL; lỗi hoặc hết thời gian giải thích vẫn giữ verdict đã hoàn tất. Đây là giới hạn chờ AI, không phải cam kết toàn bộ HTTP request dưới 45 giây khi còn nạp model hoặc truy xuất cục bộ.

`/api/status` và `execution.runtime` ghi profile, chính sách kết nối, phạm vi ngân sách và số lần gọi dịch vụ. Lớp runtime không sửa prompt, score, corpus hoặc ngưỡng model của các phép đo lịch sử. [Ma trận chức năng và minh chứng](requirements.md).
