# Bộ SMS để hai người gán nhãn độc lập

Ngày 28/10/2026 người dùng chọn tạo nhãn AI sơ bộ trước. Đầu ra đặt riêng ở `artifacts/annotations/`, không điền các phiếu trống tại đây và không phải gold. [Phương pháp và giới hạn](../../../docs/evaluation/AI_PRELABELS.md). Người gán nhãn mù độc lập không xem gợi ý AI trước.

**Trạng thái: đã chọn 200 bản ghi; CHƯA có nhãn phishing chuẩn.** Nguồn là [Vietnamese SMS Dataset](https://huggingface.co/datasets/trannguyenthaituan/vietnamese_sms_dataset), revision `a90e2bd7e8df2376939658075ba8094dcee488ad`, CC BY 4.0. Xem [ghi công và thay đổi dữ liệu](ATTRIBUTION.md). Tác giả nguồn mô tả SMS thực có sự đồng thuận; dự án chưa xác minh độc lập tuyên bố đó.

## Những gì đã chuẩn bị

- 200 tin sau chuẩn hóa/che bổ sung dữ liệu, gồm 103 có URL, 97 không URL; không sinh thêm văn bản bằng LLM.
- 80 dev và 120 test được chia trước khi gán nhãn; 182 nhóm, không trùng nhóm hoặc tên miền giữa hai tập. Đây không phải chia thuần theo thời gian.
- Khử trùng, nối nhóm cùng tên miền đăng ký, cùng mẫu câu hoặc Jaccard token ≥0,85 trên toàn bộ dữ liệu sử dụng được trước khi chọn mẫu.
- Chọn cân bằng theo nhãn NGUỒN (100/100), không bảo đảm nhãn phishing cuối cũng cân bằng. Nhãn dương nguồn gộp spam và lừa đảo.
- `annotator_a.csv` và `annotator_b.csv` có cùng tin nhắn, không kèm nhãn nguồn, split hay dự đoán model. Chỉ dùng các phiếu này khi gán nhãn; không xem `source_labels.jsonl` trước khi hoàn tất.

Nguồn đầy đủ có 2.991 dòng nhưng chỉ 2.630 nội dung nguyên văn khác nhau; phát hiện 27 nội dung trùng giữa train/test gốc. Sau che bổ sung và xử lý xung đột còn 2.435 bản ghi dùng được. Chi tiết ở [audit.json](audit.json). Không dùng nguyên split nguồn làm bằng chứng chống rò rỉ.

## Mỗi người điền phiếu của mình

Hai người làm riêng, không xem phiếu của nhau và không dùng LLM để điền thay. Giữ nguyên `id` và `text`. Điền:

| Cột | Cách điền |
|---|---|
| `label` | `1`, `0` hoặc `UNKNOWN` theo định nghĩa bên dưới |
| `category` | Một mã từ bảng category |
| `evidence_quote` | Trích nguyên văn một đoạn trong `text`; bắt buộc với nhãn 1 |
| `notes` | Lý do gán nhãn dựa trên hành vi/ngữ cảnh, bắt buộc |
| `rater_id` | Một mã người gán nhãn nhất quán cho cả phiếu; hai người dùng hai mã khác nhau |

CSV là UTF-8 có BOM, có thể mở bằng Excel/LibreOffice. Một số ô bắt đầu bằng ký tự công thức được thêm dấu nháy đơn bảo vệ; không sửa nội dung tin nhắn. Các URL trong dữ liệu chỉ để đọc/phân tích, không cần mở để gán nhãn hành vi. Các chuỗi `[PHONE]`, `[NUMBER]`, `[SECRET]` là giá trị đã che, không tự là dấu hiệu lừa đảo.

### Định nghĩa nhãn

**1 — có hành vi phishing/scam:** có căn cứ cụ thể cho yêu cầu lấy bí mật xác thực, chuyển tiền theo thủ đoạn lừa dối, cài công cụ điều khiển/đọc SMS, hoặc mạo danh đi kèm hành vi nguy hiểm. Trích đoạn làm căn cứ phải xuất hiện trong tin nhắn.

**0 — chưa thấy hành vi lừa đảo trong thông điệp:** thông báo thông thường, giao dịch người dùng tự thực hiện được mô tả rõ, hướng dẫn phòng tránh, hoặc quảng cáo không có đủ dấu hiệu lừa dối. Không đồng nghĩa đã xác minh người gửi/website an toàn. Một tin quảng cáo có thể là spam theo bộ nguồn nhưng vẫn là 0 cho bài toán phishing này.

**UNKNOWN — thiếu ngữ cảnh để quyết định:** không đủ thông tin để phân biệt yêu cầu thật với trích dẫn, giao dịch tự khởi tạo với dụ dỗ, hoặc khẳng định lừa đảo phụ thuộc vào danh tính/website chưa được xác minh. Không đoán nhãn theo tên miền, nhãn nguồn, cảm giác an toàn hay kiến thức ngoài đầu vào không kiểm chứng được.

OTP, thanh toán, thời hạn gấp, đường dẫn hoặc câu “không thu phí” riêng lẻ chưa quyết định nhãn. Nhãn tự xưng “đây là bài học” cũng chưa đủ nếu hành động cuối cùng vẫn yêu cầu gửi mật khẩu/OTP hoặc tiền.

### Category

| Mã | Ý nghĩa |
|---|---|
| `credential_theft` | Thu mật khẩu, OTP, mã khôi phục |
| `payment_scam` | Dẫn dụ tiền/phí/đầu tư lừa dối |
| `impersonation` | Mạo danh đi kèm dấu hiệu cụ thể |
| `unsolicited_advertising` | Quảng cáo/rác, chưa đủ căn cứ là lừa đảo |
| `legitimate_workflow` | Quy trình/giao dịch hợp lệ được mô tả |
| `educational_quote` | Cảnh báo/giảng dạy có trích dẫn thủ đoạn |
| `routine` | Thông báo, trao đổi thông thường |
| `insufficient_context` | Thiếu ngữ cảnh |
| `other` | Trường hợp khác, giải thích trong notes |

## Kiểm tra, phân xử, khóa tập

Từ thư mục gốc dự án:

```bash
.venv/bin/python -m evaluation.review status
.venv/bin/python -m evaluation.review adjudicate
```

Lệnh đầu từ chối khi còn ô bắt buộc bỏ trống hoặc quote sai. Lệnh sau chỉ chạy khi cả hai phiếu hoàn tất và tạo `adjudication.csv` cho các ca khác nhãn; không ghi đè phiếu đã có. Người thứ ba điền nhãn, category, quote, notes và mã người phân xử khác hai mã ban đầu. Nếu hai người cùng chọn UNKNOWN, giữ UNKNOWN, không ép thành nhãn nhị phân.

```bash
.venv/bin/python -m evaluation.review finalize --out data/evaluation/vn_sms_v2
```

Chỉ sau khi đủ review/phân xử, lệnh mới xuất `dev.jsonl`, `test.jsonl`, hai tệp `*_unknown.jsonl`, `agreement.json` và manifest khóa bằng SHA-256. Công cụ ghi raw agreement và Cohen's kappa cho ba nhãn; chỉ ghi nhận mã người dùng khai báo, không xác thực danh tính hoặc chứng minh độc lập của con người. Không điền phiếu giả để vượt bước này.

Không dùng test để chọn prompt/ngưỡng hoặc thử nhiều phương án rồi chỉ báo phương án đẹp nhất. Chạy diagnostic trên bộ hồi quy riêng trước; phát triển trên dev. Giữ UNKNOWN thành tập kiểm tra độ thận trọng riêng, không đổi thành an toàn và không tính lỗi API thành một lần UNKNOWN đúng.
