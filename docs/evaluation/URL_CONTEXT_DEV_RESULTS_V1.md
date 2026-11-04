# Kết quả đánh giá URL và ngữ cảnh — dev v1

Ngày tổng hợp: **04/11/2026**. Đã hoàn tất **720 lượt API**, trên 120 đầu vào dev × 2 cấu hình × 3 lần lặp. **LLM + URL tăng F1 khi xét URL đứng riêng, nhưng tăng báo nhầm; khi đánh giá hành động trong tin nhắn, F1 giảm.** Chưa có cơ sở kết luận cấu hình kết hợp tốt hơn một cách tổng quát.

## Dữ liệu và điều kiện so sánh

- 40 URL PhishVN thuộc 40 tên miền: 20 nhãn dương silver và 20 nhãn âm gold/silver. Nhãn là nhãn lịch sử của nguồn, chưa xác minh lại trạng thái website hiện tại.
- 80 thông điệp tự soạn, dùng lại 16 URL trong nhóm trên, mỗi URL có 5 ngữ cảnh: link trung tính, xin bí mật, bài học cảnh báo và hai biến thể prompt injection. Không phải 80 thông điệp thu được từ chiến dịch thật.
- Hai cấu hình dùng cùng DeepSeek-V4-Flash, system prompt, schema, văn bản và URL; khác biệt thông tin là có hoặc không có điểm/ngưỡng model URL. Không đưa nhãn, nguồn hay tier vào prompt. Không dùng RAG trong lượt này.
- Temperature 0,1; trần đầu ra 8.192 token; timeout 90 giây; 2 yêu cầu đồng thời. Ngưỡng model giữ nguyên: WARNING = **0,11384317278862**, HIGH = **0,47364333271980286**.
- Cấu hình và hash được lưu trước suy luận. Không đổi mẫu, prompt, ngưỡng hoặc nhãn giữa các lượt; không gọi lại phản hồi lỗi.
- Model URL chạy cục bộ trên 40 URL duy nhất, dùng lại điểm cho các ngữ cảnh. Nó chỉ được chấm về URL, không được coi là mô hình hiểu hành vi tin nhắn.

Đây là so sánh có kiểm soát về **đóng góp của thông tin model URL**. Prompt nghiên cứu khác `message-v3`, nên các số dưới đây chưa phải chất lượng ứng dụng đầu cuối. [Phương pháp và nguồn dữ liệu](URL_CONTEXT_V1.md).

## Kết quả chính

F1 của lớp dương, thang 0–100%; trung bình ± độ lệch chuẩn giữa **3 lần lặp**, không phải 3 tập dữ liệu độc lập.

| Mục tiêu | Số mẫu nhị phân mỗi lượt | LLM | LLM + URL | Chênh F1 (điểm %) |
|---|---:|---:|---:|---:|
| Rủi ro URL đứng riêng | 40 | 62,65% ± 5,83 | 76,66% ± 1,55 | +14,01 |
| Rủi ro URL khi nằm trong thông điệp | 80 | 76,42% ± 3,64 | 70,20% ± 1,65 | −6,22 |
| Hành vi lấy bí mật trong thông điệp | 64 | 95,96% ± 0,88 | 97,47% ± 0,86 | +1,51 |
| Rủi ro khi làm theo thông điệp | 80 | 96,31% ± 3,20 | 92,67% ± 0,62 | −3,64 |

16 thông điệp link trung tính có nhãn hành vi UNKNOWN, báo riêng và không ép thành nhãn âm. Nhãn rủi ro hành động được đặt theo thiết kế: xin bí mật hoặc yêu cầu mở URL nhãn dương là dương; chỉ trích dẫn để học là âm. Đây chưa phải nhãn do người chấm độc lập xác nhận.

Không thể đọc F1 tách khỏi báo nhầm và tỷ lệ có kết luận:

| Mục tiêu | FPR: LLM → LLM + URL | Coverage: LLM → LLM + URL | Accuracy: LLM → LLM + URL |
|---|---:|---:|---:|
| URL đứng riêng | 1,67% → **50,00%** | 56,67% → 95,83% | 53,33% → 70,00% |
| URL trong thông điệp | 20,00% → **85,00%** | 54,17% → 98,33% | 44,17% → 55,83% |
| Hành vi thông điệp | 7,29% → 5,21% | 98,96% → 100,00% | 95,31% → 97,40% |
| Rủi ro hành động | 4,17% → **15,83%** | 92,50% → 99,58% | 90,42% → 91,67% |

FPR là tỷ lệ cảnh báo trên toàn bộ mẫu nhãn âm. Coverage là tỷ lệ đầu vào có kết luận nhị phân. Accuracy dùng toàn bộ mẫu có nhãn nhị phân làm mẫu số; UNKNOWN và lỗi không được tính là đúng. WARNING/HIGH cùng tính là cảnh báo, LOW là không cảnh báo. Các bảng này chưa đánh giá riêng tính đúng đắn của mức HIGH so với WARNING.

Với `U+` là số mẫu dương bị UNKNOWN/lỗi, F1 được tính bằng `2TP / (2TP + FP + FN + U+)`. UNKNOWN ở lớp dương vẫn làm giảm Recall/F1; UNKNOWN ở lớp âm không làm tăng FP nhưng làm giảm coverage/accuracy. Vì vậy FPR thấp của LLM riêng một phần đi cùng việc chưa đưa ra kết luận, không đồng nghĩa nhận diện đúng gần hết URL lành.

Model URL riêng trên 40 URL có F1 **72,73%**, Recall **100%**, FPR **75%**: bắt được 20/20 mẫu dương nhưng cảnh báo 15/20 mẫu âm. Cấu hình kết hợp giảm báo nhầm so với model URL riêng, song vẫn cảnh báo trung bình 10/20 URL nhãn âm mỗi lượt. Baseline luôn cảnh báo trên tập cân bằng có F1 **66,67%**, FPR **100%**; F1 cao hơn LLM riêng không có nghĩa baseline đó hữu ích hơn.

## Phân tích và độ bất định

Trên URL đứng riêng, thêm model URL sửa đúng lần lượt **12 / 12 / 8** ca và làm sai thêm **4 / 4 / 4** ca. Chuyển từ UNKNOWN sang kết luận đúng được tính là sửa đúng. Đây là lợi ích quan sát được, đi kèm đánh đổi báo nhầm rõ rệt.

Bootstrap ghép cặp theo tên miền, lấy lại mẫu 2.000 lần và giữ các cấu hình/lần lặp cùng nhau, cho khoảng 95% của chênh F1:

| Mục tiêu | Chênh F1: LLM + URL − LLM (điểm %) |
|---|---:|
| URL đứng riêng | [−6,38; +33,66] |
| URL trong thông điệp | [−23,79; +8,67] |
| Hành vi thông điệp | [−1,52; +4,99] |
| Rủi ro hành động | [−8,14; +0,51] |

Các khoảng đều chứa 0. Chưa đủ bằng chứng về một cải thiện ổn định ngoài mẫu hiện có. Khoảng bootstrap phụ thuộc nhãn đã cố định, không bao phủ sai nhãn nguồn, việc dùng chung mẫu câu hay độ lệch khi triển khai.

Nhóm link trung tính cho thấy vấn đề rõ: LLM + URL có FPR **75% / 75% / 87,5%** trên 8 mẫu âm. Ngược lại, hai cấu hình đều xử lý đúng toàn bộ 16 ca trích URL rủi ro trong bài học ở cả ba lượt. Nhóm xin bí mật và injection cũng đạt điểm cao, nhưng dùng ít mẫu câu tự soạn; chưa chứng minh chống injection tổng quát hoặc khả năng nhận diện lừa đảo thực tế.

Model URL riêng báo nhầm ở cả bốn nguồn âm: Tín nhiệm tổ chức 4/5, Tín nhiệm website 3/5, Tranco 3/5 và Tranco Việt Nam 5/5. Đây là dấu hiệu cần rà soát model/ngưỡng theo nguồn. Chỉ từ các số đếm nhỏ này chưa thể khẳng định nguyên nhân là model học đặc điểm nguồn thay vì đặc điểm lừa đảo.

## Kiểm chứng và giới hạn

- Đủ 720 lần thử API: LLM có 357 phản hồi hợp lệ và **3 OUTPUT_TRUNCATED**; LLM + URL có 360 phản hồi hợp lệ. Giữ nguyên 3 lỗi trong điểm số, không thay bằng lượt gọi lại.
- Đã đối chiếu số học bằng scikit-learn, kiểm tra hash dữ liệu/model/prompt, payload và checkpoint. Kiểm tra trích nguyên văn chưa xác nhận chất lượng lập luận; lời giải thích chưa được chấm tay.
- Token usage ghi nhận: LLM **860.971**, LLM + URL **758.221**, tổng **1.619.192**; chưa đối chiếu hóa đơn. Trung vị thời gian gọi tương ứng **7,51 giây / 6,03 giây**, không phải độ trễ ứng dụng đầu cuối.
- Nguồn nhãn dương và âm khác nhau; dev dương chỉ có silver. Lệch nguồn chưa được loại bỏ. PhishVN đã từng được đánh giá ML, nên đây là chẩn đoán trên dữ liệu tái sử dụng, không phải holdout bên ngoài mới.
- Chọn mẫu trước dự đoán, không lọc theo cấu hình thắng. Tuy nhiên câu mẫu và nhãn ngữ cảnh vẫn do dự án tạo; chưa có bộ thông điệp thực với nhãn độc lập.
- Tỷ lệ lớp cân bằng không đại diện tỷ lệ lừa đảo khi sử dụng. Không suy rộng Precision hay FPR từ các nhóm nhỏ thành bảo đảm vận hành.
- **Chưa chạy phần test của bộ này.** Không so trực tiếp F1 với bộ 51 SMS trước vì khác dữ liệu, mục tiêu và prompt.

## Hướng cải tiến từ kết quả

1. **Rà model URL trước:** kiểm tra các URL âm bị chấm cao, đặc trưng suy luận có khớp huấn luyện không, phân bố score theo nguồn/tier và cách chọn ngưỡng cũ. Chưa quy kết nguyên nhân khi chưa kiểm tra.
2. Đăng ký tiêu chí vận hành trên dữ liệu phát triển phù hợp, ví dụ tối đa hóa Recall dưới một giới hạn FPR xác định trước. Dữ liệu hiệu chỉnh cần đủ mẫu âm theo nguồn; không chọn ngưỡng chỉ để thắng 40 URL đã xem. Nếu hiệu chỉnh xác suất, tham số hiệu chỉnh cũng chỉ học trên dữ liệu phát triển.
3. Kiểm thử cách kết hợp điểm URL với ngữ cảnh: điểm cao chưa đủ biến một lời mời trung tính thành kết luận chắc chắn; giữ riêng rủi ro URL, hành vi và mức chưa đủ thông tin. Đo lại số cảnh báo nhầm, bỏ sót và abstention theo cùng quy tắc.
4. Sau khi khóa phiên bản/tiêu chí mới, đánh giá một lần trên phần test chưa gọi LLM, báo cả kết quả bất lợi. Muốn kết luận cho người dùng thực vẫn cần thông điệp thực có nhãn được rà soát độc lập và dữ liệu URL mới ngoài tập đã phân tích.

Các mục trên là đề xuất tiếp theo; chưa thay model hoặc ngưỡng vận hành dựa trên kết quả này.

## Tệp kết quả

- [Bảng đầy đủ: từng lượt, nguồn/tier và các nhóm đối chứng](../../artifacts/evaluations/url_context_dev_results_v1/report.md).
- [Biểu đồ F1 và FPR cho URL đứng riêng và rủi ro hành động](../../artifacts/evaluations/url_context_dev_results_v1/comparison.png) — hai mục tiêu còn lại có trong bảng trên.
- [Số liệu máy đọc](../../artifacts/evaluations/url_context_dev_results_v1/summary.json), [bootstrap](../../artifacts/evaluations/url_context_dev_results_v1/bootstrap.json), [biên bản kiểm chứng](../../artifacts/evaluations/url_context_dev_results_v1/verification.json).
- [Các ca cần rà soát](../../artifacts/evaluations/url_context_dev_results_v1/cases_to_review.json).
- [Cấu hình đã đăng ký](../../artifacts/evaluations/url_context_dev_live_v1/execution.json), [checkpoint dự đoán](../../artifacts/evaluations/url_context_dev_live_v1/predictions.jsonl).

Tệp trong `artifacts/` là kết quả cục bộ; có thể không đi kèm bản clone Git. Tài liệu này giữ các số liệu và giới hạn chính để đọc độc lập.
