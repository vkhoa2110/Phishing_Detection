# URL ký tự: khả năng nhận ra nguồn và chuyển sang nguồn bị giữ ngoài

Đây là **chẩn đoán trên validation lịch sử**, không phải đánh giá độc lập hay cải thiện đã đưa vào app. Đã khóa cấu hình/mã/đầu vào trước fit, chạy đúng **5 lượt huấn luyện**, không quét tham số, không mở member test chính thức và không gọi API. Bộ dữ liệu/nhãn vẫn là PhishVN lịch sử; validation đã được xem trong quá trình phát triển.

**Phát hiện đáng chú ý:** khi bỏ 208 URL dương OpenPhish khỏi train, Recall trên 58 URL OpenPhish validation giảm **56/58 = 96,55% → 13/58 = 22,41%**, trong khi Recall Chống Lừa Đảo và gold/silver gần như giữ nguyên. Điểm toàn tập dễ che khuất điểm yếu chuyển nguồn này. Không chọn cấu hình bỏ nguồn để triển khai từ kết quả đó.

[Biểu đồ nguồn và Recall khi giữ ngoài](../../artifacts/evaluations/url_source_shift_v2/comparison.png) trình bày hai chẩn đoán riêng, không gộp thành một điểm hiệu quả.

## 1. Thiết kế đã khóa

Sử dụng [loader train/val đã khóa](../../evaluation/url_representation_v2.py), kiểm tra SHA archive, MANIFEST từng member và không giao ID/đầu vào chuẩn hóa/registrable domain giữa train và validation. Không dùng loader cũ có đọc test hoặc bảng score gộp val/test.

| Thành phần | Quy định trước fit |
|---|---|
| Đầu vào | `format_url` nguyên bản của character-v1; scheme bị bỏ, giữ marker, TF-IDF chuyển chữ thường |
| Vectorizer | Ký tự 3–5 gram; `min_df=2`, tối đa 150.000 đặc trưng, sublinear TF, L2, float64 |
| Phân loại | LR `C=1`, `liblinear`, `class_weight=balanced`, tối đa 1.000 vòng, seed 42 |
| Phạm vi học | Mỗi model chỉ học vocabulary, IDF, trọng số và class weight từ các hàng train của chính nó |
| Chẩn đoán nguồn | Hai fit: dự đoán nguồn trong riêng lớp âm và riêng lớp dương; nguồn là nhãn đích, không thêm vào URL đầu vào |
| Đối chứng nguồn | Luôn đoán nguồn đông nhất **trên train**, tie-break theo tên nguồn; chấm accuracy, balanced accuracy, macro F1, confusion |
| Loại nguồn dương | Ba fit: bỏ lần lượt Chống Lừa Đảo, OpenPhish, Tin Nhiệm Mạng; giữ nguyên toàn bộ 11.004 âm và các dương còn lại |
| Baseline URL | Nạp frozen export character-v1 và chỉ tính điểm validation; không fit lại baseline |
| Ngưỡng URL | Cố định **0,5** cho mọi model; không chọn lại bằng validation |
| Số fit/API/test | Đúng 5 fit mới; 0 API; không mở hoặc chấm test |

Train có 36.909 URL; validation có 7.266 URL, gồm 5.705 dương và 1.561 âm. Dương validation gồm Chống Lừa Đảo 5.623, OpenPhish 58 và Tin Nhiệm Mạng 24. Gold/silver chỉ có 24 dương. Thời gian tổng riêng năm lần `.fit` khoảng **5,44 giây trên máy hiện tại**; không phải benchmark phục vụ hoặc toàn pipeline.

Multiclass source classifier dùng cơ chế OvR hiện hành của `liblinear` trong môi trường scikit-learn đã khóa. Hai cảnh báo deprecation được giữ trong `fit.json`; không âm thầm đổi solver sau khi có điểm. Runner này không phải gói phục vụ và chưa bảo đảm tương thích phiên bản thư viện tương lai.

## 2. Chuỗi URL có mang thông tin nguồn không?

| Nhóm tham chiếu | Phương pháp | Accuracy | Balanced accuracy | Macro F1 |
|---|---|---:|---:|---:|
| Âm, 4 nguồn | Luôn đoán Tranco theo train | 59,90% | 25,00% | 18,73% |
| Âm, 4 nguồn | Character TF-IDF + LR dự đoán nguồn | 88,21% | 59,65% | 61,00% |
| Dương, 3 nguồn | Luôn đoán Chống Lừa Đảo theo train | **98,56%** | 33,33% | 33,09% |
| Dương, 3 nguồn | Character TF-IDF + LR dự đoán nguồn | 95,55% | **64,73%** | **65,33%** |

Source classifier nhận đúng 57/58 URL OpenPhish và 5.394/5.623 URL Chống Lừa Đảo, nhưng **0/24 Tin Nhiệm Mạng**. Ở lớp âm, nó nhận đúng 932/935 Tranco, 316/346 Tranco VN, 129/271 Tín Nhiệm Web, nhưng **0/9 Tín Nhiệm Org**. Các nguồn nhỏ không được nhận tốt đồng đều. Accuracy 98,56% của baseline dương chỉ là hệ quả Chống Lừa Đảo chiếm gần toàn bộ validation dương; không có nghĩa baseline phân biệt nguồn tốt.

Kết quả balanced accuracy/macro F1 cho thấy **nguồn có thể được dự đoán một phần từ chuỗi URL ngay trong cùng nhãn tham chiếu**. Đây chưa chứng minh classifier phishing sử dụng đúng các dấu vết đó, càng chưa chứng minh chúng đều là đặc trưng giả hoặc model chỉ học nguồn. Ngôn ngữ, phạm vi thu thập, thời gian, chiến dịch và độ tin cậy nhãn cũng có thể khác theo nguồn.

Confusion matrix đầy đủ với thứ tự hàng/cột, support và Recall từng nguồn nằm trong [summary](../../artifacts/evaluations/url_source_shift_v2/summary.json). Không gộp accuracy hai lớp thành một số vì bài toán/source set khác nhau.

## 3. Bỏ một nguồn dương khi huấn luyện

Mọi cấu hình dùng cùng ngưỡng 0,5 và đúng cùng validation. Các tỷ lệ sau là Recall theo nguồn dương và FPR trên toàn bộ âm; không diễn giải nhóm một lớp bằng Precision/F1.

| Dương bị loại khỏi train | Dương train còn lại | Recall CLD / 5.623 | Recall OpenPhish / 58 | Recall TNM / 24 | FP / 1.561 âm | FPR |
|---|---:|---:|---:|---:|---:|---:|
| Không, baseline frozen | 25.905 | 84,07% (4.727) | 96,55% (56) | 91,67% (22) | 95 | 6,09% |
| Chống Lừa Đảo, 23.621 mẫu | 2.284 | 77,61% (4.364) | 100,00% (58) | 75,00% (18) | 80 | 5,12% |
| OpenPhish, 208 mẫu | 25.697 | 84,05% (4.726) | **22,41% (13)** | 91,67% (22) | 92 | 5,89% |
| Tin Nhiệm Mạng, 2.076 mẫu | 23.829 | 83,00% (4.667) | 96,55% (56) | 91,67% (22) | 78 | 5,00% |

Bỏ OpenPhish làm Recall riêng nguồn giảm **74,14 điểm phần trăm**, tương ứng 43 URL được baseline phát hiện nay bị bỏ sót theo số đếm tổng. Không khẳng định cả 43 là các cặp chuyển dương→âm nếu chưa đối chiếu từng ID; bảng là chênh lệch TP của hai cấu hình. Các nguồn khác gần như không đổi nên một bảng điểm tổng dễ bỏ qua sự cố này.

Bỏ Tin Nhiệm Mạng vẫn phát hiện 22/24 URL Tin Nhiệm Mạng validation. Điều đó cho thấy đặc trưng có thể chuyển từ các nguồn còn lại sang nhóm nhỏ này, nhưng không chứng nhận sẽ dùng tốt trên URL Tin Nhiệm Mạng mới hơn hoặc các chiến dịch khác. Bỏ Chống Lừa Đảo làm Recall nguồn này giảm ít hơn về điểm phần trăm nhưng phải loại tới 91% dương train; không so độ giảm giữa ba trường hợp như cùng một can thiệp có cùng cỡ mẫu.

Đặc biệt, `class_weight=balanced` được tính lại theo mỗi tập train: khi bỏ nguồn, số dương, tỷ trọng nguồn và trọng số lớp đều thay đổi. Vì vậy đây là **ảnh hưởng quan sát của chính sách train sau khi loại nguồn**, chưa tách riêng tác động nhân quả của nguồn. Toàn bộ train count, source count và class weight thực tế được giữ trong [fit.json](../../artifacts/evaluations/url_source_shift_v2/fit.json).

## 4. Diễn giải và việc nên làm tiếp

Thí nghiệm trả lời được một phần câu hỏi giảng viên: chuỗi URL mang thông tin nguồn, và character model có điểm yếu rõ khi thiếu dữ liệu OpenPhish. **Không có bằng chứng nên bỏ nguồn hoặc thay model/ngưỡng ứng dụng từ lượt này.** Giảm FP bằng bỏ nguồn đồng thời có thể mất Recall; chưa có validation đại diện mới để chọn mức vận hành.

Các bước có giá trị tiếp theo:

1. Thu dữ liệu tương lai có ngày thu thập/bằng chứng, URL hợp lệ khó, nhiều nguồn và campaign; gán nhãn độc lập. Khóa tách calibration/test trước khi xem score ứng viên.
2. Đánh giá chuyển nguồn theo từng nguồn/nhãn, báo số đếm và khoảng bất định; giữ tập nhỏ, một lớp và UNKNOWN riêng. Không dùng tỷ lệ tổng thay cho chất lượng từng nguồn.
3. Nếu tiếp tục nghiên cứu train, đăng ký trước đối chứng cùng số mẫu/trọng số hoặc weighting nguồn, rồi chỉ đánh giá trên dev; không tối ưu cấu hình theo official test đã xem.
4. Chưa dùng source classifier này để quyết định URL an toàn/lừa đảo. Nguồn không hiện diện khi người dùng nhập URL mới và classifier nguồn dự đoán sai toàn bộ hai nhóm nhỏ.

## 5. Minh chứng và cách kiểm tra

- [Runner mới](../../evaluation/url_source_shift_v2.py), [9 kiểm thử tập trung](../../tests/test_url_source_shift_v2.py).
- [Protocol/hash trước fit](../../artifacts/evaluations/url_source_shift_v2/execution.json), [journal bắt đầu](../../artifacts/evaluations/url_source_shift_v2/fit_started.json).
- [Bảng đầy đủ](../../artifacts/evaluations/url_source_shift_v2/report.md), [summary/confusion](../../artifacts/evaluations/url_source_shift_v2/summary.json), [thông tin năm fit](../../artifacts/evaluations/url_source_shift_v2/fit.json).
- [Dự đoán nguồn từng URL](../../artifacts/evaluations/url_source_shift_v2/source_predictions.csv.gz), [điểm/quyết định URL](../../artifacts/evaluations/url_source_shift_v2/url_predictions.csv.gz).
- [Verifier](../../artifacts/evaluations/url_source_shift_v2/verification.json) kiểm tra hash, membership/metadata, exclusion counts, 7.266 quyết định nguồn, 29.064 quyết định URL và tính lại metrics/confusion bằng scikit-learn; không fit hoặc gọi API.

```bash
# Kiểm tra lại output hiện có; không huấn luyện, không mở test, không gọi API.
OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4 \
  .venv/bin/python -B -m evaluation.url_source_shift_v2 verify \
  --out artifacts/evaluations/url_source_shift_v2
```

Nếu tái lập thì dùng `prepare` rồi `run` với **thư mục mới**. Runner từ chối ghi đè protocol hoặc fit lại khi đã có journal bắt đầu; không retry để chọn kết quả thuận lợi hơn. Không sửa runner đã khóa cho lượt này. Technical doc có thể vào Git; raw archive, output/model artifact và báo cáo học thuật vẫn theo chính sách ignore hiện tại.
