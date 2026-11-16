# Kết quả và giới hạn

Các số dưới đây tóm tắt các lượt thực nghiệm theo từng mốc, cập nhật đến 13/11/2026. [Tài liệu lịch sử trước lần tổ chức cấu trúc](https://github.com/vkhoa2110/Phishing_Detection/tree/479c96612ca79d3e1de2d37df22d82ce19e09f23/docs) và các manifest/raw cục bộ giữ nguyên.

## URL

<a id="url"></a>

Baseline PhishVN gold/silver, 21 đặc trưng, ngưỡng 0,5: LR tái lập F1 **53,88%**, RF năm seed **46,44 ± 0,41%** so với công bố **46,32 ± 0,42%**. Còn khác biệt môi trường và một số quyết định, chưa tái lập từng bit. Đối chứng bronze gồm 39 lượt huấn luyện cục bộ; nguồn và tier tạo khác biệt rõ, chưa chứng minh model chỉ học nguồn.

Validation model ứng dụng có 24 dương gold/silver, 5.681 dương bronze và 1.561 âm. WARNING cũ tạo 1.099 FP, HIGH hiện hành tạo 243 FP. HIGH có Precision toàn validation 95,02% nhưng gold/silver chỉ 8,65% vì prevalence khác. Dải giữa được hiển thị UNKNOWN, không giải quyết toàn bộ báo nhầm bằng cách đổi tên mức cảnh báo.

| So sánh pipeline | XGBoost ứng dụng | TF-IDF ký tự + LR |
|---|---:|---:|
| Validation cross-fit nhắm FPR 5%: phát hiện dương core | 20/24 | 22/24 |
| Validation cross-fit: FP / 1.561 âm | 80 | 77 |
| Test lịch sử, ngưỡng 0,5: Recall core | 62,83% | 72,48% |
| Test lịch sử, ngưỡng 0,5: FPR | 5,62% | 2,57% |
| Test lịch sử, ngưỡng 0,5: F1 core | 60,65% | 75,19% |

Char dùng TF-IDF 3–5 gram + LR, một cấu hình train-only khóa trước fit; 131.736 đặc trưng. Khác cả biểu diễn và thuật toán nên không quy chênh lệch riêng cho LR. Export lịch sử đã xác minh 16.207 score val+test khớp bit; gói sau refactor chỉ chuyển trọng số và kiểm tra lại validation, không công bố test mới.

Không phải nguồn nào cũng tốt hơn; char Recall OpenPhish thấp hơn XGBoost ở một số policy, và còn cảnh báo nhầm URL quen thuộc. Train/validation gần như chỉ có host; path/query gắn mạnh với OpenPhish và nhãn dương. Char lowercase mất thông tin case của path. Các đối chứng bỏ marker/chỉnh nguồn chưa đủ bằng chứng thay model. XGBoost vẫn là mặc định.

200 ứng viên OpenPhish và 29 URL tham chiếu chính thức đã có chẩn đoán score, chưa có nhãn rủi ro độc lập để công bố Accuracy/F1. Bộ prospective còn thiếu quota/nhãn; số cảnh báo không tự là Recall/FPR thật.

## Thông điệp

<a id="thong-diep"></a>

Lượt component cũ: 80 SMS + 80 ngữ cảnh, 640 attempt, 634 output hợp lệ. Trên **51 SMS có nhãn AI nhị phân** (9 dương/42 âm), prompt nghiên cứu cũ:

| Cấu hình | Precision | Recall | F1 | FPR |
|---|---:|---:|---:|---:|
| LLM | 26,67% | 88,89% | 41,03% | 52,38% |
| LLM + URL | 23,53% | 88,89% | 37,21% | 61,90% |
| LLM + RAG | 22,86% | 88,89% | 36,36% | 64,29% |
| LLM + URL + RAG | 25,71% | 100% | 40,91% | 61,90% |

29 SMS UNKNOWN báo riêng. Nhiều payload không có thông tin URL/RAG bổ sung nhưng sinh độc lập; không quy mọi chênh lệch thành tác động thành phần. Bảng này không mô tả candidate v6.1 và chưa chứng minh RAG cải thiện phát hiện.

Pilot v3/v4 trên cùng 51 SMS cho F1 62,07% → 94,12%, FP 11/42 → 0/42; v4 có một dương bị cắt output. Lượt v4/v5 sau đó có F1 SMS 94,74%/100%, nhưng chỉ chín dương AI; không xem 100% này là chất lượng ngoài thực tế hoặc ghép hai lượt thành một phép so sánh.

### Pilot hội thoại 09/11

| Profile | Request | Output hợp lệ | Lỗi | Token ghi nhận |
|---|---:|---:|---:|---:|
| v5 | 36 | 34 | 2 | 160.264 |
| v6 | 36 | 16 | 20 | 197.801 |

Đây là tỷ lệ hợp lệ cấu trúc, **không phải Accuracy/F1**. 72 request chỉ gồm sáu hội thoại và 30 input khác nhau, chưa có nhãn ngữ nghĩa độc lập cho từng prefix. V6 có chín lỗi đếm một lượt và 11 output bị cắt ở cap 2.048 token.

Candidate hiện tại v6.1 sửa hợp đồng một lượt và rút gọn request. Audit offline chỉ thay quy tắc đếm giải quyết chín lỗi, giữ nguyên 11 lần cắt; không đổi kết quả pilot cũ thành 25/36 thành công thực đo. Tổng ký tự messages trên 36 input giảm 43,3%; đây không phải mức tiết kiệm token đo được. Tại mốc 09/11 chưa có lượt live v6.1; lượt mới được trình bày bên dưới, vẫn chưa có Accuracy/F1 độc lập.

Bộ `fresh_messages_v1` có 200 SMS chưa gán nhãn phishing, 80 dev review/120 reserve; 40 stress tự soạn gồm 16 injection. Cùng snapshot nguồn SMS cũ, không phải nguồn ngoài hoàn toàn mới. Ưu tiên hoàn thiện nhãn và khóa đối chứng trước lượt API kế tiếp.

### Pilot compact 11/11

Toàn bộ sáu hội thoại cũ × hai điều kiện lịch sử × hai profile: **12 input, 24 attempt**, cùng model `DeepSeek-V4-Flash`, cap 2.048 token, không RAG/URL. Bốn attempt đầu lỗi kết nối, sau đó mạng kiểm tra lại có phản hồi. Phần chưa từng gửi được đăng ký riêng và chạy 20 attempt; không thử lại bốn lỗi, không chọn mẫu theo output. Báo cáo gộp giữ đúng mẫu số ban đầu.

| Chỉ số | v5 | v6.1 |
|---|---:|---:|
| Output hợp lệ / toàn bộ attempt | 10/12 | 9/12 |
| Lỗi kết nối giữ trong mẫu số | 2 | 2 |
| Bị cắt đầu ra | 0 | 1 |
| Token provider ghi nhận | 42.492 | 30.444 |
| Trung vị phần có kết nối, 10 attempt/profile | 7,02 giây | 9,49 giây |

V6.1 dùng ít hơn **28,4% tổng token ghi nhận**; prompt token giảm 44,8% nhưng completion token tăng 65,6%. Trung vị ở phần có kết nối cao hơn 35,2%. Đây là một lượt nhỏ với đầu ra khác schema, không tách riêng tác dụng prompt hay chứng minh chênh lệch tốc độ ổn định. Usage của bốn lỗi kết nối chưa biết; không khẳng định provider xác nhận chúng dùng 0 token.

Ca cắt là `CV-05::full_history::message-v6.1`, provider báo `length`, completion token 2.048 và content chỉ 44 ký tự. Không sửa hoặc chấp nhận JSON dang dở. Chưa thu đủ telemetry để xác định vì sao ngân sách bị dùng hết. Trên chín cặp có output hợp lệ ở cả hai, nhãn khớp nhau; **đồng thuận không phải độ chính xác** khi thiếu nhãn độc lập. Không có lỗi turn/schema mới trong những phản hồi hoàn tất, nhưng số mẫu quá nhỏ để kết luận đã giải quyết mọi trường hợp.

Kết quả chưa đủ để thay bản mặc định. Tại mốc pilot 11/11, hướng thử tiếp là giữ verdict phân loại độc lập với cấu trúc tương tác bổ sung; bản triển khai và pilot vận hành mới được ghi riêng ở mục 12/11 bên dưới. Trước đánh giá chất lượng tiếp theo vẫn cần khóa nhãn phishing và UNKNOWN trên dev, giữ reserve ngoài tối ưu prompt. Không chạy model lên SMS mới/reserve trong lượt pilot compact.

- [Báo cáo gộp đủ 24 attempt](../artifacts/evaluations/compact_pilot_20261111_continuation/combined_report.md), [số đếm](../artifacts/evaluations/compact_pilot_20261111_continuation/combined_summary.json).
- [Thời gian/usage trên phần có kết nối](../artifacts/evaluations/compact_pilot_20261111_continuation/summary.json), [raw 20 response](../artifacts/evaluations/compact_pilot_20261111_continuation/responses.jsonl), [bốn lỗi ban đầu](../artifacts/evaluations/compact_pilot_20261111/responses.jsonl).
- [Phiếu output review](../artifacts/evaluations/compact_pilot_20261111_continuation/output_review.csv) chưa có nhãn người. Ẩn tên profile không bảo đảm mù hoàn toàn vì schema có thể làm lộ cấu hình.

Kiểm thử phần mềm sau bổ sung: **613 test offline đạt**; không thay thế đánh giá chất lượng model. [Protocol và lệnh tái lập](evaluation.md#kiểm-chứng-đầu-ra-compact-v61).

### Đối chứng cùng prompt/schema ngày 11/11

80 SMS dev có reference trợ lý AI **4 dương/54 âm/22 UNKNOWN**, cộng 40 stress tự soạn chấm riêng. Không dùng nhãn spam làm phishing, không suy luận 120 reserve. Cùng prompt/schema/validator/model/cap 4.096 token; chỉ thay score URL hoặc nguồn RAG. **480 ô logic dùng 212 payload khác nhau**, không sinh lại khi payload giống hệt. Model URL là Char TF-IDF + LR, RAG là E5/corpus v1; đây là prompt nghiên cứu trước verdict, chưa đo Accuracy của app v6.1.

| Cấu hình | Accuracy, UNKNOWN tính sai | F1 | Coverage | FP / 54 âm |
|---|---:|---:|---:|---:|
| llm_only | 82.76% | 57.14% | 93.10% | 6/54 |
| llm_url | 81.03% | 72.73% | 86.21% | 3/54 |
| llm_rag | 82.76% | 66.67% | 89.66% | 4/54 |
| llm_url_rag | 81.03% | 80.00% | 84.48% | 2/54 |

**Không xem F1 tăng là bằng chứng cải tiến.** So với LLM, +URL / +RAG / cả hai có 3 / 2 / 4 cảnh báo nhầm chuyển sang UNKNOWN, tất cả do output bị cắt; không có cảnh báo nhầm nào chuyển thành LOW đúng. +URL và kết hợp còn làm hai LOW đúng thành UNKNOWN, chỉ phục hồi một UNKNOWN thành LOW. Vì vậy số quyết định đúng là 48/58, 47/58, 48/58 và 47/58. Cả bốn bắt đủ 4/4 dương AI, nhưng mẫu quá ít và cả bốn không có URL context; chưa đo được tăng Recall nhờ model URL.

Toàn lượt có **170/212 output hợp lệ, 42 lần cắt đầu ra**, ghi nhận 1.599.859 token. Phần chính dừng ở guard 1,5 triệu token sau 202 request; 10 request chưa gửi được đăng ký riêng theo khoản chuyển ngân sách đã khai báo trước khi tính điểm. Giữ toàn bộ lỗi, không retry. Coverage giảm là hạn chế vận hành, không phải giảm false positive thành công.

40 stress gồm 32 nhãn nhị phân và 8 UNKNOWN: LLM F1 93,33%, +RAG 89,66%; 16 injection tự soạn lần lượt 93,33% và 85,71%. URL minh họa không qua model nên arm có URL dùng chung output với arm tương ứng. Không dùng các stress này chứng minh chống injection ngoài thực tế.

Rubric giải thích đã chấm AI **10 output hợp lệ trong 14 output khác nhau**, thuộc tám case chọn trước; bốn output lỗi không chấm. Hai output có citation chỉ thuộc stress tự soạn, chưa đủ kết luận chất lượng nguồn; phiếu người vẫn trống. Không ghép điểm rubric thành F1 phishing.

[Bảng và diễn giải đầy đủ](../artifacts/evaluations/week4_dev_20261111/classification_results/report.md) · [Rubric giải thích](../artifacts/evaluations/week4_dev_20261111/assistant_explanations/report.md) · [Mục lục minh chứng](../artifacts/evaluations/week4_dev_20261111/README.md).

### Verdict lõi và thinking ngày 12/11

<a id="verdict-loi"></a>

Đã triển khai `app.api.focused:app`: verdict ngắn, tóm tắt theo mẫu, giải thích RAG tùy chọn sau kết luận, câu hỏi bổ sung khi thiếu ngữ cảnh và telemetry không lưu văn bản reasoning. Bản stable chưa thay đổi. Tài liệu [DeepSeek](https://api-docs.deepseek.com/guides/thinking_mode/) mô tả tham số thinking; hỗ trợ thực tế qua FPT được kiểm tra bằng bốn probe vô hại, không suy ra chỉ từ tài liệu của nhà cung cấp model. Cả bốn probe hợp lệ; hai probe yêu cầu disabled không có reasoning trả về, hai probe mặc định có. Điều này không chứng minh provider không có tính toán nội bộ.

Pilot tiếp theo dùng **cùng tám input dev quen thuộc × hai schema × hai chế độ thinking = 32 request**, cùng model, cap 2.048, decoding và timeout. Khác prompt/schema có chủ ý, không tách riêng hiệu ứng một thay đổi prompt:

| Schema / thinking yêu cầu | Output hợp lệ | Cắt đầu ra | Token ghi nhận | Trung vị giây |
|---|---:|---:|---:|---:|
| v6.1 / mặc định provider | 1/8 | 7 | 31.409 | 6,33 |
| v6.1 / disabled | 8/8 | 0 | 17.773 | 1,29 |
| Verdict lõi / mặc định provider | 6/8 | 2 | 18.612 | 4,39 |
| Verdict lõi / disabled | 8/8 | 0 | 7.749 | 0,40 |

Đây là tỷ lệ phản hồi hoàn chỉnh, **không phải Accuracy hoặc F1**. Pilot nhỏ, một lượt sinh mỗi ô; chưa chứng minh độ trễ ổn định hoặc chất lượng phát hiện tốt hơn. Mọi output cắt giữ nguyên. Telemetry mới cho thấy tương quan với chế độ thinking trên các ca này; không hồi tố kết luận nguyên nhân của 42 lỗi cũ vì lượt cũ không thu trường reasoning.

Đã đăng ký so sánh v6.1 không URL / verdict lõi không URL / verdict lõi có URL trên đúng **80 SMS dev, reference AI 4 dương/54 âm/22 UNKNOWN**. Cùng model, cap 2.048 và thinking disabled; payload giống nhau dùng chung response, 240 ô logic tương ứng 199 request khác nhau. Lượt này **dừng ở 92/199 attempt: 91 hợp lệ, một HTTP 429, còn 107 chưa gửi**, ghi nhận 132.820 token; usage của lỗi HTTP chưa biết. Chưa xác định 429 do tốc độ hay quota. Không vượt gate, gửi lại lỗi hoặc công bố bảng Accuracy/F1 của lượt chạy dở. Kiểm replay xác nhận 92 checkpoint nguyên vẹn. Cả bốn dương không có URL context; dù chạy đủ, lượt này vẫn chưa đo được tăng Recall nhờ URL. Không suy luận 120 reserve.

Readiness check mới chặn kết luận cải tiến nếu chỉ giảm FP bằng UNKNOWN/lỗi, mất Accuracy/Recall/coverage, hoặc thiếu nhãn độc lập và mẫu dương. Mốc 20 dương mỗi nhóm chỉ là mục tiêu lập kế hoạch, không phải bảo đảm ý nghĩa thống kê. Chưa thu được nhãn người hoặc email lừa đảo đã xác minh mới. **647 test offline đạt**; kiểm desktop/mobile xác nhận luồng hỏi bổ sung yêu cầu đồng ý lại và không khôi phục dữ liệu đã xóa; đây là kiểm phần mềm, không phải đánh giá model.

[Minh chứng 12/11](../artifacts/evaluations/focused_20261112/README.md) · [Pilot đủ 32 request](../artifacts/evaluations/focused_20261112/operational_pilot/report.md) · [Trạng thái lượt SMS bị dừng](../artifacts/evaluations/focused_20261112/quality_dev/status.md).

### Hoàn tất đối chiếu verdict lõi ngày 13/11

Sau probe vô hại HTTP 200, đăng ký riêng 107 request chưa gửi, chạy một worker với khoảng cách bắt đầu tối thiểu bốn giây; cả 107 có output hợp lệ. Lượt gộp đủ **199 request / 240 ô logic**, 198 hợp lệ và giữ một HTTP 429 cũ, **290.022 token ghi nhận**; probe riêng 14 token, usage của lỗi cũ chưa biết. Không gửi lại key lỗi. Thời điểm/tốc độ hai pha khác nhau, không dùng lượt này để kết luận ưu thế độ trễ.

Trên cùng **58 nhãn AI nhị phân, 4 dương/54 âm**, 22 UNKNOWN tham chiếu báo riêng:

| Pipeline, đều yêu cầu thinking disabled | Đúng / 58 | Accuracy | Precision | Recall | F1 | Bất đồng dạng FP / 54 |
|---|---:|---:|---:|---:|---:|---:|
| v6.1 không thêm score URL | 41 | 70,69% | 22,22% | 100% | 36,36% | 14 |
| Verdict lõi không thêm score URL | 45 | 77,59% | 26,67% | 100% | 42,11% | 11 |
| Verdict lõi có score URL | 42 | 72,41% | 21,05% | 100% | 34,78% | 15 |

Core không URL có bốn cảnh báo theo reference âm chuyển thành LOW, một LOW chuyển thành cảnh báo; tổng số quyết định đúng tăng bốn. Chênh lệch này không do đẩy các FP sang lỗi/UNKNOWN. McNemar exact p=0,21875 trên các cặp: chưa có bằng chứng thống kê rõ về ưu thế, chưa kể reference AI và số dương rất ít. Thêm score URL làm ba LOW thành cảnh báo; bốn dương đều không có URL context nên không đo được tăng Recall nhờ URL. Cần giữ nhận định URL riêng và chưa có cơ sở khuyến nghị bật score trong LLM như một cải tiến mặc định.

**Giới hạn mục tiêu nhãn:** reference hiện xét hành vi nguy hiểm được nêu rõ trong văn bản. Một số nhãn 0 kèm ghi chú chưa xác minh URL/người gửi, kể cả thông điệp có tên miền đáng ngờ. Vì vậy các số trên là mức khớp reference hành vi AI; không được gọi 11/54 là tỷ lệ cảnh báo sai ngoài thực tế hoặc 77,59% là Accuracy phishing đã xác minh. Đã tạo phiếu riêng cho `behavior_label`, `whole_message_label` và `url_evidence_status`; chưa gán nhãn tổng thể mới hoặc thay nhãn cũ theo output. [Kiểm phạm vi nhãn](../artifacts/evaluations/recovery_20261113/scope_audit/report.md).

[Bảng đủ 199 attempt](../artifacts/evaluations/recovery_20261113/combined/report.md) · [Mục lục và amendment](../artifacts/evaluations/recovery_20261113/README.md).

## RAG

<a id="rag"></a>

Corpus v1 có 25 nguồn; v2 có 37. Model E5-small và index chạy cục bộ. Retrieval v1 trên câu trợ lý soạn: Hit@3 dev 24/26, test 7/8; từ chối ngoài phạm vi dev 14/14, test 4/4. Tỷ lệ ID nguồn trả về khớp nhãn chỉ 46,30%/41,18%. Chủ đề và tác giả gắn với corpus, chưa chứng minh tổng quát.

Pilot RAG có kiểm soát: 6 ca × 5 điều kiện, 30 request, 29 hợp lệ. Retrieved chọn nguồn 3/6, hai ca không hỗ trợ, một lỗi; oracle do tác giả chọn 6/6. Đối chứng sạch/injection đều không chọn nguồn 6/6; chỉ một mẫu injection tự soạn, chưa chứng minh chống injection rộng. Bỏ một câu vẫn có hỗ trợ có thể là hợp lý vì đoạn còn lại còn bằng chứng.

Tổng pilot hội thoại + RAG là 102 API call, 405.410 token; không retry/sửa JSON. Phiếu ngữ nghĩa chưa chấm, không gọi việc chọn span là nguồn đúng. Verdict khóa trước RAG nên lượt này không đo RAG tăng F1.

Audit 37 tóm lược có 148 claim; mới 12/37 nguồn có raw snapshot khớp hash. Phiếu người còn trống. Việc cần làm là kiểm provenance còn thiếu, chấm relevance và hỗ trợ claim, rồi cải thiện độ phủ/ngưỡng retrieval trên dev. Không thêm đáp án reserve vào corpus.

### Relevance dev ngày 11/11

Reference mới do trợ lý AI chấm trên **12 query × 25 tài liệu = 300 cặp**, giấu thứ hạng khi lập nhãn; phiếu người vẫn chưa chấm. Có 6 query tìm thấy tài liệu hỗ trợ trực tiếp trong corpus. E5 với bộ lọc hiện tại tìm được nguồn trực tiếp ở **4/6**, có **4/20** tài liệu trả về trực tiếp hỗ trợ và từ chối **3/6** query không có nguồn trực tiếp.

| Retriever, raw top-3 cùng điều kiện | Hit@3 trên 6 query có nguồn | Nguồn trực tiếp / 36 lượt trả về |
|---|---:|---:|
| BM25 | 5/6 | 5/36 |
| E5 | 5/6 | 5/36 |
| Hybrid RRF | 6/6 | 6/36 |

Tham số giữ cố định; đây là chẩn đoán nhỏ theo nhãn AI, chưa chứng minh Hybrid tổng quát tốt hơn. Raw top-3 luôn trả ba tài liệu, khác chính sách E5 có lọc, nên không so tỷ lệ nguồn trực tiếp giữa hai chính sách như một phép thắng/thua. Kho v1 thiếu cơ chế trực tiếp cho một số ca trúng thưởng đóng phí, xử lý nợ CIC và OAuth consent. Chưa thêm đáp án query vào corpus; nguồn được chấm là tóm lược, chưa kiểm chứng lại bài gốc.

[Bảng chi tiết retriever](../artifacts/evaluations/week4_dev_20261111/assistant_relevance/baseline_report.md) · [Reference và giới hạn](../artifacts/evaluations/week4_dev_20261111/assistant_relevance/manifest.json).

### Lọc hành vi ngày 12/11

Cùng 12 query/300 reference AI, corpus và index E5 cũ: thử pool dense 10, BM25/RRF, khớp nhóm hành vi và tối đa hai nguồn. Heuristic có tham khảo lỗi dev đã xem; toàn chính sách mới chưa được calibration, không phải test độc lập. Hit giảm **4/6 → 3/6**, số nguồn trực tiếp **4/20 → 3/13**, từ chối khi không có nguồn tăng **3/6 → 4/6**. Chưa đủ tốt để làm mặc định: focused vẫn dùng E5, `action_hybrid` chỉ bật rõ khi thử. Không đổi tham số tiếp để làm đẹp lượt này. [Bảng đối chiếu](../artifacts/evaluations/focused_20261112/action_retrieval/report.md).

### Mở rộng corpus có nguồn gốc ngày 13/11

Đã tải/kiểm bốn nguồn từ Bộ Công an và Microsoft Learn, gồm cảnh báo nhận thưởng phải chi tiền, mạo danh CIC, consent phishing và cấp quyền hợp lệ. Giữ nguyên 25 nguồn cũ, ghép thành bản thử nghiệm 29 tài liệu. Bổ sung 48 cặp relevance AI trước khi suy luận retrieval, đủ 348 cặp cho 12 query × 29 tài liệu. Nguồn mới được chọn từ các lỗi dev đã xem, không phải đánh giá độc lập.

| Raw E5 top-3, cùng embedding | Query có nguồn trực tiếp trong corpus | Hit / cùng 9 query có nguồn theo reference mở rộng | Nguồn trực tiếp / 36 lượt trả về |
|---|---:|---:|---:|
| Kho 25 nguồn | 6 | 5/9 | 5/36 |
| Kho 29 nguồn | 9 | 7/9 | 7/36 |

Hai hit tăng thêm thuộc CIC và OAuth; không mất hit cũ. Nhóm đóng phí nhận thưởng vẫn chưa lấy được tài liệu mới trong top-3, và nhóm giả người nhà chuyển tiền vẫn hụt nguồn. Chỉ số này khác chính sách E5 có ngưỡng/lọc của app; chưa chấm khả năng từ chối, chưa calibration index mới hoặc có nhãn người. Không đổi corpus/index app từ bảng này. [Bảng cùng mẫu số và dự đoán](../artifacts/evaluations/recovery_20261113/retrieval_results/report.md).

<a id="kiem-tra-ly-do"></a>

## Kiểm tra lý do và trích dẫn ngày 14/11

Trong 199 phản hồi vật lý của lượt core quality đã khóa, có 118 phản hồi core hợp lệ: 48 cảnh báo và 70 LOW/UNKNOWN. 80 phản hồi v6.1 và một lỗi HTTP 429 giữ nguyên, không áp dụng bộ diễn giải core. Các tóm tắt cũ có thể viết chắc chắn về “đổi nơi nhận tiền”, “phí trước” hoặc “cấp quyền” dù trích dẫn chỉ yêu cầu cập nhật địa chỉ, SIM hay liên hệ hỗ trợ.

Lớp `reason-presentation-1.0` kiểm cue cần có theo từng cơ chế, loại URL khỏi phép kiểm, không ghép cue từ các đoạn riêng. Tất cả 48 tóm tắt cảnh báo được diễn đạt có quy chiếu AI; 45 phản hồi thiếu cue hoặc có ngôn ngữ phủ định/phòng tránh chuyển sang lý do trung tính kèm cờ cần review. Ba phản hồi có cue tối thiểu vẫn chỉ là “AI nghi ngờ”, không xác nhận scam. 45 là số phản hồi, không phải 45 SMS hoặc 45 lỗi ngữ nghĩa do người xác minh.

Mức kết luận, quote, context, mã lý do gốc và trạng thái kỹ thuật của **199/199** phản hồi không đổi. Không có Accuracy/F1 mới, không thêm API call hoặc nhãn gold. 48 cảnh báo chứa 35 case ID; 45 phản hồi được gắn cờ thuộc 32 case ID, nhiều case có hai request với/không có điểm URL. Quy tắc thận trọng có thể gắn cờ cả cảnh báo đúng; không tự hạ mức để làm đẹp điểm. Phiếu ngữ nghĩa còn trống. Bản QA ban đầu gắn 48 phản hồi, trong đó ba phản hồi bị cờ vì thiếu cue tiếng Việt “để nhận”; giữ nguyên đầu ra đó và bản cuối trong hai thư mục riêng.

Áp dụng ở focused qua `run.py`; bản stable và research factory không đổi. Đổi cách diễn giải không chứng minh sửa false positive hoặc nâng chất lượng RAG. [Toàn bộ trước/sau và giới hạn](../artifacts/evaluations/claim_grounding_20261114/README.md).

## Rà soát phép đánh giá ngày 16/11

Đã thêm trace retrieval, adapter đánh giá qua runtime và báo cáo injection theo cặp. Không có lượt gọi provider thật hoặc điểm F1 mới.

- **Retrieval:** tái hiện đúng 12 query/300 cặp relevance AI và 36 ứng viên đã lưu. Raw E5 Hit@3 5/6, qua ngưỡng còn 4/6; nguồn `VN-RAG-015` hạng 2, score 0,845857 bị loại ở ngưỡng 0,849416. Số nguồn trả về giảm 36→20 và từ chối nhóm không có nguồn trực tiếp đạt 3/6. Đây là đánh đổi của chính sách, chưa đủ căn cứ hạ ngưỡng hoặc khẳng định nguồn đúng theo người chấm.
- **Parity:** 16 ca hợp đồng × 4 cấu hình, URL model thật, phản hồi AI/retrieval rỗng là fixture. Có 6/64 lượt còn check không đạt, thuộc hai ca: mất metadata URL khi hostname được chuẩn hóa hoa/thường; regex OTP có thể che nhầm `https` phía sau thành `[SECRET]`. Các check không lộ giá trị riêng tư/khôi phục URL đã xóa vẫn đạt trong những fixture này; không suy thành bảo đảm mọi PII được che. Chưa sửa hai lỗi runtime trong lượt audit.
- **Dữ liệu dev đã biết:** cùng 80 SMS có URL ở 39 mẫu theo extractor tuần 4, 36 mẫu theo intake hiện tại; chỉ 30 mẫu được cấp metadata nếu bật model URL. Có 10 mẫu khác intake, gồm cả khác chính tả tên miền và cách đọc ký tự trang trí/IDN, không coi tất cả là cải tiến. Không sửa score hoặc input tuần 4 theo kết quả này.
- **Injection:** 16 cặp/8 nhóm. LLM và +URL có bản nền đúng 15/16, bản chèn đúng 14/16 và 2 lỗi; +RAG và +URL+RAG lần lượt 14/16, 10/16 và 6 lỗi. Không có đúng→sai hợp lệ trong những cặp hai vế đều hợp lệ; tỷ lệ làm theo chỉ dẫn vẫn N/A. Lỗi kỹ thuật không được tính là phòng vệ thành công; URL stress không được chấm model, nên các arm chia sẻ phản hồi.

Suite offline tại mốc audit: 769 test đạt, một cảnh báo deprecation đã có. Các test mới xác nhận công cụ phát hiện đúng lỗi/giữ mẫu số; không phải 769 ca phân loại đúng hoặc parity đã đạt toàn bộ. [Chi tiết, phiếu review và các hash](../artifacts/evaluations/evaluation_audit_20261116/README.md).

### Sửa runtime sau audit ngày 16/11

Đã sửa metadata cho hostname hoa/thường và IDNA hợp lệ còn trong bản duyệt; không đưa URL bị xóa trở lại hoặc gửi URL gốc chứa giá trị đã che. OTP không còn làm hỏng scheme `https`; che userinfo URL có thể lặp lại mà vẫn giữ hostname. Kiểm tra bổ sung giữ nguyên từ phủ định trong lời hướng dẫn và che mật khẩu Unicode khi có cú pháp giá trị rõ (`:`, `=` hoặc `là/is`). Giá trị Unicode đứng trần vẫn có thể không được quy tắc nhận diện; bản gửi cần người dùng rà lại.

| Kiểm chứng cùng bộ ca | Trước sửa | Sau sửa |
|---|---:|---:|
| Lượt hợp đồng chưa đạt / 64 | 6 | 0 |
| SMS dev được cấp metadata / 80 | 30 | 35 |
| SMS dev có URL theo intake / 80 | 36 | 36 |

44 lượt có model call và 20 lượt còn lại giữ nguyên toàn bộ model call, score và hash đặc trưng so với audit trước. Năm SMS nhận thêm metadata vẫn cần review extractor: các chuỗi như `QK.Tu`, `P.Hiep`, `Q.Tan` có thể là viết tắt địa danh. Tăng metadata không chứng minh trích URL đúng hơn hoặc tăng F1. Không đổi model, ngưỡng, prompt hoặc corpus; RAG focused vẫn nằm sau verdict.

**848 test offline đạt**, một cảnh báo Starlette/httpx; cùng 16 ca × 4 cấu hình đạt 64/64 kiểm hợp đồng. URL model thật, phản hồi LLM/retrieval giả lập; không có Accuracy/F1, nhãn người hoặc API mới. Hai journal lịch sử 212 và 199 request đã kiểm lại bằng snapshot 106 tệp đúng hash, giữ nguyên đầu ra. [Trước/sau, manifest và giới hạn](../artifacts/evaluations/privacy_metadata_fix_20261116/README.md).

## Cách đọc kết quả

### Kiểm chứng ứng dụng ngày 13/11

Launcher `run.py` bổ sung lớp runtime cho kết nối do máy chủ quản lý, từ chối key/endpoint/model client và ngân sách chờ tối đa 45 giây dùng chung cho phân loại/giải thích. Bản xem trước được kiểm che lại sau chỉnh sửa; nếu có thay đổi phải xem/xác nhận bản mới trước provider. Có profile `focused` qua launcher; stable vẫn dùng XGBoost. Không đổi model, prompt hoặc corpus mặc định từ điểm dev.

| Model thật qua API in-process, sau nạp và warmup | Batch × URL | P95 API | Batch dưới một giây |
|---|---:|---:|---:|
| Stable / XGBoost | 100 × 5 | 10,50 ms | 100/100 |
| Focused / ký tự + LR | 100 × 5 | 5,98 ms | 100/100 |

CPU i5-11400H, process affinity bốn logical CPU; RAM máy 14,84 GiB, chưa giới hạn về 8 GB. Không gồm mạng HTTP vật lý hoặc LLM. Đây là hiệu năng quan sát trên URL tổng hợp, không phải Accuracy và chưa chứng minh toàn bộ NFR trên máy RAM 8 GB. Timeout/giữ kết quả được kiểm bằng provider mô phỏng; chưa đo SLA 45 giây của provider thật.

Audit hai cohort xác nhận 0 ID, nội dung chuẩn hóa và group trùng giữa hai nhóm 80; không có bằng chứng đổi nhãn 9/42/29 thành 4/54/22 trên cùng mẫu. [Ma trận FR/NFR và giới hạn](requirements.md), [minh chứng runtime](../artifacts/evaluations/runtime_checks_20261113/README.md).

Một tỷ lệ cao trên ít mẫu nhãn AI, dữ liệu tự soạn hoặc schema hợp lệ không thay thế độ chính xác thực tế. Kết quả cũ còn để phân tích lỗi và đối chiếu; xem [phương pháp đánh giá](evaluation.md) và [mục lục đầu ra](../artifacts/README.md) trước khi đưa số vào báo cáo.
