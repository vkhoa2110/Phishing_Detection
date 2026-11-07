# Thu ứng viên URL dương từ OpenPhish để review

Đã kiểm tra khả năng thu dữ liệu mới bằng **một snapshot Community Feed chính thức**, phục vụ nghiên cứu học thuật cục bộ. Có **200 ứng viên trên 200 miền** chưa trùng danh mục miền lịch sử đã đăng ký tại thời điểm thu. **Chưa có nhãn người, chưa là bộ test hoặc calibration hợp lệ.** Bước thu giữ nguyên trạng thái chưa chấm model trong snapshot; sau đó đã chạy [chẩn đoán riêng trên toàn bộ 200 mẫu](OPENPHISH_MODEL_DIAGNOSTIC_V1.md), vì vậy chúng hiện là dữ liệu đã dùng phát triển, không dùng lại làm holdout chưa xem.

## Nguồn và phạm vi sử dụng

[Trang feed OpenPhish](https://openphish.com/phishing_feeds.html) cung cấp Community Feed dạng text với chu kỳ cập nhật 12 giờ, dẫn trực tiếp tới endpoint công khai của chính OpenPhish trên GitHub. [Điều khoản OpenPhish](https://openphish.com/terms.html) cho phép nghiên cứu học thuật/độc lập/cá nhân trong phạm vi được nêu, đồng thời giới hạn sử dụng thương mại, nghiệp vụ tổ chức và phân phối dữ liệu cho bên thứ ba. Đã đọc hai trang chính thức trước khi thu; bản HTML cùng nguồn feed được lưu cục bộ để đối chiếu tại thời điểm lấy.

Snapshot, URL, phiếu review và mọi đầu ra chứa URL được giữ trong thư mục artifact đã ignore. **Không đưa feed hay danh sách URL lên Git, không tái phân phối và không tích hợp feed này thành blacklist phục vụ người dùng.** Tài liệu kỹ thuật chỉ công bố quy trình, hash và số đếm tổng hợp. Không gọi Community Feed là một giấy phép dữ liệu mở có thể tái phân phối.

## Quy trình đã khóa trước khi tải

1. Khóa source code, chính sách chọn tối đa 200 miền, danh mục loại trừ và đăng ký prospective đang có. Không sửa registration/normalizer/model đã khóa.
2. Chỉ GET ba endpoint cố định: trang feed, điều khoản và endpoint Community Feed được trang chính thức dẫn tới. Một lần mỗi endpoint; không retry, không theo redirect, không bỏ qua TLS. **Không mở bất kỳ URL nghi ngờ nào trong feed.**
3. Lưu nguyên byte response, mã HTTP, headers, thời điểm gửi/nhận UTC và SHA-256. Feed trả HTTP 200, `text/plain`, 15.578 byte; tải hoàn tất **07/11/2026 10:24:07.676491 UTC**.
4. Chuẩn hóa URL offline bằng normalizer hiện hành với private PSL; loại URL không hợp lệ, trùng normalized URL hoặc miền lịch sử. Index lịch sử đã đăng ký bao gồm train, validation, test lịch sử và adaptive; độ đầy đủ campaign lịch sử vẫn là giới hạn đã khai báo.
5. Xếp theo SHA-256 của tiền tố cố định cộng normalized URL, lấy URL đầu tiên mỗi miền và tối đa 200 miền. Không dùng score, dự đoán, tên thương hiệu hoặc mức độ “dễ” để chọn mẫu.
6. Giữ nhãn nguồn sơ bộ và tạo phiếu review để trống. Ở bước thu không nhập vào pack prospective hoặc gọi model; checkpoint của bước này không bị sửa sau các lượt chẩn đoán riêng.

SHA-256 raw snapshot:

```text
e17a925c5d4034c9468ce3b186740a3fdd01c807cb92a3fa40c1c3dde20fc114
```

## Số lượng và trạng thái

| Bước | Số lượng |
|---|---:|
| Dòng không rỗng trong feed | 300 |
| Không qua normalizer thận trọng | 9 |
| URL có miền trùng index lịch sử | 23 |
| URL hợp lệ chưa trùng miền lịch sử | 268 |
| Miền ứng viên độc nhất trước quota | 215 |
| URL/miền được chọn theo hash | 200 / 200 |
| Đã được người xác minh | **0** |
| Đã tính điểm model | **0** |
| Đủ điều kiện prospective hiện tại | **0** |

Chín dòng bị từ chối chỉ là ngoài phạm vi chuẩn hóa hiện hành; **không phải chín URL được xác định an toàn hoặc gỡ nhãn nguồn**. Một miền theo private PSL cũng chưa bảo đảm một campaign độc lập; các project cùng nền tảng hosting có thể thuộc cùng chiến dịch.

Mỗi ứng viên giữ:

- `source_label=1`, `label_status=external_source_provisional`; đây là nhận định của nguồn, không phải nhãn người hay kết quả ứng dụng.
- `observed_at` là lúc snapshot được tải; **không phải first-seen**, ngày URL được tạo, ngày bắt đầu tấn công hoặc ngày nguồn công bố URL. `source_first_seen_at` và `source_published_at` đều `null` vì feed không cung cấp.
- `campaign=null`, `campaign_status=unknown`, `reviewer_ids=[]`, `human_verified=false`, `prospective_eligible=false`.
- Hash chọn mẫu, dòng gốc trong snapshot và URL nguồn bằng chứng; không có score model.

Đây là nguồn toàn cầu, **không phải tập phishing Việt Nam đã xác minh**. Chưa có nhãn ngôn ngữ, nạn nhân mục tiêu, phạm vi fraud/abuse, bằng chứng trang đích hoặc nguồn dương độc lập thứ hai. Cần kiểm tra các giới hạn đó trước khi diễn giải hiệu năng cho người dùng Việt Nam.

## Việc còn thiếu trước đánh giá

Cần review độc lập nhãn phishing, xử lý bất đồng và campaign, thu nguồn dương khác cùng URL hợp lệ khó, và giữ cutoff prospective đã đăng ký. Không gán first-seen từ thời gian tải hoặc tự điền `published_at` để qua schema evidence đang yêu cầu ngày công bố. Bộ candidate này có schema riêng để giữ đúng sự thiếu metadata; phải có nguồn bằng chứng phù hợp hoặc một quy trình evidence mới được đăng ký rõ ràng trước khi nhập vào bộ đánh giá chính thức.

Chỉ đánh giá sau khi chốt dữ liệu/chính sách và đáp ứng các điều kiện nhãn/nguồn/tách campaign. Không dùng 200 ứng viên này để huấn luyện rồi đồng thời tuyên bố cải thiện trên chính chúng. Không chọn URL đưa vào tập dựa trên điểm model. Các URL có thể đã tồn tại trước lúc tải; “mới thu” không đồng nghĩa mới xuất hiện hoặc độc lập hoàn toàn với các nguồn ngoài chưa có trong index lịch sử.

## Công cụ và minh chứng

- [Bộ thu snapshot và chọn ứng viên](../../evaluation/openphish_candidates_v1.py); [5 kiểm thử offline](../../tests/test_openphish_candidates_v1.py), gồm quota/hash-order, loại miền lịch sử, trạng thái provisional, cấm tải URL ngoài ba endpoint và phiếu review để trống.
- [Protocol cục bộ trước fetch](../../artifacts/evaluations/openphish_candidates_v1/protocol.json), [retrieval metadata/hash](../../artifacts/evaluations/openphish_candidates_v1/retrieval.json).
- [Summary tổng hợp](../../artifacts/evaluations/openphish_candidates_v1/summary.json), [verifier](../../artifacts/evaluations/openphish_candidates_v1/verification.json). Verifier dựng lại toàn bộ lựa chọn offline; 0 request, 0 model inference.
- Dữ liệu nhạy cảm/giới hạn phân phối ở `artifacts/evaluations/openphish_candidates_v1/`, được `.gitignore` loại. Phiếu `blind_review.csv` không chứa nhãn nguồn hoặc score, nhưng còn URL và ngữ cảnh nguồn để review; không gọi là mù hoàn toàn.

```bash
# Kiểm tra snapshot hiện có: không tải lại và không gọi model.
.venv/bin/python -B -m evaluation.openphish_candidates_v1 verify \
  --out artifacts/evaluations/openphish_candidates_v1
```

Runner từ chối fetch lại khi đã có journal bắt đầu. Không chạy lệnh tải định kỳ trong app; một snapshot này phục vụ kiểm tra tính khả thi và chuẩn bị review cục bộ. Muốn thu đợt khác cần xem lại điều khoản hiện hành, chu kỳ nguồn và dùng thư mục/protocol mới.
