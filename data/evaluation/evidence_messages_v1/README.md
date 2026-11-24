# Bộ thông điệp bổ sung có căn cứ nguồn — v1

Khóa ngày 19/11/2026, trước suy luận. Đây là **challenge do trợ lý dựng lại từ tài liệu**, lấy mẫu có chủ đích để kiểm tra cơ chế; chưa phải tập SMS thực tế được xác thực hoặc nhãn chuẩn do người chấm. Không dùng để ước lượng tỷ lệ lừa đảo ngoài thực tế.

## Dữ liệu hiện có

- [sources.jsonl](sources.jsonl): 34 tài liệu, gồm 20 cảnh báo/vụ việc và 14 tài liệu quy trình hợp lệ. Mỗi nguồn có URL, nhà xuất bản, ngày nếu xác định được, đoạn căn cứ và hash snapshot cục bộ.
- [cases.jsonl](cases.jsonl): 88 thông điệp dựng lại — 40 tình huống lừa đảo, 40 hợp lệ, 8 thiếu ngữ cảnh — cùng 12 biến thể injection có `base_id`. **Không có bản tin được chứng thực là đã gửi/nhận thực tế.**
- [Gói đã khóa và phiếu review](../../../artifacts/evaluations/evidence_messages_20261118/README.md): nhóm, split, input chỉ gồm ID/text, hai phiếu trống, kiểm trùng và manifest.

| Nhóm, chưa tính injection | Dev | Holdout |
|---|---:|---:|
| Tình huống lừa đảo / hợp lệ / UNKNOWN | 22 / 24 / 3 | 18 / 16 / 5 |
| Hành vi nhìn thấy: dương / âm / UNKNOWN | 14 / 24 / 11 | 11 / 16 / 12 |
| Dương có URL | 9 | 9 |
| Nhóm nguồn độc lập của dương có URL | 3 | 3 |
| Biến thể injection, báo riêng | 7 | 5 |

Các tình huống gồm đổi điểm ngân hàng, truy cập thiết bị mới, VNeID, hoàn thuế, cộng tác viên nạp tiền, đầu tư không rút được tiền, vay/thu hồi tiền, giả shipper/bưu điện, OTP mạng xã hội và giả phạt nguội. Âm khó có OTP do người dùng khởi tạo, nhắc thanh toán, OAuth, giao nhận và quảng cáo đã đồng ý nhận.

## Phạm vi nhãn

`reference_status=assistant_evidence_design_not_gold`, `human_reviewed=false` cho mọi dòng. Hai nhãn có mục đích khác nhau:

- `label`: tình huống được tác giả dựng là lừa đảo/hợp lệ tại thời điểm được tài liệu mô tả. Nguồn không xác thực từng câu tin nhắn do tác giả viết.
- `behavior_label`: có yêu cầu hành vi nguy hiểm nhìn thấy trong chính tin hay chưa. `null` giữ nguyên khi chỉ có lời mời, yêu cầu trả tiền có thể hợp lệ, hoặc rủi ro nằm ở ngữ cảnh chưa xuất hiện. Đoạn `behavior_quote` khớp nguyên văn là điều kiện hình thức, không tự chứng minh ý định lừa đảo.

Phạm vi tình huống bao gồm lừa đảo chuyển tiền/ứng phí, rộng hơn phishing lấy thông tin đăng nhập. Phải đăng ký rõ nhiệm vụ và nhãn tương ứng trước khi chấm. Không dùng nhãn tình huống để phạt một bộ phân tích chỉ được giao tìm hành vi nhìn thấy. Đánh giá phát hiện URL/ra quyết định toàn ứng dụng cần protocol riêng với bằng chứng URL có đúng thời điểm.

URL được trích bằng intake hiện hành. `url_evidence` phân biệt miền từng bị cảnh báo và miền được tài liệu quy trình nhắc đến; **không URL nào được xác minh trạng thái an toàn hiện nay**. Sáu miền từ báo cáo P022 được khôi phục đúng phép `[.]` → `.`, có `source_target`; câu mời đi kèm do trợ lý viết, không phải SMS thu được từ chiến dịch đó. Không mở các đích này.

## Chia tập và giới hạn

34 thành phần liên thông theo bài nguồn/alias, miền đăng ký, campaign nếu biết, mẫu tin, gần trùng Jaccard ≥0,75 và quan hệ biến thể. Seed 20261118 cố định; không đổi seed theo kết quả. Injection cùng tập với tin gốc. ID không chứa nhãn; input và hai phiếu được xáo thứ tự bằng hash không dùng nhãn. Metadata/nhãn/lý do không đi vào payload model.

Holdout đã được trợ lý dựng dữ liệu xem. Đây là **holdout có khóa, tác giả đã tiếp xúc**, chưa phải test mù độc lập. Kiểm trùng 80 dev đã suy luận trước đó có 0 cặp trùng, 0 cặp gần trùng ở ngưỡng trên và 0 miền chung; không đọc/suy luận 120 SMS reserve.

Trong 25 ca gốc có URL, 9 trùng URL chuẩn hóa và 13 trùng miền với archive PhishVN. **Sáu dương URL của holdout trùng chính split test URL lịch sử đã xem**, không phải bằng chứng URL mới ngoài mẫu; không gọi chúng là URL huấn luyện nếu chỉ trùng test. Cần báo riêng nhóm này với nhóm chưa thấy trong inventory. Các kiểm tra không chứng minh vắng trong pretraining hoặc mọi dữ liệu khác.

Tám nguồn có chủ đề tương ứng corpus RAG hiện có theo đối chiếu thủ công; không có nghĩa nguồn sẽ hỗ trợ từng claim. Chưa kiểm hết trùng ngữ nghĩa. Corpus giữ nguyên; không đưa tin hoặc đáp án holdout vào RAG.

## Cách dùng

Snapshot nguồn và pack đầy đủ ở `artifacts/evaluations/evidence_messages_20261118/`, được giữ cục bộ. P022 lưu bản trích văn bản PDF từ công cụ web, **không có file PDF gốc**; nguồn tải lỗi không có snapshot tin cậy bị loại. Clone Git riêng chưa đủ để dựng lại offline nếu thiếu snapshot/archive.

```bash
# Kiểm hash, nguồn, intake và tính lại nhóm/split của gói cục bộ
.venv/bin/python -B -m evaluation.data.evidence_messages verify \
  --out artifacts/evaluations/evidence_messages_20261118/pack

# Xem tham số tạo một pack mới; không gọi provider
.venv/bin/python -B -m evaluation.data.evidence_messages --help
```

Sao chép `annotator_a.csv` và `annotator_b.csv` sang nơi review riêng trước khi điền; giữ nguyên bản trống đã khóa. Người chấm chỉ nhận bản phiếu, chưa nhận nhãn/lý do tác giả. Chưa có người chấm hoặc phân xử bất đồng, không đổi trạng thái thành gold.

Hiện **0 lời gọi phân loại, 0 request tới URL đích, chưa có Accuracy/F1 mới**. Trước pilot phải khóa model/prompt/schema/corpus/ngưỡng, cách xử lý lỗi/UNKNOWN và nhóm so sánh. Với focused runtime, RAG sau verdict chỉ được chấm nguồn/lời giải thích; nếu thử RAG trước verdict thì ghi là cấu hình nghiên cứu khác. Chỉ tối ưu trên dev, giữ holdout và 120 SMS cũ ngoài vòng tối ưu.
