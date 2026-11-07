# Nhóm tham chiếu URL tuyến chính thức, v1

Mục tiêu là có các URL cụ thể để review cảnh báo trên trang đăng nhập, khôi phục
mật khẩu, thanh toán và đường dẫn dài. Đây là **nhóm tham chiếu nguồn gốc do AI
biên soạn**, chưa phải tập âm chuẩn và không dùng để công bố FPR/Precision/F1.

## Chọn mẫu trước khi xem điểm model

Ngày 07/11/2026, đã khóa 36 URL, gồm 8 tuyến Việt Nam và 28 tuyến quốc tế, từ 16
nhóm miền theo đúng PSL của dự án. Danh sách gồm ngân hàng, chính phủ, trường
đại học, điện lực và dịch vụ tài khoản. Các nhóm đường dẫn được chọn trước:
login, password reset, payment, query, long path và article. Không tải model,
không gọi LLM và không đổi mẫu theo điểm dự đoán.

Hash của `selection.json`:
`f7b10637de9a4f28c0fa3c815cba06eaec03af9ef969a637b80f862197390352`.
Danh sách cũng khóa hash collector và đăng ký prospective hiện có trước khi
thu. Không thay 7 mẫu lỗi bằng mẫu khác để đủ quota.

## Kết quả thu nguồn

| Thuộc tính | Số lượng |
|---|---:|
| URL chọn trước | 36 |
| Có tài liệu nguồn thu thành công | 29 |
| Thu thất bại, giữ nguyên log | 7 |
| Nhóm miền trong các mẫu thành công | 16 |
| Tuyến Việt Nam / quốc tế thành công | 7 / 22 |
| Trùng URL hoặc miền trong exclusion lịch sử | 24 |
| Chưa trùng exclusion, vẫn chỉ là reference chờ review | 5 |
| Nhãn URL-risk đã xác minh | 0 |
| Lượt gọi model / LLM của collector | 0 / 0 |

Các tag có thể trùng trên một URL: login 4, password reset 5, payment 5, query 3,
long path 5, article 10. Nhóm có login và trang hướng dẫn thanh toán, chưa đại
diện cho mọi luồng giao dịch thực tế. Không gửi form, đăng nhập, xin reset,
thanh toán hay mở URL lừa đảo.

Lỗi gồm TLS không xác minh được tại `ts.hust.edu.vn`; timeout robots tại
`admission.stanford.edu`; redirect MIT sang host chưa nằm trong allowlist;
hai nguồn không trả HTML 200; và hai nguồn không có exact link đã đăng ký.
Collector giữ nguyên lỗi và không bỏ kiểm tra TLS, không vượt allowlist.

## Mức chứng cứ và hạn chế

Mỗi record có URL nguồn, publisher, UTC thu thực tế, URL cuối, HTTP status,
redirect chain, robots và hash snapshot. HTML/robots đầy đủ chỉ giữ trong
artifact cục bộ bị Git ignore; metadata nhỏ và phiếu review có thể được quản lý
phiên bản.

Chỉ **7/29** mẫu có một tài liệu chính thức khác dẫn exact route. **22/29** mẫu
dùng chính trang được chọn làm nguồn: 15 có self-link trong HTML, 7 chỉ có bằng
chứng trang trả HTML. Self-link không phải xác thực độc lập. Danh tính domain
được AI lựa chọn từ các website của tổ chức đã biết; collector không chứng minh
quyền sở hữu domain, không loại trừ website bị xâm nhập hoặc nội dung người dùng
đăng lên.

Vì vậy mọi record giữ `label=null`,
`label_scope=official_origin_reference`, `label_status=assistant_curated` và
`reviewer_ids=[]`. Phiếu review để trống nhãn/rationale/reviewer. Khi chấm model,
chỉ báo số cảnh báo/UNKNOWN theo route và pool, cùng các URL cần review; **không
gọi đó là false positive rate** khi chưa có nhãn rủi ro độc lập.

Đã kiểm overlap với exclusion của đăng ký prospective. 24 mẫu vào regression;
5 mẫu còn lại (MIT 1, Cloudflare 2, NHS 2) vẫn có
`prospective_eligible=false`: chưa có nhãn độc lập, campaign chưa biết. Đây là
nhóm phát triển có chủ đích, không chuyển thành test chưa từng nhìn sau khi
xem điểm model. Chứng cứ nguồn gốc cũng không được dùng để whitelist toàn miền
hoặc tự hạ mức cảnh báo của ứng dụng.

Nguồn chính thức tiêu biểu:
[Vietcombank](https://www.vietcombank.com.vn/),
[EVN](https://www.evn.com.vn/),
[GitHub hướng dẫn khôi phục thông tin truy cập](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/updating-your-github-access-credentials),
[Google khôi phục tài khoản](https://support.google.com/accounts/answer/7682439?hl=en),
[IRS thanh toán](https://www.irs.gov/payments),
[GOV.UK hướng dẫn nộp thuế](https://www.gov.uk/pay-self-assessment-tax-bill).

## Minh chứng và kiểm tra

- [Metadata, phiếu review và giải thích schema](../../data/annotation/official_url_reference_v1/README.md).
- [Danh sách khóa trước](../../data/annotation/official_url_reference_v1/selection.json).
- [Record thu thành công](../../data/annotation/official_url_reference_v1/records.jsonl).
- [Toàn bộ lượt thu, gồm lỗi](../../data/annotation/official_url_reference_v1/attempts.jsonl).
- [Tổng hợp thu nguồn](../../data/annotation/official_url_reference_v1/collection.json).
- [Collector](../../evaluation/official_url_references.py).

```bash
.venv/bin/python -B -m evaluation.official_url_references verify \
  --out data/annotation/official_url_reference_v1
```

Lệnh verify chỉ đọc record và snapshot, kiểm tra hash/overlap/route publication,
không truy cập mạng hoặc gọi model. Sáu kiểm thử offline của collector kiểm tra
allowlist, nhãn, selection lock, evidence tamper, overlap và giữ nguyên lượt lỗi.

## Phiếu review có thể dùng ngay

Đã có trang HTML tiếng Việt cục bộ tại
`artifacts/evaluations/official_url_reference_v1/review/index.html`. Trang chỉ hiển
thị metadata đã verify, URL, nguồn và quan hệ chứng cứ; không đọc hoặc hiển thị
điểm/dự đoán/nhãn rủi ro nguồn. Người dùng nhập mã của chính mình, đánh giá nguồn
gốc riêng với nhãn rủi ro 0/1/UNKNOWN và ghi lý do. Mọi lựa chọn ban đầu đều trống;
chọn nguồn gốc không tự chọn nhãn rủi ro.

Nút tải tạo CSV mới đúng schema `review.csv`, giữ mẫu chưa làm ở trạng thái trống,
không ghi đè record, không tạo người review giả và không tự chuyển thành gold.
Trang không gọi API, không mở URL, không lưu localStorage. Đóng hoặc tải lại sẽ
mất phần chưa xuất CSV. Ô CSV được escape công thức; nội dung nguồn được dựng
bằng `textContent`.

```bash
.venv/bin/python -B scripts/data/render_official_review.py \
  --out artifacts/evaluations/official_url_reference_v1/review/index-new.html
```

Ba test của renderer kiểm tra lọc thông tin dự đoán, xác minh nguồn trước khi
xuất, chống chèn script qua JSON và từ chối ghi đè. Browser smoke đã đạt ở bốn
kích thước 1440/820/390/320 pixel, gồm export UNKNOWN, CSV tám cột, escape công
thức, trường chưa làm giữ trống, không lưu phiên, không request ngoài và XSS chỉ
hiển thị dạng text. Các nhãn nhập lúc smoke là fixture và đã xóa, không phải nhãn
người.
