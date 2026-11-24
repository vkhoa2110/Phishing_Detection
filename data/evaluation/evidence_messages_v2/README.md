# Bộ thông điệp bổ sung v2 — 21/11/2026

Đây là **80 mẫu bổ sung có chủ đích**, giữ riêng bộ v1 và 120 SMS reserve. Nguồn mới so với 34 trang của v1; không có nghĩa các URL mới đối với PhishVN hoặc mọi nguồn đều chưa có trong RAG. Nhãn `label`/`behavior_label` vẫn do trợ lý thiết kế, **không phải nhãn người hoặc gold**. Chưa chạy URL model/LLM trên bộ này.

| Nhóm ca cơ sở, nhãn kịch bản | Có URL được intake nhận | Không URL | Tổng |
|---|---:|---:|---:|
| Tình huống lừa đảo | 20 | 20 | 40/72 |
| Quy trình hợp lệ/âm khó | 12 | 12 | 24/72 |
| Thiếu ngữ cảnh | 4 | 4 | 8/72 |
| Tổng ca cơ sở | 36 | 36 | 72/72 |

Thêm **8 biến thể injection ghép cặp**, không tính thành tám tình huống độc lập mới. Có 34 nguồn và 34 thành phần nhóm. Chủ đề gồm giả khóa tài khoản/thiết bị mới, điểm thưởng nhà mạng, khoản vay ứng phí, sao kê giả, OTP liên kết ví, tuyển dụng nạp tiền, giao hàng/hội viên, hoàn rút đầu tư, thuế, thiệp cưới và tống tiền bằng nội dung deepfake. Không có kiểm tra ảnh/video/QR thật: ứng dụng chỉ nhận phần văn bản.

## Xuất xứ và phạm vi nhãn

- **64/72 ca cơ sở dựng lại**, **8/72 là trích đoạn công khai ngắn** từ cảnh báo; tám biến thể tự soạn riêng. Không có tin thực nhận được xác thực: **0/80**. Không lấy tên hiển thị email hoặc địa chỉ người gửi riêng lẻ làm một thông điệp gốc.
- Tám trích đoạn đều không đầy đủ; chỉ một subject có kênh EMAIL rõ, bảy đoạn giữ UNKNOWN. Không ghép diễn giải của bài nguồn vào input để tạo thêm bằng chứng cho model.
- `label` mô tả tình huống theo tài liệu/thiết kế; `behavior_label` xét hành vi nhìn thấy trong đoạn input. Ca cơ sở có **32 dương/24 âm/16 chưa xác định về hành vi**, khác nhãn tình huống 40/24/8. Đặc biệt tám trích đoạn nằm trong cảnh báo nhưng thiếu căn cứ hành vi khi đọc riêng.
- Kênh ca cơ sở: **28 SMS/37 EMAIL/7 UNKNOWN**. 64 kênh của ca dựng do tác giả chọn, không phải 64 email/SMS thu được. Nguồn nói “tin nhắn” chung không tự chuyển thành SMS.
- `source_briefs/` chỉ lưu trích dẫn ≤25 từ mỗi nguồn, URL có trong nguồn và tóm lược do trợ lý viết; **không phải toàn văn/snapshot HTML gốc**. Hash chứng minh brief không bị sửa, không tự chứng minh bài web gốc hoặc nhãn đúng.
- URL nguy hiểm là đích **được cảnh báo tại thời điểm lịch sử**; URL dịch vụ là địa chỉ được tài liệu công bố. Cả hai đều `current_safety_verified=false`. Không tự thêm miền, protocol/path, không biến email người gửi thành URL và không truy cập đích nghi vấn.

## Chia tập và kiểm trùng

Khóa source/template/campaign/miền đăng ký/quan hệ biến thể và Jaccard ≥0,75 trong cùng component; seed **20261121** cố định, không chọn lại theo kết quả. Có **45 dev/35 holdout**, tương ứng **40/32 ca cơ sở**. Dev có 27 tình huống dương/9 âm/4 thiếu; holdout có 13/15/4. Đây là holdout tác giả đã xem, không phải test mù độc lập.

Dương có URL: dev **14 ca/3 component**, holdout **6 ca/1 component**. Dù tổng đủ 20 ca, số nhóm độc lập còn ít, nhất là holdout; chưa đủ để kết luận tổng quát nhiều campaign. Không đổi seed để làm đẹp bảng.

Audit tự động với 100 ca v1 và 80 SMS dev không thấy trùng chính xác hoặc gần trùng ở ngưỡng đã đặt, cũng không thấy miền chung. Chỉ so khớp bằng máy, không in nội dung holdout cũ hoặc chạy lại model; 120 SMS reserve không đưa vào so sánh. Trong PhishVN, **1/80 ca trùng URL chuẩn hóa** (ca hợp lệ, split test lịch sử) và **22/80 trùng miền**. Không gọi toàn bộ bộ này là ngoài mẫu đối với URL model.

Một nguồn (`S2-R02`) đã có trong corpus v1/v2 tại `VN-RAG-016`, gắn với một ca thiếu ngữ cảnh. Các nguồn mới **không được thêm vào RAG**. Kiểm URL/alias/trích ngắn không chứng minh hết trùng ngữ nghĩa hoặc vắng trong pretraining.

[Kết quả audit và quota](../../../artifacts/evaluations/supplement_collection_20261121/README.md) · [Pack đã khóa](../../../artifacts/evaluations/supplement_collection_20261121/pack_v2/manifest.json).

## Người chấm và cách dùng

[Phiếu A](../../../artifacts/evaluations/supplement_collection_20261121/pack_v2/human_review/annotator_a.csv) và [phiếu B](../../../artifacts/evaluations/supplement_collection_20261121/pack_v2/human_review/annotator_b.csv): 80 dòng/phiếu, chỉ mã mù, text và cột người trống. Không gửi sources/cases, khóa nối ID, inventory hoặc nhãn thiết kế cho người chấm. [Hướng dẫn phạm vi chấm](../../../artifacts/evaluations/supplement_collection_20261121/annotation_instructions.md). Hiện **0/80 cặp đủ hai người**, chưa có đồng thuận hay F1.

Lệnh kiểm từ gốc repo, không gọi provider:

```bash
.venv/bin/python -B -m evaluation.data.evidence_supplement verify \
  --out artifacts/evaluations/supplement_collection_20261121/pack_v2
```

Giữ SHA manifest ở nơi độc lập và thêm `--manifest-sha256 SHA_DA_LUU` để kiểm thay thế cả pack. Muốn tạo phiên bản khác phải dùng output mới, không sửa lại nhãn/split/hash của pack đã khóa. Không chạy holdout để tối ưu prompt hoặc đưa đáp án vào corpus. Sau khi có nhãn người vẫn cần đăng ký riêng phép đối chứng, scope hành vi/URL/toàn thông điệp và cách tính lỗi/UNKNOWN.
