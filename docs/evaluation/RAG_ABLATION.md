# So sánh LLM, URL và RAG

## Kết quả ngày 27/10/2026

Đã hoàn tất **400 lượt API chính**, 100 mẫu × 4 arm, cùng một phiên bản DeepSeek-V4-Flash. Đối chiếu bằng scikit-learn đạt: 100 ca, 400 checkpoint, 9 đầu ra được chấm (ML riêng, bốn arm và bốn fusion), 200 đoạn nguồn giữ lại khớp nguyên văn. Kiểm tra này không thẩm định nhãn hoặc ngữ nghĩa lời giải thích. Bộ kiểm thử mã nguồn có **82 test đạt**.

| Cấu hình | Precision | Recall toàn bộ | F1 toàn bộ | Accuracy | Báo nhầm / 50 mẫu âm | UNKNOWN |
|---|---:|---:|---:|---:|---:|---:|
| LLM | 100,00% | 100,00% | 100,00% | 100,00% | 0 | 0 |
| LLM + URL | 66,67% | 100,00% | 80,00% | 75,00% | 25 | 0 |
| LLM + RAG | 98,00% | 98,00% | 98,00% | 98,00% | 1 | 1 |
| LLM + URL + RAG | 71,01% | 98,00% | 82,35% | 77,00% | 20 | 3 |
| Hệ thống đầy đủ sau fusion | 63,29% | 100,00% | 77,52% | 71,00% | 29 | 0 |

**Các tỷ lệ trên chỉ áp dụng cho bộ mô phỏng này.** LLM đạt 100% trên nhiều tình huống rõ dấu hiệu và dữ liệu tự gán nhãn không chứng minh phát hiện hoàn hảo ngoài thực tế. Có 96 ca với cả bốn phản hồi thành công; các ca còn lại vẫn giữ trong chỉ số toàn bộ. Bốn UNKNOWN là lỗi hết token: `P26/llm_rag`, `N08/llm_url_rag`, `P17/llm_url_rag`, `N29/llm_url_rag`. Không có phản hồi LOW sai cho mẫu dương trong lượt chính; Recall giảm ở nhánh RAG do abstain dương.

### Điều rút ra từ phép so sánh

- **Thêm điểm URL đang làm tăng báo nhầm.** So với LLM, thêm metadata URL làm sai thêm 25 ca và không sửa được ca nào trong bộ này. Trên riêng 60 tin có URL, model URL báo 29/30 mẫu âm, ứng dụng sau fusion cũng 29/30; đây là dữ liệu miền ví dụ có nhãn hành vi thông điệp, không phải FPR của model trên URL Việt Nam thực tế. Đối chiếu [PhishVN](PHISHVN.md) để đánh giá URL thật.
- **RAG có ích ở một số ca khi LLM đã nhận metadata ML, nhưng chưa chứng minh cải thiện so với LLM thuần.** So `llm_url` → `llm_url_rag`: sửa đúng 4 ca (`N05`, `N10`, `N26`, `N30`), làm 2 ca vốn đúng thành UNKNOWN; accuracy tăng 75% → 77%. Trên tập có cả hai phản hồi thành công: sửa 4, làm sai thêm 0. Đây là phân tích phụ, không thay mẫu số toàn bộ hoặc chứng minh lợi ích tổng quát.
- **Fusion đang xóa bớt lợi ích ngữ cảnh.** `llm_url_rag` có 28 TN; fusion chỉ còn 21 TN. Fusion sửa một dương abstain nhờ ML nhưng làm bảy mẫu vốn được LLM nhận diện đúng thành cảnh báo. Quy tắc ưu tiên ML đưa cả bốn cấu hình về cùng kết quả cuối trên bộ này.
- **RAG cũng có thể làm cảnh giác quá mức.** `N13` chỉ mời đọc lịch phỏng vấn, nói không thu phí; LLM thuần LOW nhưng LLM + RAG WARNING. Lời giải thích lấy việc chưa xác minh được nhà tuyển dụng và miền ví dụ làm lý do cảnh báo, dù chưa có hành vi thu tiền hay bí mật trong thông điệp. Nhãn mô phỏng và ranh giới WARNING cần được người gán nhãn độc lập thẩm định.
- **Nhóm không URL:** cả bốn cấu hình đều đúng 40/40, không UNKNOWN. Đây là các tình huống khá rõ dấu hiệu; khi không URL, hai arm bật ML chỉ nhận mảng rỗng, không đo được ích lợi từ model URL.

### Nguồn dẫn và chi phí

| Cấu hình | Token ghi nhận | Thời gian API trung vị | Thành công có dùng RAG | Lượt giữ được ≥1 nguồn dẫn | Trích dẫn bị loại |
|---|---:|---:|---:|---:|---:|
| LLM | 139.197 | 2,04 giây | 0 | 0 | 0 |
| LLM + URL | 170.319 | 2,37 giây | 0 | 0 | 0 |
| LLM + RAG | 292.944 | 4,12 giây | 68 | 56 | 15 |
| LLM + URL + RAG | 324.989 | 5,20 giây | 66 | 57 | 19 |

RAG được yêu cầu 100 lượt/arm nhưng chỉ 69 đầu vào có nguồn vượt ngưỡng; các lượt lỗi không tính vào số thành công dùng RAG. Tổng token ghi nhận trong lượt chính là **927.449**, chưa gồm usage của bốn phản hồi bị cắt vì lớp dịch vụ không trả usage khi gặp lỗi; không dùng con số này đối chiếu hóa đơn tuyệt đối. LLM + RAG dùng khoảng **2,10 lần** token LLM thuần, với median API gần gấp đôi. Tổng retrieval cục bộ cho 100 ca là 4,64 giây, có cả lần đầu nạp model, được thực hiện trước các cuộc gọi API và không nằm trong median API.

`Trích dẫn bị loại` đếm từng mục không qua kiểm tra ID/quote hoặc trùng tài liệu; không phải 34 nguồn giả mạo khác nhau. Hai nhánh giữ lần lượt 99 và 101 trích dẫn. Khớp quote không đảm bảo lập luận hợp lý: ví dụ `N29/llm_rag` dùng nguồn về OTP trong giao dịch do người dùng chủ động để giải thích việc URL có `/otp`; quan hệ này còn gián tiếp và cần chấm ngữ nghĩa. Không gọi 200 trích dẫn vượt kiểm tra là 200 lập luận đã được xác nhận.

### Kiểm tra riêng giới hạn token

Lượt chính khóa ngân sách **4.096 token**, timeout 90 giây, khác cấu hình ứng dụng tại lúc thử là 40.960 token và 45 giây. Sau khi chốt toàn bộ số đo chính, chạy riêng bốn ca hết token với 8.192 token, giữ model/prompt/văn bản/nguồn/ML. Cả bốn trả được JSON hợp lệ: `P17` HIGH, `P26` HIGH, `N29` LOW đúng nhãn; `N08` HIGH vẫn báo nhầm. Token bổ sung ghi nhận 22.469. Không thay thế checkpoint gốc hoặc tính lại F1 bằng kết quả chọn sau khi thấy lỗi.

Đây là chẩn đoán nguyên nhân lỗi trên tập con được chọn theo thất bại, không chứng minh cấu hình 8.192 token có accuracy hay coverage đó trên toàn bộ dữ liệu. Tệp nằm riêng trong `artifacts/evaluations/rag_budget_diagnostic_v1/`. Chạy lại bằng `python -m evaluation.token_budget_diagnostic --live --run PRIMARY_DIR --out NEW_DIAGNOSTIC_DIR`; mặc định chỉ lập kế hoạch nếu không có `--live`.

### Hướng cải tiến từ kết quả này

Ưu tiên đánh giá quy tắc xử lý xung đột: tách cảnh báo URL và đánh giá hành vi thông điệp, tránh để mức ML tự động lấn át mọi ngữ cảnh giáo dục hay phòng ngừa. Chọn và xác nhận quy tắc mới trên validation thông điệp thực, không chỉnh cho vừa 100 mẫu đã xem. Giữ RAG để thử lợi ích về giải thích có nguồn, đồng thời bổ sung câu hỏi phân biệt quy trình hợp lệ, rubric nguồn/claim, và cơ chế kiểm soát độ dài/suy luận phù hợp tài nguyên API. Chưa có bằng chứng đủ để tăng quy mô corpus hoặc đổi embedding chỉ nhằm nâng F1.

## Thiết kế

Lượt `rag_ablation_v1`, ngày 27/10/2026, dùng `data/evaluation/vietnamese_messages_rag_v1.jsonl`: **100 tin nhắn mô phỏng tiếng Việt**, 50 lừa đảo và 50 bình thường. Trong đó 60 mẫu có URL lấy nguyên văn từ bộ chẩn đoán v1; 40 mẫu không URL mới gồm 20 tình huống với hai ngữ cảnh đối lập. Mỗi nhóm có và không URL đều cân bằng nhãn. Đây là nhãn hành vi trong thông điệp do trợ lý soạn trước lượt chạy, chưa được thẩm định độc lập; không phải nhãn danh tiếng website. Các cặp ngữ cảnh phụ thuộc nhau, không coi là 100 quan sát độc lập khi suy luận thống kê.

| Arm | Nội dung gửi LLM | Kết quả được chấm |
|---|---|---|
| `llm_only` | Văn bản đã che thông tin | Nhận định LLM trước fusion |
| `llm_url` | Cùng văn bản, thêm điểm và ngưỡng URL | Nhận định LLM trước fusion |
| `llm_rag` | Cùng văn bản, thêm tài liệu vượt ngưỡng | Nhận định LLM trước fusion |
| `llm_url_rag` | Cùng văn bản, điểm URL và tài liệu | Nhận định LLM trước fusion |

Từ mỗi đầu ra LLM, công cụ tính thêm `fusion_*` theo đúng quy tắc ứng dụng đang chạy, không gọi thêm API. `url_model_only` được báo riêng; mẫu không URL trả UNKNOWN. Không dùng kết quả fusion làm baseline LLM thuần vì như vậy vẫn chứa quyết định từ ML.

Giữ nguyên XGBoost, feature, ngưỡng WARNING `0.11384317278862` và HIGH `0.47364333271980286`; không chọn lại ngưỡng trên bộ này. RAG dùng E5-small đã ghim revision, 25 tóm lược, top-3, cosine tối thiểu `0.849416` đã chọn trên dev. Hai arm RAG dùng chung snapshot truy xuất. Nhãn, lý do gán nhãn, ID ca và category không được gửi API; tin nhắn test không được thêm vào corpus.

LLM là `DeepSeek-V4-Flash` qua FPT, prompt `baseline-1.0` và `rag-1.0`, temperature 0.1, top_p=1, top_k=40; ngân sách tối đa 4.096 token/lượt, timeout 90 giây, tối đa hai lượt đồng thời. Xáo thứ tự bằng seed 20261027 và luân phiên vị trí các arm. Mỗi arm chạy một lần; không retry hoặc loại bỏ lỗi. Không URL thì arm bật ML chỉ thêm mảng kết quả rỗng; chênh lệch trong nhóm này không chứng minh model URL giúp ích.

RAG tìm được tài liệu cho 69/100 mẫu; 31 mẫu không đạt ngưỡng dùng lại prompt baseline. Vì vậy phải báo cả cấu hình **yêu cầu RAG** và số lượt **thực dùng RAG**. Dẫn nguồn vượt kiểm tra tự động chỉ chứng minh ID được truy xuất và đoạn trích khớp nguyên văn; chưa chứng minh nguồn hỗ trợ nhận định về ngữ nghĩa. Chấm rubric cần người đánh giá đối chiếu dấu hiệu, nguồn và lập luận, chưa thay bằng tỷ lệ khớp quote.

## Chạy lại và kiểm chứng

Chuẩn bị model URL và RAG theo [hướng dẫn](../guides/RAG.md), cài profile evaluation và rag. Từ thư mục gốc:

```bash
# Chỉ chuẩn bị ML và truy xuất cục bộ, không gọi API.
.venv/bin/python -m evaluation.ablation --out artifacts/evaluations/rag_ablation_new

# Dùng khóa trong .env, tối đa 400 lượt API mới.
.venv/bin/python -m evaluation.ablation --live --max-new-calls 400 --out artifacts/evaluations/rag_ablation_new
.venv/bin/python scripts/evaluation/verify_rag_ablation.py artifacts/evaluations/rag_ablation_new
.venv/bin/python scripts/evaluation/plot_rag_ablation.py artifacts/evaluations/rag_ablation_new
```

Lặp đúng cấu hình/thư mục để tiếp tục bằng checkpoint, không trả phí lại cho lượt đã lưu, kể cả lượt lỗi. Chọn thư mục mới nếu thay model, prompt, mã xử lý, corpus, dataset hoặc tham số. `--max-new-calls 4` cho phép thử ít lượt; kết quả còn pending là chưa hoàn tất. HTTP xác thực, hết số dư, sai cấu hình, 429 hoặc ba lỗi liên tiếp sẽ dừng sớm. API có thể đã tính token cho request không nhận được phản hồi; token ghi nhận chỉ phản ánh những usage nhận được thành công.

Đầu ra cục bộ trong `artifacts/evaluations/rag_ablation_v1/`:

- `manifest.json`: hash dữ liệu, nguồn mã, model, chỉ mục, corpus, phiên bản và cấu hình API; không chứa khóa.
- `prepared_cases.json` và `.sha256`: URL đã chấm cùng snapshot tài liệu cho từng ca, dùng chung và tái sử dụng khi resume.
- `checkpoints.jsonl`, `results.jsonl`: phản hồi, bằng chứng và nguồn của từng lượt; CSV để lọc các ca sai.
- `summary.json`, `report.md`: chỉ số toàn bộ, nhóm URL/không URL, category, prompt injection, status, lỗi, token và thời gian.
- `verification.json`: đối chiếu số đo độc lập bằng scikit-learn, từng checkpoint, đầu ra fusion và quote.
- `metrics`, `strata`, `confusion_matrices` dạng PNG/SVG.

HIGH/WARNING là cảnh báo dương; LOW là âm. UNKNOWN, lỗi và pending không được coi là an toàn hay dự đoán đúng. Recall và F1 toàn bộ tính dương abstain là bỏ sót; accuracy chia toàn bộ mẫu; coverage báo phần có nhãn nhị phân. FPR tính trên tất cả mẫu âm. Báo nhầm, bỏ sót và UNKNOWN được giữ riêng.

## Đối chiếu phương pháp truy xuất

```bash
.venv/bin/python -m evaluation.retrieval_comparison --out artifacts/rag-evaluation/retrieval_comparison_new
```

So sánh cùng 25 chunk text-only, top-3: BM25 với k1=1.2, b=0.75; E5 cosine; Hybrid RRF k=60. BM25 dùng từ Unicode viết thường, giữ dấu, chưa tách từ tiếng Việt. Các siêu tham số được giữ cố định; ngưỡng lọc chọn trên 40 dev theo cùng quy tắc hit@3 ≥90%, không thay ngưỡng ứng dụng. Test chỉ có 12 câu do trợ lý soạn (8 có nguồn, 4 không nguồn), đã từng được đánh giá E5; đây là phép so sánh thăm dò, chưa phải test độc lập mới.

| Phương pháp sau lọc | Hit@3 trên 8 câu có nguồn | Precision từng nguồn trả về | Từ chối đúng 4 câu không nguồn |
|---|---:|---:|---:|
| BM25 | 7/8 (87,50%) | 41,18% | 4/4 |
| E5-small | 7/8 (87,50%) | 41,18% | 4/4 |
| Hybrid RRF | 7/8 (87,50%) | 63,64% | 3/4 |

Không lọc, E5 có hit@3 là 8/8, hai phương pháp kia 7/8, nhưng cả ba luôn trả nguồn cho cả câu không liên quan. Hit@3 cao không đồng nghĩa mọi tài liệu trả về đều phù hợp. Hybrid chưa chứng minh cải thiện đủ để thay cấu hình hiện tại: precision nguồn tốt hơn trên bộ nhỏ, đổi lại một false retrieval. Cần tập relevance lớn hơn có hai người gán nhãn và các diễn đạt khác nhau, tách phát triển/kiểm thử, trước khi thay retriever.

## Giới hạn diễn giải

Bộ tin nhắn gồm nhiều mẫu rõ dấu hiệu, các miền ví dụ và tỷ lệ hai lớp 50/50; điểm rất cao của LLM không chứng minh chất lượng trên dữ liệu ngoài thực tế. Model URL được huấn luyện cho URL thực, còn nhãn ở đây là hành vi của thông điệp, nên phải đối chiếu [PhishVN](PHISHVN.md) khi nhận xét bộ phân loại URL. Một lần gọi không đo được độ ổn định qua nhiều lần chạy. Các số đo truy xuất và dẫn nguồn không thay thế Precision/Recall/F1 phân loại hoặc rubric ngữ nghĩa.

Đánh giá tiếp theo cần tin nhắn Việt Nam được thu thập và ẩn danh hợp lệ, hai người gán nhãn, chia theo nguồn/chiến dịch trước khi chỉnh prompt hoặc fusion, rồi khóa một tập test mới. Những kết luận từ lượt này dùng để xác định lỗi và hướng cải tiến, không dùng lại nó làm tập test độc lập sau khi điều chỉnh.
