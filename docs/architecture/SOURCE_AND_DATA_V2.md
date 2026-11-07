# Phát triển tiếp: chuyển nguồn, URL thực và công cụ review

Cập nhật **07/11/2026**. Lượt này tập trung dữ liệu và cảnh báo URL sau [nghiên cứu v1](RESEARCH_NEXT_V1.md). Đã chạy đối chứng, thu dữ liệu mới và tạo công cụ review; **chưa chứng minh model mới tốt hơn để thay bản đang dùng**. Không huấn luyện hoặc mở test SMS, không sửa báo cáo học thuật hoặc gọi LLM API trong lượt này.

## 1. Những gì đã hoàn tất

| Phần | Đầu ra | Kết luận |
|---|---|---|
| Kiểm tra lệch nguồn | 2 source classifiers + 3 lượt bỏ từng nguồn dương khỏi train | Chuyển nguồn yếu ở OpenPhish; không kết luận model chỉ học nguồn |
| Thử giảm shortcut | 3 model char mới: bỏ www trong feature view, cân bằng nguồn, kết hợp | Chưa cải thiện tổng thể; không thay V1 |
| Kiểm tra thang score | 10 calibrator theo nhóm miền, hai phạm vi fit và prior controls | Calibration phù hợp một thành phần dữ liệu có thể sai mạnh ở thành phần khác |
| Tuyến URL thực | 29 tham chiếu thu được từ 36 lựa chọn đã khóa; giữ 7 lỗi | Chưa có nhãn rủi ro; model vẫn cảnh báo phần lớn |
| Nguồn dương mới | 200 ứng viên trên 200 miền từ snapshot OpenPhish | Nhãn nguồn sơ bộ, không là test gold hoặc tập Việt Nam đã xác minh |
| Chấm ngoài dữ liệu cũ | 116 score tham chiếu + 1.000 score OpenPhish, không fit lại | Phải đọc cả số cảnh báo ở hai nhóm, không suy ra F1 từ nhóm một lớp |
| Review và chống tái sử dụng | HTML gán nhãn, CSV xuất riêng, bổ sung 236 dòng adaptive vào đăng ký mới | Chưa có nhãn người; không để dữ liệu đã xem quay lại test tương lai |

Tổng cộng **18 fit cục bộ**: 6 mô hình URL đối chứng, 2 mô hình nhận diện nguồn và 10 calibrator. Các export nghiên cứu giữ từ lần fit gốc, không refit để chọn seed tốt. Model, ngưỡng và pipeline app hiện tại không được thay bằng các ứng viên vừa thử.

## 2. Kết quả giải thích vì sao cần dữ liệu khác nguồn

Bỏ chỉ 208 URL dương OpenPhish khỏi train làm Recall trên 58 URL OpenPhish validation giảm từ **56 xuống 13**, trong khi số phát hiện Chống Lừa Đảo gần như giữ nguyên và gold/silver vẫn 22/24. Số tổng có thể che một nguồn bị bỏ sót rất nhiều. Việc loại nguồn cũng đổi số mẫu và class weight, nên chưa là kiểm định nhân quả thuần túy về nguồn.

Source classifier trong cùng lớp đạt balanced accuracy 59,65% ở âm và 64,73% ở dương, cao hơn majority-source baseline 25%/33,33%; nhưng không nhận đúng nguồn của nhóm nhỏ Tin Nhiệm Mạng và Tín Nhiệm Org. Accuracy dương còn thấp hơn baseline luôn chọn nguồn lớn nhất. [Chi tiết và giới hạn](../evaluation/URL_SOURCE_SHIFT_V2.md).

Ba can thiệp mới không giải quyết được tổng thể:

| Model | FP /1.561, ngưỡng 0,5 | TP core /24 | FP tại FPR5 cross-fit |
|---|---:|---:|---:|
| V1 giữ nguyên | 95 | 22 | 77 |
| A: bỏ www trong model view | 156 | 22 | 78 |
| B: cân bằng nguồn | 106 | 23 | 83 |
| C: kết hợp | 164 | 23 | 77 |

A/C giảm mạnh Recall Chống Lừa Đảo. B tăng khả năng cảnh báo OpenPhish nhưng tăng FP. Không sửa nhãn, không bỏ hàng có view trùng, không coi hai hostname www/non-www tương đương an toàn. [Cấu hình, collision và mọi kết quả](../evaluation/URL_SOURCE_ROBUST_V3.md).

Đối chứng calibration cũng cho thấy chọn tập không đại diện rất nguy hiểm: fit sigmoid trên all cải thiện Brier toàn validation **0,096168 → 0,071928**, nhưng làm Brier core xấu hơn **0,063362 → 0,180650**. Fit core cho kết quả ngược lại, với rất ít dương. Không đưa calibrator vào app từ kết quả này. [Phương pháp và bảng đầy đủ](../evaluation/URL_PROBABILITY_AUDIT_V2.md).

## 3. Dữ liệu mới đã có và chưa có

**29 tuyến tham chiếu:** thu được 7 URL Việt Nam, 22 quốc tế từ 16 nhóm miền; gồm đăng nhập, reset mật khẩu, thanh toán, query, bài viết và đường dẫn dài. Có 7 record được một tài liệu khác dẫn tới exact route; 22 dùng chính trang mục tiêu làm nguồn. Cả hai loại vẫn cần review; chứng cứ nguồn gốc không tự tạo nhãn URL-risk benign.

V1 cảnh báo **25/29**; A/B/C lần lượt 20/26/26 tại ngưỡng validation đã khóa. Đây là số cảnh báo trên tham chiếu **chưa có nhãn rủi ro**, không gọi là FPR. Không chọn A từ số 20 vì đã làm giảm mạnh Recall một nguồn khác. [Dữ liệu và mức chứng cứ](../evaluation/OFFICIAL_URL_REFERENCES_V1.md); [kết quả score](../evaluation/OFFICIAL_URL_DIAGNOSTIC_V1.md).

**200 ứng viên OpenPhish:** lấy một URL mỗi miền theo thứ tự hash đã khóa, ngoài danh mục miền lịch sử tại thời điểm thu. Feed không có first-seen, ngày công bố hoặc campaign, nên giữ các trường đó chưa biết. Không mở URL nghi ngờ; không dùng dữ liệu này làm blacklist ứng dụng. Nguồn toàn cầu, chưa xác định tỷ lệ mẫu Việt Nam. URL/raw feed được giữ cục bộ, không tái phân phối lên Git.

| Model | Cảnh báo /200 ứng viên nguồn dương | Cảnh báo /29 tham chiếu chính thức |
|---|---:|---:|
| Char V1 | 195 | 25 |
| A | 193 | 20 |
| B | 200 | 26 |
| C | 200 | 26 |

Bảng dùng cutoff FPR5 lịch sử riêng của mỗi model, không phải FPR thực đo bằng nhau trên dữ liệu mới. **Không ghép hai cột thành confusion matrix, Precision hoặc F1:** cột đầu chỉ có nhãn nguồn sơ bộ; cột sau không có nhãn rủi ro. Cảnh báo 200/200 không chứng minh model tốt hơn nếu cũng cảnh báo gần hết các tuyến tham chiếu. XGBoost cảnh báo 177/200 ở cutoff validation hoặc 193/200 tại 0,5. [Snapshot và điều kiện nguồn](../evaluation/OPENPHISH_CANDIDATES_V1.md); [chẩn đoán năm model](../evaluation/OPENPHISH_MODEL_DIAGNOSTIC_V1.md).

## 4. Trang review dùng ngay

Đã tạo [phiếu HTML tiếng Việt](../../artifacts/evaluations/official_url_reference_v1/review/index.html) cho 29 mẫu. Có thể mở tại **http://127.0.0.1:8002/** khi server review cục bộ đang chạy:

```bash
python3 -B -m http.server 8002 --bind 127.0.0.1 \
  --directory artifacts/evaluations/official_url_reference_v1/review
```

Nhập reviewer ID, đánh giá nguồn gốc riêng với rủi ro 0/1/UNKNOWN, ghi lý do và tải CSV mới. Mẫu chưa review để trống; chọn nguồn gốc không tự điền nhãn rủi ro. Trang che mọi score/model/nhãn nguồn, không API, localStorage, tự mở URL hoặc ghi đè corpus. Nguồn/URL vẫn hiển thị để review nên không phải mù hoàn toàn.

Một lượt người review không tự thành gold. Nếu dùng AI hỗ trợ thì vẫn ghi rõ AI/provisional; không tạo hai danh tính AI để qua gate hai người. [Renderer](../../scripts/data/render_official_review.py), [phiếu CSV gốc](../../data/annotation/official_url_reference_v1/review.csv), [kiểm tra browser](../../artifacts/evaluations/official_url_reference_v1/review/verification.json).

## 5. Giữ test tương lai tách biệt

[Đăng ký v2](../../artifacts/evaluations/prospective_url_registration_v2/protocol.json) thay cho v1 đối với những lượt thu sau: giữ danh mục cũ và thêm **236 dòng exposure** — toàn bộ 36 URL đã chọn (kể cả thu thất bại), cùng 200 URL feed đã dùng chẩn đoán. Không sửa đăng ký/pack v1 hoặc dữ liệu đã khóa. Hai model vận hành char V1/XGBoost và các ngưỡng của chúng vẫn giữ như cũ; các model V3 chưa được chọn làm ứng dụng.

Cutoff test vẫn là **14/11/2026 00:00 UTC**. [Pack v2 khởi tạo](../../artifacts/evaluations/prospective_url_pack_v2/manifest.json) đã verify nhưng **0 mẫu đủ điều kiện, ready=false**. Có 229 ứng viên/tham chiếu mới cho phát triển không đồng nghĩa có 229 mẫu test đã xác minh. Không điền giả ngày công bố bằng ngày tải để vượt schema evidence của prospective. Campaign lịch sử/mới chưa rõ vẫn là giới hạn chưa giải quyết.

Đã có dữ liệu và giao diện để bắt đầu review thực. Bước quyết định tiếp theo là có nhãn URL-risk có bằng chứng cho các URL hợp lệ khó và mẫu dương từ nhiều nguồn, rồi khóa chính sách trước khi thu/chấm test tương lai. Các lần chạy dev tiếp theo phải giữ mọi lỗi và kết quả bất lợi như lượt này.

## 6. Kiểm chứng

**531 kiểm thử offline đạt** sau các thay đổi; còn một cảnh báo deprecation Starlette/httpx sẵn có. Verifier giữ hash và tính lại 58.128 quyết định của đối chứng nguồn V3, 232 quyết định trên tham chiếu chính thức và 2.000 quyết định của feed; không sửa lỗi bằng chạy lại để lấy phản hồi thuận lợi.

Trang review kiểm tra đạt trên 1440/820/390/320px, nhãn mặc định trống, nguồn gốc không điền hộ nhãn rủi ro, UNKNOWN xuất được, mẫu chưa làm không có reviewer giả, XSS chỉ hiển thị text và CSV escape công thức. Browser test không tạo nhãn thật, gọi API hoặc gửi yêu cầu bên ngoài. Kiểm thử phần mềm không xác nhận nhãn nguồn, URL-risk hoặc tính đúng ngữ nghĩa của chứng cứ.

Raw feed, URL OpenPhish, score và các danh mục exposure có chứa chúng đều được Git ignore. Báo cáo học thuật trong `docs/reports/` vẫn giữ cục bộ. Git chỉ lưu mã nguồn, kiểm thử, tài liệu kỹ thuật và metadata tham chiếu công khai.
