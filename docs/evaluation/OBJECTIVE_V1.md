# Bộ đánh giá có quy trình cố định — objective v1

Ngày chuẩn bị: 02/11/2026. Người dùng yêu cầu trợ lý tự tạo bộ đánh giá. **Đã có dữ liệu và nhãn tham chiếu AI để kiểm tra sơ bộ; chưa có nhãn chuẩn do người đánh giá độc lập.** Không gọi API bên ngoài trong lượt chuẩn bị này.

**Cập nhật 03/11/2026:** đã hoàn tất 364 lượt gọi trên phần dev có nhãn nhị phân, gồm 51 SMS × 4 cấu hình và 40 ca mô phỏng × 4 cấu hình. Có 4 lỗi, được giữ trong kết quả; chưa chạy test. Xem [kết quả và phân tích giới hạn](OBJECTIVE_DEV_RESULTS_V1.md), [bảng chỉ số đầy đủ](../../artifacts/evaluations/objective_dev_results_v1/report.md) và [biểu đồ](../../artifacts/evaluations/objective_dev_results_v1/comparison.png). Nhãn AI vẫn chưa được xác nhận độc lập.

## Những tệp nên mở trước

| Nội dung | Tệp |
|---|---|
| Mục lục bộ dữ liệu | [README](../../data/annotation/objective_v1/README.md) |
| SMS cùng nhãn, lý do và căn cứ | [SMS review.csv](../../data/annotation/objective_v1/provisional_reference/sms/review.csv) |
| Tình huống khó cùng nhãn tham chiếu | [Challenge review.csv](../../data/annotation/objective_v1/provisional_reference/challenge/review.csv) |
| Protocol khóa đầu vào/điều kiện chạy | [protocol.json](../../data/annotation/objective_v1/protocol.json) |
| Quy tắc nhãn hành vi | [classification_rubric.json](../../data/annotation/objective_v1/classification_rubric.json) |
| Chấm độ liên quan tài liệu | [retrieval/rubric.json](../../data/annotation/objective_v1/retrieval/rubric.json) |
| Chấm lời giải thích | [explanation_rubric.json](../../data/annotation/objective_v1/explanation_rubric.json) |

CSV là UTF-8 có BOM, mở bằng Excel/LibreOffice. Nhãn `0` nghĩa là chưa thấy hành vi lừa đảo trong thông điệp; không xác nhận người gửi hoặc URL an toàn. `UNKNOWN` là thiếu căn cứ, không chuyển thành nhãn 0. Nhãn 1 có căn cứ trích nguyên văn và lý do. Người dùng có thể phản biện từng nhãn; không sửa tệp khóa để hợp thức hóa dự đoán của mô hình, mà ghi nhận thành phiên bản annotation mới trước lượt test mới.

## Dữ liệu và phân bố nhãn tham chiếu

| Tập | Dev: 1 / 0 / UNKNOWN | Test: 1 / 0 / UNKNOWN | Tổng |
|---|---|---|---:|
| SMS bên ngoài | 9 / 42 / 29 | 12 / 69 / 39 | 200 |
| Mô phỏng đối chiếu | 16 / 24 / 8 | 8 / 12 / 4 | 72 |

**Không gộp hai hàng thành một F1 chung.** Nhãn và văn bản ở hai nhóm có nguồn gốc khác nhau. Với SMS, chỉ 81 mẫu test hiện có nhãn AI nhị phân, gồm 12 dương; 39 UNKNOWN được giữ riêng. Cỡ mẫu dương nhỏ nên chênh lệch vài mẫu có ảnh hưởng lớn, chưa đủ cho kết luận tổng quát về hiệu năng thực tế.

SMS lấy nguyên 200 bản ghi đã chọn từ nguồn bên ngoài, kế thừa 80 dev/120 test, nhóm domain/template và nguồn dữ liệu có ghi công. Đã che bổ sung một dạng giá trị mật khẩu cấp 2 trong phiên bản dẫn xuất; nguồn cũ không bị sửa. Bộ nguồn do tác giả mô tả là SMS thực, dự án chưa xác minh độc lập quá trình thu thập. Không có email thực trong tập này. [Ghi công/giấy phép](../../data/annotation/vn_sms_v2/ATTRIBUTION.md).

Trợ lý đọc 200 nội dung theo rubric, không dùng nhãn nguồn, nhãn AI cũ, điểm ML hoặc thứ hạng RAG để gán lại. Đây vẫn chỉ là một lượt nhận định AI; có thể sai hoặc thiếu nhất quán. 200 SMS đã có nhãn AI sơ bộ từ trước, vì vậy không mô tả chúng là test chưa từng được xem. [Ghi chú annotation gắn hash đầu vào](../../data/evaluation/objective_sms_reference_notes_v1.json).

72 ca mới do trợ lý soạn, thuộc 12 nhóm: OTP ngân hàng, hóa đơn doanh nghiệp, device code, hỗ trợ điều khiển thiết bị, lấy lại tiền, tuyển dụng, giả công an, đặt vé, đầu tư, giao hàng, học bổng và QR đăng nhập. Mỗi nhóm có sáu biến thể: yêu cầu rủi ro; quy trình thông thường; thiếu ngữ cảnh; yêu cầu rủi ro kèm injection; quy trình thường kèm injection ép cảnh báo; trích dẫn giáo dục. Có **24 ca chứa injection**, gồm cả hướng ép LOW lẫn ép HIGH.

Cùng nhóm dùng cùng URL minh họa trung tính để tránh nhãn bị quyết định bởi URL khác nhau. Tất cả sáu biến thể ở cùng split; 8 nhóm dev/4 nhóm test, không trùng domain giữa hai split. Không tuyên bố độc lập mọi ý tưởng hoặc chuỗi injection chung. Nhãn mô phỏng theo chính vai trò do tác giả thiết kế nên có tính vòng tròn; chỉ dùng kiểm tra đối chiếu, không chứng minh độ chính xác độc lập.

## Cách giữ phép so sánh công bằng

- Cùng nội dung và quy tắc che dữ liệu cho bốn arm: LLM; LLM + URL; LLM + RAG; LLM + RAG + URL. Không gửi nhãn, lý do hoặc tên tập cho LLM.
- Cố định model, prompt `message-v3`, corpus/index/ngưỡng hiện tại, seed, trần 8.192 token và timeout 90 giây; lưu hash dữ liệu, mã nguồn và cấu hình.
- Một lượt chính đã đăng ký. Muốn đo lặp, chốt phiên bản protocol trước và báo mọi lượt; không chọn lượt tốt nhất.
- Phát triển bằng dev. Test giữ cho lượt sau khi chốt; không lọc mẫu theo việc model đoán đúng/sai, không cho đáp án test vào RAG.
- Báo số lượng hai lớp, Precision/Recall/F1, FPR, coverage, lỗi và token. Mẫu phishing bị model trả UNKNOWN/lỗi vẫn nằm trong mẫu số Recall/F1; lỗi kỹ thuật không được tính là từ chối đúng.
- Gold/reference UNKNOWN không có nhãn nhị phân nên tách riêng. Công cụ ablation hiện chấm phần nhị phân; các tệp UNKNOWN đã giữ để kiểm tra mức thận trọng sau, chưa có kết quả ở phần này.
- Bộ đối chứng được định nghĩa gồm luôn cảnh báo và luôn LOW. Đây là đối chứng cần báo khi có kết quả thật, không phải số đo của hệ thống lúc chuẩn bị.
- Nhãn AI chỉ được chạy với `diagnostic`; không vượt cổng `validate_gold`. Chưa chạy hoặc còn pending thì báo cáo protocol không xuất F1 như kết quả mô hình.

Hash cục bộ giúp phát hiện thay đổi, không thay việc đăng ký protocol ở bên thứ ba hoặc kiểm soát người điều phối nhìn test. Nếu mã hoặc artifact đã khóa thay đổi, cần phiên bản protocol mới. Các gói ZIP mù phục vụ chuyển cho người review được tạo cục bộ, không phải tệp nguồn bắt buộc trên Git.

## Tập đánh giá RAG

24 truy vấn được chọn bằng seed theo loại nguồn và split, trước nhãn relevance hoặc kết quả retriever: 12 dev/12 test, gồm 16 SMS và 8 ca mô phỏng. Mỗi truy vấn ghép với **toàn bộ 25 tài liệu**, thành 600 cặp, tránh chỉ chấm tài liệu mà một phương pháp trả ra.

Thang relevance: 0 không liên quan; 1 cùng chủ đề/hướng dẫn chung; 2 hỗ trợ trực tiếp một dấu hiệu hoặc bước xác minh phù hợp; UNKNOWN chưa quyết định. Grade 2 cần đoạn nguồn và lý do, có xét đơn vị và thời điểm. Không yêu cầu tài liệu xác nhận người gửi thật/giả. Có thể một tin chưa đủ nhãn phishing nhưng vẫn có nguồn hữu ích để hướng dẫn xác minh.

Theo yêu cầu tự tạo, đã có **600 nhận định AI sơ bộ** ở `artifacts/annotations/objective_retrieval_ai_v1/review.csv`. Trợ lý đọc truy vấn/tóm lược/phạm vi, không đọc ranking để gán relevance. Bản này đánh dấu 10 truy vấn có nguồn trực tiếp, 14 chưa có; **đây là phân bố annotation AI, không phải Hit@3 hoặc hiệu quả retrieval đã đo**. Có thể còn nguồn hữu ích bị bỏ sót hoặc khác cách diễn giải thang điểm. Các nguồn là bản tóm lược, không phải toàn văn bài gốc.

Công cụ [relevance_review.py](../../evaluation/relevance_review.py) hỗ trợ review mù, phân xử, khóa nhãn và chấm Hit@3, Precision@3, Precision trên tài liệu đã trả, Recall@3, MRR@3, nDCG@3 và từ chối đúng khi thiếu nguồn. Chấm cả 25 tài liệu mới đủ căn cứ kết luận không có nguồn; query còn UNKNOWN phải được báo riêng. Công cụ không tính chất lượng retrieval từ nhãn AI như human gold.

```bash
.venv/bin/python -m evaluation.relevance_review status \
  --workspace data/annotation/objective_v1/retrieval
```

Hai phiếu mù hiện trống; công cụ sẽ báo chờ review. Không tạo hai danh tính người giả để coi hai lượt AI là độc lập.

## Lời giải thích

32 mẫu được chọn trước phản hồi, 8 mẫu mỗi dataset/split. Khi có kết quả, dùng cùng mẫu ở cả bốn arm, ẩn tên arm/model/nhãn kết luận và chấm riêng từng chiều 0–2: dấu hiệu đúng, nguồn liên quan, claim được nguồn hỗ trợ, hành động phù hợp. Hai chiều nguồn dùng N/A khi không dẫn nguồn; báo thêm tỷ lệ có nguồn, không tự cho 0 hoặc 2. Việc có nguồn vẫn có thể làm người chấm đoán được arm nên không hứa mù hoàn toàn.

Đã xuất [phiếu chấm mù dev](../../artifacts/evaluations/objective_dev_results_v1/explanation_blind_dev.csv) theo đúng 16 mẫu dev được chọn trước, mỗi mẫu có bốn dòng tương ứng bốn cấu hình. Trong 64 dòng, 39 có phản hồi hợp lệ, 1 lỗi và 24 chưa chạy do nhãn tham chiếu UNKNOWN; không thay mẫu để lấy đủ phản hồi đẹp. Các ô điểm còn trống, chưa có kết quả chất lượng lời giải thích. Bảng ánh xạ dành cho người điều phối được lưu riêng, không đưa cho người chấm mù. Citation khớp substring không được tính thành điểm ngữ nghĩa.

## Lệnh sử dụng

Kiểm tra đầu vào:

```bash
.venv/bin/python -m evaluation.benchmark_pack verify \
  --out data/annotation/objective_v1
```

Chuẩn bị bốn cấu hình trên dev bằng nhãn AI sơ bộ, **không gọi provider**:

```bash
.venv/bin/python -m evaluation.objective_run \
  --pack data/annotation/objective_v1 --dataset sms --split dev --reference ai \
  --out artifacts/evaluations/objective_sms_dev_prepared_v1

.venv/bin/python -m evaluation.objective_run \
  --pack data/annotation/objective_v1 --dataset challenge --split dev --reference ai \
  --out artifacts/evaluations/objective_challenge_dev_prepared_v1
```

Hai thư mục `*_prepared_v1` là bản chuẩn bị offline, với `new_api_calls=0`, `metrics_ready=false`, `metrics=null`. Chúng không chứa số đo mô hình. Các lượt gọi được người dùng cho phép sau đó nằm riêng tại `objective_sms_dev_live_v1` và `objective_challenge_dev_live_v1`; đã hoàn tất, `metrics_ready=true`. Test vẫn chưa được chạy qua model trong protocol này.

Chỉ khi chủ động thêm `--live` mới gọi API; nhãn AI vẫn là diagnostic. Để chạy benchmark human-gold, phải có hai phiếu thực, phân xử nếu cần, xuất bằng `evaluation.review finalize`, rồi dùng `--reference human --reviewed-manifest ...`.

Muốn tạo lại vào phiên bản mới:

```bash
.venv/bin/python -m evaluation.benchmark_pack prepare --out data/annotation/objective_v1_rebuild
.venv/bin/python -m evaluation.relevance_reference --pack data/annotation/objective_v1 \
  --out artifacts/annotations/objective_retrieval_ai_v1_rebuild
```

Các tệp mới không ghi đè kết quả, model, corpus hoặc phiếu gán nhãn cũ. Bộ dữ liệu giúp đánh giá minh bạch và tái lập hơn; **chưa đủ cơ sở gọi kết quả với nhãn AI là đánh giá khách quan độc lập**.
