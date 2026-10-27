# Đánh giá có và không có model URL

**Đánh giá URL có nhãn thật:** công cụ `python -m evaluation.phishvn` dùng PhishVN V4, kiểm tra archive/manifest, khôi phục fingerprint huấn luyện và giữ nguyên train/validation/test theo nguồn. Báo cáo ở [docs/PHISHVN_EVALUATION.md](../docs/PHISHVN_EVALUATION.md). Phần bên dưới là bộ chẩn đoán ngữ cảnh mô phỏng, có mục đích khác.

Bộ `data/vietnamese_messages_v1.jsonl` gồm **60 thông điệp tiếng Việt có URL**: 30 nhãn phishing (`1`), 30 nhãn thông thường (`0`). Sáu nhóm ngân hàng, giao hàng, công việc, mua sắm, cơ quan nhà nước và ngữ cảnh/prompt injection; mỗi nhóm có 5 mẫu mỗi lớp. Đây là dữ liệu mô phỏng do người viết công cụ soạn, chưa được thẩm định độc lập. Nhãn đã cố định trước khi gọi model, dựa vào hành vi trong thông điệp, không phải kết quả dự đoán.

Có sáu cặp `pair_id` dùng cùng URL trong hai ngữ cảnh đối lập, nhằm kiểm tra việc điểm URL lấn át ngữ cảnh. Các mẫu còn lại dùng URL khác nhau. Các miền ví dụ và địa chỉ IP tài liệu được dùng cho tình huống giả lập; một số mẫu có chuỗi URL công khai. Không truy cập website khi đánh giá. Mẫu có URL trông đáng ngờ nhưng chỉ trích dẫn trong bài học phòng chống phishing được gán `0`.

## Năm cấu hình

| Tên trong kết quả | Dữ liệu/quyết định được đo |
|---|---|
| `url_model_only` | Mức cao nhất từ các URL, không phân tích nội dung thông điệp |
| `llm_only` | LLM đọc văn bản có URL; không nhận điểm ML, không áp dụng fusion |
| `llm_with_url_model` | Cùng văn bản và prompt, thêm kết quả ML; lấy nhận định LLM trước fusion |
| `fusion_independent` | Kết hợp model URL với chính đầu ra `llm_only`, không gọi thêm API |
| `fusion_with_url_model` | Kết hợp model URL và đầu ra LLM đã nhận metadata ML, tương ứng hệ thống đầy đủ |

Chỉ tắt `include_ml` trong API của ứng dụng **vẫn còn ML trong fusion**. Công cụ này dùng trực tiếp `LLMService` để có baseline thực sự không chịu ảnh hưởng model URL. Mỗi thông điệp được gọi hai lần, độc lập; không gửi nhãn, lý do gán nhãn hay ID ca kiểm thử cho LLM. Giữ nguyên prompt `baseline-1.0`, model, feature và ngưỡng. Thứ tự ca được xáo trộn bằng seed cố định; thứ tự hai cấu hình được đảo luân phiên sau khi xáo trộn. Tối đa hai lượt đồng thời.

## Chạy lại

Từ thư mục chứa `run.py`, dùng Python 3.12 và gói model thật:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-eval.txt
.venv/bin/python -m pytest -q
```

Chỉ chạy model URL tại máy, không gọi API:

```bash
.venv/bin/python -m evaluation.run --out reports/offline_url_v1
```

Đánh giá cả hai cấu hình LLM, dùng `FPT_API_KEY` trong `.env`. Lệnh này sử dụng API thật và token của tài khoản:

```bash
.venv/bin/python -m evaluation.run --live --max-tokens 4096 --max-new-calls 120 --out reports/url_model_ablation_v1
.venv/bin/python scripts/plot_evaluation.py reports/url_model_ablation_v1
```

Thư mục kết quả đã có trong dự án chứa lần chạy thật. Khi lặp đúng lệnh và cấu hình, kết quả đã checkpoint được tái sử dụng, không gửi lại API. Để tạo lần chạy độc lập mới, chọn thư mục `--out` mới. Dùng `--max-new-calls 2` để giới hạn lượt thử; đó là báo cáo chưa hoàn tất, không phải kết quả toàn bộ bộ test. `--timeout` mặc định 90 giây, `--workers` nhận 1 hoặc 2. Thay đổi model, dữ liệu, mã đánh giá, prompt hoặc tham số cần thư mục kết quả mới.

Ứng dụng hiện có thể đặt `LLM_MAX_TOKENS` khác trong `.env`; công cụ ghi đè có chủ đích bằng `--max-tokens` và ghi giá trị thật vào manifest. Lượt chính dùng 4.096 cho cả hai nhánh. Lượt thử 1.536 token đã xuất hiện phản hồi bị cắt và được lưu riêng tại `reports/pilot_1536_tokens`, không gộp vào kết quả chính.

## Số đo và đầu ra

- `HIGH`/`WARNING`: cảnh báo dương; `LOW`: âm; `UNKNOWN`, lỗi và chưa chạy: abstain.
- Accuracy lấy số dự đoán đúng chia **toàn bộ 60 mẫu**; abstain không được tính đúng. Coverage cho biết tỷ lệ đưa ra được nhãn nhị phân.
- Precision = TP/(TP+FP). Recall lấy **toàn bộ mẫu dương** làm mẫu số, kể cả dương abstain. F1 dùng recall này, tương đương `2TP/(2TP+FP+FN+unknown_positive)`.
- FPR = FP/toàn bộ mẫu âm. `unknown_negative` vẫn được báo riêng, không coi là TN. Mẫu số bằng 0 được ghi `null`/N/A.
- Thống kê theo cặp ghi số mẫu được sửa đúng/làm sai thêm khi đổi cấu hình. Báo cả toàn bộ mẫu và tập có hai lượt LLM thành công; không chỉ chọn các phản hồi thành công để trình bày số đo đẹp hơn.

Đầu ra gồm `report.md`, `summary.json`, `comparison.csv`, `results.jsonl`, `checkpoints.jsonl` và `manifest.json`; biểu đồ PNG/SVG được tạo bằng script riêng. Manifest có SHA-256 dữ liệu, model, mã nguồn và các phiên bản thư viện. Các lỗi HTTP và token được lưu theo từng nhánh, không lưu API key hay header Authorization.

Checkpoint lưu từng phản hồi hoàn tất. Không tự retry lỗi API; dừng sớm khi lỗi xác thực, hết số dư, sai endpoint/model, HTTP 429 hoặc ba lỗi liên tiếp. Khi ngắt tiến trình, request đang bay có thể đã được nhà cung cấp tính token dù chưa nhận được phản hồi. Kết quả có trạng thái pending/lỗi phải được đọc cùng coverage và mã lỗi. Công cụ vẽ biểu đồ so sánh nhận lượt đã hoàn tất đủ 120 lần thử, giữ phản hồi lỗi thành UNKNOWN. CLI đánh giá trả exit code 1 nếu có cặp chưa thành công đầy đủ để nhắc kiểm tra lỗi; điều này không xóa các số đo hoặc tự gọi lại API.

## Phạm vi kết luận

Kết quả cho biết hành vi của cấu hình hiện tại trên bộ chẩn đoán nhỏ, có chủ đích. Không suy rộng thành Accuracy/F1 của model ngoài thực tế; không phải bộ URL được gán nhãn độc lập, không đo độ an toàn thực tế của website, không chứng minh chất lượng trên PhishVN. Dữ liệu có các mẫu đơn giản và miền ví dụ, nên LLM có thể đạt điểm rất cao và model URL có thể gặp phân phối khác dữ liệu huấn luyện. Các cặp kiểm soát còn phụ thuộc nhau. McNemar chỉ mang tính thăm dò, không dùng để khẳng định khả năng tổng quát.

Muốn dùng trong báo cáo nghiên cứu, cần tập email/tin nhắn thực được hai người gán nhãn độc lập, chia theo chiến dịch và tên miền, khóa test set trước khi điều chỉnh prompt/ngưỡng, rồi lặp LLM nhiều lần với cùng ngân sách token. Tập URL độc lập phải được đánh giá riêng nếu muốn kết luận về bộ phân loại URL.
