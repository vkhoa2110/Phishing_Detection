# Ngưỡng cảnh báo URL: kiểm tra mức báo nhầm và validation cần bổ sung

Hoàn tất **05/11/2026**. Đã so sánh **7 chính sách cảnh báo** trên 7.266 điểm validation đã lưu của **đúng model XGBoost đang dùng trong ứng dụng**. Không huấn luyện lại, không gọi LLM, không dùng URL test để chọn ngưỡng và không thay ngưỡng ứng dụng.

**Kết luận:** tăng ngưỡng có thể giảm báo nhầm nhưng làm mất nhiều mẫu dương. Validation hiện có chưa đủ đại diện để chốt một ngưỡng mới. Đặc biệt, Precision cao trên toàn validation không bảo đảm Precision cao ở gold/silver hoặc trong lưu lượng sử dụng thật.

## 1. Cách kiểm tra

- Kiểm tra SHA-256 của model/config/archive so với manifest lịch sử; đối chiếu toàn bộ ID, URL, nguồn, tier và nhãn với file validation chính thức. Không đọc bảng train/test hay dự đoán test trong lượt này.
- Giữ nguyên score, model, hai mốc cũ và nhãn nguồn. Score thô chưa phải xác suất đã hiệu chỉnh.
- Ba đối chứng: WARNING cũ **0,11384317278862**, HIGH hiện hành **0,47364333271980286**, cố định **0,5**.
- Bốn chính sách mới: chọn ngưỡng nhỏ nhất sao cho FPR trên URL âm trong nhóm chọn ngưỡng không quá **5% hoặc 1%**, xét toàn nhóm hoặc từng nguồn âm. Dùng **một ngưỡng chung** khi suy luận, không yêu cầu biết nguồn dataset của URL người dùng.
- Chỉ dùng điểm/nguồn của URL âm để chọn bốn ngưỡng mới; không tối ưu theo F1/Recall dương. Điểm bằng ngưỡng vẫn là cảnh báo; loại toàn bộ điểm hòa ở biên khi cần. Nếu không có ngưỡng khả thi trong [0,1], ghi không khả thi, không gán URL là an toàn.
- Chia validation thành **5 nhóm theo hash tên miền**; mỗi lần chọn ngưỡng bằng 4 nhóm và chấm trên nhóm tên miền còn lại. Một tên miền luôn ở cùng nhóm. Báo toàn bộ chính sách, không chọn seed/cấu hình thắng bằng test.

Đây là **cross-fit ngưỡng trên dev lịch sử**. Model, early stopping và các ngưỡng cũ đã sử dụng validation này từ trước, nên phép chia lại không biến dữ liệu thành test độc lập. Kết quả trên nhóm giữ ngoài giúp kiểm tra việc chọn ngưỡng, chưa loại bỏ thiên lệch chọn model hoặc thích nghi với dev.

Các chỉ số dưới đây chỉ đo **có phát cảnh báo URL hay không**. URL không được cảnh báo không tự có nghĩa là LOW/an toàn: app v4 còn vùng UNKNOWN. Không dùng F1 nhị phân của bảng này làm thước đo đầy đủ cho chính sách ba mức.

## 2. Kết quả theo tên miền giữ ngoài bước chọn ngưỡng

Validation có **1.561 URL âm** và **5.705 URL dương**, trong đó **5.681 dương bronze**. Chỉ có **24 dương gold/silver**.

| Chính sách | Báo nhầm / 1.561 URL âm | FPR | Phát hiện / 24 dương gold/silver | Recall gold/silver |
|---|---:|---:|---:|---:|
| WARNING cũ | 1.099 | 70,40% | 24 | 100,00% |
| HIGH hiện hành | 243 | 15,57% | 23 | 95,83% |
| Ngưỡng 0,5 | 180 | 11,53% | 22 | 91,67% |
| Nhắm FPR toàn nhóm ≤5% | 80 | 5,12% | 20 | 83,33% |
| Nhắm FPR toàn nhóm ≤1% | 17 | 1,09% | 14 | 58,33% |
| Nhắm FPR từng nguồn ≤5% | 53 | 3,40% | 19 | 79,17% |
| Nhắm FPR từng nguồn ≤1% | 6 | 0,38% | 10 | 41,67% |

“Nhắm ≤5%” là ràng buộc thực nghiệm **trên 4 nhóm chọn ngưỡng**, không phải bảo đảm trên nhóm giữ ngoài. Vì vậy mức 5,12% hoặc 1,09% không mâu thuẫn với quy tắc chọn. Với chính sách theo từng nguồn, FPR Tranco giữ ngoài vẫn là **5,13%** ở mục tiêu 5%; chính sách mục tiêu toàn nhóm 5% có FPR riêng Tranco **7,81%**.

Ngưỡng fit lại bằng toàn validation của hai chính sách toàn nhóm 5%/1% lần lượt khoảng **0,719511 / 0,904335**. Các số này **không phải năm ngưỡng dùng để tạo bảng cross-fit**, cũng chưa là ngưỡng triển khai. Ví dụ chính sách toàn nhóm 5% dùng năm ngưỡng từ khoảng **0,705260 đến 0,744719**.

Không thể vừa yêu cầu giảm báo nhầm rất mạnh vừa mặc định Recall được giữ nguyên. Ở dữ liệu này, chuyển từ HIGH hiện hành sang chính sách toàn nhóm 5% giảm 163 cảnh báo nhầm, nhưng phát hiện ít hơn 3/24 dương gold/silver. Mỗi mẫu dương tương ứng khoảng **4,17 điểm % Recall**, nên cỡ nhóm còn quá nhỏ để diễn giải thay đổi vài mẫu như cải thiện ổn định.

## 3. Vì sao HIGH có Precision khoảng 95% mà người dùng vẫn gặp báo nhầm?

Tại đúng ngưỡng HIGH hiện hành:

- Toàn validation: **4.637 TP, 243 FP**, Precision **95,02%**.
- Chỉ gold/silver: **23 TP, 243 FP**, Precision **8,65%**.

Hai nhóm giữ nguyên tập âm và số FP; chỉ khác phần dương. Validation toàn tập có nhiều dương bronze hơn, nên Precision cao hơn rõ rệt. Không dùng Precision 95,02% đó để khẳng định “mỗi cảnh báo của ứng dụng có 95% khả năng đúng”. Tên HIGH là mức cảnh báo, không phải khoảng tin cậy 95%.

Ví dụ **giả định** chỉ 1% URL đầu vào có nhãn dương và các tỷ lệ có điều kiện đo trên validation chuyển nguyên sang lưu lượng này:

| Chính sách | TP dự kiến / 10.000 URL | FP dự kiến | Bỏ sót dự kiến | Precision dự kiến |
|---|---:|---:|---:|---:|
| HIGH hiện hành | 95,8 | 1.541,1 | 4,2 | 5,85% |
| Nhắm FPR toàn nhóm ≤5% | 83,3 | 507,4 | 16,7 | 14,11% |
| Nhắm FPR toàn nhóm ≤1% | 58,3 | 107,8 | 41,7 | 35,11% |

Công thức: `Precision = prior × Recall / (prior × Recall + (1 − prior) × FPR)`. Dùng Recall gold/silver và hỗn hợp URL âm hiện có. **Đây là bài toán giả định để phân tích độ nhạy**, không phải tỷ lệ phishing đo trong người dùng thật, dự báo lưu lượng hay một kết quả kiểm thử triển khai. Nhãn lịch sử còn có thể sai và bao gồm phạm vi lừa đảo/abuse rộng hơn phishing lấy thông tin đăng nhập.

## 4. Đề xuất vận hành và cách lấy validation mới

Chưa đưa một trong bốn ngưỡng mới vào app chỉ vì bảng dev có FPR thấp hơn. Giữ phân biệt **cảnh báo URL**, **hành vi trong thông điệp** và **chưa đủ thông tin**; không biến điểm URL thấp thành bảo đảm tin nhắn an toàn. Chính sách hiện tại và hạn chế được ghi ở [QUALITY_V4.md](../architecture/QUALITY_V4.md).

Chính sách nhắm FPR 5% là **ứng viên để kiểm tra trên dữ liệu mới**, không phải cấu hình đã đạt yêu cầu vận hành. Mục tiêu sản phẩm cần chốt trước: mức báo nhầm có thể chấp nhận, mức bỏ sót, phạm vi người dùng và cách xử lý UNKNOWN. Báo các khoảng bất định và tỷ lệ trả UNKNOWN; không giảm cảnh báo bằng cách gọi tất cả ca khó là an toàn.

Đợt dữ liệu tiếp theo nên có hai phần độc lập, mục tiêu ban đầu như sau:

| Phần | Dương mục tiêu | Âm mục tiêu | Cách sử dụng |
|---|---:|---:|---|
| Calibration mới | 200 miền | 400 miền | Chọn ngưỡng/quy tắc sau khi xác minh nhãn |
| Test thu ở giai đoạn sau | 200 miền | 400 miền | Khóa riêng; chỉ mở sau khi chốt pipeline và ngưỡng |

Đây là **chỉ tiêu thu thập, chưa phải 1.200 URL đã có nhãn**. Mỗi miền/campaign thuộc một phần; kiểm tra giao với toàn bộ train/validation/test, kho uy tín, URL/ngữ cảnh và các tập đã dùng để sửa model. Không chuyển 487 dương test PhishVN cũ sang validation mới. URL đã xem có thể dùng chẩn đoán, không đổi tên thành holdout mới.

Yêu cầu cho đợt thu thập:

1. **Ghi thời gian và nguồn bằng chứng.** Mỗi URL có `id`, URL chuẩn hóa, registrable domain, campaign nếu biết, ngày thu thập, nguồn/giấy phép, ngày của bằng chứng, nhãn, người đánh giá và lý do. Giữ snapshot/hash của bằng chứng; báo không đủ căn cứ nếu không thể xác minh tại thời điểm thu thập.
2. **Dương đa dạng, cùng định nghĩa lớp.** Giả ngân hàng/định danh, giao hàng, tuyển dụng, đầu tư/thu hồi tiền, hỗ trợ kỹ thuật, chiếm tài khoản; ghi riêng credential phishing, chiếm tiền, phát tán mã độc hoặc abuse khác. Nếu đổi định nghĩa nhãn so với PhishVN thì phải báo thành nhiệm vụ khác.
3. **Âm khó nhưng đã xác minh.** Luồng thanh toán/đăng nhập thật, đường dẫn dài/có query hoặc token, website nhỏ hợp lệ, landing page marketing. Không chỉ lấy tên miền nổi tiếng/trang chủ. Nguồn công bố không được tự đồng nghĩa với nhãn, và không chọn URL theo điểm model.
4. **Nhãn độc lập trước điểm model.** Hai người đọc bằng chứng, không thấy score hoặc quyết định LLM; phân xử bất đồng. AI chỉ hỗ trợ sơ bộ và ghi rõ nguồn nhãn. Ca chưa xác minh giữ UNKNOWN, không ép đủ chỉ tiêu hoặc đổi nhãn cho khớp dự đoán.
5. **Chốt protocol trước mở test.** Khóa dữ liệu, prompt, corpus, model và cách chọn ngưỡng. Báo theo nguồn/loại URL/thời gian cùng số đếm, Recall, FPR, Precision theo tỷ lệ mẫu, coverage và độ bất định theo miền. Test không dùng để chọn lại ngưỡng.

Với chỉ 9 URL âm ở nguồn `tinnhiem_org` hiện tại, 0/9 báo nhầm chưa chứng minh FPR thấp: ngay cả giả định 9 quan sát Bernoulli độc lập và ngưỡng cố định, cận trên một phía 95% khi không gặp lỗi là `1 − 0,05^(1/9) ≈ 28,31%`. Với 400 quan sát âm độc lập và 0 lỗi, cận tương ứng khoảng **0,75%**; nếu có lỗi, phụ thuộc miền hoặc đã chọn ngưỡng trên cùng mẫu thì không được dùng kết luận đó. 400 URL âm tổng cũng không đủ để chứng nhận mức này cho từng nhóm nhỏ. Các chỉ tiêu trên là điểm khởi đầu thực tế, không phải chứng nhận đủ mẫu cho mọi mục tiêu.

## 5. Phần LLM/RAG đã sẵn sàng đến đâu?

Rà lại ngày 05/11/2026:

| Hạng mục | Trạng thái |
|---|---|
| 200 SMS nguồn ngoài, split/phiếu/rubric | Đã có |
| Hai phiếu người gán nhãn SMS | Mỗi phiếu **0/200 nhãn đã điền** |
| 24 truy vấn × 25 nguồn RAG | Đã có 600 cặp, chọn trước ranking |
| Hai phiếu người chấm relevance | Mỗi phiếu **0/600 grade đã điền** |
| Nhãn AI SMS/relevance | Đã có, chỉ dùng diagnostic |
| Pilot v3/v4 cùng điều kiện | Đã chạy 240 lần; [kết quả và giới hạn](../architecture/QUALITY_V4.md) |
| Ablation LLM / URL / RAG với prompt v4 | Chưa chạy; lượt component cũ dùng prompt khác |

Các phiếu đang có: [SMS A](../../data/annotation/objective_v1/classification/sms/annotator_a.csv), [SMS B](../../data/annotation/objective_v1/classification/sms/annotator_b.csv), [relevance A](../../data/annotation/objective_v1/retrieval/annotator_a.csv), [relevance B](../../data/annotation/objective_v1/retrieval/annotator_b.csv). [Rubric và protocol](OBJECTIVE_V1.md) cùng công cụ review/phân xử đã có; không tạo thêm hai danh tính AI để thay hai người.

Việc tiếp theo có thể tiến hành độc lập: hoàn thiện bằng chứng/nhãn cho các ca spam–lừa đảo bất đồng; chấm relevance cho nhóm dev và rubric lời giải thích; chuẩn bị lượt v4 với cùng schema, prompt, bộ kiểm tra và thông số cho bốn cấu hình. Khi payload hai cấu hình giống nhau vì không có URL/nguồn, cần báo rõ và giữ nhóm đối chứng để tách dao động sinh lại khỏi tác dụng RAG. Không thêm đáp án test vào corpus. Các kết quả từ nhãn AI tiếp tục mang nhãn diagnostic.

## 6. Tái lập và bằng chứng

- [Báo cáo đầy đủ từng nguồn](../../artifacts/evaluations/url_calibration_v1/report.md).
- [Summary, năm ngưỡng từng chính sách và các giả định prior](../../artifacts/evaluations/url_calibration_v1/summary.json).
- [Protocol/hash khóa trước tính toán](../../artifacts/evaluations/url_calibration_v1/execution.json).
- [Dự đoán giữ ngoài theo từng URL/chính sách](../../artifacts/evaluations/url_calibration_v1/predictions.csv.gz).
- [Kiểm chứng bằng scikit-learn](../../artifacts/evaluations/url_calibration_v1/verification.json).
- [Bộ chạy](../../evaluation/url_calibration.py), [kiểm thử](../../tests/test_url_calibration.py).

```bash
# Kiểm tra kết quả đã lưu; không gọi API hoặc huấn luyện.
.venv/bin/python -B -m evaluation.url_calibration verify \
  --out artifacts/evaluations/url_calibration_v1

# Tái lập vào thư mục mới; cần snapshot validation/model/archive đúng hash.
.venv/bin/python -B -m evaluation.url_calibration run \
  --out artifacts/evaluations/url_calibration_rebuild
```

Đã đối chiếu **50.862 quyết định** (7 chính sách × 7.266 URL), confusion matrix và Precision/Recall/F1 từng nhóm, fold và hash. **304 kiểm thử offline đạt**; một cảnh báo deprecation Starlette/httpx đã có từ trước. Các kiểm chứng xác nhận số học và cách tách bước chọn ngưỡng, không xác nhận nhãn lịch sử đúng hoặc ứng dụng đã đạt chất lượng ngoài thực tế.
