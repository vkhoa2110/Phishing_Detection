# Candidate v6: URL che dấu, cấu trúc tương tác và kiểm tra RAG

Ngày chốt thiết kế: **08/11/2026**. Đây là profile thử nghiệm; `python run.py` vẫn chạy v4. Các thay đổi dưới đây được tách khỏi kết quả cũ để không làm mất khả năng tái lập.

**Cập nhật sau sửa 09/11/2026:** đã sửa nối schema v6 sang RAG, parser hội thoại, kiểm tra authority/IDNA và công cụ kiểm chứng đánh giá. Biên bản phát hiện trước sửa được giữ bên dưới; trạng thái hiện tại và gói mới nằm ở mục cuối. Đã có [pilot 102 lần gọi API](../evaluation/V6_PILOT_V1.md); chưa có kết quả độ chính xác độc lập. Pilot phát hiện thêm lỗi hợp đồng đếm một lượt và nhiều phản hồi v6 bị cắt ở trần 2.048 token.

**Bản candidate hiện tại là v6.1:** entry point `app.candidate_v6:app` đã dùng prompt ngắn và hợp đồng đếm lượt mới. `app/message_policy_v6.py` giữ nguyên để tái lập pilot 6.0; xem mục khắc phục v6.1 ở cuối tài liệu.

## Sáu hạng mục đã bổ sung

| # | Hạng mục | Đầu ra hiện có | Trạng thái bằng chứng |
|---|---|---|---|
| 1 | URL Unicode/che dấu | `app/url_intake_v2.py`; nhận diện zero-width, `[.]`, NFKC và IDNA; luôn giữ chuỗi gốc và log phép đổi | Test contract; chưa đo Recall ngoài thực tế |
| 2 | Mất thông tin biểu diễn URL | `evaluation/url_representation_audit_v3.py` | Audit train/validation, không fit và không mở test |
| 3 | Can thiệp bằng chứng RAG | `evaluation/rag_controlled_v1.py` 1.2: retrieved/oracle/bỏ câu thiết kế/đối chứng sạch/đối chứng có injection | Đã chạy 30 request ở gói live riêng; chưa chấm tay ngữ nghĩa |
| 4 | Chuỗi nguồn → tóm lược → claim hiển thị | `evaluation/rag_summary_audit_v1.py` và phiếu 148 claim | 12/37 nguồn có raw đã khớp hash; phiếu người chấm còn trống |
| 5 | Cấu trúc hội thoại | `app/message_policy_v6.py`; requester/recipient/action/asset/beneficiary/stage/persuasion | Đã chạy 72 request theo tiền tố/lịch sử/profile; v5 hợp lệ 34/36, v6 16/36. Đây là kiểm tra đầu ra, không phải Accuracy |
| 6 | Prompt injection gián tiếp trong RAG | Cặp `control_clean`/`control_injected` tách tài liệu tấn công khỏi oracle; verdict khóa trước RAG; gói kiểm thử dùng span selection, app chỉ dùng khi chọn đúng mode | Kiểm tra biên kiến trúc; mặc định app còn là `free_text`, chưa chứng minh robustness ngữ nghĩa |

## URL intake v2

Candidate nhận thêm bốn cách viết đã xác định trước: ký tự định dạng zero-width trong URL, dấu chấm viết `[.]`/`(.)`/`{.}`, ký tự fullwidth được NFKC chuẩn hóa và hostname Unicode được đổi sang ASCII IDNA. Mỗi kết quả gồm `original`, `analysis_url`, danh sách `transformations`, `requires_user_review=true` và `opened=false`.

Chuỗi gốc không bị thay. URL khôi phục chỉ được chấm cục bộ; metadata score của URL này không tự gửi cho LLM vì URL ASCII không xuất hiện nguyên văn trong bản người dùng duyệt. Intake không phân giải DNS, tải trang hay khẳng định URL là cùng một đích. Giới hạn năm URL tính cả URL khôi phục.

## Thông tin bị mất trong model URL hiện hành

Audit đọc đúng 36.909 train và 7.266 validation lịch sử. Không có collision exact, sau formatter hoặc sau lowercase trong từng split. Phép biến đổi kiểm soát cho kết quả:

| Phép biến đổi | URL đủ điều kiện | Score thay đổi |
|---|---:|---:|
| Đảo hoa/thường hostname | 500 | 0 |
| Đảo hoa/thường path | 33 | 0 |
| Đảo case hex trong percent-encoding | 0 | Không đánh giá được |

Hostname không phân biệt hoa/thường nên bất biến là phù hợp. HTTP path có thể phân biệt hoa/thường; 0/33 score thay đổi xác nhận vectorizer lowercase đã xóa phân biệt đó. Audit chưa có nhãn cho URL biến đổi, nên không dùng kết quả này để công bố F1 hoặc thay model. Bước hợp lý tiếp theo là thêm biểu diễn giữ nguyên case của path/query và đánh giá train-only trên validation mới.

## RAG có kiểm soát và provenance claim

Gói RAG có 6 ca × 5 điều kiện. Kết luận phân loại được khóa trước khi dựng payload; schema đầu ra chỉ cho chọn tối đa hai cặp `source_span_id`/`input_span_id`. Điều kiện injection thêm câu lệnh độc vào nội dung nguồn, không vào system prompt. Thước đo cấu trúc chỉ cho biết output hợp lệ, từ chối hay lỗi; đúng/sai về hỗ trợ claim vẫn cần người chấm phiếu mù.

Audit corpus tách 37 tóm lược thành 148 claim. Chỉ 12 tài liệu có source text cục bộ trùng `source_text_sha256`; 25 tài liệu còn lại phải ghi `source_unavailable` cho tới khi thu lại đúng snapshot. Không dùng chính phần tóm lược làm “bằng chứng” cho nó.

## Hội thoại v6

Prompt yêu cầu cấu trúc người yêu cầu, người nhận, hành động, tài sản/quyền truy cập, bên hưởng lợi, giai đoạn và chiến thuật thuyết phục. Validator chỉ xác nhận schema, tập nhãn và số lượt không vượt đầu vào. Cờ `interaction_semantics_verified=false` luôn được giữ vì code không thể biết vai trò do LLM suy ra có đúng nghĩa hay không.

Gói dev gồm 3 ca HIGH và 3 ca LOW, mỗi ca ba lượt, kèm phiếu mù. Đây là đối chứng tác giả tự soạn, không phải nhãn người độc lập. Không dùng sáu ca này để tuyên bố độ chính xác sản phẩm.

## Chạy thử và tái lập

Chạy candidate v6 tại máy:

```bash
.venv/bin/uvicorn app.candidate_v6:app --host 127.0.0.1 --port 8000
```

Chuẩn bị các phép đánh giá offline trong thư mục mới:

```bash
.venv/bin/python -m evaluation.url_representation_audit_v3 run --out NEW_URL_AUDIT
.venv/bin/python -m evaluation.rag_summary_audit_v1 prepare --out NEW_SUMMARY_AUDIT
.venv/bin/python -m evaluation.rag_controlled_v1 prepare --out NEW_RAG_PACK
.venv/bin/python -m evaluation.conversation_structure_v1 prepare --out NEW_CONVERSATION_PACK
```

Ba lệnh `prepare` và URL audit không gọi API. `rag_controlled_v1 score` chỉ đọc file response đã thu riêng; không tự gửi request. Kết quả cục bộ ngày 08/11/2026 nằm dưới `artifacts/evaluations/` và bị Git ignore theo chính sách dự án.

## Điều kiện trước khi cân nhắc thay v4

1. Chạy cùng model/thông số trên gói hội thoại và một tập tin nhắn mới; giữ mọi lỗi/UNKNOWN trong mẫu số.
2. Chấm mù đủ 30 output RAG, gồm hỗ trợ đúng, từ chối đúng và làm theo injection.
3. Hoàn tất review 148 claim hoặc loại khỏi corpus các claim chưa có source snapshot.
4. Thử biểu diễn URL giữ case path trên train/validation, rồi đăng ký trước khi mở test mới.
5. Chỉ đưa v6 thành mặc định nếu giảm lỗi có ý nghĩa mà không làm tăng FPR hoặc suy diễn không có căn cứ.

## Biên bản phát hiện trước sửa — 09/11/2026

Phần này giữ phát hiện của lượt nghiên cứu trước khi sửa. Trạng thái khắc phục hiện tại ở mục cuối. Lượt nghiên cứu đọc mã, tái hiện lỗi bằng mock/offline và kiểm tra train/validation. Không gọi provider, không huấn luyện lại và không mở phần test trong archive PhishVN. Các phát hiện dưới đây không phải kết quả độ chính xác mới.

### 1. Sửa lỗi tích hợp trước khi đo chất lượng

- `app/candidate_v6.py` chuyển toàn bộ verdict có trường `interaction` vào `build_retrieval_query`. Hàm này kiểm tra lại bằng `MessageVerdict` với `extra="forbid"`, gây `ValidationError`. Exception bị đổi thành `retrieval=unavailable`. Tái hiện bằng HTTP mock với `use_rag=true`: phân loại thành công, một lần gọi provider giả, **không gọi retriever**. Cần chiếu verdict về schema nền tại ranh giới retrieval/explanation, đồng thời giữ interaction trong kết quả v6; thêm test tích hợp có bật RAG.
- Regex người nói trong `app/message_policy_v6.py` cho phép thiếu dấu `:`. Văn bản `Xin chào.\nTôi cần xác minh giao dịch ngân hàng.` bị nhận nhầm thành hai lượt với người nói `Xin` và `Tôi cần xác minh giao dịch ngân`. Cần delimiter rõ ràng và ca kiểm tra văn xuôi, dòng nối tiếp, timestamp, URL và lời trích dẫn.
- App mặc định dùng `free_text` và cấu hình corpus/index v1; gói `rag_controlled_v1` dùng span selection và corpus/index v2. Khóa manifest thực thi gồm model, prompt/parser hash, corpus/index hash, mode và token budget. Kết quả component khác cấu hình không được ghi thành kết quả app mặc định.

### 2. Bổ sung URL đầy đủ, kiểm soát nguồn và dạng URL

Kiểm tra riêng `data/splits/url_train.csv` và `url_val.csv` bên trong `data/raw/PhishVN_v3.1.0_open.zip`:

| Split | Tổng mẫu | Có path khác rỗng hoặc `/` | Dương/âm trong nhóm có path | Có query |
|---|---:|---:|---:|---:|
| Train | 36.909 | 116 (0,314%) | 108 / 8 | 31 |
| Validation | 7.266 | 33 (0,454%) | 31 / 2 | 10 |

Toàn bộ query thuộc OpenPhish và mang nhãn dương. OpenPhish cung cấp 99/116 path train và 30/33 path validation. Chống Lừa Đảo và các nhóm Tranco đều chỉ chứa host; hai split không có URL non-ASCII. Vì vậy tác dụng của path/query hiện bị lẫn với nguồn và nhãn. Đây là giới hạn dữ liệu, chưa chứng minh model chỉ học nguồn.

Đề xuất một tập dev mới có cả URL hợp lệ và lừa đảo chứa path/query, lưu thời điểm và bằng chứng nhãn, chia theo miền/campaign. So sánh model hiện tại, biểu diễn host-only và host+path trên cùng split; báo riêng từng dạng URL. Không thể kiểm tra đầy đủ path model chỉ với 8 âm train và 2 âm validation có path.

Có thể dùng [PhreshPhish](https://arxiv.org/abs/2507.10854) làm nguồn đánh giá ngoài bổ sung vì nghiên cứu này thiết kế benchmark nhằm giảm leakage và thay đổi tỷ lệ lớp. Phải chốt phiên bản/split, kiểm tra trùng dữ liệu đã tiếp xúc và báo riêng kết quả quốc tế; nó không thay thế tập Việt Nam. Đây là đề xuất áp dụng, chưa tải hoặc đánh giá bộ này.

### 3. Thống nhất cách hiểu URL giữa các tầng

Intake v2 bỏ qua bước kiểm tra phục hồi với URL đã được bộ trích xuất strict nhận. Tái hiện: `https://bücher.de/Login` giữ nguyên, còn `bücher.de/Login` được IDNA hóa; URL có scheme chứa U+200B không có cảnh báo biến đổi. `https://a..com/` cũng được intake nhận nhưng reputation canonicalizer từ chối. Đây là lỗi nhất quán giữa các tầng, không phải bằng chứng URL ví dụ có độc hại.

Python codec IDNA hiện dùng làm `faß.de` thành `fass.de`; cách xử lý UTS #46 nontransitional cho `xn--fa-hia.de`. Nếu dùng cùng khóa để tra uy tín, sự khác biệt này có thể gộp sai hostname. Reputation hiện còn là thử nghiệm, không được mô tả thành lỗi bypass đang hoạt động ở app mặc định.

Đề xuất kiểm tra mọi authority qua cùng chính sách đã khóa, giữ nguyên input và path/query, hiển thị các cách hiểu khi mơ hồ. Thêm ma trận conformance cho Unicode/Punycode, ký tự ẩn, label rỗng, dấu chấm cuối, backslash và userinfo. [Tài liệu Python](https://docs.python.org/3.12/library/codecs.html#module-encodings.idna) và [UTS #46](https://www.unicode.org/reports/tr46/) phân biệt cơ chế IDNA; IDNA hợp lệ không chứng minh an toàn và không tự giải quyết giả mạo ký tự giống nhau.

### 4. Đo RAG theo bằng chứng hỗ trợ, sửa đối chứng trước khi gọi API

Trong v6, verdict khóa trước RAG. Vì vậy lợi ích RAG cần đo bằng hỗ trợ đúng cho claim, trích dẫn đúng, hướng xử lý và từ chối khi thiếu bằng chứng; **F1 phân loại không phải đầu ra mà nhánh RAG này được phép cải thiện**. Nếu nghiên cứu RAG trước phân loại, phải đăng ký một arm khác với giả thuyết riêng.

Gói hiện có các vấn đề cần sửa:

- `irrelevant_equal_budget` chỉ chọn tài liệu khác ID, chưa chứng minh không liên quan. Nó cắt theo ký tự; 4/6 đoạn còn ngắn hơn oracle. Cần xác minh relevance và khớp token theo tokenizer đã chọn, hoặc công bố rõ độ lệch ngân sách.
- Bỏ câu được gọi là quyết định vẫn để lại bằng chứng đủ ở một số ca. Cần phân biệt **cùng chủ đề / hỗ trợ một phần / đủ hỗ trợ claim / mâu thuẫn**, thay vì giả định bỏ một câu là mất căn cứ. Đây là hướng vận dụng từ [Sufficient Context, ICLR 2025](https://arxiv.org/abs/2411.06037), chưa phải kết quả đã chứng minh trong dự án.
- Injection đang thêm vào oracle có bằng chứng đúng. Ở RC-01/02, lệnh độc và bằng chứng đúng cùng một span, nên chọn span không chứng minh làm theo lệnh độc. Đối chứng mới cần tách attack span và dùng cặp sạch/bị chèn trên nguồn không hỗ trợ hoặc mâu thuẫn; đo chọn span tấn công, hỗ trợ sai và từ chối riêng.
- Scorer chưa kiểm hash protocol/request hoặc trạng thái HTTP/finish reason/model/usage. JSON parse được từ response bị cắt không được tính là thành công nếu runtime từ chối nó.

Đánh giá riêng retriever bằng nguồn đã chấm và generator bằng nguồn oracle; thêm số liệu toàn pipeline. Dùng cùng verdict cố định ở mọi nhánh giải thích, giữ lỗi trong mẫu số, báo chi phí và độ trễ.

### 5. Kiểm tra bằng chứng nguồn và tính đầy đủ của phiếu

Validator `rag_summary_audit_v1` hiện chỉ kiểm trường, chưa đối chiếu tập claim đã khóa. Một dòng với claim/document ID không tồn tại, excerpt tùy ý và thời gian không hợp lệ vẫn có thể trả `human_review_complete=True`.

Trước khi dùng phiếu làm minh chứng, phải yêu cầu đúng tập **148 claim ID**, không trùng/thiếu/thừa; khóa nội dung claim và document/source hash; kiểm excerpt có trong snapshot tương ứng và timestamp hợp lệ. Kiểm tra máy chỉ xác nhận liên kết và tính đầy đủ; mức hỗ trợ ngữ nghĩa vẫn cần người chấm. Hiện có **12/37 tài liệu** có raw khớp hash, không phải 12/148 claim đã được xác minh.

### 6. Đánh giá ngữ cảnh, cảnh báo sớm và khả năng từ chối

Sáu hội thoại hiện tại đều cung cấp đủ ba lượt, chưa kiểm tra phát hiện sớm hoặc lợi ích của lịch sử. Đề xuất cặp **chỉ lượt cuối / đầy đủ lịch sử**, đánh giá lần lượt tiền tố 1, 2, 3 lượt với nhãn riêng theo thông tin đã xuất hiện. So sánh v5/v6 cùng model và ngân sách. Đo lượt cảnh báo đầu tiên có căn cứ, cảnh báo quá sớm trên hội thoại hợp lệ và lỗi suy diễn vai trò.

Tạo cặp chỉ đổi một yếu tố: tự nhập OTP trong ứng dụng so với đọc OTP cho người gọi; cảnh báo trích lời lừa đảo so với yêu cầu thực hiện; cùng URL nhưng đổi người nhận tiền. Các phép đổi chính tả/định dạng giữ nghĩa phải giữ kết luận. Đây là cách vận dụng kiểm thử hành vi của [CheckList, ACL 2020](https://aclanthology.org/2020.acl-main.442/); dữ liệu tự soạn vẫn phải báo riêng với dữ liệu thực có nhãn người.

UNKNOWN hiện chỉ là dải điểm. Replay cutoff char hiện hành trên validation lịch sử cho **87/7.266 UNKNOWN (1,20%)**, LOW vẫn có 900 nhãn dương (898 bronze, 2 silver), HIGH có 78 nhãn âm. Đây là phép áp dụng một cutoff trên toàn validation, khác kết quả 77 FP cross-fit, không phải test mới. Cần phân biệt mơ hồ khi parse, thiếu ngữ cảnh, model từ chối và lỗi API; đo lỗi theo tỷ lệ mẫu được kết luận, báo nhầm trên 1.000 âm và bỏ sót khi giữ UNKNOWN trong mẫu số phù hợp.

### Thứ tự đề xuất

1. Sửa nối schema RAG, parser hội thoại/URL và kiểm tra phiếu; xác nhận các nhánh thực sự chạy bằng test tích hợp offline.
2. Khóa lại manifest và đối chứng RAG/hội thoại; chọn ca trước khi xem output, chấm mù và giữ lỗi.
3. Thu URL đầy đủ cùng tin nhắn/hội thoại mới; giữ test chưa xem, chốt nhãn/phạm vi trước khi so sánh.
4. Chạy pilot ghép cặp, báo chỉ số phát hiện, nguồn dẫn và chi phí riêng. Chỉ mở rộng model nếu phân tích lỗi cho thấy dữ liệu và biểu diễn hiện tại đã đủ kiểm tra giả thuyết đó.



## Trạng thái sau khắc phục — 09/11/2026

| Phát hiện | Kết quả sửa và kiểm chứng |
|---|---|
| Verdict có `interaction` làm hỏng RAG | Chiếu rõ về `MessageVerdict` tại ranh giới RAG, giữ nguyên verdict v6. Test HTTP mock xác nhận thứ tự classification → retrieval → explanation ở cả free text và span selection; response bị cắt vẫn là lỗi và không đổi kết luận |
| Văn xuôi bị tạo thành hội thoại | Bắt buộc nhãn có delimiter; hỗ trợ nhãn trong ngoặc vuông và nối dòng tiếp diễn. Không tạo vai trò từ văn xuôi, timestamp, URL hoặc trích dẫn minh họa trong các ca hồi quy |
| URL có scheme bỏ qua kiểm tra | Intake 2.1 kiểm tra authority của cả URL strict và URL phục hồi. Dùng chung UTS #46 nontransitional/STD3 với reputation 1.1; `faß.de` giữ khóa `xn--fa-hia.de`, khác `fass.de`. Giữ path/query/fragment; authority mơ hồ bị đưa vào invalid thay vì chấm model |
| Không biết cấu hình thực thi | API v6 trả runtime manifest chứa model yêu cầu/thực tế nếu có, mode, ngân sách token, corpus/index và hash mã nguồn. Gói RAG ghi rõ chỉ là component experiment, không khẳng định tương đương app mặc định |
| Đối chứng RAG gây hiểu nhầm | Protocol 1.2 thay nhiễu được suy từ ID bằng đối chứng tự soạn có ghi rõ nguồn; attack dùng document/span riêng. Bỏ tên “equal budget”; công bố chưa khớp token. Đổi thành `design_sentence_removed`, không giả định nguồn còn lại thiếu căn cứ |
| Scorer bỏ qua lỗi/khóa thực thi | Kiểm hash request/pack/corpus/index/mã nguồn; response gắn request hash, HTTP, finish reason, model, usage và thời gian. `length`, HTTP lỗi và transport lỗi giữ trong mẫu số. Không ghi đè phiếu đã có |
| Phiếu có thể hoàn tất sai inventory | Bắt buộc đúng toàn bộ claim ID, không thiếu/thừa/trùng; khóa claim/nguồn; kiểm hash snapshot, excerpt có trong nguồn và datetime có múi giờ. Không tự xác minh danh tính reviewer hoặc ý nghĩa hỗ trợ |
| Chưa đo lợi ích lịch sử/cảnh báo sớm | `prepare-paired` khóa 72 request = 6 hội thoại × 3 tiền tố × 2 điều kiện lịch sử × 2 profile v5/v6. Có 30 đầu vào khác nhau để chấm mù; không sao chép nhãn cuối hội thoại sang tiền tố trước đó |

Các số đo hồi quy phần mềm không phải Accuracy/F1 model. Bản v4 và v5 cùng các protocol lịch sử giữ nguyên; riêng policy reputation thử nghiệm tăng lên 1.1 nên kết quả reputation cũ không tự mô tả policy mới. Sáu hội thoại vẫn là ca tự soạn, hai profile có đầu ra khác nhau và cùng giới hạn token không có nghĩa cùng lượng suy luận.

Gói chuẩn bị mới nằm tại `artifacts/evaluations/v6_hardening_20261109/`:

- `rag_controlled/`: 30 request, protocol `rag-controlled-v1-1.2`, chưa có response LLM.
- `summary_audit/`: 148 claim, 12/37 nguồn có snapshot khớp hash; 0 claim được chấm.
- `conversation_paired/`: 72 request, 30 input khác nhau; phiếu nhãn còn trống.

Không sửa hoặc ghi đè các gói ngày 08/11. Gói legacy không đáp ứng protocol mới phải được dựng lại ở thư mục mới; không sửa trực tiếp request đã khóa để đổi model.

### Lệnh mới và định dạng response

```bash
.venv/bin/python -m evaluation.rag_controlled_v1 prepare --out NEW_RAG_PACK --model MODEL_ID --max-tokens 2048
.venv/bin/python -m evaluation.rag_summary_audit_v1 prepare --out NEW_SUMMARY_AUDIT
.venv/bin/python -m evaluation.rag_summary_audit_v1 validate --sheet NEW_SUMMARY_AUDIT/claims.csv
.venv/bin/python -m evaluation.conversation_structure_v1 prepare-paired --out NEW_CONVERSATION_PACK --model MODEL_ID
```

Scorer RAG nhận đúng một dòng cho mỗi request, gồm `key`, `request_sha256`, `content`, `http_status`, `finish_reason`, `provider_model`, `usage` và `elapsed_ms`. Với lỗi kết nối, ghi `transport_error` và `http_status=null`; `usage={}` nếu không thu được, không tự điền token bằng 0 để giả là usage đã biết. Ví dụ thành công về transport, mô hình từ chối dẫn nguồn:

```json
{"key":"RC-01::oracle","request_sha256":"COPY_FROM_LOCKED_REQUEST","http_status":200,"finish_reason":"stop","provider_model":"ACTUAL_PROVIDER_MODEL","usage":{},"elapsed_ms":1200,"content":"{\"selections\":[]}"}
```

Chấm bằng `.venv/bin/python -m evaluation.rag_controlled_v1 score --out NEW_RAG_PACK --responses responses.jsonl`. Metadata ghi bởi người thu phản hồi; hash là ràng buộc tái lập, không phải xác thực độc lập dịch vụ. Trạng thái cấu trúc, chọn attack span và chấm ngữ nghĩa là những thước đo khác nhau.

Để thử app với cùng mode/corpus/index đã chọn trong gói RAG, cấu hình rõ:

```bash
PHISHLENS_CANDIDATE_RAG_MODE=span_selection RAG_CORPUS=data/knowledge/corpus_v2/documents.jsonl RAG_INDEX_DIR=artifacts/rag/e5-small-v2-r1 .venv/bin/uvicorn app.candidate_v6:app --host 127.0.0.1 --port 8000
```

Lệnh này chỉ đồng bộ mode/corpus/index. Các can thiệp nguồn và verdict tự soạn trong gói vẫn là thí nghiệm component, không trở thành kết quả end-to-end của app.

Kiểm chứng cuối lượt: **580 test offline đạt**, một cảnh báo deprecation Starlette/httpx. Smoke qua API với model char thật đạt bốn ca (Unicode có/không scheme, sharp-s và hostname sai); hai cách viết Unicode tương ứng cho cùng score sau chuẩn hóa. [Minh chứng](../../artifacts/evaluations/v6_hardening_20261109/verification.json) và [URL smoke](../../artifacts/evaluations/v6_hardening_20261109/url_smoke.json). Không dùng các ca này để tính Accuracy/F1.

Lượt API tiếp theo đã hoàn thành và lưu riêng tại `artifacts/evaluations/v6_pilot_live_20261109/`: 102 attempt/102 response, 405.410 token ghi nhận, không retry. [Báo cáo tiếng Việt và bộ dữ liệu bổ sung](../evaluation/V6_PILOT_V1.md). Bộ chuẩn bị và minh chứng offline ở trên được giữ như mốc trước suy luận, không bị sửa để thay phản hồi lỗi.


## Khắc phục sau pilot: v6.1 — 09/11/2026

Bản sửa trong `app/message_policy_v61.py` và factory `app/candidate_v6.py`. Profile là `message-v6.1`, parser `message-parser-6.1`, pipeline `analysis-pipeline-6.1-candidate`. Entry point vẫn là `app.candidate_v6:app`; `python run.py` tiếp tục dùng v4. Không đổi `.env`, model URL hoặc các kết quả API cũ.

- Một dòng có nhãn người nói được nhận là một lượt. Văn xuôi không có nhãn được xem là một thông điệp, không tự tạo người nói. Payload công bố `input_structure.visible_turn_limit`, và parser dùng cùng giới hạn; vượt giới hạn vẫn là lỗi.
- Prompt được viết gọn thay cho việc nối nhiều lớp hướng dẫn. Giữ quy tắc phân biệt quảng cáo/lừa đảo, OTP tự nhập/gửi cho người gọi, trích dẫn/yêu cầu thật, injection ép HIGH/LOW và rủi ro nội dung/URL.
- Giới hạn summary 240 ký tự; tối đa hai evidence, quote/reason mỗi trường 180 ký tự; tối đa hai bước xử lý, mỗi bước 180 ký tự. Có schema đầu ra trong payload và vẫn giữ vai trò/giai đoạn tương tác. Code không tự cắt hoặc sửa JSON để vượt validator.
- Dùng chung transport một lần gọi của v6, rồi áp parser mới trên raw response đã hoàn tất. `finish_reason=length`, lỗi HTTP hoặc output thiếu vẫn là lỗi. Không gọi lại để sửa kết quả.
- Quy tắc kiểm trích đoạn và chuyển cảnh báo thiếu bằng chứng sang UNKNOWN không thay đổi. `interaction_semantics_verified=false` vẫn giữ; schema hợp lệ không chứng minh vai trò được suy ra đúng.

### Kiểm chứng offline

Phát lại 36 raw response v6 của pilot, **chỉ đổi quy tắc đếm lượt và giữ giới hạn độ dài của schema cũ**, giải quyết 9 phản hồi bị từ chối do một lượt; không đổi 16 verdict vốn hợp lệ. Giữ nguyên 11 phản hồi bị cắt. Đây là chẩn đoán validator, **không phải 25/36 là tỷ lệ thành công thực đo của app v6.1**: app còn áp hợp đồng đầu ra gọn mà các phản hồi cũ không được yêu cầu tuân theo.

Trên cùng 36 input, tổng ký tự phần messages giảm từ **364.322 xuống 206.562**, tương đương **43,3%**. Đây không phải số token. Chưa có số đo mới về reasoning, độ trễ, tỷ lệ cắt đầu ra hoặc F1.

**600 test offline đạt**, một cảnh báo deprecation Starlette/httpx. Gồm API một lượt, giới hạn schema, thiếu bằng chứng phải UNKNOWN, quá số lượt phải lỗi, RAG sau phân loại và không chấp nhận JSON bị cắt. `evaluation.v6_pilot verify` vẫn kiểm chứng nguyên vẹn 102 attempt/response của pilot cũ.

Tái lập audit mà không gọi provider:

```bash
.venv/bin/python scripts/evaluation/check_v61_contract.py --out NEW_CONTRACT_AUDIT
.venv/bin/python -m evaluation.v6_pilot verify --out artifacts/evaluations/v6_pilot_live_20261109
```

[Audit](../../artifacts/evaluations/v61_contract_fix_v1/report.md), [số liệu và hash](../../artifacts/evaluations/v61_contract_fix_v1/summary.json).

### Token cấu hình và lượt kiểm tra tiếp theo

`LLM_MAX_TOKENS` trong `.env` là cấu hình ứng dụng. Candidate giới hạn giá trị hiệu lực bằng `min(LLM_MAX_TOKENS, 8192)`. Pilot 102 lần gọi có `max_tokens=2048` trong từng payload đã khóa; đổi `.env` không sửa ngân sách hoặc kết quả pilot cũ.

Đã chuẩn bị riêng **12 request v6.1**, gồm toàn bộ sáu hội thoại ở hai điều kiện lượt cuối/đầy đủ lịch sử, cùng cap 2.048 token. Chưa gọi API. [Request](../../artifacts/evaluations/v61_contract_fix_v1/smoke_requests.jsonl) và [khóa cấu hình](../../artifacts/evaluations/v61_contract_fix_v1/smoke_registration.json). Không chọn riêng các ca v6 cũ thất bại để tạo kết quả đẹp.

Lượt này chỉ kiểm tra tính hoàn tất JSON và lỗi hợp đồng một lượt; chưa đánh giá khả năng tổng quát. Sau đó mới chốt prompt/schema để so sánh LLM và LLM + URL trên bộ SMS mới có nhãn phiên bản hóa. Nhãn nguồn spam không thay thế nhãn phishing; reserve vẫn chưa chạy model.
