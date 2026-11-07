# Thử mô hình URL ký tự: TF-IDF + Logistic Regression

Hoàn tất **06/11/2026**. Đã chạy **một cấu hình được khai báo trước khi huấn luyện**, không quét siêu tham số, không chọn seed theo kết quả và không gọi API. Mô hình ứng dụng và ngưỡng ứng dụng giữ nguyên.

**Kết quả chính:** mô hình ký tự là ứng viên đáng thử tiếp. Trên validation lịch sử, ở chính sách nhắm FPR 5%, mô hình phát hiện 22/24 dương gold/silver với 77 cảnh báo nhầm, so với 20/24 và 80 cảnh báo nhầm của XGBoost đang tích hợp. Trên test lịch sử, ngưỡng cố định 0,5 cho F1 gold/silver 75,19% so với 60,65%. Đây chưa là kết quả trên dữ liệu ngoài mới, chưa đủ để thay model ứng dụng.

[Biểu đồ so sánh](../../artifacts/evaluations/url_char_baseline_v1/comparison.png) trình bày riêng validation cross-fit và test lịch sử; không gộp hai phần thành một điểm.

## 1. Giả thuyết và quy trình

XGBoost hiện dùng 21 đặc trưng cấu trúc tổng hợp. Thí nghiệm này kiểm tra xem mô hình sử dụng chuỗi ký tự có bổ sung thông tin hostname/path hữu ích hay không. Không yêu cầu trước mô hình mới phải thắng.

| Thành phần | Cấu hình khóa trước khi fit |
|---|---|
| Dữ liệu | PhishVN v3.1.0 open; cùng split chính thức với model ứng dụng |
| Train | Toàn bộ 36.909 URL: 25.905 dương, 11.004 âm |
| Đầu vào | `format_url` của model đang tích hợp; bỏ scheme, giữ netloc/path/query/fragment và marker; vectorizer chuyển chữ thường |
| Vectorizer | TF-IDF ký tự 3–5 gram, `min_df=2`, tối đa 150.000 đặc trưng, sublinear TF, L2, float64 |
| Phân loại | Logistic Regression, `C=1`, `liblinear`, `class_weight=balanced`, tối đa 1.000 vòng, seed 42 |
| Phạm vi học | Vocabulary, IDF và trọng số phân loại chỉ học trên train |
| Đối chứng | Điểm XGBoost ứng dụng đã lưu; xác minh hash model/config và metadata từng URL |
| Chính sách chấm | Ngưỡng 0,5; hoặc chọn bằng URL âm validation để nhắm FPR 5%/1% |
| Chọn ngưỡng validation | Năm nhóm theo hash registrable domain; chọn trên bốn nhóm, chấm nhóm còn lại |
| Test lịch sử | Áp dụng ngưỡng đã chọn bằng toàn validation; không chọn lại theo test |

SHA-256 archive là `308351e9d0c0fca13a81f2f63524a7dee08ccba6c775848d125b3da5525d0ab5`. Trước khi fit đã kiểm tra MANIFEST, nhãn/split và không giao ID, đầu vào chuẩn hóa hoặc registrable domain giữa train/val/test.

Fit cục bộ trên CPU mất khoảng **1,39 giây**, tạo **131.736 đặc trưng**, LR hội tụ sau 7 vòng và không có cảnh báo. Thời gian này chỉ là một lần đo fit trên máy hiện tại, không phải benchmark tốc độ phục vụ hay chi phí toàn pipeline.

Đây là **so sánh hai pipeline**. XGBoost đã sử dụng validation cho early stopping/chọn model từ trước; cấu hình TF-IDF mới được định trước và không dùng validation để fit. Do khác cả cách biểu diễn và mô hình, không diễn giải chênh lệch thành tác động riêng của thuật toán LR hay riêng TF-IDF.

## 2. Kết quả validation: chọn ngưỡng trên miền khác

Validation có **24 dương gold/silver**, **5.681 dương bronze** và **1.561 âm**. Tập âm của nhóm gold/silver trùng với tập âm toàn validation.

| Chính sách | Model | Phát hiện dương core | Recall core | Báo nhầm / 1.561 âm | FPR | Recall bronze |
|---|---|---:|---:|---:|---:|---:|
| Cố định 0,5 | XGBoost | 22/24 | 91,67% | 180 | 11,53% | 78,65% |
| Cố định 0,5 | TF-IDF + LR | 22/24 | 91,67% | 95 | 6,09% | 84,19% |
| Nhắm FPR 5% | XGBoost | 20/24 | 83,33% | 80 | 5,12% | 70,99% |
| Nhắm FPR 5% | TF-IDF + LR | 22/24 | 91,67% | 77 | 4,93% | 83,05% |
| Nhắm FPR 1% | XGBoost | 14/24 | 58,33% | 17 | 1,09% | 57,56% |
| Nhắm FPR 1% | TF-IDF + LR | 16/24 | 66,67% | 18 | 1,15% | 71,70% |

Mục tiêu FPR áp dụng trên phần chọn ngưỡng, không bảo đảm đạt trên phần giữ ngoài. Ở mục tiêu 1%, mô hình ký tự phát hiện thêm hai dương core nhưng cũng có thêm một FP; không được nói tốt hơn trên mọi chỉ số hoặc có cùng FPR chính xác. Ở mục tiêu 5%, kết quả ký tự tốt hơn trên các tỷ lệ quan sát, nhưng chỉ 24 dương core: một URL tương ứng 4,17 điểm phần trăm Recall, chưa đủ để suy ra mức cải thiện ổn định.

Validation này đã được xem và đã dùng để phát triển hệ thống từ trước. Cross-fit ở đây chỉ kiểm tra bước chọn ngưỡng; không xóa thiên lệch chọn model, thích nghi với dev hoặc biến validation thành test độc lập.

## 3. Test lịch sử: áp dụng ngưỡng đã khóa từ validation

Test có **487 dương gold/silver**, **4.609 dương bronze** và **3.845 âm**. Test đã được xem trong các đợt trước; các số sau chỉ là phân tích hồi cứu. Không dùng test để chọn mô hình/ngưỡng hay gọi đó là holdout mới.

| Chính sách | Model | Recall core | FPR | F1 core | Recall bronze | F1 toàn test |
|---|---|---:|---:|---:|---:|---:|
| Cố định 0,5 | XGBoost | 62,83% | 5,62% | 60,65% | 79,54% | 85,57% |
| Cố định 0,5 | TF-IDF + LR | 72,48% | 2,57% | 75,19% | 87,81% | 91,71% |
| Nhắm FPR 5% trên val | XGBoost | 47,23% | 2,47% | 56,65% | 71,84% | 81,10% |
| Nhắm FPR 5% trên val | TF-IDF + LR | 70,43% | 2,11% | 75,30% | 86,57% | 91,13% |
| Nhắm FPR 1% trên val | XGBoost | 27,52% | 0,75% | 41,23% | 56,52% | 69,66% |
| Nhắm FPR 1% trên val | TF-IDF + LR | 40,25% | 0,34% | 56,32% | 74,25% | 82,92% |

Ở ngưỡng 0,5, mô hình ký tự có **353 TP / 99 FP** ở core so với **306 TP / 216 FP** của XGBoost. F1 core tăng **14,53 điểm phần trăm**; Recall tăng khoảng **9,65 điểm**, FPR giảm khoảng **3,04 điểm**. Bảng dùng đúng XGBoost đang tích hợp, không phải model XGBoost CPU refit trong [thí nghiệm nguồn trước](URL_SOURCE_AUDIT_V1.md), nên không ghép lẫn các số giữa hai thí nghiệm.

FPR trên test của chính sách nhắm 5% trên val có thể thấp hơn 5% vì phân phối điểm/nguồn khác. Chưa đo Recall tại đúng cùng một FPR test, bởi chọn ngưỡng từ nhãn test để ép ngang FPR sẽ không còn là đánh giá ngưỡng đã chốt từ validation.

## 4. Kiểm tra chuyển nguồn và hạn chế

Không phải mọi nguồn đều được lợi. Ví dụ ở validation với mục tiêu FPR 1%:

- Recall Chống Lừa Đảo: ký tự **71,83%**, XGBoost **57,30%**.
- Recall OpenPhish: ký tự **58,62%**, XGBoost **82,76%**; mô hình ký tự kém hơn rõ trên nhóm này.
- FPR Tranco toàn cầu: ký tự **1,71%**, XGBoost **1,50%**.
- FPR Tranco VN: ký tự **0,29%**, XGBoost **0%**.

Ở mục tiêu 5%, FPR Tranco VN của ký tự là **3/346 = 0,87%**, trong khi XGBoost không có FP trên 346 URL đó. Các nhóm nhỏ chưa đủ để chứng nhận FPR ngoài thực tế; không giấu ngoại lệ sau điểm toàn tập.

Mô hình ký tự có thể ghi nhớ tên thương hiệu, cấu trúc đường dẫn, chiến dịch hoặc dấu vết nguồn thu thập. Tách tên miền không bảo đảm tách được campaign. Nhãn nguồn/tier vẫn là nhãn lịch sử, không phải nhãn người độc lập đã xác minh; nguồn, thời gian và chất lượng nhãn còn gắn với nhau. Score LR cân bằng lớp chưa được hiệu chỉnh thành xác suất phishing trong lưu lượng người dùng.

**Chưa thay model mặc định.** Đã xuất gói candidate cục bộ để có thể thử theo lựa chọn riêng, với kiểm chứng tương đương ở mục 5. Bước đánh giá tiếp theo hợp lý là khóa ứng viên này và chấm trên dữ liệu mới có bằng chứng/nhãn độc lập, âm khó và campaign đa dạng; chốt mục tiêu FPR/Recall trước khi mở test tương lai. Không tiếp tục tinh chỉnh char model theo chính test lịch sử này để làm điểm đẹp hơn.

## 5. Gói suy luận candidate tùy chọn

[Dịch vụ candidate](../../app/url_char_service.py) nạp JSON và mảng NPZ (`allow_pickle=False`), không dùng pickle/joblib và không học trong lúc phục vụ. Bộ export phát lại **một lần đúng cấu hình đã khóa**, xác minh hash vocabulary/IDF/hệ số và toàn bộ **16.207 điểm validation + test khớp từng bit** với checkpoint. Gói JSON/NPZ được nạp lại bằng dịch vụ suy luận và tiếp tục kiểm tra đủ các điểm trước khi công bố thư mục `deployment/`.

- [Manifest export và bằng chứng tương đương](../../artifacts/evaluations/url_char_baseline_v1/deployment/export.json).
- Hash trọng số, vocabulary, mã chuẩn hóa, mã runner và mã suy luận phải khớp; phiên bản numpy/scipy/scikit-learn phải khớp bản đã kiểm chứng. Không đáp ứng thì dịch vụ báo unavailable, không suy ra URL ít rủi ro.
- Giao diện `CharURLService(artifact_dir, preprocessing_path)` có `load(reload=False)`, `status()` và `predict(urls)` tương thích dịch vụ model hiện có; lớp `ConservativeURLModel` có thể giữ dải giữa là UNKNOWN.
- Ngưỡng thấp **0,5** là đối chứng cố định đã khai báo trước fit; HIGH **0,5259423981707284** là ngưỡng từ toàn validation theo mục tiêu FPR 5%, không lấy từ score XGBoost. Raw model trả LOW dưới 0,5; WARNING từ 0,5 đến dưới HIGH; HIGH từ HIGH. Wrapper đổi WARNING thành UNKNOWN.
- **Ngưỡng 0,5 không phải cận xác suất an toàn và chưa được chọn để tối ưu vùng abstention.** Dải UNKNOWN này khá hẹp; cấu hình candidate chỉ phục vụ thử nghiệm có ghi rõ giới hạn, không chứng nhận mức vận hành trên người dùng thật. Điểm dưới 0,5 vẫn có thể là URL lừa đảo.

Trong kiểm tra suy luận cục bộ, `https://example.com/` có score khoảng **0,64936**, tức HIGH theo candidate. Ví dụ URL minh họa thông dụng này cho thấy mô hình vẫn có cảnh báo không phù hợp; không che vấn đề đó bằng F1 lịch sử cao hơn và không sửa ngưỡng để làm riêng ví dụ này qua. Nó được giữ như phát hiện diagnostic mới, chưa phải một tập đánh giá ngoài đủ đại diện.

Đã có [10 kiểm thử dịch vụ](../../tests/test_url_char_service.py) về dựng lại model khớp chính xác, wrapper, mã/weights/phiên bản/ngưỡng không tương thích, URL lỗi và không ghi đè export. Cùng 8 kiểm thử runner, **18 kiểm thử tập trung đạt**. Gói model nằm trong thư mục artifact đã được `.gitignore` loại khỏi Git.

```bash
# Chỉ chạy nếu deployment/ chưa tồn tại; không ghi đè hoặc retry để chọn kết quả.
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python -B -m app.url_char_service export \
  --audit-dir artifacts/evaluations/url_char_baseline_v1
```

## 6. Minh chứng và tái lập

- [Protocol/hash khóa trước fit](../../artifacts/evaluations/url_char_baseline_v1/execution.json).
- [Thông tin fit, hash vocabulary/IDF/trọng số](../../artifacts/evaluations/url_char_baseline_v1/fit.json).
- [Điểm từng URL](../../artifacts/evaluations/url_char_baseline_v1/scores.csv.gz), [quyết định từng URL/chính sách](../../artifacts/evaluations/url_char_baseline_v1/decisions.csv.gz).
- [Summary đầy đủ theo nguồn/tier](../../artifacts/evaluations/url_char_baseline_v1/summary.json), [bảng kết quả](../../artifacts/evaluations/url_char_baseline_v1/report.md).
- [Kiểm chứng độc lập](../../artifacts/evaluations/url_char_baseline_v1/verification.json): **97.242 quyết định, 144 nhóm chỉ số**, hash đầu vào/đầu ra, confusion matrix và Precision/Recall/F1 bằng scikit-learn.
- [Bộ chạy](../../evaluation/url_char_baseline.py), [8 kiểm thử](../../tests/test_url_char_baseline.py) về fit train-only, chống giao dữ liệu, test không ảnh hưởng ngưỡng, held-out domain không ảnh hưởng ngưỡng và bảo toàn kết quả đã có.

```bash
# Kiểm tra kết quả cục bộ đã lưu, không fit/gọi API.
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python -B -m evaluation.url_char_baseline verify \
  --out artifacts/evaluations/url_char_baseline_v1

# Tái lập sang thư mục mới; cần raw archive và model/prediction đúng hash.
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python -B -m evaluation.url_char_baseline prepare \
  --out artifacts/evaluations/url_char_baseline_rebuild
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python -B -m evaluation.url_char_baseline run \
  --out artifacts/evaluations/url_char_baseline_rebuild
```

Kết quả artifact và dữ liệu/model cục bộ tiếp tục được `.gitignore` loại khỏi Git; bộ chạy, kiểm thử và tài liệu kỹ thuật là phần có thể quản lý phiên bản. Không ghi vào báo cáo tuần hoặc thay đổi kho nhãn test.
