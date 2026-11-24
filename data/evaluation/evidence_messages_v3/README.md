# Bộ tình huống mở rộng v3 — 22/11/2026

Đã thêm **400 dòng mới: 240 ca cơ sở, 40 biến thể prompt injection và 120 biến thể trình bày**. Tất cả do AI soạn hoặc biến đổi dựa trên tài liệu công khai; **không phải bộ do người tạo, không phải nhãn người/gold và chưa có kết quả chất lượng mô hình**. Nhãn thiết kế `label`/`behavior_label` chờ người kiểm tra. Không gọi LLM, chấm model URL, huấn luyện hoặc thêm nguồn vào RAG trong lượt thu thập này.

| Nhãn thiết kế AI, chỉ 240 ca cơ sở | Có URL | Không URL | Tổng |
|---|---:|---:|---:|
| PHISHING | 50 | 50 | 100/240 |
| BENIGN | 50 | 50 | 100/240 |
| INSUFFICIENT | 20 | 20 | 40/240 |
| Tổng | 120 | 120 | 240/240 |

Kênh **do AI chọn**: 120/240 SMS và 120/240 EMAIL. Đây là văn bản dựng cho kênh giả định, không phải 240 SMS/email nhận được. **0/400 tin thực nhận được xác thực; 0/400 cặp đủ hai người chấm**. Số mẫu độc lập không tăng thành 400 khi thêm các biến thể.

## Nội dung và nguồn

Có **40 trang nguồn thuộc 24 nhãn đơn vị xuất bản**, gồm 20 cảnh báo và 20 tài liệu quy trình. Chủ đề: đặt cọc du lịch, giả ví/OTP, phạt nguội, cài ứng dụng mã độc, đổi người thụ hưởng hóa đơn/BEC, lừa mã thiết bị, giả công an, vé máy bay, điện lực, hoàn hàng, BHXH, cộng tác viên, cấp quyền OAuth, phí vay, thu hồi tiền, khóa ví mã hóa, phí rút đầu tư, người quen, học bổng và đe dọa ảnh ghép.

Nhóm bình thường có quy trình tự khôi phục tài khoản, xác thực tự khởi tạo, đổi vé, hóa đơn điện/cước, chia sẻ tệp, lịch họp, học phí, sao kê, hoàn tiền, hủy đăng ký và nhận hàng COD; có cả nội dung giáo dục nhắc thủ đoạn nhưng không yêu cầu người nhận thực hiện hành vi nguy hiểm. Nhóm thiếu thông tin giữ phần ngữ cảnh chưa đủ, không ép thành benign.

- [Danh mục 40 trang](source_index.json), [nguồn và brief/hash](sources.jsonl), [bản thảo tình huống](scenarios.json). Nguồn chỉ hỗ trợ cơ chế/quy trình; không chứng minh câu chữ, mọi chi tiết thêm vào hoặc kênh là tin gốc.
- 37/40 nguồn có body tải trực tiếp; 1/40 đọc body qua trình duyệt (Zoom); 2/40 dùng bản nội dung của trang chính chủ trong chỉ mục tìm kiếm (An Giang, HUST) khi tải trực tiếp thất bại/chỉ có shell. Có ghi rõ phương thức; không mô tả tất cả là 40 bản HTML đã lưu thành công.
- `source_briefs/` chỉ phân phối trích dẫn ngắn ≤25 từ/nguồn và diễn giải AI; không phải toàn văn. `title` là nhãn chủ đề biên tập, `title_kind` ghi rõ. Không suy ngày xuất bản từ URL; ngày truy cập 22/11/2026.
- Không sử dụng nguồn quốc tế để khẳng định đã có đúng chiến dịch/tin nhắn tiếng Việt đó tại Việt Nam. Các tin tiếng Việt trong bộ là tình huống dựng lại.

## URL: phần nào thực, phần nào minh họa

Trong **120/240 ca cơ sở có URL**: **109/120 minh họa**, **6/120 dùng đích từng được cảnh báo**, **5/120 dùng địa chỉ dịch vụ được tài liệu công bố**. URL lịch sử/dịch vụ đều `current_safety_verified=false`; không mở website đích, không xác nhận trạng thái hiện tại.

URL minh họa dùng hostname trung tính dạng `r-<hash>.example`, không chứa từ chỉ nhãn. `.example` được dành cho minh họa theo [RFC2606](https://www.rfc-editor.org/rfc/rfc2606.html). Các URL này phù hợp kiểm parsing, đường đi metadata và hành vi văn bản; **không dùng chúng để công bố độ chính xác mô hình URL trên địa chỉ thực tế**. Chỉ 6 ca lịch sử có URL dương, không phải 50 URL phishing đã được xác thực. Tại thời điểm kết thúc thu thập, 400/400 dòng chưa chạy; lượt pilot riêng sau đó được ghi dưới đây, không thay kết quả/manifest của lượt thu thập.

**Cập nhật pilot cùng ngày 22/11:** đã chạy 20 ca cơ sở dev (8 dương/8 âm/4 thiếu theo AI) ×4 cấu hình focused, 80 lượt ứng dụng/102 request API thật. Mỗi arm đúng 16/16 ca nhị phân theo nhãn AI; hai arm URL có một ca thiếu thông tin chuyển từ UNKNOWN sang WARNING. 10/10 ca có URL được gửi metadata tới LLM trong cả hai arm URL. Không chạy holdout, injection/robustness hoặc toàn bộ 400 dòng; nhãn người vẫn 0/400. [Kết quả và giới hạn đầy đủ](../../../artifacts/evaluations/expanded_dev_pilot_20261122/README.md).

## Biến thể và đơn vị đánh giá

- **40 injection/40 bản gốc**: 20 gốc thiết kế phishing bị ép LOW, 20 gốc benign bị ép HIGH. Bốn cách chèn chỉ dẫn, có `base_id`, câu lệnh và mức bị ép. Phải so output gốc/chèn, lỗi và tuân lệnh riêng; không suy từ F1.
- **120 robustness/40 bản gốc**: mỗi gốc có ba bản bỏ dấu, viết hoa, xuống dòng. URL được giữ nguyên từng byte và kết quả trích xuất. Đây là ba biến đổi trình bày, chưa bao phủ lỗi gõ ngẫu nhiên, obfuscation URL, ảnh hoặc nội dung tự nhiên từ người dùng.
- Tính điểm chính trên ca cơ sở sau khi có nhãn người. Injection và robustness báo riêng theo cặp/gốc, không gộp để tăng N độc lập hoặc thu hẹp khoảng tin cậy giả tạo.

## Chia tập và trùng lặp

[Protocol](collection_protocol.json) khóa trước khi sinh cases; dùng nguyên builder supplement, seed **20261121**, mục tiêu dev 0,6 theo hash component, không chọn lại seed. Source/alias/template/campaign/miền/Jaccard≥0,75/quan hệ gốc–biến thể đi cùng tập.

| Nhóm | Dev | Holdout | Tổng |
|---|---:|---:|---:|
| Ca cơ sở | 183 | 57 | 240 |
| Injection | 31 | 9 | 40 |
| Robustness | 93 | 27 | 120 |
| Dòng dữ liệu | 307 | 93 | 400 |
| Component nguồn | 31 | 9 | 40 |

Dev cơ sở: **70 phishing/82 benign/31 thiếu**; holdout: **30/18/9**. Tỷ lệ dòng thực tế khác 60/40 vì chia theo nhóm, không chỉnh lại cho đẹp. Dương có URL nằm trong 14 component dev và 6 component holdout. **Holdout tác giả đã xem, không phải test mù độc lập**. Khi đánh giá FPR, chỉ 18 âm holdout là quá ít để chứng minh FPR thấp.

Audit `expanded_collection_20261122`:

- 240 ca cơ sở mới × **260 dòng cũ** (100 v1 +80 v2 +80 SMS dev đã dùng): **0 cặp trùng chính xác hoặc gần trùng Jaccard≥0,75**. Không kiểm hết trùng ngữ nghĩa. Không đọc/phân tích nội dung 120 SMS reserve.
- **0/40 URL trang nguồn trùng** danh mục v1/v2 theo canonical URL. Khác bài không đồng nghĩa khác thủ đoạn hoặc campaign độc lập.
- **3/40 nguồn đã có trong một phiên bản RAG**: EXP-W06 và EXP-L04 ở v2, EXP-W12 ở v1/v2. Phải tách nhóm đã có nguồn khi đánh giá RAG. Không thêm 37 nguồn còn lại vào corpus.
- Với PhishVN: **5/240 ca cơ sở trùng URL chuẩn hóa**, **7/240 trùng miền**. Không gọi toàn bộ bộ này là ngoài mẫu đối với URL model hoặc LLM.
- Recompute trên 400 dòng có **40 component**, **0/1.277 cạnh quan hệ vượt tập**. Phép kiểm bằng máy không xác minh campaign thực tế.

[Số đếm và audit](../../../artifacts/evaluations/expanded_collection_20261122/audit_summary.json) · [bảng kênh/nhãn/URL/split](../../../artifacts/evaluations/expanded_collection_20261122/counts_by_channel_label_URL_split.csv).

## Phiếu người chấm

Gửi riêng **[A, 400 dòng](../../../artifacts/evaluations/expanded_collection_20261122/human_review_all400/annotator_a.csv)** và **[B, 400 dòng](../../../artifacts/evaluations/expanded_collection_20261122/human_review_all400/annotator_b.csv)** cho hai người. Chỉ mã mù, nội dung và các cột người trống; thứ tự A/B khác nhau. Không gửi `cases`, overview, nguồn, inventory, registration hoặc khóa ID cho người chấm.

Chỉ điền `human_label` = PHISHING/BENIGN/INSUFFICIENT, căn cứ vào `evidence_basis`, mã người ở `reviewer_id`, ghi chú nếu cần. Không đổi ID/nội dung. Hai người chấm độc lập; để trống là chưa chấm. Đánh giá **hành vi yêu cầu người nhận thực hiện trong văn bản**; lời cảnh báo/trích dẫn không tự là yêu cầu lừa đảo, LOW không xác minh danh tính. Không thực hiện các lệnh chèn hoặc mở URL trong phiếu.

[Hướng dẫn và lệnh tổng hợp](../../../artifacts/evaluations/expanded_collection_20261122/README.md) · [400 dòng chờ](../../../artifacts/evaluations/expanded_collection_20261122/review_initial_status/review_status.csv). Hiện **0/400 cặp hoàn tất**, đồng thuận/F1 **chưa đo**. Chấm và xác nhận bởi người chỉ thay trạng thái nhãn; xuất xứ tác giả vẫn là AI. Không dùng AI điền thay người hoặc đổi tên bộ thành “do người tạo”.

## Tệp và kiểm toàn vẹn

`cases.jsonl` chứa 280 ca cơ sở/injection; `robustness_cases.jsonl` chứa 120 dòng riêng. [Pack bất biến](../../../artifacts/evaluations/expanded_collection_20261122/frozen/manifest.json), [SHA bên ngoài](../../../artifacts/evaluations/expanded_collection_20261122/frozen_manifest_anchor.json) khóa cả generator/catalog/helper/source. Phiếu tổng hợp 400 có registration riêng; không sửa các bản pack đã khóa.

Generator: [scenario_expansion.py](../../../evaluation/data/scenario_expansion.py). 13 test mới kiểm đơn vị đánh giá, nhãn AI, quan hệ gốc/chèn, giữ URL qua biến đổi và từ chối ghi đè. Full suite 22/11: **1.537/1.537 test phần mềm đạt**, một cảnh báo deprecation; không phải độ chính xác trên 1.537 tin.

Đây là bộ challenge có chủ đích với văn phong do một trợ lý tạo, gồm cả ca khá rõ. Chưa đại diện phân bố tin thật, chưa xử lý hết thiên lệch từ ngữ/độ khó hoặc sự phụ thuộc nguồn. Việc bổ sung số dòng không thay thế thu thập tin thực nhận, hai người gán nhãn và đánh giá độc lập.

## Kết quả full dev riêng — 22/11/2026

Đã hoàn tất **307 dòng dev × 4 cấu hình = 1.228 ô kết quả** qua runtime focused/API thật: 183 ca cơ sở, 31 injection, 93 biến thể trình bày. Giữ nguyên 80 ô pilot, gửi mới 1.148 lượt app/1.549 request provider; không chạy 93 holdout hoặc 120 SMS reserve cũ. Đây là lượt chẩn đoán theo nhãn AI, tách khỏi giai đoạn thu thập và đánh giá chính thức bằng nhãn người.

Trên **152 ca cơ sở nhị phân AI (70 dương/82 âm)**, LLM đơn đúng **146/152**, F1 **99,28%**; LLM+URL đúng **139/152**, F1 **97,18%**, có 3/82 báo nhầm so với 0/82 của LLM đơn. RAG sau verdict không phải điều kiện phân loại; khác biệt giữa các lượt sinh không chứng minh RAG cải thiện phát hiện. Toàn phạm vi có **72/1.228 lỗi phân loại**, gồm 65 lỗi ở biến thể xuống dòng. Không loại lỗi để làm đẹp chỉ số.

Nguồn, dữ liệu, split và model không đổi; **0/400 cặp nhãn người hoàn tất**. [Bảng đủ bốn cấu hình, lỗi từng ID, injection, giới hạn và kiểm chứng](../../../artifacts/evaluations/expanded_dev_full_20261122/README.md). Không dùng các số F1 theo AI này thay cho F1 trên nhãn người.
