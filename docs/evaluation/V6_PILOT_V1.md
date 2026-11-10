# Pilot v6 và bộ thông điệp bổ sung — 09/11/2026

Đã thực hiện **102 lần gọi API thật**, đúng một lần cho mỗi request đã khóa: 30 RAG và 72 hội thoại. Model yêu cầu là `DeepSeek-V4-Flash`, trần đầu ra 2.048 token. Journal được ghi trước khi gửi; không retry, sửa JSON hoặc thay phản hồi lỗi. Raw response đã được kiểm tra lại bằng parser tương ứng và khóa hash.

## Kết quả hội thoại

**Đây là tỷ lệ phản hồi hợp lệ về cấu trúc và hợp đồng xử lý, không phải Accuracy/F1 phát hiện lừa đảo.** Chưa có nhãn ngữ nghĩa độc lập cho từng tiền tố.

| Profile | Yêu cầu | Hợp lệ | Lỗi | Token ghi nhận | Độ trễ trung vị |
|---|---:|---:|---:|---:|---:|
| message-v5 | 36 | 34 | 2 | 160,264 | 3.17 giây |
| message-v6 | 36 | 16 | 20 | 197,801 | 6.92 giây |

V6 có **9 lỗi hợp đồng đếm lượt**: parser đang trả danh sách rỗng với một dòng có nhãn người nói, trong khi model khai báo đã dùng một lượt. Các phản hồi này vẫn là lỗi của lượt đã khóa. V6 còn 11 lần bị cắt đầu ra; v5 có một lần bị cắt và một JSON không hợp lệ. Chưa sửa prompt/parser hoặc nâng token giữa thí nghiệm.

Kết quả này cho thấy **v6 chưa phù hợp để thay bản mặc định** trong điều kiện pilot. Nó chưa chứng minh mô hình suy luận kém hơn: v6 phải xuất thêm cấu trúc tương tác, có prompt dài hơn và bị một lỗi validator. Cùng trần token không có nghĩa hai profile có cùng khối lượng đầu ra.

72 request chỉ có **6 hội thoại, 30 đầu vào hiển thị khác nhau**; không tính thành 72 mẫu độc lập. Các nhánh cùng payload ở tiền tố đầu được giữ để thấy dao động và lỗi, không quy chênh lệch đó thành lợi ích lịch sử.

## Kết quả RAG

| Điều kiện | Yêu cầu | Chọn nguồn | Không có hỗ trợ | Lỗi |
|---|---:|---:|---:|---:|
| Nguồn truy xuất thực tế | 6 | 3 | 2 | 1 |
| Nguồn do tác giả chọn | 6 | 6 | 0 | 0 |
| Bỏ một câu theo thiết kế | 6 | 6 | 0 | 0 |
| Đối chứng không liên quan | 6 | 0 | 6 | 0 |
| Đối chứng không liên quan + injection | 6 | 0 | 6 | 0 |

Nguồn do tác giả chọn tạo được lựa chọn ở 6/6 ca, trong khi truy xuất thực tế có 3 ca chọn nguồn, 2 ca không hỗ trợ và một phản hồi bị cắt. Cần kiểm tra độ phủ/ngưỡng truy xuất trước khi chỉ tăng model sinh. Trong hai ca không hỗ trợ, RC-04 không được retriever trả nguồn; RC-01 có một nguồn nhưng generator không chọn. Cần phân biệt thiếu nguồn, nguồn không phù hợp và lỗi sinh thay vì gom thành một lỗi retrieval. Ví dụ RC-01 hỏi việc giao tài khoản ngân hàng cho bên tuyển dụng, nhưng nguồn nhận được nói về chuyển nhầm tiền; theo chẩn đoán của trợ lý, chúng cùng chủ đề ngân hàng nhưng khác cơ chế. Đây chưa phải điểm relevance do người chấm.

Không có lần chọn attack span trong 6 ca injection. Đây chỉ là quan sát với **một mẫu lệnh chèn và tài liệu đối chứng tự soạn**, chưa phải chứng minh chống injection tốt ngoài thực tế. Nguồn và lệnh tấn công được tách thành document/span riêng.

Bỏ một câu vẫn tạo lựa chọn ở 6/6 ca; không gọi đây là lỗi vì đoạn còn lại vẫn có thể hỗ trợ cơ chế hoặc bước xác minh. Tồn tại trích dẫn không chứng minh hỗ trợ ngữ nghĩa. Các phiếu chấm người vẫn trống. Verdict khóa trước RAG nên không dùng lượt này để khẳng định RAG tăng F1 phân loại.

## Tài nguyên và minh chứng

Tổng usage do provider ghi nhận: **405,410 token**, gồm 47,345 cho RAG. Có telemetry usage ở cả 102 phản hồi; không tự quy đổi sang tiền khi chưa có bảng giá/hợp đồng. Trung vị trên là độ trễ mỗi lần gọi trong điều kiện hai worker, không phải thời gian phản hồi toàn app.

- [Báo cáo chi tiết](../../artifacts/evaluations/v6_pilot_live_20261109/report.md).
- [Khóa thực thi](../../artifacts/evaluations/v6_pilot_live_20261109/execution.json), [raw response](../../artifacts/evaluations/v6_pilot_live_20261109/responses.jsonl) và [kiểm chứng](../../artifacts/evaluations/v6_pilot_live_20261109/verification.json).
- [Lỗi theo từng request](../../artifacts/evaluations/v6_pilot_live_20261109/error_diagnostics.jsonl).
- [Phiếu chấm RAG](../../artifacts/evaluations/v6_pilot_live_20261109/rag_scored/semantic_review.csv) và [phiếu output hội thoại](../../artifacts/evaluations/v6_pilot_live_20261109/conversation_output_review.csv).

## Bộ dữ liệu bổ sung

Đã chuẩn bị [fresh_messages_v1](../../data/annotation/fresh_messages_v1/README.md):

- **200 SMS nguồn**, thuộc 200 nhóm; 80 development review và 120 reserve review. Có 100 mẫu chứa URL. Không giao ID hoặc nhóm với bộ 200 SMS trước.
- Lấy cân bằng theo nhãn nguồn: 100/100. **Đây là nhãn spam/không spam để lấy mẫu, không phải 100 phishing/100 hợp lệ.** Nhãn phishing của cả 200 mẫu đang để trống; chưa chạy model lên bộ này.
- Cùng snapshot nguồn công khai đã dùng trước, không mô tả thành nguồn ngoài độc lập mới hoặc test hoàn toàn chưa tiếp xúc. Việc loại trừ được chứng minh cho 200 mẫu cũ và các nhóm liên quan, không chứng minh loại hết mọi exposure lịch sử.
- **40 ca stress tự soạn** thuộc tám tình huống, gồm 16 ca injection. Có biến thể rủi ro, hợp lệ, thiếu ngữ cảnh và ép HIGH/LOW. Nhãn thiết kế của trợ lý để riêng, không coi là gold.
- Các biến thể trong cùng tình huống giữ cùng URL minh họa. URL dùng miền dự trữ và không có nhãn rủi ro URL; không dùng chúng tính F1 URL hoặc gộp với SMS thật thành một điểm chung.

[Manifest](../../data/annotation/fresh_messages_v1/manifest.json), [phiếu A](../../data/annotation/fresh_messages_v1/annotator_a.csv), [phiếu B](../../data/annotation/fresh_messages_v1/annotator_b.csv), [kiểm chứng dữ liệu](../../artifacts/evaluations/fresh_message_ablation_plan_v1/data_verification.json). Khi review, làm trên bản sao để giữ nguyên gói đã khóa.

## So sánh tiếp theo

Đã ghi [kế hoạch LLM / LLM + URL](../../artifacts/evaluations/fresh_message_ablation_plan_v1/plan.json), trạng thái chưa đủ điều kiện suy luận. Dùng cùng profile v5, model, dữ liệu và schema; chỉ thay metadata URL. Nếu payload không khác thì dùng chung phản hồi cho phép so sánh chính, giữ lặp sinh ngẫu nhiên thành một diagnostic riêng. Nhãn spam nguồn, lý do tham chiếu và điểm model không được đưa cho người gán nhãn.

Trước lượt tiếp theo cần khóa nhãn phishing với UNKNOWN giữ riêng, kiểm tra giao miền với dữ liệu train URL và chốt cấu hình thực thi. Không giả định LLM + URL phải thắng. Bộ reserve không dùng để sửa prompt. RAG sau phân loại được chấm nguồn/lời giải thích riêng.

Kiểm thử phần mềm sau khi thêm runner/bộ dữ liệu: **585 test offline đạt**, một cảnh báo deprecation Starlette/httpx. Đây là kiểm chứng phần mềm, không thay thế đánh giá chất lượng phát hiện.

Cập nhật sau pilot: đã có [bản sửa v6.1 và audit offline](../architecture/QUALITY_V6_TRIAL.md#khắc-phục-sau-pilot-v61--09112026). Các bảng trong tài liệu này tiếp tục mô tả nguyên trạng lượt 6.0, không thay phản hồi lỗi bằng kết quả phát lại parser mới.
