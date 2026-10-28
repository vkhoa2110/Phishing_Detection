# Tách hành vi tin nhắn và rủi ro URL — v2

Ngày 28/10/2026. Thay đổi này sửa phạm vi kết luận và chuẩn bị đánh giá độc lập; không phải công bố model đã tăng độ chính xác trên dữ liệu thực.

## Hai mục tiêu khác nhau

`final.risk_level` trong chế độ text bây giờ nói về **hành vi trong bản đã gửi LLM**. `assessments.url.risk_level` luôn giữ đánh giá chuỗi URL tại máy. LOW về hành vi không xóa cảnh báo URL. Giao diện hiển thị cảnh báo URL riêng, có màu và thông báo khi hai kết quả khác nhau. URL riêng lẻ vẫn có headline là mức của mô hình URL.

| Tình huống | Hành vi trong nội dung | URL | Hiển thị |
|---|---|---|---|
| LLM LOW, URL HIGH | LOW | HIGH | Hai mức riêng; cảnh báo URL và yêu cầu xác minh vẫn hiện |
| LLM HIGH, URL LOW | HIGH | LOW | Cảnh báo hành vi; ghi rõ điểm URL thấp không bác bỏ hành vi |
| LLM lỗi/tắt, URL HIGH | UNKNOWN | HIGH | Chưa kết luận hành vi, vẫn giữ cảnh báo URL |
| LLM LOW, có URL lỗi | LOW | UNKNOWN/partial | Nêu rõ URL chưa được đánh giá đầy đủ |
| Không URL, LLM hợp lệ | Theo LLM | not_present | Không tạo URL hoặc điểm giả |
| Chỉ URL, ML thiếu/lỗi | not_applicable | UNKNOWN | Không dùng nhận định LLM để giả thành kết quả ML |

API bổ sung `final.scope`, `final.policy_version`, `final.requires_review`, `final.review_reason`, `assessments.url`, `assessments.message`. Policy `separate-assessments-2.0`. Vì ý nghĩa headline đã được thu hẹp, không lấy chênh lệch headline v1/v2 làm bằng chứng một bộ phân loại đã tốt hơn trên cùng mục tiêu.

Mặc định `include_ml=false` trong API và giao diện. ML vẫn chạy cho URL; tùy chọn chỉ quyết định có đưa điểm ML vào prompt hay không. Không thay feature, trọng số hoặc các ngưỡng URL/RAG.

## Prompt theo phạm vi

Ứng dụng dùng `message-2.0` cho text, `message-rag-2.0` khi có nguồn. Các prompt yêu cầu phân biệt giao dịch tự khởi tạo, nơi nhập OTP, yêu cầu thực sự và trích dẫn giáo dục; thiếu chứng minh an toàn không tự là bằng chứng lừa đảo. Đầu ra thêm `context_kind`; trường này không tự ghi đè mức cảnh báo. Câu tự xưng “bài học” không tạo ngoại lệ cho yêu cầu lấy bí mật.

Quote phải xuất hiện trong bản gửi LLM; HIGH/WARNING thiếu quote hợp lệ chuyển UNKNOWN. RAG vẫn kiểm tra ID/đoạn nguồn, chưa kiểm chứng entailment. Nếu người dùng sửa bản gửi, giao diện ghi rõ kết luận chỉ áp dụng cho bản đã sửa.

`fuse_legacy`, `baseline-1.0`, `rag-1.0` được giữ cho các công cụ v1. Không sửa snapshot thực nghiệm cũ. Hash mã thay đổi sẽ chặn resume vào lượt cũ; chọn thư mục `--out` mới khi chạy lại.

## Dữ liệu mới và điều kiện chạy benchmark

Đã tải snapshot CC BY 4.0 từ [Vietnamese SMS Dataset](https://huggingface.co/datasets/trannguyenthaituan/vietnamese_sms_dataset), ghim revision. Tác giả mô tả SMS thực; dự án chưa xác minh độc lập quy trình thu thập. Nhãn 1 nguồn gộp spam/scam nên không được dùng trực tiếp làm nhãn phishing.

Đã chuẩn bị [200 bản ghi chờ review](../../data/annotation/vn_sms_v2/README.md), 80 dev/120 test; 103 có URL/97 không URL. Chia theo component của domain, mẫu câu và Jaccard token trước khi lấy mẫu. Không trùng domain/group giữa hai tập. Bước này không phải split thuần theo thời gian. Không thêm tin nhắn hoặc nhãn test vào kho RAG.

`evaluation.review` yêu cầu hai phiếu hoàn tất với mã khác nhau, quote hợp lệ, rationale và category; ca khác nhãn cần người thứ ba. Sau đó mới xuất nhãn chuẩn và hash khóa tập. CLI chỉ kiểm tra cấu trúc/khai báo, không xác thực danh tính người gán nhãn. Tình trạng hiện tại là **awaiting_human_review**; chưa có kết quả F1 trên 200 mẫu này.

Sau khi người gán nhãn hoàn tất, kiểm tra offline trước:

```bash
.venv/bin/python -m evaluation.ablation \
  --dataset data/evaluation/vn_sms_v2/dev.jsonl \
  --reviewed-manifest data/evaluation/vn_sms_v2/manifest.json \
  --prompt-profile message-v2 --fusion-policy separate \
  --out artifacts/evaluations/context_dev_v2 --max-tokens 8192 --seed 20261028
```

Thêm `--live --max-new-calls 320` để chạy tối đa 80 × 4 lượt trên dev; số mẫu nhị phân thực có thể thấp hơn do UNKNOWN được giữ riêng. Tập test khóa dùng `test.jsonl` với thư mục mới; tối đa 480 lượt cho 120 × 4. Công cụ từ chối trước khi gọi model/API nếu thiếu manifest đã review hoặc tệp hash không khớp. `--diagnostic` chỉ dành cho kiểm tra mô phỏng được ghi rõ, không phải cách thay nhãn chuẩn bằng nhãn nguồn.

Giữ ngân sách bằng nhau cho bốn arm, báo P/R/F1, FP/FN/UNKNOWN, coverage, token và latency. Dùng ít nhất ba lượt với thư mục khác nhau để đo dao động nếu tài nguyên cho phép; trình bày từng lượt và độ phân tán. Không lấy lỗi API làm UNKNOWN đúng trong tập gold UNKNOWN. Bootstrap phải lấy mẫu theo nhóm/chiến dịch nếu thêm khoảng tin cậy; chưa dùng bootstrap từng dòng như các quan sát độc lập.

## Rubric lời giải thích trước khi xem kết quả test

Chấm mù cấu hình trên cùng mẫu, mỗi chiều 0–2; ghi lý do chấm:

| Chiều | 0 | 1 | 2 |
|---|---|---|---|
| Dấu hiệu | Sai/bịa/nhầm trích dẫn với yêu cầu | Đúng một phần, còn suy diễn | Đúng hành vi và ngữ cảnh |
| Nguồn liên quan | Không liên quan | Liên quan gián tiếp | Trực tiếp hỗ trợ điều được đối chiếu |
| Claim được nguồn hỗ trợ | Vượt nguồn/mâu thuẫn | Hỗ trợ một phần | Claim nằm trong phạm vi nguồn |
| Hướng xử lý | Nguy hiểm/không phù hợp | Chung chung | Cụ thể, phù hợp và không đòi bí mật |

Với lời giải thích không dẫn nguồn, hai chiều nguồn ghi N/A, không tự cho 0 hoặc 2; báo riêng tỷ lệ có nguồn và số khẳng định chưa có căn cứ. Trích đúng không tự đạt điểm hỗ trợ. So sánh cùng tập mẫu cố định trước, không chỉ chọn lời giải thích đẹp hoặc mẫu RAG thành công.

## Kiểm tra triển khai

Test offline bao phủ ma trận mức URL/LLM, fallback khi lỗi, bảo toàn cảnh báo URL, redaction, nhãn tách spam/phishing, rò rỉ nhóm/domain, hai người cùng ID, quote sai, phân xử, UNKNOWN và hash tập khóa. Lượt `context_regression_v2` dùng sáu mẫu mô phỏng chọn từ các lỗi/ngữ cảnh đã biết, bốn arm, ngân sách 8.192; là diagnostic, không đo độ chính xác tổng quát. Kết quả được lưu riêng trong `artifacts/evaluations/context_regression_v2/`.

Đã chạy **117 test offline đạt**; **24/24 lượt API diagnostic hợp lệ**, không lỗi/cắt token. Các ca N13 (lịch phỏng vấn), N26 (bài học trích dẫn) trả LOW ở cả bốn arm, trong khi URL vẫn HIGH; P17/P26/PU16 giữ HIGH cho yêu cầu lấy bí mật hoặc prompt injection. Nguồn/quote và số đo diagnostic được đối chiếu bằng script độc lập, chưa chấm entailment bằng người.

Đã kiểm tra giao diện 1440×1000 và 390×844: dùng replay phản hồi thật cho nhánh LLM, không gọi API thêm; nhánh tắt LLM gọi backend/model cục bộ thật. Cảnh báo URL HIGH vẫn hiện cạnh headline hành vi LOW; tắt LLM cho UNKNOWN về hành vi và giữ URL HIGH. Không lỗi JavaScript hoặc tràn ngang. Ảnh và biên bản ở `context_regression_v2/browser/`.
