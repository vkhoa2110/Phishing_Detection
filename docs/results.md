# Kết quả và giới hạn

Các số dưới đây tóm tắt những lượt đã hoàn tất trước lần tổ chức cấu trúc 10/11/2026. Đây không phải kết quả chạy model mới trong lần dọn dự án. [Tài liệu lịch sử đầy đủ](https://github.com/vkhoa2110/Phishing_Detection/tree/479c96612ca79d3e1de2d37df22d82ce19e09f23/docs) và các manifest/raw cục bộ giữ nguyên.

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

Candidate hiện tại v6.1 sửa hợp đồng một lượt và rút gọn request. Audit offline chỉ thay quy tắc đếm giải quyết chín lỗi, giữ nguyên 11 lần cắt; không đổi kết quả pilot cũ thành 25/36 thành công thực đo. Tổng ký tự messages trên 36 input giảm 43,3%; đây không phải mức tiết kiệm token đo được. Chưa chạy live v6.1 mới hoặc có Accuracy/F1 độc lập.

Bộ `fresh_messages_v1` có 200 SMS chưa gán nhãn phishing, 80 dev review/120 reserve; 40 stress tự soạn gồm 16 injection. Cùng snapshot nguồn SMS cũ, không phải nguồn ngoài hoàn toàn mới. Ưu tiên hoàn thiện nhãn và khóa đối chứng trước lượt API kế tiếp.

## RAG

<a id="rag"></a>

Corpus v1 có 25 nguồn; v2 có 37. Model E5-small và index chạy cục bộ. Retrieval v1 trên câu trợ lý soạn: Hit@3 dev 24/26, test 7/8; từ chối ngoài phạm vi dev 14/14, test 4/4. Tỷ lệ ID nguồn trả về khớp nhãn chỉ 46,30%/41,18%. Chủ đề và tác giả gắn với corpus, chưa chứng minh tổng quát.

Pilot RAG có kiểm soát: 6 ca × 5 điều kiện, 30 request, 29 hợp lệ. Retrieved chọn nguồn 3/6, hai ca không hỗ trợ, một lỗi; oracle do tác giả chọn 6/6. Đối chứng sạch/injection đều không chọn nguồn 6/6; chỉ một mẫu injection tự soạn, chưa chứng minh chống injection rộng. Bỏ một câu vẫn có hỗ trợ có thể là hợp lý vì đoạn còn lại còn bằng chứng.

Tổng pilot hội thoại + RAG là 102 API call, 405.410 token; không retry/sửa JSON. Phiếu ngữ nghĩa chưa chấm, không gọi việc chọn span là nguồn đúng. Verdict khóa trước RAG nên lượt này không đo RAG tăng F1.

Audit 37 tóm lược có 148 claim; mới 12/37 nguồn có raw snapshot khớp hash. Phiếu người còn trống. Việc cần làm là kiểm provenance còn thiếu, chấm relevance và hỗ trợ claim, rồi cải thiện độ phủ/ngưỡng retrieval trên dev. Không thêm đáp án reserve vào corpus.

## Cách đọc kết quả

Một tỷ lệ cao trên ít mẫu nhãn AI, dữ liệu tự soạn hoặc schema hợp lệ không thay thế độ chính xác thực tế. Kết quả cũ còn để phân tích lỗi và đối chiếu; xem [phương pháp đánh giá](evaluation.md) và [mục lục đầu ra](../artifacts/README.md) trước khi đưa số vào báo cáo.
