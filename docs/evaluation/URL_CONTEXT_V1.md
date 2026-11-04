# Bộ đánh giá URL và ngữ cảnh v1

Ngày tạo: 03/11/2026. Đã dựng **160 URL nguồn thực và 200 ca ghép ngữ cảnh, tổng cộng 360 đầu vào**. Khi tạo pack chưa chạy model, chưa gọi API hoặc có F1; lượt thực nghiệm được đăng ký riêng sau đó. Mục tiêu là kiểm tra giả thuyết “thông tin model URL giúp LLM” trên đúng nhiệm vụ, cho phép cả kết quả cải thiện lẫn suy giảm.

**Lượt dev đã hoàn tất, tổng hợp ngày 04/11/2026:** `artifacts/evaluations/url_context_dev_live_v1/execution.json` khóa 120 đầu vào dev, ba lượt cho mỗi cấu hình LLM (720 yêu cầu), DeepSeek-V4-Flash, temperature 0,1, trần 8.192 token và timeout 90 giây. Model URL dùng ngưỡng đã có, không chọn lại. Đã đủ 720 lần thử, giữ nguyên 3 lỗi cắt đầu ra; `metrics_ready=true` và `stop_reason=all_calls_completed`. [Kết quả và phân tích đánh đổi](URL_CONTEXT_DEV_RESULTS_V1.md): F1 URL đứng riêng tăng nhưng báo nhầm tăng, F1 hành động trong thông điệp giảm. Test chưa chạy trong lượt này.

Mở [README bộ dữ liệu](../../data/annotation/url_context_v1/README.md), [CSV nội dung và nhãn](../../data/annotation/url_context_v1/reference_review.csv), [protocol](../../data/annotation/url_context_v1/protocol.json) và [kiểm tra dữ liệu](../../data/annotation/url_context_v1/audit.json).

## Điểm khác với bộ 51 SMS

Bộ trước đánh giá **hành vi trong thông điệp** bằng nhãn AI; phần lớn mẫu không có tài liệu RAG và nhiều mẫu không có URL. Bộ này đánh giá riêng rủi ro URL và cách kết hợp nó với ngữ cảnh. Nó bổ sung cho bộ SMS, không thay bộ SMS và không so trực tiếp F1 giữa hai bộ.

| Thành phần | Dev | Test theo split nguồn | Tổng |
|---|---:|---:|---:|
| URL thực, một URL/một miền | 40: 20 dương, 20 âm | 120: 60 dương, 60 âm | 160 |
| Ca đối chiếu ngữ cảnh | 80, ghép từ 16 URL dev | 120, ghép từ 24 URL test | 200 |
| Đầu vào mỗi cấu hình LLM | 120 | 240 | 360 |

40 URL dùng cho ngữ cảnh là tập con của 160 URL. Vì thế 360 đầu vào **không phải 360 quan sát độc lập**. Khi ước lượng bất định phải nhóm theo tên miền; các dạng câu mẫu còn được dùng chung, nên chỉ coi phần ghép là chẩn đoán có kiểm soát.

## Nguồn URL và chọn mẫu

PhishVN v3.1.0, DOI `10.17632/b97hxbxtpd.4`, archive được kiểm tra SHA-256 và manifest. Đã khôi phục fingerprint `d3d1ee19f42b` của cấu hình huấn luyện từ notebook/gói inference để đối chiếu các split. Chỉ dùng gold/silver; không dùng bronze trong bộ này.

| Nguồn / tier / nhãn nguồn | Dev | Test |
|---|---:|---:|
| Tín nhiệm mạng / silver / dương | 20 | 30 |
| Tín nhiệm mạng / gold / dương | 0 | 30 |
| Tín nhiệm tổ chức / gold / âm | 5 | 15 |
| Tín nhiệm website / gold / âm | 5 | 15 |
| Tranco Việt Nam / silver / âm | 5 | 15 |
| Tranco toàn cầu / silver / âm | 5 | 15 |

Quota được đặt trước dự đoán. Trong từng nhóm, chọn tên miền theo hash với seed cố định rồi chọn một URL đại diện; không dùng score ML, lỗi LLM, độ bất đồng hoặc chọn lại seed theo kết quả. Tranco giúp giữ các URL lành mà model có thể báo nhầm, không chỉ lấy tên miền quen thuộc dễ nhận biết.

Đã kiểm tra không trùng miền train/dev/test. Loại 80 miền thuộc các danh sách URL đã chọn trong các lượt LLM PhishVN trước; danh sách tệp và hash nằm trong protocol. **Toàn bộ val/test PhishVN đã từng được chạy ML và phân tích**, nên bộ này là tái sử dụng holdout để chẩn đoán, không phải test bên ngoài mới. Cũng không xác định được mức độ URL đã xuất hiện trong dữ liệu tiền huấn luyện LLM.

Gold/silver là tier của nguồn, không phải dự án xác minh lại từng URL. Theo datasheet, nhãn positive có phạm vi lừa đảo/lạm dụng rộng hơn credential phishing. Nhãn lịch sử không chứng minh website còn nguy hiểm hoặc còn hoạt động hiện tại. Dev chỉ có silver dương do split validation nguồn không có gold dương; vẫn phải báo kết quả test theo tier. Nguồn dương và âm khác nhau, nên lệch nguồn chưa được loại bỏ. Tỷ lệ 50/50 cũng không đại diện tỷ lệ sử dụng thực tế.

## Ba nhãn riêng cho mỗi ca

| Trường | Cách xác định |
|---|---|
| `url_risk` | Nhãn URL của nguồn: 1 hoặc 0, giữ nguyên giữa các ngữ cảnh |
| `message_behavior` | Hành vi lấy bí mật theo nội dung tự soạn: 1; giáo dục không yêu cầu làm theo: 0; lời mời mở link trung tính: UNKNOWN |
| `action_risk` | Theo định nghĩa chẩn đoán: yêu cầu lấy bí mật **hoặc** yêu cầu mở URL nhãn dương → 1; chỉ trích trong bài học → 0 |

`action_risk=0` chỉ có nghĩa là không thỏa hai điều kiện đã định, không xác nhận người gửi hoặc giao dịch an toàn. Nhãn hành vi và hành động là nhãn theo thiết kế, chưa được người chấm độc lập. Không được dùng nhãn URL để tuyên bố câu chữ của người gửi tự nó có hành vi lừa đảo.

Mỗi URL trong nhóm đối chiếu có năm biến thể, với cùng đường dẫn thật:

| Ngữ cảnh | URL nhãn 0: hành vi / hành động | URL nhãn 1: hành vi / hành động |
|---|---|---|
| Lời mời mở đường dẫn trung tính | UNKNOWN / 0 | UNKNOWN / 1 |
| Yêu cầu gửi mật khẩu và OTP cho người nhắn | 1 / 1 | 1 / 1 |
| Trích đường dẫn để học, yêu cầu không mở | 0 / 0 | 0 / 0 |
| Yêu cầu lấy bí mật + injection ép LOW | 1 / 1 | 1 / 1 |
| Bài học + injection ép HIGH | 0 / 0 | 0 / 0 |

Nhóm đầu tạo cơ hội đo đóng góp thông tin URL khi văn bản không đủ. Các nhóm sau kiểm tra chiều ngược lại: URL lành không được “rửa sạch” yêu cầu lấy OTP; URL xấu không được biến bài cảnh báo thành yêu cầu lừa đảo. Mẫu injection có ở cả hai lớp. Câu chữ dev/test khác nhau, nhưng vẫn chia sẻ vai trò ngữ nghĩa; không tuyên bố tách toàn bộ họ kịch bản.

Phần ghép không chứng minh các URL từng được gửi với nội dung đó. Đây không phải SMS/email thu được từ chiến dịch thật. Trường `reference_kind` ghi rõ nguồn gốc này.

## So sánh công bằng

Ba cấu hình cần báo: **model URL riêng**, **LLM**, **LLM + URL**. Model URL riêng chỉ có mục tiêu URL; không tự coi nó hiểu ngữ cảnh. So sánh nó với LLM + URL để kiểm tra LLM có thực sự đóng góp thêm hay chỉ lặp lại ML.

Hai cấu hình LLM dùng cùng [system prompt](../../data/annotation/url_context_v1/system_prompt.txt), schema ba chiều, văn bản và URL. Khác biệt duy nhất về thông tin là danh sách `url_model` rỗng hoặc có điểm/ngưỡng của model. Không gửi nhãn nguồn, tier, category, lý do, tên split hoặc ID cho provider. Đây là prompt nghiên cứu mới, **không phải điểm của ứng dụng `message-v3`**.

Chấm riêng:

- URL-only: F1, Precision, Recall, FPR, Accuracy, Coverage đối với nhãn nguồn.
- Ngữ cảnh: các chỉ số trên theo từng chiều; reference UNKNOWN báo riêng, không ép thành nhãn âm.
- Các nhóm đối chứng: link trung tính; URL lành nhưng xin bí mật; URL rủi ro trong bài học; injection.
- Theo nguồn/tier; các nhóm chỉ một lớp cần đọc số đếm và các chỉ số có mẫu số xác định.
- Cặp LLM → LLM + URL: bao nhiêu ca sửa đúng, bao nhiêu ca làm sai thêm. Chênh lệch F1 phải đọc cùng FPR và coverage.
- Lỗi đầu ra, thời gian và token khi chạy API. F1 lớp dương vẫn có thể bỏ qua UNKNOWN ở lớp âm, nên không bỏ các cột accuracy/coverage/lỗi.

Khuyến nghị ba lượt LLM mỗi cấu hình, báo riêng từng lượt và trung bình/độ lệch chuẩn. Nếu chạy toàn bộ, đó là **2.160 yêu cầu API**; riêng dev là 720 và đã hoàn tất. Phần test 1.440 yêu cầu chưa chạy. Model URL có thể tính một lần trên 160 URL rồi dùng lại. Trước mỗi thí nghiệm cần chốt execution manifest gồm model, ngưỡng, hash runner, số lượt, tham số sinh, trần gọi và chính sách lỗi. Có thể chọn ngân sách khác trước lần chạy đầu của thí nghiệm đó; phải ghi rõ trong manifest, không đổi sau khi thấy kết quả.

## Công cụ đã có

Xác minh pack, không suy luận model/API:

```bash
.venv/bin/python -m evaluation.url_context_pack verify \
  --out data/annotation/url_context_v1
```

Dựng lại bằng quy tắc đã định vào thư mục mới, không đọc score ML:

```bash
.venv/bin/python -m evaluation.url_context_pack prepare \
  --out data/annotation/url_context_v1_rebuild
```

Công cụ [url_context_score.py](../../evaluation/url_context_score.py) nhận JSONL dự đoán lưu sẵn. Mỗi dòng có `id`, `arm` (`llm_only`, `llm_url`, `url_model`), `repeat` (LLM từ 1; ML là 0), `status` (`ok`/`error`). Phản hồi `ok` có `outputs` chứa đủ ba trường với mức `HIGH`, `WARNING`, `LOW` hoặc `UNKNOWN`; ML để hai chiều ngữ cảnh là UNKNOWN. Phản hồi lỗi có `error_code`, không kèm dự đoán dùng được. `id` là khóa lưu cục bộ, không được gửi vào prompt.

```bash
.venv/bin/python -m evaluation.url_context_score \
  --pack data/annotation/url_context_v1 --split dev \
  --predictions PATH_TO_REAL_PREDICTIONS.jsonl --repetitions 3 \
  --out artifacts/evaluations/url_context_dev_v1/summary.json
```

Thiếu dự đoán thì `metrics_ready=false`, `metrics=null`; không lấy phần đã chạy làm kết quả hoàn tất. Trùng ID/cấu hình/lượt hoặc dự đoán sai schema bị từ chối. Lỗi trên mẫu dương vẫn làm giảm Recall/F1. Công cụ nhập chỉ kiểm chứng cấu trúc/số học, **không xác thực rằng file đó thực sự đến từ API**; kết quả chính cần checkpoint và execution manifest của runner.

Runner [url_context_run.py](../../evaluation/url_context_run.py) dùng schema mới, cùng validator cho hai cấu hình. Nó khóa cấu hình trước suy luận, lưu journal trước mỗi yêu cầu và checkpoint sau phản hồi. Mỗi lượt chỉ thử một lần; khi tiếp tục sau ngắt, yêu cầu đã ghi journal nhưng thiếu phản hồi được giữ là `INTERRUPTED_REQUEST`, không tự gửi lại. Dừng khi gặp lỗi HTTP cần xử lý hoặc ba lỗi liên tiếp. Resume sai cấu hình bị từ chối.

Chuẩn bị model URL cục bộ và đăng ký cấu hình, chưa gọi API:

```bash
.venv/bin/python -m evaluation.url_context_run --split dev --repetitions 3 \
  --out artifacts/evaluations/url_context_dev_live_v1
```

Thêm `--live` để chạy/tiếp tục các lượt đã đăng ký; không gửi lại checkpoint đã có:

```bash
.venv/bin/python -m evaluation.url_context_run --split dev --repetitions 3 \
  --out artifacts/evaluations/url_context_dev_live_v1 --live
```

Sau khi đủ lượt, kiểm chứng bằng scikit-learn và tạo bảng/biểu đồ vào thư mục mới:

```bash
.venv/bin/python scripts/evaluation/report_url_context.py \
  --run artifacts/evaluations/url_context_dev_live_v1 \
  --out artifacts/evaluations/url_context_dev_results_v1
```

Các phiếu mù [A](../../data/annotation/url_context_v1/reviewer_a.csv) và [B](../../data/annotation/url_context_v1/reviewer_b.csv) để trống. Người chấm cần tuân thủ ba mục tiêu và có nguồn để xét lại nhãn URL; chỉ nhìn chuỗi URL không đủ xác minh nhãn. Các phiếu này không tự tạo human gold khi chưa có review/phân xử thật.

## Khi nào mới nói LLM + URL tốt hơn?

Chỉ khi cùng mục tiêu, cùng mẫu và điều kiện chạy cho thấy lợi ích ổn định, báo đầy đủ đánh đổi báo nhầm/coverage và số ca bị làm sai thêm. Nếu chỉ cải thiện ở nhóm link trung tính, kết luận giới hạn ở nhóm đó. Nếu model URL riêng tốt ngang hoặc tốt hơn cấu hình kết hợp, phải báo điều đó. Nếu không cải thiện, giữ kết quả và xem lại chất lượng model, ngưỡng hoặc cách dùng điểm; không thay bộ test để hợp thức hóa giả thuyết.
