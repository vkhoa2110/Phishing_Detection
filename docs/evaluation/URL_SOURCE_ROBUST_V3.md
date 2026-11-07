# URL V3: đối chứng biểu diễn www và cân bằng nguồn

**Kết luận:** cả ba can thiệp chưa cho thấy lợi ích tổng thể so với character V1. Giữ V1; không đổi model/ngưỡng ứng dụng từ kết quả này. Chỉ B qua cổng nghiên cứu đã đăng ký, nhưng vẫn tăng báo nhầm và giảm nhẹ Recall toàn nhóm. Qua cổng không đồng nghĩa mô hình tốt hơn hoặc được triển khai.

## Thiết kế đã khóa trước huấn luyện

Đúng **3 lượt fit mới**, không sweep, không chọn seed/config theo kết quả. Đối chứng là export V1 đã khóa: trước fit, toàn bộ 7.266 score validation phải khớp checkpoint V1 từng bit. Chỉ đọc thành viên `train` và `val` trong archive chính thức; không đọc/chấm official test và không gọi API.

Train giữ **36.909 URL = 25.905 dương + 11.004 âm**. Validation giữ **7.266 URL = 5.705 dương + 1.561 âm**, trong đó gold/silver chỉ **24 dương**. Đây là validation lịch sử đã xem nhiều lần, chỉ có giá trị phát triển/chẩn đoán.

TF-IDF char 3–5, `min_df=2`, tối đa 150.000 đặc trưng, lowercase, sublinear TF, chuẩn L2; Logistic Regression `C=1`, liblinear, seed 42, tối đa 1.000 vòng. Vocab và IDF chỉ fit train, mọi arm giữ nguyên tập hàng/nhãn. Cấu hình chi tiết và hash đầu vào nằm trong [execution.json](../../artifacts/evaluations/url_source_robust_v3/execution.json).

| Arm | Biểu diễn | Trọng số LR |
|---|---|---|
| V1 đối chứng | `format_url` gốc, giữ marker | `class_weight=balanced` |
| A | Giữ marker V1; bỏ đúng một tiền tố hostname `www.` trong view của model | `class_weight=balanced` |
| B | `format_url` gốc | `class_weight=None`, sample weight cân bằng nguồn trong mỗi nhãn |
| C | View như A | Trọng số như B |

A/C chỉ bỏ bốn ký tự đầu `www.` tại đúng vị trí hostname, không phân biệt hoa/thường. Userinfo, cổng, case còn lại, path, query, fragment và marker V1 được giữ nguyên. Raw URL, ID và nhóm miền không đổi. Ví dụ `https://name:www.pass@WWW.Example.COM:443/www.path?q=www.x` có view `[DOMAIN] name:www.pass@Example.COM:443 [PATH] /www.path?q=www.x`.

Đây là biểu diễn mất thông tin phục vụ mô hình. **Không khẳng định website có/không có www là cùng nội dung, cùng nhãn hoặc cùng độ tin cậy.** Không sửa URL người dùng hay dùng biến đổi này làm danh sách tin cậy.

Trọng số B/C, với N là số hàng train, Kᵧ là số nguồn xuất hiện trong nhãn y:

`sample_weight_i = N / (2 × Kᵧ × count_train(y, source_i))`

Mỗi nhãn có tổng trọng số N/2; mỗi nguồn trong một nhãn có khối lượng bằng nhau. TF-IDF vẫn fit mọi tài liệu train không trọng số; chỉ LR nhận sample weight. Không kết hợp thêm `class_weight=balanced`. OpenPhish chỉ có 208 mẫu train nên mỗi mẫu có trọng số 29,57, lớn hơn nhiều so với Chống Lừa Đảo (0,26); điều này có thể khuếch đại đặc điểm hoặc nhiễu của nguồn nhỏ.

**Collision được giữ và báo rõ:** view bỏ www tạo 11.724 nhóm trùng train (23.448 hàng), 2.814 nhóm trùng validation (5.628 hàng); không có nhóm xung đột nhãn trong hai tập này. Không xóa hàng, không sửa nhãn hoặc giả định hai URL tương đương. Mọi URL cùng miền vẫn nằm cùng fold. Số URL không tương đương số quan sát độc lập.

## Kết quả validation

Chính sách chính là ngưỡng cố định 0,5 và FPR5 cross-fit: chọn ngưỡng từ các mẫu âm ở bốn nhóm miền, chấm nhóm thứ năm, lặp đủ năm nhóm theo quy tắc SHA256 cũ. FPR5 là mục tiêu thực nghiệm trên phần chọn ngưỡng; không bảo đảm FPR bằng/nhỏ hơn 5% ở phần còn lại hoặc ngoài thực tế.

| Arm | TP gold/silver /24, ngưỡng 0,5 | FP /1.561, ngưỡng 0,5 | TP gold/silver /24, FPR5 | FP /1.561, FPR5 | Recall toàn nhóm, FPR5 |
|---|---:|---:|---:|---:|---:|
| V1 | 22 | 95 | 22 | 77 | 83,09% |
| A: bỏ www | 22 | 156 | 22 | 78 | 66,38% |
| B: cân bằng nguồn | 23 | 106 | 22 | 83 | 82,38% |
| C: kết hợp | 23 | 164 | 22 | 77 | 66,43% |

Tại FPR5, TP theo từng nguồn dương:

| Nguồn | V1 | A | B | C |
|---|---:|---:|---:|---:|
| Chống Lừa Đảo /5.623 | 4.662 | 3.712 | 4.620 | 3.710 |
| OpenPhish /58 | 56 | 53 | 58 | 58 |
| Tin Nhiệm Mạng /24 | 22 | 22 | 22 | 22 |

Tại FPR5, FP theo từng nguồn âm:

| Nguồn | V1 | A | B | C |
|---|---:|---:|---:|---:|
| Tin Nhiệm tổ chức /9 | 0 | 0 | 0 | 0 |
| Tin Nhiệm website /271 | 6 | 7 | 5 | 5 |
| Tranco /935 | 68 | 68 | 78 | 71 |
| Tranco VN /346 | 3 | 3 | 0 | 1 |

Nguồn chỉ có một lớp báo Recall hoặc FPR; Precision/F1 để N/A. Không diễn giải 0/9 FP là xác nhận nguồn đó an toàn hoặc hiệu quả đã đạt 100%. [summary.json](../../artifacts/evaluations/url_source_robust_v3/summary.json) và [report.md](../../artifacts/evaluations/url_source_robust_v3/report.md) giữ đủ các nguồn/tier, cutoffs từng fold và ngưỡng toàn validation. [failures.json](../../artifacts/evaluations/url_source_robust_v3/failures.json) giữ toàn bộ ID FP/FN cùng ca sửa được/thoái lui so với V1.

## Cổng nghiên cứu và diễn giải

Đã đăng ký trước fit: tại FPR5 cross-fit cần phát hiện ít nhất 22/24 dương gold/silver và không giảm Recall của bất kỳ nguồn dương nào quá 5 điểm phần trăm so với V1. A và C không qua vì Recall Chống Lừa Đảo giảm khoảng 16,9 điểm phần trăm; A còn giảm OpenPhish 5,17 điểm. B qua, nhưng FP tăng 77→83 và tổng TP giảm 4.740→4.700. [candidate_gates.json](../../artifacts/evaluations/url_source_robust_v3/candidate_gates.json) giữ kết quả đầy đủ, luôn ghi `deployment_authorized=false`.

Các ca smoke đã biết chỉ để mô tả, không có nhãn trong phép đánh giá và không dùng để chọn ngưỡng/model. B cho score rất cao trên `example.com` (0,9926), `example.org` (0,9812), URL GitHub dự án (0,9800) và Google (0,9979); A giảm score Google nhưng chưa xử lý được những ca còn lại. Không suy ra hiệu quả tổng thể từ bốn ví dụ này. Xem [smoke.json](../../artifacts/evaluations/url_source_robust_v3/smoke.json).

Thí nghiệm cho thấy bỏ một dấu hiệu nghi là shortcut không tự động cải thiện mô hình, và cân bằng nguồn theo số lượng cũng không bảo đảm chuyển nguồn tốt hơn. Đây không phải kiểm định nhân quả rằng model chỉ học nguồn: nguồn còn gắn với thời gian, nhãn, kiểu URL và campaign. Can thiệp www làm thay đổi vocab/IDF, và mất thông tin có thể loại bỏ cả tín hiệu hữu ích lẫn shortcut. Cần dữ liệu mới có bằng chứng, nhiều nguồn và các URL âm khó trước khi chọn mức vận hành khác.

## Minh chứng và tái kiểm tra

Runner [evaluation/url_source_robust_v3.py](../../evaluation/url_source_robust_v3.py) đã khóa hash trước fit; không chỉnh mã sau khi chạy. Ba model được xuất từ **đúng lần fit gốc** dưới `research_models/`, gồm JSON vocab và NPZ IDF/hệ số/intercept/classes, không pickle hoặc fit lại. Model tái dựng có score của toàn bộ 7.266 URL validation khớp từng bit; vocab/IDF B khớp V1, C khớp A. Đây là export nghiên cứu, chưa thay model đang chạy.

[verification.json](../../artifacts/evaluations/url_source_robust_v3/verification.json) xác nhận 58.128 quyết định, 96 nhóm, ba fit mới, không test, không API. Test phần mềm kiểm tra thay đúng hostname, giữ userinfo/IPv6/port/literal marker, train-only weights/vocab, collision không đổi nhãn, fold không tự dùng nhãn/score của chính nó để chọn ngưỡng, chống ghi đè và export khớp score. Test phần mềm không thay thế đánh giá hiệu quả model.

Chỉ kiểm tra lại, không huấn luyện/gọi API:

```bash
.venv/bin/python -B -m evaluation.url_source_robust_v3 verify \
  --out artifacts/evaluations/url_source_robust_v3
```

`prepare`/`run` chỉ dành cho thư mục thí nghiệm mới khi có lý do nghiên cứu rõ ràng. Giữ mọi kết quả âm, không chạy lại để chọn seed thuận lợi, không dùng official test để quyết định can thiệp tiếp theo.
