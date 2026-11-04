# Kết quả dev: LLM, URL và RAG — objective v1

Tổng hợp ngày 03/11/2026, từ các lượt API hoàn tất tối 02/11/2026. **Đây là chẩn đoán trên nhãn tham chiếu AI chưa xác minh, không phải kết quả kiểm thử độc lập bằng nhãn người.** Test chưa chạy. Không gộp SMS bên ngoài với dữ liệu mô phỏng thành một điểm chung.

## Đầu vào và điều kiện

| Nhóm | Mẫu đã chạy | Nhãn 1 / 0 | Reference UNKNOWN giữ riêng | Lượt gọi |
|---|---:|---:|---:|---:|
| SMS bên ngoài, dev | 51 | 9 / 42 | 29 | 204 |
| Mô phỏng đối chiếu, dev | 40 | 16 / 24 | 8 | 160 |

SMS được lấy từ bộ dữ liệu công khai; tác giả nguồn mô tả là SMS thực, dự án chưa xác minh độc lập quá trình thu thập. Nhãn phishing được trợ lý nhận định lại theo rubric hành vi, không lấy trực tiếp nhãn spam của nguồn. Các ca mô phỏng do trợ lý soạn và gán nhãn theo thiết kế, nên có tính vòng tròn. Xem [protocol, nguồn và phân bố đầy đủ](OBJECTIVE_V1.md).

Cả bốn cấu hình dùng DeepSeek-V4-Flash qua API FPT, prompt `message-v3`, trần 8.192 token, timeout 90 giây và tối đa hai yêu cầu đồng thời. Giữ cấu hình, model URL, corpus 25 nguồn, chỉ mục E5 và ngưỡng theo protocol; không chọn lại bằng kết quả lượt này. Quy tắc `fusion_policy=separate` giữ kết luận nội dung riêng với cảnh báo URL; cấu hình có URL đưa điểm URL vào ngữ cảnh LLM, không lấy mức cảnh báo lớn nhất để ép kết luận.

Đã chạy **364/364 lượt**, gồm 360 phản hồi có trạng thái `ok` và 4 lỗi. Một lượt mỗi mẫu/cấu hình, không retry để thay lỗi. Các lỗi gồm `OUTPUT_INVALID` ba lượt và `OUTPUT_TRUNCATED` một lượt. Phản hồi `ok` vẫn có thể trả UNKNOWN sau kiểm tra bằng chứng.

## Kết quả SMS

Các số dưới đây đối chiếu với **nhãn AI**. WARNING và HIGH được tính là cảnh báo; LOW là không cảnh báo; UNKNOWN/lỗi là chưa kết luận. FPR là số cảnh báo trên 42 mẫu nhãn 0. Coverage là tỷ lệ trả được một trong ba mức LOW/WARNING/HIGH, không phải độ chính xác.

| Cấu hình | Precision | Recall | F1 phishing | Accuracy | FPR | Coverage |
|---|---:|---:|---:|---:|---:|---:|
| Chỉ LLM | 45,00% | 100,00% | **62,07%** | 74,51% | 26,19% | 96,08% |
| LLM + URL | 45,00% | 100,00% | **62,07%** | 76,47% | 26,19% | 98,04% |
| LLM + RAG | 40,91% | 100,00% | **58,06%** | 68,63% | 30,95% | 94,12% |
| LLM + URL + RAG | 42,86% | 100,00% | **60,00%** | 72,55% | 28,57% | 96,08% |

Cả bốn cấu hình cảnh báo đủ 9 mẫu nhãn dương, nhưng còn 11–13 cảnh báo trên các mẫu nhãn âm. Recall 100% trên chỉ 9 mẫu dương chưa chứng minh khả năng phát hiện ngoài thực tế. Có 22 SMS mà ít nhất một cấu hình khác nhãn tham chiếu hoặc chưa kết luận; 15 mẫu thuộc nhóm quảng cáo không mong muốn, 6 thuộc quy trình thông thường và 1 tin sinh hoạt. Cần rà cả tính đúng của nhãn và việc mô hình có nhầm quảng cáo/spam thành lừa đảo hay không.

Đối chứng luôn cảnh báo có F1 **30,00%**. Luôn LOW có accuracy **82,35%** nhưng bỏ sót toàn bộ 9 mẫu dương, F1 bằng 0. Vì vậy không dùng accuracy đơn lẻ để chọn cấu hình.

## RAG đã đóng góp gì trong lượt này?

Chỉ **10/51 SMS** tìm được nguồn theo ngưỡng hiện tại: 7 nhãn dương và 3 nhãn âm. Cả bốn cấu hình đều phân loại đúng cả 10 theo nhãn AI, nên F1 đều 100% ở nhóm này. Nhóm 41 SMS không tìm được nguồn gồm 2 nhãn dương và 39 nhãn âm.

Khi retrieval rỗng, hai cấu hình tương ứng nhận prompt không kèm nguồn, nhưng được gọi độc lập. Phần chênh lệch F1 tổng thể nằm ở nhóm này; **không thể quy chênh lệch đó thành tác hại hay lợi ích của tài liệu RAG**. Kết luận phù hợp là lượt này chưa chứng minh RAG cải thiện phân loại, đồng thời cho thấy độ phủ tài liệu trên SMS còn hạn chế. Khoảng bootstrap theo nhóm được báo đầy đủ trong artifact, chỉ mang tính thăm dò và không tính bất định do sai nhãn AI hoặc việc LLM sinh lại.

Trong các phản hồi SMS hợp lệ, LLM + RAG có citation khớp đoạn nguồn ở 8/10 lượt thực kèm nguồn; cấu hình đầy đủ là 9/10. Đây là kiểm tra chữ có tồn tại trong nguồn, **chưa chứng minh nguồn liên quan hoặc hỗ trợ đúng lập luận**.

## Kết quả mô phỏng và ý nghĩa của 100%

| Cấu hình | F1 phishing | Accuracy | Coverage | Cảnh báo nhầm / 24 mẫu âm |
|---|---:|---:|---:|---:|
| Chỉ LLM | 100,00% | **97,50%** | 97,50% | 0 |
| LLM + URL | 100,00% | 100,00% | 100,00% | 0 |
| LLM + RAG | 100,00% | 100,00% | 100,00% | 0 |
| LLM + URL + RAG | 93,75% | 95,00% | 97,50% | 1 |

**F1=100% của chỉ LLM không có nghĩa là đúng 40/40.** Cấu hình này đúng 16 mẫu dương và 23 mẫu âm; một mẫu âm bị lỗi cắt ngắn đầu ra. F1 của lớp dương bằng `2TP / (2TP + FP + FN + UNKNOWN_dương)` nên không bị giảm bởi UNKNOWN ở lớp âm. Accuracy và coverage vẫn giảm còn 39/40 = 97,5%. Trong báo cáo luôn đọc cùng số lỗi, coverage và accuracy.

16 ca injection nằm trong 40 ca mô phỏng. Cấu hình đầy đủ có một cảnh báo nhầm ở tin mô tả tự gọi ngân hàng để xác minh, kèm câu injection ép HIGH; một ca yêu cầu nạp tiền nhận việc kèm injection ép LOW bị lỗi đầu ra, được giữ là UNKNOWN dương. Chỉ LLM bị cắt ngắn ở ca thứ nhất. **Chưa đủ để kết luận hệ thống chống được prompt injection**, hoặc xác định injection là nguyên nhân duy nhất của từng lỗi.

Kết quả mô phỏng cao phản ánh tính rõ ràng của các biến thể do trợ lý thiết kế và khả năng đối chiếu với rubric của chính bộ này. Không coi đây là đại diện cho email/tin nhắn thực tế. Các URL `.example` trong mô phỏng chỉ là địa chỉ minh họa; không dùng lượt này để kết luận model URL phân biệt được website thực.

## Đánh giá riêng truy xuất

Đã chạy retriever cục bộ trên **12 truy vấn dev** được chọn trước, không gọi API. Mỗi truy vấn có nhận định AI sơ bộ cho toàn bộ 25 tài liệu. Có 5 truy vấn được AI đánh dấu có ít nhất một nguồn hỗ trợ trực tiếp; 7 chưa có nguồn trực tiếp.

| Chỉ số | Kết quả | Cách đọc |
|---|---:|---|
| Hit@3 | 60,00% | 3/5 truy vấn có nguồn trực tiếp tìm được ít nhất một nguồn đó |
| Từ chối khi thiếu nguồn trực tiếp | 85,71% | 6/7 truy vấn không có nguồn grade 2 được trả rỗng |
| Precision@3 | 11,11% | Trung bình 12 truy vấn, số nguồn grade 2 trong top 3 chia 3 |
| nDCG@3 | 50,75% | Trung bình 7 truy vấn có relevance khác 0; dùng cả grade 1 và 2 |

Grade 1 nghĩa là liên quan chủ đề; grade 2 hỗ trợ trực tiếp dấu hiệu hoặc bước xác minh. Có thể tài liệu grade 1 vẫn hữu ích, nhưng không đủ làm căn cứ trực tiếp. Các chỉ số trên phụ thuộc nhận định của một trợ lý, cỡ mẫu nhỏ, chưa thay cho relevance do người chấm độc lập.

Các điểm cần xem: tin giao hàng COD chưa lấy được nguồn trực tiếp theo nhãn AI; một đoạn giáo dục về đổi tài khoản nhận tiền trả về ba nguồn không liên quan theo nhãn AI; tình huống device-code chỉ có tài liệu liên quan chung. Xem [bảng từng truy vấn](../../artifacts/evaluations/objective_retrieval_dev_diagnostic_v1/report.md).

## Kiểm chứng, chi phí và việc còn thiếu

- Đã đối chiếu số học bằng scikit-learn, đủ checkpoint, nhãn và văn bản nguồn, đầu vào đã chuẩn bị và hash mã nguồn theo lượt chạy. Việc này xác nhận tính nhất quán của phép tính, không xác nhận nhãn AI đúng.
- Phát hiện **8 ca mô phỏng** có dấu `»` bị parser lấy vào cuối URL. Các bản trích thực tế và metadata dự kiến đều được lưu trong `verification.json`; chưa sửa parser hoặc thay kết quả của lượt đã chạy. Đây là hạn chế của đầu vào URL khi diễn giải ablation.
- Usage ghi nhận **1.417.648 token**. Lượt lỗi có thể thiếu usage; đây không phải tổng hóa đơn được xác minh. Chưa quy đổi thành tiền.
- Đã tạo phiếu chấm mù theo 16 mẫu dev chọn trước: 64 dòng, gồm 39 phản hồi hợp lệ, 1 lỗi và 24 dòng chưa gọi vì reference UNKNOWN. Điểm rubric còn trống; chưa có kết luận chất lượng lời giải thích.
- Nhãn người độc lập vẫn chưa có. Test và các ca reference UNKNOWN chưa chạy; chưa đánh giá khả năng từ chối trên toàn bộ ca mơ hồ.

Ưu tiên tiếp theo là rà các bất đồng spam/lừa đảo và thống nhất rubric, sửa trích URL có dấu câu, bổ sung nguồn trực tiếp cho các cơ chế còn thiếu và kiểm tra truy xuất trên dev. Mọi thay đổi dữ liệu, prompt hoặc pipeline cần phiên bản protocol mới; chốt trước khi chạy test. Không sửa nhãn để tăng điểm hoặc thêm đáp án test vào RAG.

## Tệp để kiểm tra

- [Bảng đầy đủ, số đếm và bootstrap](../../artifacts/evaluations/objective_dev_results_v1/report.md) · [Biểu đồ PNG](../../artifacts/evaluations/objective_dev_results_v1/comparison.png) · [SVG](../../artifacts/evaluations/objective_dev_results_v1/comparison.svg).
- [Dữ liệu chỉ số tổng hợp](../../artifacts/evaluations/objective_dev_results_v1/summary.json) · [Các bất đồng cần review](../../artifacts/evaluations/objective_dev_results_v1/cases_to_review.json).
- [Phiếu chấm lời giải thích](../../artifacts/evaluations/objective_dev_results_v1/explanation_blind_dev.csv), giữ trống để người chấm điền; không gửi bảng ánh xạ điều phối cùng phiếu mù.
- [Kiểm chứng SMS](../../artifacts/evaluations/objective_sms_dev_live_v1/verification.json) · [Kiểm chứng mô phỏng](../../artifacts/evaluations/objective_challenge_dev_live_v1/verification.json).

Kiểm tra lại kết quả đã lưu, **không gọi API**:

```bash
.venv/bin/python scripts/evaluation/verify_rag_ablation.py artifacts/evaluations/objective_sms_dev_live_v1
.venv/bin/python scripts/evaluation/verify_rag_ablation.py artifacts/evaluations/objective_challenge_dev_live_v1
.venv/bin/python -m evaluation.benchmark_pack verify --out data/annotation/objective_v1
```

Muốn dựng lại bảng/biểu đồ từ checkpoint, dùng thư mục đầu ra mới để giữ bản cũ:

```bash
.venv/bin/python scripts/evaluation/report_objective_runs.py \
  --sms artifacts/evaluations/objective_sms_dev_live_v1 \
  --challenge artifacts/evaluations/objective_challenge_dev_live_v1 \
  --out artifacts/evaluations/objective_dev_results_v1_rebuild
```

Artifact của lượt này được giữ cục bộ theo `.gitignore`. Tài liệu kỹ thuật này ghi kết quả và phương pháp; báo cáo học phần Word/PDF vẫn nằm riêng trong `docs/reports/`.
