# Phương pháp đánh giá

## Dữ liệu và nhãn

| Nhóm | Mục đích | Giới hạn |
|---|---|---|
| PhishVN với split chính thức | Huấn luyện/validation và đối chiếu test URL lịch sử | Test đã xem, nguồn/tier và thời gian còn gắn với nhãn |
| `data/annotation/objective_v1` | 200 SMS ngoài, 80 dev/120 test; challenge và 24 truy vấn nguồn riêng | Nhãn AI sơ bộ, phiếu người chưa hoàn tất |
| `data/annotation/url_context_v1` | 160 URL nguồn thực và 200 ca ngữ cảnh | Nhãn URL, hành vi và vai trò URL phải chấm riêng |
| `data/annotation/fresh_messages_v1` | 200 SMS review mới và 40 ca stress | Cùng snapshot nguồn SMS cũ; spam không phải phishing |
| `data/evaluation/rag_retrieval_*` | Chọn ngưỡng và chẩn đoán truy xuất | Câu do trợ lý soạn, chưa phải relevance gold |
| Gói prospective URL cục bộ | Chuẩn bị calibration/test tương lai theo thời gian, miền và campaign | Chưa đủ nhãn độc lập và quota để công bố test |

Giữ nguyên manifest, phân chia dev/reserve và phiếu review. Không đưa nhãn nguồn, đáp án, tier hoặc lý do gán nhãn vào payload LLM. Gán nhãn người trên bản sao phiếu mù, phân xử bất đồng rồi khóa phiên bản. Nhãn AI phải ghi rõ là AI, không tự điền tên người đánh giá. Nguồn chính thức chỉ là tham chiếu xuất xứ, chưa đủ để gán mọi URL của nguồn là benign.

## So sánh công bằng

1. Đăng ký giả thuyết, tập mẫu, model, prompt/schema, token, timeout, seed, corpus/index, quy tắc lỗi và giới hạn chi phí trước khi chạy.
2. Bốn arm LLM / LLM + URL / LLM + RAG / LLM + URL + RAG dùng cùng input và điều kiện; chỉ thay đúng thành phần nghiên cứu. Báo riêng các ca có/không có thông tin bổ sung. Nếu payload giống hệt, dùng chung response cho đối chiếu chính hoặc coi sinh lặp là diagnostic.
3. Chọn ngưỡng/prompt trên dev. Các split tách miền/campaign; không dùng test để chọn cấu hình. Các lượt đã xem chỉ được báo hồi cứu.
4. Không ép kết quả LLM + URL phải tốt hơn. Chênh lệch có thể do false positive URL, tài liệu lệch cơ chế, schema hoặc dao động sinh.
5. Với RAG sau phân loại, verdict khóa trước retrieval: F1 phân loại không thể chứng minh giá trị của nhánh này. Đo nguồn dẫn và lời giải thích riêng.

## Chỉ số và mẫu số

- **Precision** = TP/(TP+FP); **Recall** = TP/(TP+FN); **F1** = 2TP/(2TP+FP+FN); **FPR** = FP/(FP+TN). Thang 0–1, có thể trình bày theo phần trăm.
- **Accuracy** dùng toàn bộ mẫu nhị phân và phải kèm tỷ lệ lớp, baseline luôn HIGH/luôn LOW. Nhóm một lớp chỉ báo Recall hoặc FPR thích hợp.
- Predicted UNKNOWN và lỗi không được xóa để làm đẹp số. UNKNOWN trên dương làm giảm Recall/F1 theo protocol; báo coverage và lỗi riêng. Gold UNKNOWN nằm nhóm riêng, không tự đổi thành âm.
- Với dữ liệu lặp/biến thể, báo số mẫu và số nhóm độc lập, khoảng bất định theo nhóm nếu có; không coi các prefix của một hội thoại là độc lập.
- Báo FP trên 1.000 âm, Recall từng nguồn/tier và độ nhạy theo prevalence. Score model chưa hiệu chỉnh không phải xác suất phishing.
- Lưu mọi attempt, lỗi HTTP/transport/finish reason, model provider, usage và độ trễ. Không retry để thay phản hồi lỗi bằng kết quả thuận lợi hơn.

## Truy xuất và giải thích

Relevance chấm 0 không liên quan, 1 cùng chủ đề, 2 hỗ trợ trực tiếp. Chấm toàn bộ cặp truy vấn × tài liệu hoặc pool có thiết kế rõ; không chỉ chấm tài liệu được retriever hiện tại chọn. Báo Hit@k, Precision/Recall nguồn, khả năng từ chối ngoài phạm vi, từng mẫu số và nhãn AI/người.

Rubric giải thích chấm từng chiều 0–2: dấu hiệu đúng trong input, nguồn liên quan, claim được nguồn hỗ trợ, hướng xử lý phù hợp. Không có nguồn thì chiều nguồn là N/A theo protocol. Quote khớp chỉ xác nhận tồn tại chuỗi; không xác nhận entailment. Nguồn không có raw snapshot phải ghi thiếu provenance thay vì dùng chính tóm lược làm bằng chứng.

Hội thoại chấm riêng từng tiền tố theo thông tin đã xuất hiện; đo cảnh báo đầu tiên có căn cứ và cảnh báo sớm sai. Injection gồm ép LOW/HIGH trong input và trong tài liệu RAG. Các ca tự soạn phải báo riêng với SMS nguồn ngoài.

## Lệnh theo nhóm

Tất cả chạy từ root; xem `--help` trước khi thực thi. `NEW_DIR` phải là thư mục chưa có run cũ.

```bash
# Chuẩn bị dữ liệu/phiếu, không gọi LLM
.venv/bin/python -m evaluation.data.fresh_messages --out NEW_REVIEW_PACK
.venv/bin/python -m evaluation.data.review --help
.venv/bin/python -m evaluation.data.prospective_urls --help

# Chuẩn bị đối chứng RAG/hội thoại, không gọi LLM
.venv/bin/python -m evaluation.rag.controlled prepare --out NEW_RAG_PACK --model MODEL_ID --max-tokens 2048
.venv/bin/python -m evaluation.rag.summary_audit prepare --out NEW_SUMMARY_AUDIT
.venv/bin/python -m evaluation.messages.conversation prepare-paired --out NEW_CONVERSATION_PACK --model MODEL_ID

# Chẩn đoán biểu diễn URL trên train/validation
.venv/bin/python -m evaluation.url.representation_audit run --out NEW_URL_AUDIT

# Chọn ngưỡng/đánh giá retrieval; không gọi LLM, có đọc split truy vấn test
.venv/bin/python -m evaluation.rag.metrics --help
```

Runner `evaluation.messages.interaction_pilot` cần gói nguồn có hash tương thích với mã hiện hành. Runner này chỉ gọi API khi `run --live`. Một số runner cũ như `evaluation.messages.improvement_pilot run` gọi API trực tiếp theo protocol; không chạy `run` để thử import. Dùng `--help` hoặc `prepare` thích hợp. Các scorer/validator lịch sử có thể từ chối mã sau refactor; xem [tái lập lịch sử](development.md#tai-lap-lich-su).

[Danh sách công cụ](../scripts/README.md) · [Kết quả hiện có](results.md).
