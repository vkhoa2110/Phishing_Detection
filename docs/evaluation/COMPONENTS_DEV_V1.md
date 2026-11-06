# So sánh LLM, model URL và RAG — component dev v1

Ngày đăng ký và hoàn tất: **04/11/2026**. Đã đủ **640/640 lần thử API**, 634 phản hồi hợp lệ và 6 lỗi. **Chưa có cấu hình cải thiện đồng đều: RAG tăng F1 hành động trên ngữ cảnh tự soạn, nhưng các cấu hình đều báo nhầm cao trên SMS.** Không thay model, ngưỡng, nhãn hoặc kho RAG để tìm cấu hình thắng.

## Cấu hình và nhiệm vụ

| Cấu hình | Thông tin ngoài văn bản/URL nguyên văn |
|---|---|
| LLM | Không thêm thông tin |
| LLM + URL | Điểm và ngưỡng model URL |
| LLM + RAG | Đoạn tài liệu vượt ngưỡng truy xuất |
| LLM + URL + RAG | Cả hai loại thông tin trên |
| Model URL riêng, tính cục bộ | Chỉ phân loại chuỗi URL, không hiểu hành vi tin nhắn |

Bốn cấu hình LLM nhận cùng prompt, schema ba chiều, văn bản đã che dữ liệu, cấu hình sinh và validator. Chỉ thay danh sách `url_model` và `reference_documents`, các danh sách không dùng để rỗng. Không gửi ID, nhãn, nguồn nhãn, tier, nhóm mẫu hoặc lý do gán nhãn vào provider.

Prompt nghiên cứu kế thừa cách tách rủi ro URL / hành vi tin nhắn / rủi ro làm theo, bổ sung quy tắc RAG và nguồn dẫn. Đây **không phải prompt `message-v3` của ứng dụng, cũng không giống nguyên prompt lượt URL/ngữ cảnh trước**. Không so F1 giữa các lượt như một cải tiến cùng điều kiện.

Model URL chỉ chấm chiều URL khi có nhãn nguồn phù hợp; không so F1 URL của model với F1 hành vi của LLM như cùng nhiệm vụ. Không có cấu hình “chỉ RAG” dự đoán nhãn: retriever lấy tài liệu, không tự phân loại tin nhắn.

## Dữ liệu dev đã khóa

| Nhóm | Đầu vào | Nhãn dùng chấm |
|---|---:|---|
| SMS nguồn công khai | 80 | Hành vi: 9 dương, 42 âm, 29 UNKNOWN; nhãn AI chưa xác minh |
| Thông điệp đối chiếu dùng URL thực | 80 | URL: 40/40; hành vi: 32/32 và 16 UNKNOWN; hành động: 40/40; nhãn theo thiết kế và nhãn URL lịch sử |

Giữ toàn bộ nhóm SMS dev, bao gồm 29 nhãn chưa đủ thông tin. Chỉ 51 SMS có nhãn nhị phân vào Precision/Recall/F1; 29 mẫu còn lại báo phân bố đầu ra và lỗi riêng, không ép thành nhãn âm hoặc gọi việc trả UNKNOWN là chính xác đã được xác minh.

80 thông điệp đối chiếu dùng 16 URL, mỗi URL 5 biến thể, gồm link trung tính, xin bí mật, trích dẫn giáo dục và prompt injection hai chiều. Các dòng không phải quan sát độc lập; ngữ cảnh do trợ lý soạn, chưa phải tin nhắn thu từ chiến dịch thật. Hai nhóm dataset luôn báo riêng, không gộp thành một F1 chung.

Nguồn và nhãn giữ nguyên từ [objective v1](OBJECTIVE_V1.md) và [URL/context v1](URL_CONTEXT_V1.md). Dữ liệu đã được xem trước đây; đây là dev diagnostic, không phải holdout ngoài mới. Phần test chưa được chạy trong thực nghiệm này.

## Tài nguyên và điều kiện

- DeepSeek-V4-Flash qua endpoint FPT đã cấu hình; temperature 0,1, top_p 1, top_k 40, trần 8.192 token, timeout 90 giây, hai worker.
- Một lần gọi mỗi đầu vào/cấu hình: **160 × 4 = 640 lần thử API**. Một lượt không cho phép báo độ lệch chuẩn giữa các lần sinh; không chọn phản hồi tốt nhất hoặc thay lỗi bằng retry.
- Model XGBoost và ngưỡng giữ nguyên: WARNING **0,11384317278862**, HIGH **0,47364333271980286**.
- RAG dùng chỉ mục đang cấu hình: multilingual-e5-small, snapshot 25 tài liệu, top_k 3, ngưỡng cosine **0,849416**. Hai cấu hình RAG dùng cùng kết quả truy xuất đã lưu trước khi gọi API. Chưa so sánh các embedding/retriever khác trong lượt này.
- Chuẩn bị trước suy luận LLM: **15/80 SMS** và **58/80 thông điệp đối chiếu** có tài liệu. Phải đọc riêng nhóm có/không có nguồn; không quy mọi chênh lệch tổng thành tác dụng của RAG.
- Kho uy tín từ thử nghiệm trước chỉ được tra cứu ở mốc 04/11, không dùng nhãn trong kho làm điểm model hoặc cấp nhãn đánh giá cho LLM. Các URL xuất hiện trong 160 đầu vào đều không có hit; không có thông tin uy tín bổ sung để lập một cấu hình LLM riêng có ý nghĩa. [Kết quả thử nghiệm kho uy tín](REPUTATION_V1.md).

## Kiểm soát chạy và chấm điểm

[Bộ chạy](../../evaluation/component_ablation.py) ghi cấu hình, hash mã nguồn/model/embedding/corpus và dữ liệu trước suy luận. Lưu checkpoint và journal trước mỗi yêu cầu; khi tiếp tục, lần thử đã bắt đầu nhưng không có phản hồi được giữ là lỗi `INTERRUPTED_REQUEST`, không gửi lại. Dừng khi lỗi HTTP cần xử lý hoặc ba lỗi liên tiếp.

Cả bốn cấu hình dùng cùng kiểm tra JSON, mức dự đoán, trích dẫn đầu vào và nguồn dẫn. `source_quote` phải nằm trong tài liệu đã cấp; nguồn dẫn không tồn tại hoặc trích sai làm phản hồi không hợp lệ. Text trong corpus là đoạn tóm lược biên tập; khớp chữ trong corpus không có nghĩa là lời trích nguyên văn của trang web gốc. Kiểm tra này chưa xác nhận nguồn liên quan hoặc claim được hỗ trợ đúng về ngữ nghĩa; chưa có điểm rubric do người chấm độc lập.

HIGH/WARNING tính là cảnh báo, LOW là không cảnh báo. UNKNOWN/lỗi giữ riêng; mẫu dương chưa kết luận vẫn giảm Recall/F1. Accuracy dùng toàn bộ mẫu có nhãn nhị phân, UNKNOWN không tính đúng. Luôn đọc F1 cùng FPR và coverage. Báo cả baseline luôn cảnh báo/luôn LOW, số ca sửa đúng và làm sai thêm khi thêm từng thành phần.

[Công cụ tổng hợp](../../scripts/evaluation/report_components.py) kiểm tra lại số học bằng scikit-learn, payload, phản hồi gốc, hash và checkpoint. Bootstrap theo `group_id` là thăm dò trên nhãn cố định và một lần sinh; không bao phủ sai nhãn AI, việc dùng chung câu mẫu, mức dao động API hoặc lệch khi triển khai.

## Trạng thái và kết quả

Đã đủ checkpoint; `metrics_ready=true`, `stop_reason=all_calls_completed`. Số học đã được đối chiếu scikit-learn, kiểm tra lại payload, phản hồi gốc, quote, hash và journal. Việc này xác nhận sự nhất quán của phép tính, không biến nhãn AI thành gold.

### SMS: hành vi trong thông điệp

Chấm trên **51 nhãn nhị phân AI: 9 dương/42 âm**; 29 UNKNOWN được chạy và báo riêng. Các số là một lần sinh, không phải trung bình nhiều lần.

| Cấu hình | Precision | Recall | F1 | Accuracy | FPR | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| LLM | 26,67% | 88,89% | 41,03% | 50,98% | 52,38% | 94,12% |
| LLM + URL | 23,53% | 88,89% | 37,21% | 43,14% | 61,90% | 94,12% |
| LLM + RAG | 22,86% | 88,89% | 36,36% | 41,18% | 64,29% | 94,12% |
| LLM + URL + RAG | 25,71% | 100,00% | 40,91% | 43,14% | 61,90% | 94,12% |

Các cấu hình cảnh báo nhầm **22 / 26 / 27 / 26** trong 42 SMS nhãn âm. Baseline luôn cảnh báo có F1 **30%**; luôn LOW có accuracy **82,35%** nhưng bỏ sót cả 9 mẫu dương. Điểm hiện tại chưa phù hợp để khẳng định chất lượng sử dụng thực tế.

**Không kết luận “RAG làm hại” chỉ từ F1 tổng giảm.** Trong 51 SMS nhị phân, chỉ 10 có nguồn, 41 không có nguồn. Ở 10 mẫu có nguồn, LLM và LLM + RAG cùng F1 **85,71%**; khác biệt tổng giữa hai arm là 5 cảnh báo nhầm tăng thêm ở nhóm không có nguồn, nơi payload hai arm giống nhau. Ngay cả khoảng bootstrap thăm dò của chênh F1 tổng [−10,00; −0,98] điểm % cũng không xác nhận tác hại nhân quả của tài liệu khi chênh lệch xuất hiện ở các lần sinh trên đầu vào giống nhau.

Với 10 SMS có nguồn, cấu hình đầy đủ có F1 100% nhưng chỉ đúng **9/10**, vì một mẫu âm trả UNKNOWN. Tương tự mọi bảng khác, không đọc F1 lớp dương như accuracy.

Trên toàn bộ 80 SMS, 65 mẫu không có nguồn nên hai payload LLM / LLM + RAG giống nhau; **12/65** cặp vẫn khác mức hành vi. 42 SMS không có điểm URL bổ sung, trong đó 11 cặp LLM / LLM + URL khác đầu ra. Điều này cho thấy dao động sinh lại còn đáng kể dù temperature 0,1.

29 nhãn UNKNOWN không được chấm đúng/sai. Số mẫu được cảnh báo lần lượt là **24 / 25 / 23 / 25**; số trả UNKNOWN là **1 / 2 / 0 / 0**. Đây là phân bố đầu ra, chưa chứng minh các cảnh báo đó sai hoặc UNKNOWN luôn đúng.

### Ngữ cảnh dùng URL thực

| Mục tiêu — F1 | LLM | LLM + URL | LLM + RAG | LLM + URL + RAG |
|---|---:|---:|---:|---:|
| Rủi ro URL, 80 mẫu | 73,97% | 73,39% | 70,00% | 69,64% |
| Hành vi, 64 mẫu nhị phân | 98,46% | 95,38% | 100,00% | 100,00% |
| Rủi ro làm theo, 80 mẫu | 93,33% | 90,70% | 96,10% | 91,95% |

| Mục tiêu | FPR theo thứ tự bốn cấu hình trên | Coverage theo cùng thứ tự |
|---|---|---|
| Rủi ro URL | 15,00% / 72,50% / 30,00% / 82,50% | 41,25% / 92,50% / 55,00% / 96,25% |
| Hành vi | 3,12% / 6,25% / 0% / 0% | 100% / 98,44% / 98,44% / 98,44% |
| Rủi ro làm theo | 0% / 17,50% / 0% / 17,50% | 83,75% / 98,75% / 88,75% / 98,75% |

Model URL riêng trên chiều URL có F1 **69,57%**, Recall **100%**, FPR **87,50%**, coverage **100%**. 80 dòng dùng lại 16 URL, trong đó model cảnh báo nhầm 7/8 URL nhãn âm. Đây không phải kết quả trên 40 URL đứng riêng của lượt trước.

RAG không kèm điểm URL tăng F1 hành động **93,33% → 96,10%**, sửa đúng 6 ca và làm sai thêm 2 ca; accuracy tăng **83,75% → 88,75%**. Tuy nhiên, khoảng bootstrap theo miền của chênh F1 **[−1,56; +8,10] điểm %** còn chứa 0. Mẫu câu tự soạn khá rõ, chỉ 16 miền, một lần sinh; chưa đủ để nói RAG cải thiện ổn định trên thông điệp thực.

Hai cấu hình có RAG đạt F1 hành vi 100% nhưng cùng accuracy **63/64 = 98,44%**, vì một mẫu âm bị lỗi cắt ngắn. Điểm cao trên các mẫu đối chiếu theo thiết kế chưa chứng minh chất lượng ngoài thực tế hoặc chống prompt injection tổng quát.

### Tài nguyên, nguồn dẫn và lỗi

| Cấu hình | Phản hồi hợp lệ / lỗi | Token usage ghi nhận | Latency trung vị |
|---|---:|---:|---:|
| LLM | 159 / 1 | 412.231 | 6,00 giây |
| LLM + URL | 158 / 2 | 434.475 | 5,25 giây |
| LLM + RAG | 158 / 2 | 565.659 | 8,00 giây |
| LLM + URL + RAG | 159 / 1 | 518.001 | 6,71 giây |

Tổng usage **1.930.366 token**, chưa đối chiếu hóa đơn. Có 3 `OUTPUT_TRUNCATED` ở ba ca injection và 3 `OUTPUT_INVALID` do trích không nguyên văn ở cùng một SMS, thuộc ba arm. Toàn bộ lỗi được giữ; không retry. Không quy kết injection là nguyên nhân cắt đầu ra chỉ vì các lỗi đó nằm trong nhóm injection.

Trong 15 SMS được cấp nguồn, LLM + RAG có trích dẫn khớp corpus ở **11/15** phản hồi, cấu hình đầy đủ **13/15**. Trên 58 ngữ cảnh được cấp nguồn, các số tương ứng **31/58** và **30/58**. Đây chưa phải độ đúng ngữ nghĩa của lời giải thích.

### Hướng xử lý từ kết quả

Ưu tiên phân biệt quảng cáo/spam với hành vi lừa đảo rõ ràng và kiểm tra khả năng giữ UNKNOWN khi thiếu căn cứ. Lượt này dùng prompt ba chiều và validator nghiên cứu khác `message-v3`, nên kết quả này **không chứng minh ứng dụng bị hồi quy so với bảng SMS cũ**. Cần đối chiếu các ca bất đồng dưới cùng prompt và validator trước khi đưa thay đổi vào ứng dụng.

Tiếp theo, đánh giá độ liên quan của nguồn trong các ca đã truy xuất và rà model URL/ngưỡng trên dev phù hợp. Giữ riêng dữ liệu thực với ca tự soạn; không sửa nhãn hoặc thêm đáp án vào kho để tăng F1. Chưa nên chọn cấu hình vận hành chỉ từ lượt chẩn đoán này.

- [Bảng đầy đủ và so sánh theo cặp](../../artifacts/evaluations/components_dev_results_v1/report.md).
- [Biểu đồ F1, FPR và coverage](../../artifacts/evaluations/components_dev_results_v1/comparison.png), [SVG](../../artifacts/evaluations/components_dev_results_v1/comparison.svg).
- [Summary, bootstrap, đối chứng và lỗi](../../artifacts/evaluations/components_dev_results_v1/summary.json), [các ca cần review](../../artifacts/evaluations/components_dev_results_v1/cases_to_review.json).
- [Biên bản kiểm chứng](../../artifacts/evaluations/components_dev_results_v1/verification.json).

Tệp cục bộ: [execution](../../artifacts/evaluations/components_dev_live_v1/execution.json), [đầu vào và nhãn](../../artifacts/evaluations/components_dev_live_v1/cases.jsonl), [ML/retrieval chuẩn bị sẵn](../../artifacts/evaluations/components_dev_live_v1/prepared.json).

```bash
# Chuẩn bị/kiểm tra cấu hình; không gọi API.
.venv/bin/python -m evaluation.component_ablation \
  --out artifacts/evaluations/components_dev_live_v1

# Chạy hoặc tiếp tục theo checkpoint đã lưu.
.venv/bin/python -m evaluation.component_ablation \
  --out artifacts/evaluations/components_dev_live_v1 --live

# Chỉ chạy sau khi hoàn tất; kiểm chứng và tạo báo cáo, không gọi API.
.venv/bin/python scripts/evaluation/report_components.py \
  --run artifacts/evaluations/components_dev_live_v1 \
  --out artifacts/evaluations/components_dev_results_v1
```

Không chỉnh source đã khóa khi lượt đang chạy; nếu đổi phương pháp phải dùng phiên bản và thư mục mới. Artifact được giữ cục bộ theo `.gitignore`; báo cáo học thuật vẫn nằm ngoài Git.
