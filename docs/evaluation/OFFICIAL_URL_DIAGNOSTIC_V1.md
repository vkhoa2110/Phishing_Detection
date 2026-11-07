# Chẩn đoán cảnh báo trên URL tham chiếu nguồn chính thức

**Kết quả:** V1 cảnh báo **25/29** URL tham chiếu tại cả hai ngưỡng đã khóa. Ba can thiệp A/B/C cũng còn cảnh báo nhiều. Đây là dấu hiệu cần kiểm tra khả năng chuyển sang các tuyến thực tế, chưa phải tỷ lệ báo nhầm vì mọi URL trong nhóm này vẫn giữ `label=null`.

Không thay model, ngưỡng hoặc mức cảnh báo của ứng dụng từ phép chẩn đoán này. Đặc biệt, chứng cứ một website tự trả HTML hoặc có self-link không đủ để tự hạ HIGH hay tạo whitelist.

## Tập tham chiếu và khóa quy trình

Chấm **toàn bộ 29 record thu thành công** từ [nhóm tham chiếu nguồn gốc V1](OFFICIAL_URL_REFERENCES_V1.md); không lọc theo nhãn, nguồn, mức chứng cứ, điểm dự đoán hoặc việc đã trùng dữ liệu lịch sử. Bảy lượt thu thất bại ban đầu được giữ trong log của collector, không thay bằng URL khác và không đưa thành record có score giả.

Nhóm này được AI biên soạn, không phải nhãn âm độc lập. Có 7 URL Việt Nam, 22 quốc tế, 16 nhóm miền; 24 record có trùng URL hoặc miền trong exclusion lịch sử. Năm record còn lại cũng chưa đủ điều kiện prospective test vì chưa có nhãn độc lập và campaign chưa biết. Chỉ **7/29** có tài liệu nguồn khác dẫn exact route; **22/29** dùng chính trang mục tiêu làm nguồn, gồm cả self-link. Không đồng nhất nguồn tự dẫn với xác minh độc lập.

Runner mới [official_url_diagnostic_v1.py](../../evaluation/official_url_diagnostic_v1.py) kiểm hash selection, record, log thu, snapshot HTML/robots và đăng ký exclusion qua collector. Trước lần dự đoán đầu tiên, runner khóa bản sao mọi case, hash mã nguồn, toàn bộ model/manifest và bảng ngưỡng. Protocol: [execution.json](../../artifacts/evaluations/official_url_diagnostic_v1/execution.json), SHA256 `d3812ef2934eb37dcf41ca51468ef94ccea1d0763c3e7dd44b2da38d5f685818`.

Chỉ URL gốc đi vào model; nguồn, publisher, nhãn, chứng cứ và tag chỉ dùng nhóm kết quả sau suy luận. Bốn arm là export V1 gốc và đúng ba model từ lần fit [đối chứng V3](URL_SOURCE_ROBUST_V3.md), không fit lại. Điểm V1 validation được kiểm khớp checkpoint từng bit, các export V3 cũng được kiểm lại trước khi chấm tham chiếu. Chạy **116 score = 29 × 4**, **232 quyết định = 116 × 2 ngưỡng**, không lỗi suy luận, không API, không truy cập website và không đọc/chấm official test.

## Cảnh báo theo model và ngưỡng

Chính sách thứ hai dùng đúng cutoff FPR5 chọn từ **toàn validation lịch sử** ở V3, không chọn lại trên 29 tham chiếu và khác với năm cutoff riêng của cross-fit. Tên chính sách mô tả cách chọn cutoff trước đây, không có nghĩa 5% trên nhóm tham chiếu này.

| Arm | Cutoff 0,5: cảnh báo /29 | Tỷ lệ cảnh báo | Cutoff validation đã khóa | Cảnh báo /29 tại cutoff đã khóa | Tỷ lệ cảnh báo |
|---|---:|---:|---:|---:|---:|
| V1 | 25 | 86,21% | 0,525942398 | 25 | 86,21% |
| A: bỏ www trong model view | 23 | 79,31% | 0,616131779 | 20 | 68,97% |
| B: cân bằng nguồn | 26 | 89,66% | 0,531897565 | 26 | 89,66% |
| C: kết hợp | 26 | 89,66% | 0,590741039 | 26 | 89,66% |

Không chọn A vì có ít cảnh báo hơn trên nhóm không nhãn này: A đã làm giảm Recall nguồn Chống Lừa Đảo quá giới hạn đăng ký ở V3. Số cảnh báo thấp không tự chứng minh phát hiện tốt hơn; mô hình luôn không cảnh báo cũng đạt số cảnh báo bằng 0.

## Nhóm khu vực, mức tiếp xúc và chứng cứ

Bảng dưới dùng cutoff validation đã khóa của từng arm; số liệu là **cảnh báo/số record**.

| Nhóm | V1 | A | B | C |
|---|---:|---:|---:|---:|
| Việt Nam | 4/7 | 3/7 | 4/7 | 4/7 |
| Quốc tế | 21/22 | 17/22 | 22/22 | 22/22 |
| Regression: URL hoặc miền đã tiếp xúc | 21/24 | 17/24 | 21/24 | 21/24 |
| Chưa trùng exclusion, chỉ tham chiếu chờ review | 4/5 | 3/5 | 5/5 | 5/5 |
| Có tài liệu nguồn khác với target | 7/7 | 7/7 | 7/7 | 7/7 |
| Dùng chính target làm nguồn | 18/22 | 13/22 | 19/22 | 19/22 |

Một tài liệu nguồn khác vẫn chưa đồng nghĩa được người độc lập xác minh quyền sở hữu hoặc độ tin cậy hiện tại. Không dùng 7/7 này để suy ra rủi ro thực hoặc tỷ lệ sai; mục đích là chỉ ra tuyến cần review tiếp.

## Nhóm đường dẫn

Cùng cutoff validation đã khóa, cảnh báo/số record:

| Tag | V1 | A | B | C |
|---|---:|---:|---:|---:|
| Login | 4/4 | 4/4 | 4/4 | 4/4 |
| Password reset | 5/5 | 5/5 | 5/5 | 5/5 |
| Payment | 5/5 | 4/5 | 5/5 | 5/5 |
| Query | 2/3 | 2/3 | 2/3 | 2/3 |
| Long path | 4/5 | 4/5 | 4/5 | 4/5 |
| Article | 9/10 | 9/10 | 9/10 | 9/10 |

Tag có thể trùng, không cộng các hàng thành tổng mẫu. [summary.json](../../artifacts/evaluations/official_url_diagnostic_v1/summary.json) và [report.md](../../artifacts/evaluations/official_url_diagnostic_v1/report.md) giữ đủ mọi tag, nhóm overlap URL/miền, khu vực và chứng cứ cho cả hai chính sách. Raw URL/score/case nằm riêng trong artifact bị Git ignore; tài liệu này chỉ báo tổng hợp.

## Giới hạn và bước tiếp theo

Đây là stress diagnostic có chủ đích, quy mô nhỏ và không có nhãn rủi ro. Không tính Precision/Recall/F1 hay FPR; không xác nhận website hợp lệ chỉ từ không cảnh báo hoặc chứng cứ nguồn gốc. Cảnh báo rất nhiều trên các tuyến đăng nhập, khôi phục và thanh toán cho thấy kết quả validation lịch sử chưa đủ đại diện cho tuyến sử dụng thực tế.

Giữ V1 làm đối chứng, tiếp tục bổ sung nhãn có bằng chứng và review độc lập, nguồn âm khó có thời gian thu, nhiều miền/campaign và nhóm dương mới tương ứng. Không thêm 29 tham chiếu này vào train rồi gọi lại chúng là test độc lập, không đổi nhãn thành benign để hoàn thành bảng, và không tìm ngưỡng giảm cảnh báo trên chính các record vừa xem.

Kiểm tra lại chỉ đọc checkpoint/hash, không chấm model lại, không mạng và không fit:

```bash
.venv/bin/python -B -m evaluation.official_url_diagnostic_v1 verify \
  --out artifacts/evaluations/official_url_diagnostic_v1
```

[verification.json](../../artifacts/evaluations/official_url_diagnostic_v1/verification.json) xác nhận giữ toàn bộ 29 record và mọi score/quyết định. Kiểm thử phần mềm kiểm tra URL là đầu vào duy nhất, nguồn/chứng cứ không thay score, lỗi/score không hữu hạn được giữ, dùng `>=` tại cutoff đã khóa, nhóm tag chồng lấp, không mất/trùng record, và khóa case/model chống thay đổi. Kiểm thử phần mềm không phải đánh giá chất lượng model.
