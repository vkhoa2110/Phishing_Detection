# Đối chứng URL V2: bỏ marker không cải thiện đồng đều

Hoàn tất **07/11/2026**. Đã huấn luyện đúng **một cấu hình mới**, chỉ chấm validation lịch sử, không gọi API và không thay mô hình/ngưỡng của ứng dụng. **Không triển khai V2:** một số URL quen thuộc giảm điểm, nhưng báo nhầm toàn nhóm tăng ở ngưỡng 0,5 và Recall OpenPhish giảm mạnh.

## Thiết kế đối chứng

V1 là TF-IDF ký tự + Logistic Regression đã export, có marker tổng hợp như `[DOMAIN]`, `[IP]`, `[IPv6]`, `[PATH]`. V2 dùng cùng bộ tách URL đã khóa và ghép:

```text
parts.netloc + parts.path + ("?" + parts.query nếu có) + ("#" + parts.fragment nếu có)
```

Hai cách đều bỏ scheme. V2 giữ authority, cổng, đường dẫn, query, fragment và percent encoding; không xóa chuỗi giống marker nếu đó là nội dung thật của URL. Vectorizer chuyển chữ thường như V1. Không thêm whitelist, không bỏ `www`, không fusion hoặc đổi trọng số lớp.

| Thành phần | Cấu hình cố định |
|---|---|
| Dữ liệu | PhishVN v3.1.0 open, đúng train/validation chính thức |
| Train | 36.909 URL: 25.905 dương, 11.004 âm |
| Validation | 7.266 URL: 5.705 dương, 1.561 âm |
| Validation gold/silver | 24 dương, 1.561 âm |
| TF-IDF | Ký tự 3–5 gram; `min_df=2`; `max_features=150000`; sublinear TF; L2; float64 |
| Logistic Regression | `C=1`; `liblinear`; `class_weight=balanced`; tối đa 1.000 vòng; seed 42 |
| Phạm vi học | Vocabulary, IDF, hệ số chỉ học trên train |
| Đối chứng | V1 export giữ nguyên; toàn bộ 7.266 score validation dựng lại khớp từng bit với checkpoint V1 |
| Chọn ngưỡng | Cố định 0,5; hoặc FPR mục tiêu 5% trên URL âm của bốn nhóm miền, chấm nhóm miền còn lại |
| Kiểm soát | Khóa protocol, cấu hình và hash nguồn trước fit; không sweep hoặc fit lại sau khi xem kết quả |

Loader chỉ mở hai member train/validation trong archive. Khi đối chiếu checkpoint V1 dạng gzip chung, chỉ record `split=val` được lấy và diễn giải score; không diễn giải score của record test. Không mở member official test, không dự đoán hoặc chấm official test trong lượt này. Validation đã từng được xem/phân tích nên đây vẫn là **diagnostic dev**, không phải holdout mới.

V2 tạo 121.715 đặc trưng, hội tụ sau 7 vòng, không có cảnh báo. Thời gian fit khoảng 1,01 giây là một lần đo cục bộ, không phải benchmark tổng pipeline.

## Kết quả theo nhóm

Các số dưới đây là validation domain cross-fit; chính sách cố định 0,5 cũng đi qua cùng các nhóm để giữ cùng cách ghi nhận. Ngưỡng FPR5 toàn validation của V1 là 0,5259423982, V2 là 0,6180902172; đó **không phải** năm ngưỡng riêng của cross-fit, không được triển khai và không bảo đảm FPR ngoài thực tế.

| Nhóm/chính sách | V1 TP/dương | V2 TP/dương | V1 FP/âm | V2 FP/âm | V1 F1 | V2 F1 |
|---|---:|---:|---:|---:|---:|---:|
| Gold/silver, 0,5 | 22/24 | 23/24 | 95/1.561 | 168/1.561 | 31,21% | 21,40% |
| Gold/silver, FPR5 | 22/24 | 21/24 | 77/1.561 | 77/1.561 | 35,77% | 34,43% |
| Toàn validation, 0,5 | 4.805/5.705 | 5.037/5.705 | 95/1.561 | 168/1.561 | 90,62% | 92,34% |
| Toàn validation, FPR5 | 4.740/5.705 | 4.719/5.705 | 77/1.561 | 77/1.561 | 90,10% | 89,88% |

FPR tại 0,5 tăng **6,09% → 10,76%**. Cùng FPR5 cross-fit, cả hai có FPR 4,93% nhưng V2 mất một dương gold/silver. F1 toàn validation tăng ở 0,5 trong khi gold/silver giảm vì 99,58% dương validation là bronze; không lấy điểm tổng để che khác biệt thành phần nguồn. F1 gold/silver ở đây cũng không so trực tiếp với F1 75,19% trên **test lịch sử** trong thí nghiệm V1: hai split có tỷ lệ lớp khác nhau.

Các nguồn một lớp chỉ báo Recall hoặc FPR, không tính Precision/F1 làm chất lượng chung:

| Nguồn | Dương/âm | Recall V1 → V2 tại 0,5 | Recall V1 → V2 tại FPR5 | FPR V1 → V2 tại 0,5 | FPR V1 → V2 tại FPR5 |
|---|---:|---:|---:|---:|---:|
| Chống Lừa Đảo | 5.623/0 | 84,07% → 88,88% | 82,91% → 83,39% | N/A | N/A |
| OpenPhish | 58/0 | **96,55% → 27,59%** | **96,55% → 15,52%** | N/A | N/A |
| Tin Nhiệm Mạng | 24/0 | 91,67% → 95,83% | 91,67% → 87,50% | N/A | N/A |
| Tin nhiệm tổ chức | 0/9 | N/A | N/A | 0,00% → 11,11% | 0,00% → 0,00% |
| Tin nhiệm website | 0/271 | N/A | N/A | 2,58% → 4,43% | 2,21% → 1,85% |
| Tranco toàn cầu | 0/935 | N/A | N/A | 9,09% → 16,15% | 7,27% → 7,59% |
| Tranco VN | 0/346 | N/A | N/A | 0,87% → 1,16% | 0,87% → 0,29% |

| Tier | Dương/âm | TP V1 → V2 tại 0,5 | FP V1 → V2 tại 0,5 | TP V1 → V2 tại FPR5 | FP V1 → V2 tại FPR5 |
|---|---:|---:|---:|---:|---:|
| Gold | 0/280 | 0 → 0 | 7 → 13 | 0 → 0 | 6 → 5 |
| Silver | 24/1.281 | 22 → 23 | 88 → 155 | 22 → 21 | 71 → 72 |
| Bronze | 5.681/0 | 4.783 → 5.014 | 0 → 0 | 4.718 → 4.698 | 0 → 0 |

## Dấu vết nguồn và các ví dụ đã biết

Phân bố `www` trên **train** khác rõ theo nguồn:

| Nhãn tham chiếu / nguồn | URL có `www` / tổng | Tỷ lệ |
|---|---:|---:|
| Dương / Chống Lừa Đảo | 11.651/23.621 | 49,32% |
| Dương / OpenPhish | 40/208 | 19,23% |
| Dương / Tin Nhiệm Mạng | 155/2.076 | 7,47% |
| Âm / Tin nhiệm tổ chức | 62/1.659 | 3,74% |
| Âm / Tin nhiệm website | 5/3.362 | 0,15% |
| Âm / Tranco toàn cầu | 2/4.170 | 0,05% |
| Âm / Tranco VN | 0/1.813 | 0,00% |

N-gram quanh `www` có đóng góp dương lớn ở ví dụ `www.google.com`. Đây là dấu hiệu cần kiểm tra shortcut theo nguồn, **chưa chứng minh quan hệ nhân quả hoặc mô hình chỉ học nguồn**: nguồn gắn với thời gian, loại URL, cách chuẩn hóa và chất lượng nhãn. Không tự bỏ `www` hay mặc định hai biến thể cùng nhãn, vì hai hostname có thể trỏ nội dung khác nhau.

Top n-gram dương quanh `[PATH]` cũng không đủ chứng minh marker gây báo nhầm. Ví dụ tổng đóng góp của các n-gram nằm hoàn toàn trong marker ở `example.com` là **âm −0,9505**, trong khi intercept là +2,6378. Việc bỏ marker còn làm đổi vocabulary, IDF, chuẩn hóa L2 và hệ số của các term khác. Chẩn đoán hệ số là mô tả score, không là phân tích nhân quả.

Bốn ví dụ sau đã được biết trước lượt V2, không có nhãn tham chiếu trong benchmark, không dùng chọn ngưỡng và được giữ riêng khỏi số đo:

| URL | Score V1 | Score V2 |
|---|---:|---:|
| `https://example.com/` | 0,6494 | 0,2773 |
| `https://example.org/` | 0,5168 | 0,1508 |
| `https://github.com/vkhoa2110/Phishing_Detection` | 0,7666 | 0,5810 |
| `https://www.google.com/` | 0,9437 | 0,6736 |

Giảm score vài URL quen thuộc không chứng minh giải quyết báo nhầm chung. Thí nghiệm này giữ nguyên cả kết quả thuận lợi lẫn bất lợi; không tìm thêm cấu hình hoặc đổi ngưỡng để biến V2 thành phương án thắng.

## Quyết định và giới hạn

Giữ V1 làm ứng viên hiện có, không export/triển khai V2. Kết quả âm giúp loại bỏ giả thuyết đơn giản “bỏ marker sẽ tốt hơn”, trong điều kiện dữ liệu và cấu hình đang thử; chưa chứng minh marker luôn hữu ích cho mọi mô hình/dữ liệu.

Ưu tiên tiếp theo là dữ liệu calibration mới có đủ URL hợp lệ khó và dương được xác minh từ nhiều nguồn, lưu thời gian/bằng chứng; giữ test tương lai tách biệt theo miền và campaign khi có thể. Các cặp biến thể hoặc phân tích support có thể dùng để chẩn đoán, không tự biến thành nhãn đúng hoặc cơ chế miễn cảnh báo. Chỉ 24 dương core validation chưa đủ chốt chính sách vận hành.

## Tái kiểm tra và minh chứng

```bash
.venv/bin/python -B -m evaluation.url_representation_v2 verify \
  --out artifacts/evaluations/url_representation_v2
```

Lệnh trên không fit hoặc gọi API. Runner từ chối ghi đè protocol và từ chối fit lần hai khi journal `fit_started.json` đã tồn tại. **15 kiểm thử offline đạt**: giữ nguyên URL thật, chỉ học train, chống giao miền/URL, held-out fold không ảnh hưởng ngưỡng, không mở test member, không diễn giải score test, giữ protocol và từ chối drift/refit.

- [Runner đã khóa](../../evaluation/url_representation_v2.py), [test](../../tests/test_url_representation_v2.py).
- [Protocol trước fit](../../artifacts/evaluations/url_representation_v2/execution.json), [fit](../../artifacts/evaluations/url_representation_v2/fit.json).
- [Bảng số đo đầy đủ](../../artifacts/evaluations/url_representation_v2/report.md), [summary theo nguồn/tier/fold](../../artifacts/evaluations/url_representation_v2/summary.json).
- [Chẩn đoán `www`, hệ số và smoke](../../artifacts/evaluations/url_representation_v2/diagnostics.json).
- [Kiểm chứng 29.064 quyết định, 48 nhóm](../../artifacts/evaluations/url_representation_v2/verification.json): score baseline khớp từng bit; confusion và Precision/Recall/F1 đối chiếu độc lập.
- [Đối chứng V1](URL_CHAR_BASELINE_V1.md).
