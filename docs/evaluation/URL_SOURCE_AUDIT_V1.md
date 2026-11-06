# PhishVN: tái lập baseline và kiểm tra ảnh hưởng của bronze/nguồn

Hoàn tất ngày **05/11/2026**. Đã chạy **39 lượt huấn luyện cục bộ**, gồm 6 lượt tái lập LR/RF trong môi trường thư viện tham chiếu và 33 lượt so sánh ba nhóm huấn luyện. Không gọi LLM, không thay model/ngưỡng ứng dụng.

**Kết luận chính:** đã chạy cấu hình gold/silver, ngưỡng 0,5 để đối chiếu baseline công bằng hơn. Thêm bronze không làm kết quả xấu đi đồng đều: trên core test, F1 tăng ở cả ba mô hình nhưng Recall/FPR thay đổi khác nhau. Chênh lệch nguồn, thời điểm, chất lượng nhãn và định nghĩa lớp dương chưa được tách hoàn toàn. Đây là phân tích hồi cứu trên test PhishVN đã xem, không phải một test độc lập mới.

## 1. Protocol và kiểm tra đầu vào

- Giữ split chính thức: train **36.909**, validation **7.266**, test **8.941**; kiểm tra không giao nhau theo ID, URL chuẩn hóa và registrable domain.
- Dùng nguyên **21 đặc trưng đã công bố**, bỏ `is_https`; ID, nguồn, tier và nhãn không là đầu vào mô hình. Giữ thứ tự hàng trong bảng đặc trưng của tác giả.
- Baseline chính dùng ngưỡng **0,5** ở mọi nhóm. LR chạy một lần; RF và XGBoost chạy các seed **0–4**, báo trung bình ± độ lệch chuẩn tổng thể (`ddof=0`). Không chọn mô hình/seed tốt nhất bằng test.
- RF: 300 cây, `class_weight=balanced`. LR: `max_iter=1000`, `class_weight=balanced`, không thêm scaler để giữ protocol tác giả.
- XGBoost là nhánh mở rộng: depth 6, min-child-weight 6, learning-rate 0,03; **241 vòng cố định** lấy từ `best_iteration+1` của model cũ, vốn được chọn trên validation lịch sử; CPU, không early stopping hoặc tìm tham số mới trong lượt này. Không gọi đây là baseline XGBoost do bài báo công bố hoặc bản tái lập từng bit của model GPU đang cài.
- Khóa cấu hình, danh sách ID, hash mã nguồn/đầu vào trước huấn luyện. Giữ dự đoán từng URL và cảnh báo thư viện; không loại kết quả bất lợi hoặc huấn luyện lại để chọn kết quả thuận lợi hơn.

| Nhóm train | URL | Dương | Âm | Mục đích |
|---|---:|---:|---:|---|
| `verified_core` | 13.080 | 2.076 | 11.004 | Gold/silver, đối chiếu protocol bài báo |
| `all` | 36.909 | 25.905 | 11.004 | Đo ảnh hưởng của việc thêm toàn bộ bronze |
| `bronze_matched` | 13.080 | 2.076 | 11.004 | Thay dương core bằng cùng số dương bronze; giữ đúng các URL âm |

Bronze đối chứng được chọn bằng SHA-256 của ID với tiền tố cố định, trước dự đoán; gồm 2.065 Chống Lừa Đảo và 11 OpenPhish. Không chọn bằng điểm hoặc độ đúng của model. Nhóm này kiểm soát số lượng/tỷ lệ lớp nhưng không loại bỏ khác biệt về thời gian, nội dung và sai nhãn.

Core test giữ nguyên **4.332 URL: 487 dương/3.845 âm**. Full test là **8.941 URL: 5.096 dương/3.845 âm**. Hai nhóm có cùng tập âm; do đó FPR của cùng một model bằng nhau giữa hai nhóm. Không gộp chúng hoặc dùng chênh F1 giữa hai nhóm như mức cải thiện của model.

## 2. Đối chiếu với kết quả công bố

Đã tải gói bằng chứng chính thức `PhishVN_v3.0.0_results_bundle.zip`, xác minh SHA-256 và MANIFEST, đọc dự đoán theo ID cùng bảng số đo từng seed. Tái lập riêng với NumPy **1.26.4**, pandas **2.2.2**, scikit-learn **1.4.2**, joblib **1.4.2**. Môi trường ứng dụng không bị thay thư viện.

| Model, gold/silver test, ngưỡng 0,5 | F1 công bố | F1 tái lập môi trường tham chiếu |
|---|---:|---:|
| Logistic Regression | 53,88% | 53,88% |
| Random Forest, 5 seed | 46,32 ± 0,42% | 46,44 ± 0,41% |

**Không khớp hoàn toàn từng score.** LR có cùng quyết định tại 0,5 trên cả 4.332 URL, nhưng chênh score lớn nhất 0,04057. RF có tổng cộng 38 quyết định khác trên 21.660 cặp URL×seed, chênh score lớn nhất 0,08667. F1 trung bình RF lệch khoảng **0,11 điểm %**. Hệ điều hành/kiến trúc CPU, Python patch và thư viện toán khác môi trường macOS ARM của tác giả; chưa tách riêng nguyên nhân sai khác, không tự quy toàn bộ cho làm tròn số.

Điều đã đạt là khớp dữ liệu, nhóm train/test, đặc trưng, seed, tham số chính, ngưỡng và các phiên bản thư viện chính. Phải báo sai khác còn lại khi gọi đây là tái lập. Không so trực tiếp F1 XGBoost học cả bronze ở WARNING với F1 RF/LR core ở 0,5 để kết luận vượt baseline.

Nguồn: [release mã tác giả](https://github.com/vuthainguyen1602/phishvn/releases/tag/dib-113195), [dữ liệu và gói kết quả trên Mendeley](https://data.mendeley.com/datasets/b97hxbxtpd/4). Snapshot mã được ghim commit `bdebc126097d18e0837253f6367726ceb7303202`, kèm giấy phép và hash trong thư mục chạy.

## 3. Kết quả so sánh các nhóm huấn luyện

Bảng dưới dùng **cùng môi trường dự án** (scikit-learn 1.7.2, NumPy 2.1.3) cho tất cả các nhóm, cùng ngưỡng 0,5. Đây là so sánh nội bộ; không trộn với môi trường tham chiếu ở mục 2. Ví dụ LR core ở đây là 53,91%, khác nhẹ 53,88% của môi trường tham chiếu.

### Trên core test gold/silver

| Model | Train | Precision | Recall | F1 | FPR |
|---|---|---:|---:|---:|---:|
| LR | Core | 39,34% | 85,63% | 53,91% | 16,72% |
| LR | All | 56,61% | 65,91% | 60,91% | 6,40% |
| LR | Bronze cùng số dương | 60,32% | 62,42% | 61,35% | 5,20% |
| RF | Core | 41,62 ± 0,62% | 52,53 ± 0,56% | 46,44 ± 0,41% | 9,34 ± 0,28% |
| RF | All | 51,51 ± 0,33% | 75,85 ± 0,38% | 61,35 ± 0,22% | 9,05 ± 0,14% |
| RF | Bronze cùng số dương | 52,28 ± 0,38% | 45,75 ± 0,48% | 48,79 ± 0,34% | 5,29 ± 0,09% |
| XGB cố định vòng | Core | 41,99 ± 0,19% | 74,95 ± 0,43% | 53,83 ± 0,25% | 13,11 ± 0,07% |
| XGB cố định vòng | All | 57,56 ± 0,69% | 64,48 ± 0,43% | 60,82 ± 0,36% | 6,02 ± 0,19% |
| XGB cố định vòng | Bronze cùng số dương | 59,86 ± 0,56% | 56,63 ± 0,33% | 58,20 ± 0,18% | 4,81 ± 0,13% |

Thêm toàn bộ bronze làm F1 core tăng khoảng **7,00 / 14,91 / 6,99 điểm %** ở LR/RF/XGB. Tuy nhiên, LR và XGB đánh đổi bằng Recall thấp hơn. RF cải thiện Recall nhiều hơn ở `all` so với đối chứng bronze cùng số dương; chưa thể quy lợi ích đó chỉ cho nguồn bronze, vì `all` có cả dương core và số lượng dương lớn hơn.

Bootstrap ghép cặp theo domain, 1.000 lần, trên các model/nhãn đã cố định cho khoảng 95% của chênh F1 `all − core` trên core test: LR **[+3,75; +10,25]**, RF **[+11,04; +18,98]**, XGB **[+3,56; +10,28] điểm %**. Khoảng chênh FPR RF còn chứa 0; không khẳng định RF giảm báo nhầm ổn định chỉ từ mức trung bình 9,34% → 9,05%. Các khoảng không bao phủ sai nhãn, chạy lại huấn luyện hoặc lệch triển khai.

### Trên full test

| Model | F1: train Core | F1: train All | F1: train Bronze cùng số dương |
|---|---:|---:|---:|
| LR | 91,16% | 86,20% | 85,50% |
| RF | 77,40 ± 0,17% | 87,13 ± 0,07% | 78,29 ± 0,14% |
| XGB cố định vòng | 88,89 ± 0,14% | 85,75 ± 0,06% | 83,33 ± 0,07% |

Không có một kết luận “thêm bronze luôn tốt hơn” trên mọi model/tập. LR và XGB có F1 full test giảm trong khi F1 core tăng; RF tăng ở cả hai. Thứ hạng phụ thuộc nhóm đánh giá và điểm vận hành. Tỷ lệ dương khác nhau làm Precision/F1 thay đổi, dù tập âm và FPR không đổi.

[Biểu đồ so sánh](../../artifacts/evaluations/url_source_audit_v1/comparison.png), [SVG](../../artifacts/evaluations/url_source_audit_v1/comparison.svg). Thanh sai số là độ lệch chuẩn qua seed, không phải khoảng tin cậy 95%.

## 4. Có phải model chỉ học nguồn dữ liệu?

Bằng chứng hiện có cho thấy phụ thuộc mạnh vào nhóm dữ liệu, **chưa chứng minh model chỉ học nguồn**. Cùng một bộ 21 đặc trưng, XGB có các tỷ lệ sau tại 0,5:

| Nhóm train | Recall Tin Nhiệm Mạng | Recall Chống Lừa Đảo | FPR Tranco toàn cầu | FPR Tranco VN |
|---|---:|---:|---:|---:|
| Core | 74,95% | 89,43% | 50,56% | 2,55% |
| All | 64,48% | 79,86% | 20,88% | 1,64% |
| Bronze cùng số dương | 56,63% | 75,96% | 16,26% | 1,42% |

Tin Nhiệm Mạng không có dương trong nhóm train bronze đối chứng; Chống Lừa Đảo/OpenPhish không có trong nhóm train core. Đây là kiểm tra chuyển nguồn ở bước fit, không phải chứng nhận một nguồn chưa từng được xem trong toàn bộ quá trình phát triển. Chỉ có 30 OpenPhish trong test, nên tỷ lệ riêng nguồn này rất bất định.

Nguồn gắn với nhãn, chất lượng, thời gian và dạng URL. Nhãn dương PhishVN bao gồm phạm vi chống lừa đảo/abuse rộng hơn đánh cắp thông tin đăng nhập; không xem các tier như nhãn người tuyệt đối. Đối chứng cùng cỡ mẫu giúp kiểm tra thêm nhưng không tách hết các yếu tố. Nên báo Recall cho nguồn chỉ có dương, FPR cho nguồn chỉ có âm; Precision/F1 ở các nhóm một lớp được ghi N/A.

Kết quả từng nguồn/tier của **LR, RF và XGB trong lượt mới** nằm trong CSV và JSON. Chưa khôi phục dự đoán gốc của LightGBM/DomURLs-BERT từ lần huấn luyện tuần 2; không suy diễn kết quả hai mô hình đó từ bảng này.

## 5. Ngưỡng chọn trên validation gần toàn bronze có phù hợp không?

Validation có **5.705 dương**, trong đó **5.681 bronze (99,58%)**. Core validation chỉ còn **24 dương/1.561 âm**. Tối ưu F2 với ràng buộc Precision trên hai nhóm này dẫn tới những điểm vận hành rất khác nhau.

Ví dụ XGB mới, train All, seed 0; giữ nguyên model, chỉ đổi nhóm validation dùng để chọn ngưỡng:

| Calibration | Ngưỡng WARNING | Recall core test | FPR core test |
|---|---:|---:|---:|
| Toàn validation | 0,038842 | 99,38% | 35,84% |
| Chỉ core validation | 0,954517 | 18,48% | 0,05% |

Đây là chẩn đoán hồi cứu, không đề xuất đưa một trong hai ngưỡng vào app. Chỉ đổi sang validation core cũng không giải quyết được vấn đề: quá ít dương, độ lệch thời gian/nguồn lớn và ngưỡng có thể cực đoan.

Điều kiện HIGH cũ là Precision ≥95% với ít nhất 30 cảnh báo. **Ngay cả khi phát hiện đủ 24 dương, Precision tối đa ở 30 cảnh báo chỉ là 24/30 = 80%**. Vì vậy toàn bộ các lượt calibration core đều không có HIGH khả thi theo điều kiện này.

Cần chuẩn bị validation có đủ dương và URL hợp lệ khó, kiểm tra theo nguồn/thời gian, đặt trước đánh đổi Recall/FPR phù hợp và báo coverage. Không đặt ngưỡng theo tên nguồn dataset vì ứng dụng không biết nguồn đó khi nhận URL mới. Chính sách v4 đang dùng vẫn được mô tả ở [QUALITY_V4.md](../architecture/QUALITY_V4.md); lượt này không thay model hoặc ngưỡng vận hành.

## 6. Sai khác đặc trưng cần lưu ý

Đã đối chiếu toàn bộ **53.116** hàng giữa bảng đặc trưng gốc và bộ sinh đặc trưng hiện tại, trên cùng biểu diễn URL của bảng gốc. Có **38 hàng** khác ít nhất một đặc trưng liên quan Public Suffix List: 30 train, 5 validation, 3 test; các cột là `dom_len`, `tld_len`, `subdom_cnt`. Các đặc trưng còn lại khớp trong dung sai đã chốt.

Ngoài ra, bảng đặc trưng thêm scheme và chuẩn hóa chữ thường, trong khi bảng split giữ một số cách viết gốc. Phép nối dùng khóa một-một đã chuẩn hóa; kiểm tra toàn bộ ID/nhãn/split/tier, không nối chỉ bằng vị trí hàng hoặc sửa nhãn để làm khớp.

Thí nghiệm dùng nguyên giá trị đặc trưng đã công bố cho tất cả các nhóm, không âm thầm thay bằng phiên bản PSL hiện tại. Khi tái huấn luyện cho triển khai sau này, nên đóng gói/ghim PSL cùng model và kiểm tra lại vector train–inference.

## 7. Tệp bàn giao và tái lập

- [Báo cáo tự động](../../artifacts/evaluations/url_source_audit_v1/report.md).
- [Summary đầy đủ, khoảng bootstrap và calibration](../../artifacts/evaluations/url_source_audit_v1/summary.json).
- [CSV từng model/seed/nguồn/tier](../../artifacts/evaluations/url_source_audit_v1/metrics_by_source_tier.csv).
- [Protocol khóa trước fit](../../artifacts/evaluations/url_source_audit_v1/execution.json), [audit dữ liệu/đặc trưng](../../artifacts/evaluations/url_source_audit_v1/data_audit.json), [kiểm chứng](../../artifacts/evaluations/url_source_audit_v1/verification.json).
- `upstream/`: snapshot mã nguồn MIT, kết quả tham chiếu, môi trường và provenance.
- `reference_reproduction/`: 6 lượt tái lập trong môi trường thư viện gốc.
- `fits/`, `predictions/`: 33 cấu hình và dự đoán validation/test; không xuất thêm 33 bộ trọng số vì chưa dùng để triển khai.

Kiểm tra lại lượt hoàn tất, không huấn luyện hoặc gọi API:

```bash
.venv/bin/python -B -m evaluation.url_source_audit verify \
  --out artifacts/evaluations/url_source_audit_v1
```

Chạy lại trên máy hiện tại vào thư mục mới, tái sử dụng snapshot nguồn đã kiểm tra:

```bash
mkdir -p artifacts/evaluations/url_source_audit_rebuild
cp -a artifacts/evaluations/url_source_audit_v1/upstream \
  artifacts/evaluations/url_source_audit_rebuild/upstream
.venv/bin/python -B -m evaluation.url_source_audit prepare \
  --out artifacts/evaluations/url_source_audit_rebuild --threads 4

# Môi trường tham chiếu riêng; không thay thư viện môi trường ứng dụng.
python3 -m venv /tmp/phishvn-reference
/tmp/phishvn-reference/bin/python -m pip install \
  numpy==1.26.4 pandas==2.2.2 scipy==1.12.0 \
  scikit-learn==1.4.2 joblib==1.4.2 threadpoolctl==3.2.0
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  /tmp/phishvn-reference/bin/python -B scripts/evaluation/reproduce_phishvn_baseline.py \
  --out artifacts/evaluations/url_source_audit_rebuild
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python -B -m evaluation.url_source_audit run \
  --out artifacts/evaluations/url_source_audit_rebuild
```

Clone Git không kèm các artifact cục bộ. Cần cài hai archive PhishVN đúng hash và chuẩn bị snapshot upstream đúng commit trước `prepare`; URL/hash của nguồn nằm trong provenance của lượt bàn giao. Môi trường tham chiếu tạm có thể dựng lại bằng lệnh trên.

Kiểm chứng đã đối chiếu confusion matrix/P/R/F1 bằng scikit-learn, phép tổng hợp qua seed bằng `statistics`, các ID/split/nhãn dự đoán và hash đầu vào/mã nguồn. **294 test offline đạt**. Các kiểm tra xác nhận phép tính và protocol, không xác nhận mọi nhãn nguồn là đúng hoặc kết luận đã tổng quát sang lưu lượng thực.
