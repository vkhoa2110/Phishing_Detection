# Đánh giá ảnh hưởng của model URL

Thời điểm tạo lượt chạy (UTC): 2026-10-26T14:34:36.866222+00:00

Bộ dữ liệu: 60 mẫu, 30 phishing / 30 thông thường. Cặp có cả hai lượt LLM thành công: 19.

Trạng thái: {'live': True, 'stop_reason': 'pilot_stopped_for_output_truncation', 'note': 'Pilot 1536-token cap produced OUTPUT_TRUNCATED; kept separate from the complete 4096-token experiment. Two in-flight requests were cancelled; usage may not be reported by provider.'}

| Cấu hình | Coverage | Accuracy toàn bộ | Precision | Recall toàn bộ | F1 toàn bộ | FPR | TP/FP/TN/FN | UNKNOWN (+/-) |
|---|---:|---:|---:|---:|---:|---:|---|---|
| url_model_only | 100.00% | 51.67% | 50.85% | 100.00% | 67.42% | 96.67% | 30/29/1/0 | 0/0 |
| llm_only | 38.33% | 38.33% | 100.00% | 46.67% | 63.64% | 0.00% | 14/0/9/0 | 16/21 |
| llm_with_url_model | 31.67% | 25.00% | 76.47% | 43.33% | 55.32% | 13.33% | 13/4/2/0 | 17/24 |
| fusion_independent | 38.33% | 23.33% | 60.87% | 46.67% | 52.83% | 30.00% | 14/9/0/0 | 16/21 |
| fusion_with_url_model | 36.67% | 21.67% | 59.09% | 43.33% | 50.00% | 30.00% | 13/9/0/0 | 17/21 |

## Cách đọc

- `llm_only`: LLM chỉ nhận văn bản có URL, không chạy model URL cho quyết định này và không dùng quy tắc kết hợp ML.
- `llm_with_url_model`: cùng LLM/prompt/văn bản, nhận thêm điểm và ngưỡng model URL; đánh giá trước quy tắc tổng hợp.
- `fusion_independent`: kết hợp model URL với chính kết quả `llm_only`, tách tác động của quy tắc tổng hợp.
- `fusion_with_url_model`: kết quả ứng dụng khi model URL tham gia cả prompt và quy tắc tổng hợp.
- `url_model_only`: mức cao nhất của các URL trong thông điệp, không phân tích ngữ cảnh văn bản.
- HIGH/WARNING = dự đoán dương; LOW = âm; UNKNOWN/lỗi/chưa chạy = abstain. Accuracy lấy toàn bộ mẫu làm mẫu số; recall và F1 tính mẫu dương abstain là bỏ sót, không tự đổi abstain thành LOW. Precision/F1 không xác định được ghi N/A khi mẫu số bằng 0.

## So sánh theo cặp

| Tác động | Phạm vi | Sửa đúng | Làm sai thêm | Chênh accuracy | McNemar exact p |
|---|---|---:|---:|---:|---:|
| metadata_effect | all_cases, n=60 | 0 | 8 | -13.33% | 0.0078 |
| metadata_effect | both_llms_successful, n=19 | 0 | 4 | -21.05% | 0.1250 |
| fusion_effect | all_cases, n=60 | 0 | 9 | -15.00% | 0.0039 |
| fusion_effect | both_llms_successful, n=19 | 0 | 6 | -31.58% | 0.0312 |
| full_system_effect | all_cases, n=60 | 0 | 10 | -16.67% | 0.0020 |
| full_system_effect | both_llms_successful, n=19 | 0 | 6 | -31.58% | 0.0312 |

## Những mẫu thay đổi hoặc sai

- P01 (banking, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N01 (banking, nhãn 0): LLM=LOW, LLM+metadata=HIGH, tổng hợp=HIGH; URL ML=HIGH.
- N02 (banking, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P03 (banking, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N03 (banking, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P04 (banking, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N04 (banking, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P05 (banking, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N05 (banking, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N06 (delivery, nhãn 0): LLM=LOW, LLM+metadata=HIGH, tổng hợp=HIGH; URL ML=HIGH.
- P07 (delivery, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N07 (delivery, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P08 (delivery, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N08 (delivery, nhãn 0): LLM=LOW, LLM+metadata=HIGH, tổng hợp=HIGH; URL ML=HIGH.
- P09 (delivery, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N09 (delivery, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N10 (delivery, nhãn 0): LLM=LOW, LLM+metadata=UNKNOWN, tổng hợp=HIGH; URL ML=HIGH.
- N11 (work, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P12 (work, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N12 (work, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P13 (work, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N13 (work, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N14 (work, nhãn 0): LLM=LOW, LLM+metadata=LOW, tổng hợp=HIGH; URL ML=HIGH.
- P15 (work, nhãn 1): LLM=HIGH, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N15 (work, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N16 (shopping, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P17 (shopping, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N17 (shopping, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P18 (shopping, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N18 (shopping, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N19 (shopping, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P20 (shopping, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N20 (shopping, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N21 (government, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=LOW.
- N22 (government, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P23 (government, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N23 (government, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N24 (government, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N25 (government, nhãn 0): LLM=LOW, LLM+metadata=UNKNOWN, tổng hợp=HIGH; URL ML=HIGH.
- N26 (context, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P27 (context, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N27 (context, nhãn 0): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- P28 (context, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N28 (context, nhãn 0): LLM=LOW, LLM+metadata=LOW, tổng hợp=HIGH; URL ML=HIGH.
- P29 (context, nhãn 1): LLM=UNKNOWN, LLM+metadata=UNKNOWN, tổng hợp=UNKNOWN; URL ML=HIGH.
- N29 (context, nhãn 0): LLM=LOW, LLM+metadata=HIGH, tổng hợp=HIGH; URL ML=HIGH.
- N30 (context, nhãn 0): LLM=LOW, LLM+metadata=UNKNOWN, tổng hợp=HIGH; URL ML=HIGH.

## Phạm vi và giới hạn

Dữ liệu do người viết công cụ tự soạn trước khi chạy, chưa được người gán nhãn độc lập thẩm định. Đây là kiểm thử chẩn đoán tổng hợp, không phải test set ngoài thực tế hay đánh giá Accuracy/F1 tổng quát của model. Không dùng dữ liệu này để chọn lại ngưỡng hoặc huấn luyện.

Mỗi mẫu có ít nhất một URL. Sáu cặp kiểm soát dùng cùng URL với hai ngữ cảnh đối lập; tách theo `pair_id` khi chia dữ liệu sau này. Nhiều URL dùng miền ví dụ, một số dùng chuỗi URL công khai và IP dành cho tài liệu; không truy cập website và không xác nhận nội dung website. Nhãn nói về yêu cầu trong thông điệp, không phải nhãn xác thực của từng website.

LLM chạy một lần mỗi cấu hình, temperature=0.1; kết quả có thể dao động. McNemar là so sánh thăm dò trên mẫu nhỏ có các cặp kiểm soát phụ thuộc nhau, không chứng minh khả năng tổng quát. Không tự retry API; checkpoint giữ từng kết quả để chạy tiếp mà không trả phí lặp. Các lỗi API và UNKNOWN được báo riêng.

`manifest.json` lưu hash dữ liệu, model, mã nguồn và prompt; `results.jsonl` lưu từng dự đoán, bằng chứng, token và thời gian; `summary.json` có thêm số đo theo nhóm; `comparison.csv` mở được trong bảng tính. Không lưu API key.
