# Chẩn đoán model trên 200 ứng viên OpenPhish mới thu

Đã hoàn tất **1.000 score và 2.000 quyết định**, giữ toàn bộ 200 ứng viên, không lỗi suy luận. Không fit, gọi LLM/API, mở website nghi ngờ, đổi ngưỡng theo feed hoặc thay model ứng dụng.

Các URL mang **nhãn nguồn sơ bộ**, chưa có nhãn rủi ro của người độc lập. Đây là nhóm một nguồn, chỉ có nhãn nguồn dương, không phải bộ test gold hoặc bằng chứng hiệu quả triển khai.

## Dữ liệu và khóa trước suy luận

Dùng toàn bộ 200 URL trên 200 miền từ [snapshot OpenPhish](OPENPHISH_CANDIDATES_V1.md), chọn theo hash trước khi chấm score. Không thêm/bỏ URL theo score hoặc chọn lại mẫu dễ. Tại bước thu, các miền chưa trùng danh mục lịch sử; campaign/first-seen vẫn chưa biết, vì vậy không suy ra độc lập hoàn toàn hoặc mới bắt đầu tấn công vào ngày tải.

[Runner mới](../../evaluation/openphish_model_diagnostic_v1.py) khóa code, 200 case, model/trọng số, môi trường và hai chính sách trước suy luận. Chỉ chuỗi URL đi vào model; nhãn nguồn, publisher và metadata không là đặc trưng. Nhóm lỗi sẽ giữ UNKNOWN trong mẫu số 200; lượt thực tế không gặp lỗi.

Năm model gồm XGBoost đang dùng, char V1 và ba arm [V3](URL_SOURCE_ROBUST_V3.md) từ lần fit gốc. Không huấn luyện lại hoặc chọn seed sau khi nhìn feed. Ngưỡng thứ hai là cutoff chọn theo mục tiêu FPR5 trên toàn validation **lịch sử**; không có nghĩa FPR5 trên nhóm mới và không phải so sánh cùng FPR thực đo trên dữ liệu mới.

## Kết quả

| Model | Cảnh báo tại 0,5 /200 | Cutoff validation đã khóa | Cảnh báo tại cutoff đã khóa /200 | Lỗi |
|---|---:|---:|---:|---:|
| XGBoost | 193 | 0,719510853 | 177 | 0 |
| Char V1 | 195 | 0,525942398 | 195 | 0 |
| A: bỏ www trong model view | 196 | 0,616131779 | 193 | 0 |
| B: cân bằng nguồn | 200 | 0,531897565 | 200 | 0 |
| C: kết hợp | 200 | 0,590741039 | 200 | 0 |

Số cảnh báo là mức đồng thuận với ứng viên được nguồn đánh dấu dương, **chưa phải Recall được kiểm chứng bằng nhãn người**. Không có âm đối chứng để tính Precision/F1/accuracy/FPR. Khoảng Wilson trong artifact chỉ minh họa giả định URL độc lập; campaign/hosting dùng chung hoặc sai nhãn nguồn có thể làm kết luận lạc quan.

B/C đạt 200 cảnh báo nhưng cũng cảnh báo **26/29** tuyến tham chiếu ở [chẩn đoán nguồn chính thức](OFFICIAL_URL_DIAGNOSTIC_V1.md). Nhóm tham chiếu chưa có nhãn rủi ro nên không ghép hai nhóm thành confusion matrix hoặc F1. Hai kết quả cho thấy cần kiểm tra cả cảnh báo thừa và bỏ sót trước khi chọn model; không chọn B/C vì riêng số 200/200.

Từ lượt chấm này, cả 200 URL đã trở thành **dữ liệu dùng chẩn đoán/phát triển**. Không dùng lại làm test chưa từng xem. Đã xuất danh mục exposure riêng và đưa vào đăng ký loại trừ mới; chưa đưa feed vào huấn luyện hoặc blacklist của app. Raw feed, URL và phiếu review tiếp tục nằm trong artifact ignored, theo phạm vi sử dụng của nguồn đã kiểm tra khi thu.

## Minh chứng

- [Protocol/hash trước suy luận](../../artifacts/evaluations/openphish_model_diagnostic_v1/execution.json).
- [Summary tổng hợp](../../artifacts/evaluations/openphish_model_diagnostic_v1/summary.json), [báo cáo đầy đủ và khoảng Wilson](../../artifacts/evaluations/openphish_model_diagnostic_v1/report.md).
- [Verifier](../../artifacts/evaluations/openphish_model_diagnostic_v1/verification.json) tính lại mọi quyết định từ checkpoint, không fit hoặc suy luận lại.
- [4 kiểm thử hợp đồng](../../tests/test_openphish_model_diagnostic_v1.py): lỗi/score không hợp lệ giữ UNKNOWN, mẫu số giữ đủ, cutoff không tìm bằng feed, thiếu/trùng kết quả bị từ chối, cấm nâng nhãn nguồn thành gold.

```bash
.venv/bin/python -B -m evaluation.openphish_model_diagnostic_v1 verify \
  --out artifacts/evaluations/openphish_model_diagnostic_v1
```

Lệnh verify không tải nguồn, không gọi model/API và không in URL nghi ngờ.
