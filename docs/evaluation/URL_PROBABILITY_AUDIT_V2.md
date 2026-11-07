# Hiệu chỉnh score phụ thuộc vào tập calibration

Đã chạy **10 calibrator**, không fit lại mô hình URL, không chấm test hoặc gọi API. Kết quả chỉ là chẩn đoán trên validation lịch sử đã dùng phát triển; không export calibrator hoặc đổi ngưỡng của ứng dụng.

## Thiết kế

Dùng đúng 7.266 score validation của char V1 đã đối chiếu từng bit trong [V2](URL_REPRESENTATION_V2.md). File đầu vào chỉ có validation; không đọc các score test nằm trong checkpoint V1 gộp.

Chia năm nhóm miền bằng quy tắc hash hiện có. Mỗi lượt chỉ fit trên bốn nhóm, chấm nhóm còn lại. Hai phạm vi fit:

- **all:** toàn bộ URL của bốn nhóm; có 4.531–4.637 dương trong mỗi lượt fit, phần lớn bronze.
- **core:** chỉ gold/silver của bốn nhóm; có 16–22 dương trong mỗi lượt fit. Toàn validation core chỉ 24 dương.

Calibrator là sigmoid logistic có L2 cố định `C=1`, `lbfgs`, không class weighting, đầu vào `logit(raw_score)` clip ở 1e-8. Không sweep; slope phải dương để không đảo thứ hạng score. Đây là logistic sigmoid có regularization, không giả nhận khớp toàn bộ thuật toán Platt/soft-target của một thư viện khác. Mỗi phạm vi có đối chứng hằng số là tỷ lệ dương ước lượng từ đúng bốn nhóm fit; không dùng tỷ lệ của nhóm đang chấm.

Protocol khóa trước fit, giữ mọi cảnh báo/lỗi và không fit thêm một bản trên toàn validation để phục vụ app. Verifier dựng lại xác suất từ slope/intercept đã lưu, kiểm tra membership/hash và tính lại số đo, không fit lần hai.

## Kết quả out-of-fold

Brier và log-loss thấp hơn là tốt hơn trên đúng nhóm tham chiếu được chấm. Hai chỉ số phản ánh cả khả năng phân biệt và chất lượng xác suất, không phải phép đo calibration thuần túy.

| Arm | Brier gold/silver | Log-loss gold/silver | Brier toàn validation | Log-loss toàn validation |
|---|---:|---:|---:|---:|
| Score V1 gốc | 0,063362 | 0,238690 | 0,096168 | 0,303770 |
| Sigmoid fit all | 0,180650 | 0,534320 | 0,071928 | 0,222689 |
| Sigmoid fit core | 0,007985 | 0,031839 | 0,255749 | 1,126568 |
| Prior fit all | 0,608367 | 1,519924 | 0,168824 | 0,520718 |
| Prior fit core | 0,014955 | 0,079909 | 0,761601 | 3,301007 |

Sigmoid fit all cải thiện số đo toàn validation nhưng làm Brier core tệ hơn gần ba lần. Trên core, mean score sau calibrator all là 0,3397 trong khi tỷ lệ dương tham chiếu chỉ 24/1.585 = 1,51%. Sigmoid fit core phù hợp hơn trên core, nhưng làm xấu toàn validation; chỉ có 24 dương không đủ kết luận chuyển tốt sang nguồn mới.

Không chọn một calibrator chỉ từ bảng này để áp lên người dùng thật. Chưa biết nguồn/tỷ lệ lớp của người dùng có giống hai phạm vi trên không. Hiệu chỉnh xác suất cũng không tự tạo thêm thông tin để phân biệt URL, hoặc bảo đảm giảm báo nhầm. Giữ cùng số 0,5 sau khi đổi thang xác suất không là so sánh cùng điểm vận hành.

## Minh chứng

- [Runner đã khóa](../../evaluation/url_probability_audit_v2.py), [9 kiểm thử](../../tests/test_url_probability_audit_v2.py).
- [Protocol](../../artifacts/evaluations/url_probability_audit_v2/execution.json), [tham số 10 fit](../../artifacts/evaluations/url_probability_audit_v2/fits.json).
- [Summary theo nguồn/tier và reliability bins](../../artifacts/evaluations/url_probability_audit_v2/summary.json), [báo cáo](../../artifacts/evaluations/url_probability_audit_v2/report.md), [verifier](../../artifacts/evaluations/url_probability_audit_v2/verification.json).
- [scikit-learn: Probability calibration](https://scikit-learn.org/stable/modules/calibration.html) giải thích hiệu chỉnh xác suất, yêu cầu dữ liệu fit/calibration tách biệt và giới hạn diễn giải proper scores.

```bash
.venv/bin/python -B -m evaluation.url_probability_audit_v2 verify \
  --out artifacts/evaluations/url_probability_audit_v2
```
