# Cải tiến v4: phân biệt quảng cáo với lừa đảo, giữ vùng URL chưa chắc chắn

Ngày triển khai: **04/11/2026**. Đã sửa và kiểm tra trên dev; bật khi chạy `python run.py`. **Kết quả có cải thiện trên SMS theo nhãn AI, chưa phải chứng nhận chất lượng ngoài thực tế.**

## Vấn đề và thay đổi

Lượt component trước cho thấy nhiều cảnh báo dựa vào suy đoán: SMS có cước phí bị gọi là lừa đảo, thông báo hủy đơn bị xem là dẫn dụ, tên thương hiệu bị coi là bằng chứng mạo danh. Prompt nghiên cứu ba chiều của lượt đó khác prompt ứng dụng; không dùng F1 của nó làm điểm ứng dụng trước/sau.

V4 tập trung vào **hành vi lừa đảo có trong lời yêu cầu**:

- Quảng cáo/spam, khuyến mãi hoặc dịch vụ thu phí không tự là phishing. Đọc điều kiện cước phí là lưu ý tiêu dùng, không tự biến thành cảnh báo chiếm đoạt.
- Không tự bịa mạo danh, mã độc, đầu số thu phí cao hoặc việc người nhận chưa khởi tạo giao dịch. Thiếu xác minh người gửi không tự chứng minh lừa đảo.
- Vẫn cảnh báo yêu cầu gửi mật khẩu/OTP cho người khác, trả phí để rút tiền/giải ngân/nhận việc, giao quyền thiết bị và các yêu cầu nguy hiểm có dấu hiệu lừa dối cụ thể. Nhãn QC/TB không miễn trừ những yêu cầu đó.
- LOW nghĩa là chưa thấy dấu hiệu lừa đảo qua nội dung; không xác minh người gửi hoặc URL. Thiếu ngữ cảnh quyết định thì UNKNOWN. Trích dẫn giáo dục và yêu cầu thực sự được xét riêng.
- Trích đúng nguyên văn, giữ cách viết/token đã che. Giữ cùng schema và bộ kiểm tra cấu trúc với v3, không dùng code ép các ca sai nhãn thành LOW để tăng F1.

[message_service.py](../../app/message_service.py) cung cấp hai chính sách v3/v4 qua cùng transport, cùng schema `MessageVerdict`, cùng validator. Đầu vào không kèm nhãn/ID/nhóm hoặc lý do gán nhãn. Mã baseline trong `app.main`, prompt v3 và các snapshot cũ được giữ để tái lập.

[quality.py](../../app/quality.py) ghép các dịch vụ mới với HTTP routes, bảo vệ dữ liệu và workflow hiện có. Bản gửi API vẫn đi qua xem trước, che dữ liệu và xác nhận của người dùng; cảnh báo nội dung và URL giữ riêng. Trace ghi cả schema v3 tương thích và chính sách sinh thực tế v4. Giới hạn đầu ra tối đa 8.192 token; giá trị thấp hơn do người dùng cấu hình vẫn được giữ.

RAG vẫn bật được trong thiết lập nhưng **không tự bật chỉ vì kho sẵn sàng**. Đường mặc định khớp với lượt kiểm chứng v4 không kèm RAG/điểm URL. Prompt có RAG cũng có quy tắc phân biệt spam và chống suy rộng từ tài liệu, nhưng chưa chạy lại toàn bộ ablation RAG với v4. Chưa có bằng chứng v4 cải thiện ngữ nghĩa nguồn dẫn.

## Kiểm chứng v3/v4 trên cùng điều kiện

Đăng ký trước **120 đầu vào × 2 chính sách = 240 lần thử**:

- Giữ toàn bộ 80 SMS dev: 9 dương, 42 âm theo nhãn AI, 29 UNKNOWN báo riêng.
- Chọn 8 miền trong nhóm URL/ngữ cảnh dev bằng hash, bốn URL mỗi nhãn nguồn, giữ đủ năm biến thể mỗi URL: 40 ca, gồm 32 nhãn hành vi nhị phân và 8 UNKNOWN. Không chọn theo lỗi hoặc điểm model.
- Cùng DeepSeek-V4-Flash, temperature 0,1, trần 8.192 token, timeout 90 giây, hai worker; một lần sinh mỗi chính sách. App dùng timeout người dùng đang cấu hình, hiện là 45 giây.
- Chỉ thay system prompt; không cấp ML/RAG cho cả hai arm để tách tác dụng quy tắc hành vi. Cả hai dùng đúng schema/validator ứng dụng v3, khác lượt component ba chiều trước.
- Giữ nguyên nhãn, dataset, test và các kết quả trước đó. Không retry lỗi, không chọn lần sinh tốt nhất.

Tiêu chí dev đặt trước gồm giảm FPR ít nhất 10 điểm % hoặc còn tối đa 15%; Recall ít nhất 8/9 và không mất quá một mẫu dương so với control; coverage ít nhất 90% và không giảm quá 5 điểm %; hồi quy giữ Recall ít nhất 15/16, F1 không giảm quá 5 điểm %, không tăng cảnh báo nhầm giáo dục. Có tiêu chí coverage/Recall để tránh giảm báo nhầm bằng trả UNKNOWN hàng loạt.

### Kết quả SMS: 51 nhãn nhị phân AI

| Chỉ số | v3 | v4 |
|---|---:|---:|
| TP / FP / TN / FN | 9 / 11 / 30 / 0 | 8 / 0 / 42 / 0 |
| UNKNOWN dương / âm | 0 / 1 | 1 / 0 |
| Precision | 45,00% | 100,00% |
| Recall toàn tập | 100,00% | 88,89% |
| F1 lớp dương | 62,07% | 94,12% |
| Accuracy | 76,47% | 98,04% |
| FPR | 26,19% | 0/42 = 0% |
| Coverage | 98,04% | 98,04% |

V4 sửa đúng 12 ca và làm sai thêm 1 ca. Mẫu dương chưa kết luận của v4 là **OUTPUT_TRUNCATED**, vẫn tính là bỏ sót trong Recall/F1, không gọi lại để thay điểm. Không có mẫu dương nào trong lượt này bị v4 trả LOW. **0/42 cảnh báo nhầm trên dev không bảo đảm FPR bằng 0 ngoài thực tế.**

Bootstrap thăm dò trên 46 nhóm SMS, nhãn cố định, cho khoảng 95% chênh F1 **[+8,17; +63,64] điểm %**, 1.999/2.000 lần lấy mẫu có F1 xác định. Khoảng này không bao phủ sai nhãn AI, sự thích nghi với dev hay dao động sinh lại. Đây là một ứng viên được phát triển sau khi đã đọc các lỗi dev, không phải xác nhận trên test độc lập.

29 SMS reference UNKNOWN được giữ riêng. V3 trả HIGH/WARNING/LOW/UNKNOWN tương ứng 15/8/1/5; v4 là 10/9/5/5. Không gọi các đầu ra này đúng/sai khi chưa có nhãn rõ ràng.

### Hồi quy ngữ cảnh

Trên 32 nhãn nhị phân, cả hai có **F1 86,49%, Recall 100%, coverage 100%, accuracy 84,38%**. Vẫn có **5/16 mẫu âm bị cảnh báo** ở mỗi chính sách; số ca sửa đúng và làm sai thêm đều là 2. Chưa giải quyết được hoàn toàn trích dẫn giáo dục/injection; không tuyên bố chống injection tổng quát.

Ứng viên đạt các tiêu chí dev đã đặt trước, bao gồm không tăng tổng cảnh báo nhầm giáo dục. Tiêu chí “không tăng” không có nghĩa là không còn lỗi. Phần test chưa chạy.

### Lỗi và tài nguyên

Đủ 240 lần thử: **238 phản hồi hợp lệ, 2 lỗi**. V3 có 1 OUTPUT_INVALID ở SMS reference UNKNOWN; v4 có 1 OUTPUT_TRUNCATED ở SMS nhãn dương. Usage ghi nhận: v3 **380.639 token**, v4 **543.035 token**; tổng **923.674**, chưa đối chiếu hóa đơn. Prompt v4 dài hơn và tốn token hơn, không coi đây là tối ưu chi phí.

Đã đối chiếu số học bằng scikit-learn, kiểm tra raw response, payload, hash nguồn, journal và các tiêu chí. Chỉ kiểm chứng tính nhất quán, không xác nhận nhãn AI đúng.

## Chính sách URL thận trọng

[url_policy.py](../../app/url_policy.py) giữ nguyên model, score và hai mốc từ validation cũ:

| Điểm URL | Mức vận hành v4 |
|---|---|
| Dưới 0,11384317278862 | LOW: chưa thấy dấu hiệu rõ theo model |
| Từ 0,11384317278862 đến dưới 0,47364333271980286 | UNKNOWN: chưa đủ tin cậy để cảnh báo chắc chắn |
| Từ 0,47364333271980286 | HIGH: cảnh báo URL, chưa xác minh trang đích |

Không học ngưỡng mới từ tập đánh giá. Dải WARNING cũ chuyển thành UNKNOWN, **không tạo thêm kết luận LOW**; áp dụng chính sách lặp lại vẫn giữ đúng hai ngưỡng gốc. Score chưa là xác suất đã hiệu chỉnh. Đầu ra lưu cả mức/ngưỡng gốc và mức/ngưỡng vận hành.

| Nhóm / chỉ số | Cũ | Chính sách thận trọng |
|---|---:|---:|
| 40 URL dev: FPR | 75,00% | 5,00% |
| 40 URL dev: Recall | 100,00% | 95,00% |
| 40 URL dev: Coverage | 100,00% | 62,50% |
| 40 URL dev: Accuracy | 62,50% | 60,00% |
| 40 URL dev: F1 | 72,73% | 95,00% |
| Toàn validation 7.266 URL: FPR | 70,40% | 15,57% |
| Toàn validation: Recall | 99,12% | 81,28% |
| Toàn validation: Coverage | 100,00% | 74,21% |
| Toàn validation: F1 | 90,78% | 87,61% |

**Đây là giảm mức khẳng định bằng abstention, không phải model học tốt hơn.** Trên 40 URL, 14 cảnh báo nhầm và 1 cảnh báo đúng chuyển thành UNKNOWN; không có ca cảnh báo nào chuyển LOW. Trên toàn validation, 1.018 mẫu dương chuyển UNKNOWN, nên Recall/F1 giảm. Không chỉ chọn hàng dev có F1 tăng để tuyên bố cải thiện tổng quát.

Giao diện hiển thị UNKNOWN đúng nghĩa, không còn gọi các URL này là “điểm vượt ngưỡng cảnh báo”. Cần tiếp tục cải thiện dữ liệu/model URL; chính sách này chưa giải quyết chất lượng phân tách nguồn hay tạo bằng chứng uy tín hiện hành. Kho uy tín vẫn là prototype cũ, chưa được bật làm nguồn xác minh trong app.

## Chạy và tái lập

```bash
.venv/bin/python run.py
# Mặc định: quality-v4; ứng dụng cục bộ tại http://127.0.0.1:8000

PHISHLENS_PROFILE=legacy .venv/bin/python run.py
# Chạy lại ứng dụng baseline v3 khi cần đối chiếu.
```

Các script thực nghiệm cũ vẫn dùng source/prompt baseline đã khóa, không tự đổi sang v4 qua `run.py`. Điểm vào `app.main:app` vẫn là v3; `app.quality:app` là v4. Mặc định mới chỉ áp dụng khi khởi động lại qua `run.py`.

- [Pilot: báo cáo đầy đủ](../../artifacts/evaluations/quality_v4_pilot_results_v1/report.md), [số liệu và bootstrap](../../artifacts/evaluations/quality_v4_pilot_results_v1/summary.json), [kiểm chứng](../../artifacts/evaluations/quality_v4_pilot_results_v1/verification.json).
- [Biểu đồ SMS và đánh đổi URL](../../artifacts/evaluations/quality_v4_pilot_results_v1/comparison.png), [SVG](../../artifacts/evaluations/quality_v4_pilot_results_v1/comparison.svg).
- [Đăng ký pilot và tiêu chí](../../artifacts/evaluations/quality_v4_pilot_v1/execution.json), [checkpoint](../../artifacts/evaluations/quality_v4_pilot_v1/predictions.jsonl).
- [URL: bảng đủ validation/dev](../../artifacts/evaluations/quality_v4_url_policy_v2/report.md), [JSON](../../artifacts/evaluations/quality_v4_url_policy_v2/summary.json).
- [Kiểm tra UI desktop/mobile trước khi thiết kế lại, không gọi API LLM](../../artifacts/ui/baseline-v4/verification.json).

Artifacts được giữ cục bộ; tài liệu này lưu số liệu và giới hạn chính để đọc độc lập. Tiếp theo cần nhãn người hoặc nguồn xác minh độc lập, xử lý cảnh báo nhầm giáo dục, kiểm tra lại cấu hình có RAG và cải thiện URL trên dữ liệu phát triển phù hợp trước khi khóa test.
