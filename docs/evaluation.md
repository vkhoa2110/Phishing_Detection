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

### Tránh kết luận từ F1 tăng nhờ lỗi trên mẫu âm

F1 lớp dương không tính predicted UNKNOWN trên mẫu âm là FP. Nếu model bị cắt đầu ra trên một cảnh báo nhầm thì FP giảm và F1 có thể tăng dù chưa xử lý đúng mẫu đó. Luôn báo Accuracy toàn tập nhị phân (mọi UNKNOWN/lỗi tính sai), coverage, số UNKNOWN trên âm, cùng ma trận chuyển alarm → LOW và alarm → UNKNOWN. `evaluation.messages.ablation_interpretation --out COMPLETE_RUN` tái kiểm raw đã khóa, xuất các chuyển này và giải thích cạnh bảng F1. Không dùng FPR thấp hơn nhờ mất output để tuyên bố chất lượng tốt hơn.

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

## Kiểm chứng đầu ra compact v6.1

`evaluation.messages.compact_pilot` khóa một lượt mới với v5 đối chứng và v6.1, trên toàn bộ sáu hội thoại cũ, mỗi hội thoại hai điều kiện full-history/last-turn: **12 input, 24 request**, không thêm reserve SMS hoặc RAG/URL. Model, thông số sinh, cap 2.048 token và timeout giống nhau; schema đầu ra khác nhau nên chỉ đánh giá tính vận hành, không tách riêng tác dụng rút gọn prompt.

```bash
.venv/bin/python -m evaluation.messages.compact_pilot prepare --out NEW_COMPACT_RUN
.venv/bin/python -m evaluation.messages.compact_pilot run --out NEW_COMPACT_RUN --live
.venv/bin/python -m evaluation.messages.compact_pilot verify --out NEW_COMPACT_RUN
.venv/bin/python -m evaluation.messages.compact_pilot report --out NEW_COMPACT_RUN
```

Lệnh `run` bỏ `--live` chỉ kiểm cấu hình, không gọi provider. Journal ghi trước mỗi lần gửi; lỗi/cắt đầu ra và attempt bị gián đoạn không được thử lại. Source hash, requests và kết quả được khóa; phiếu output review không bị ghi đè khi xuất lại báo cáo. Dừng ở lỗi quyền/hạn mức, ba transport error hoặc ngân sách token ghi nhận; hai request đang chạy có thể hoàn tất cùng batch. Chênh lệch nhãn giữa hai profile chưa chứng minh ai đúng khi không có nhãn độc lập. Accuracy/F1 luôn để trống.

Nếu lượt dừng chỉ có lỗi kết nối, sau khi kiểm tra lại mạng có thể đăng ký phần **chưa từng gửi** bằng `scripts/evaluation/continue_compact_pilot.py prepare --parent ORIGINAL_RUN --out NEW_CONTINUATION`. Chạy continuation bằng runner thông thường rồi dùng `scripts/evaluation/continue_compact_pilot.py report --out NEW_CONTINUATION` để gộp kết quả. Hash parent được giữ, mọi lỗi ban đầu vẫn tính trong mẫu số và không gửi trùng key. Không dùng cơ chế này để vượt chặn HTTP quyền/hạn mức hoặc thay output model sai. Bảng continuation riêng chỉ là tập con; báo cáo chính phải dùng `combined_report.md` và `combined_summary.json`.

## Đối chứng dev bốn cấu hình và chấm nguồn ngày 11/11

`evaluation.data.fresh_dev` chỉ lấy **80 development_review** từ gói `fresh_messages_v1` đã khóa; 120 reserve được giữ ngoài suy luận. Nhãn nguồn spam không vào payload. Hai phiếu người để trống; nhãn AI và tình trạng không nhận được phản hồi gán nhãn phải phân biệt với UNKNOWN về ngữ nghĩa. Nếu dùng trợ lý review trực tiếp thì giữ thành reference riêng, không vá phản hồi API bị lỗi hoặc gọi là nhãn người.

`evaluation.messages.fresh_ablation` so sánh bốn arm với **cùng prompt, schema MessageRAGVerdict, validator, model, decoding và cap 4.096 token**. Payload chỉ khác `url_results` và `reference_documents`. Mọi payload giống hệt trên cùng case dùng chung response; do đó 120 case × 4 arm là 480 ô logic nhưng chỉ 212 request khác nhau ở lượt 11/11. URL minh họa trong 40 stress tự soạn không được đưa qua model. Model URL của lượt này là TF-IDF ký tự + LR đã có, không phải XGBoost mặc định. RAG dùng corpus v1 25 tài liệu và index E5 cố định, trước phân loại để nghiên cứu tác động; đây không phải nhánh RAG sau verdict của candidate.

```bash
# Mọi --out bên dưới phải mới. prepare không gọi API.
.venv/bin/python -m evaluation.data.fresh_dev --help
.venv/bin/python -m evaluation.messages.fresh_ablation prepare --pack DEV_PACK --labels AI_REFERENCE --out NEW_ABLATION
.venv/bin/python -m evaluation.messages.fresh_ablation run --out NEW_ABLATION --live
.venv/bin/python -m evaluation.messages.fresh_ablation verify --out NEW_ABLATION
.venv/bin/python -m evaluation.messages.fresh_ablation report --out NEW_ABLATION

# Chọn query/explanation case trước khi đọc kết quả; tạo phiếu người chưa chấm.
.venv/bin/python -m evaluation.rag.dev_review prepare-retrieval --pack DEV_PACK --classification NEW_ABLATION --out NEW_RELEVANCE
.venv/bin/python -m evaluation.rag.dev_review prepare-explanations --relevance NEW_RELEVANCE --out NEW_EXPLANATIONS
```

Runner `evaluation.common.registered` khóa source/input/request, ghi journal trước khi gửi, chỉ chạy khi có `--live`, không retry hoặc sửa JSON. Truncation/HTTP/timeout giữ nguyên; chỉ xuất bảng so sánh sau khi toàn bộ inventory có kết quả hoặc lỗi được ghi nhận. Ngân sách là token provider ghi nhận; lỗi thiếu usage không được giả định miễn phí. `evaluation.common.continuation` chỉ đăng ký phần chưa từng gửi sau dừng vận hành và giữ nguyên lỗi parent; không vượt chặn quyền/hạn mức/token.

Ngân sách nội bộ phân loại ban đầu là 1,5 triệu token ghi nhận. Trước khi xem điểm phân loại, lượt 11/11 đăng ký riêng khoản chuyển 200.000 token từ review API không dùng sang phần request chưa gửi nếu chạm giới hạn; bản đăng ký ban đầu giữ nguyên. Đây là sửa đổi protocol có ghi nhận, không phải cơ chế continuation tự vượt gate hoặc thay đổi ngân sách người dùng. Mọi phản hồi cũ vẫn giữ nguyên.

Relevance chọn cố định 12 query × **toàn bộ 25 tài liệu = 300 cặp**, không chỉ chấm top-k. Tài liệu xáo thứ tự và giấu điểm/rank khi lập reference AI. Chấm lời giải thích dùng tám case chọn trước (32 ô logic, có dùng chung output); tên arm bị ẩn nhưng vẫn có thể suy ra từ nguồn hiển thị. Các phiếu AI và người tách biệt, chiều nguồn không có citation để N/A. Corpus chưa được mở rộng bằng đáp án của các query này.

Lượt này có kiểm tra miền URL trùng train, các nhóm thật sự nhận thêm URL/RAG, baseline luôn HIGH/LOW và lỗi kỹ thuật. Accuracy/F1 theo nhãn AI chỉ là mức khớp reference sơ bộ; 4 mẫu dương trong 80 SMS không đủ chứng minh chất lượng triển khai hoặc ưu thế thống kê. [Minh chứng cục bộ](../artifacts/evaluations/week4_dev_20261111/README.md).

## Verdict lõi, telemetry và điều kiện kết luận cải tiến

`evaluation.messages.core_pilot` đăng ký bốn probe vô hại, sau đó factorial **tám input dev quen thuộc × hai schema × hai yêu cầu thinking**. Mọi arm cùng model, cap 2.048, decoding và timeout; schema/prompt khác nhau có chủ ý. Đo output hoàn chỉnh, lỗi, usage và độ trễ, để trống Accuracy/F1. Telemetry chỉ ghi số lượng, không lưu văn bản reasoning. Không chấp nhận JSON dang dở; lỗi cũ giữ nguyên.

```bash
# Dùng thư mục mới; prepare và run không có --live đều không gọi API.
.venv/bin/python -m evaluation.messages.core_pilot prepare-probe --out NEW_PROBE
.venv/bin/python -m evaluation.messages.core_pilot run --out NEW_PROBE --live
.venv/bin/python -m evaluation.messages.core_pilot prepare --pack LOCKED_DEV_PACK --probe NEW_PROBE --out NEW_OPERATIONAL
.venv/bin/python -m evaluation.messages.core_pilot run --out NEW_OPERATIONAL --live
.venv/bin/python -m evaluation.messages.core_pilot report --out NEW_OPERATIONAL
```

`evaluation.messages.core_quality` khóa so sánh pipeline v6.1 không URL / core không URL / core có URL trên cùng 80 SMS và reference AI trước đó. URL score lấy từ cache đã khóa, không fit lại. Cùng cap 2.048 và thinking disabled; RAG ở sau verdict nên không tạo arm RAG giả để công bố tăng F1 phân loại. Payload giống hệt trên cùng ca dùng chung response. Mẫu dương có URL bằng 0, không đánh giá được lợi ích Recall của URL.

```bash
.venv/bin/python -m evaluation.messages.core_quality prepare --study COMPLETE_PREVIOUS_STUDY --probe COMPLETE_PROBE --out NEW_QUALITY
.venv/bin/python -m evaluation.messages.core_quality run --out NEW_QUALITY --live
.venv/bin/python -m evaluation.messages.core_quality verify --out NEW_QUALITY
# Chỉ xuất bảng sau khi toàn bộ inventory có kết quả hoặc lỗi được ghi nhận.
.venv/bin/python -m evaluation.messages.core_quality report --out NEW_QUALITY
```

Lượt 12/11 dừng khi gặp HTTP 429, 92/199 attempt; `report` từ chối tính so sánh đầy đủ. Không đổi manifest, vượt gate hoặc gửi lại lỗi. 107 request chưa gửi không được giả thành lỗi hoặc UNKNOWN đã quan sát. Usage lỗi thiếu phải để chưa biết; không tự coi bằng 0. [Trạng thái và minh chứng](../artifacts/evaluations/focused_20261112/README.md).

Runner khóa hash cả các module Python liên quan tại lúc đăng ký. Pilot 32 request dùng mã trước khi đổi lựa chọn retriever mặc định về E5. Mã đúng thời điểm được giữ tại `artifacts/evaluations/focused_20261112/source_snapshot`; chạy verify từ thư mục snapshot, dùng Python môi trường dự án và đường dẫn tuyệt đối tới run. Không sửa hash của pilot cho khớp mã mới. Các module Python lịch sử không bị chỉnh trong lượt này; replay lượt week4 vẫn dùng mã hiện tại được.

`evaluation.rag.action_comparison` chỉ chấm lại 12 query/300 reference AI trên cùng index/corpus; lọc hành vi có tham khảo lỗi dev, chưa calibration. Báo cả nguồn trực tiếp bị mất và khả năng từ chối. Không thay tham số tiếp theo kết quả này hoặc coi retrieval Hit là F1 phishing.

`evaluation.messages.readiness --study COMPLETE_PREVIOUS_STUDY --out NEW_READINESS` kiểm Accuracy toàn tập, Recall, coverage, lỗi, chuyển FP → LOW thực sự và chất lượng/kích thước nhãn. Mốc 20 dương mỗi nhóm là mục tiêu lập kế hoạch, không thay kiểm định hoặc khoảng bất định. Bản readiness 12/11 áp dụng cho ablation week4 cũ, không chấm chất lượng focused chưa chạy đủ. Thiếu nhãn người và dương có URL vẫn là công việc dữ liệu cần làm.

[Danh sách công cụ](../scripts/README.md) · [Kết quả hiện có](results.md).

## Amendment vận hành và mở rộng nguồn ngày 13/11

Sau một probe vô hại trả HTTP 200, `scripts/evaluation/recover_core_quality.py` đăng ký riêng phần chưa gửi của lượt core quality bị HTTP 429. Tham số model/payload/parser/timeout giữ nguyên; đổi sang một worker và cách tối thiểu bốn giây giữa các lần bắt đầu. Lỗi 429 ban đầu giữ trong mẫu số; không gửi lại key đã attempt. Giới hạn token ghi nhận còn lại trừ cả probe; usage của lỗi cũ vẫn chưa biết. Đây là thay đổi protocol có ghi nhận, không sửa gate hoặc manifest của lượt cũ. Nếu gặp lỗi quyền, 429 mới hoặc chạm budget thì tiếp tục dừng. Probe thành công không xác định được nguyên nhân 429 trước đó.

`prepare --parent PARENT --health HEALTH_DIR --out NEW_CONTINUATION` kiểm hash parent và probe thành công cùng provider trong 15 phút. `run --out NEW_CONTINUATION --live` dùng transport có pacing; `merge --child NEW_CONTINUATION --out NEW_MERGED` chỉ ghép khi inventory còn lại đầy đủ, kiểm không trùng/thiếu/thay payload rồi xuất bảng toàn lượt. Thời điểm và tốc độ hai pha khác nhau, cần ghi hạn chế đó khi báo kết quả.

Mở rộng corpus dùng 25 nguồn cũ nguyên vẹn và bốn nguồn mới đã tải/kiểm chủ đề/hash. Chấm thêm **48 cặp AI** trước khi chạy retrieval mới, ghép với 300 cặp cũ thành **12 query × 29 tài liệu = 348 cặp**. Có hai phiếu người còn trống. Nguồn mới được chọn để xử lý lỗi dev đã xem nên chỉ là đánh giá phát triển, không dùng từ “test độc lập”.

`evaluation.rag.corpus_comparison` so raw E5 top-3 hai corpus, không đổi embedding/tham số và chưa chọn ngưỡng từ chối. Mẫu số chính là cùng chín query có nguồn trực tiếp theo reference mở rộng; báo riêng số query mà mỗi corpus có khả năng trả lời. Không so 5/6 cũ với 7/9 mới như cùng mẫu số. Hai ca còn hụt nguồn trực tiếp được giữ lại: nhận thưởng đóng phí và giả người nhà yêu cầu chuyển tiền. Index mới chưa được dùng trong app mặc định hoặc giải thích lại output của ablation đã khóa.

## Kiểm chứng runtime, dữ liệu và FR/NFR

`evaluation.data.cohort_audit` so ID, nội dung chuẩn hóa và group; chỉ gọi là đổi nhãn khi cùng ID và nội dung tương ứng. Lượt 13/11 có hai nhóm 80 SMS không trùng ID/text/group. Bảng CSV ghi N/A khi mẫu không có ở một cohort, không tự tạo nhãn hoặc lý do thay đổi.

```bash
.venv/bin/python -m evaluation.data.cohort_audit \
  --old-binary data/annotation/objective_v1/provisional_reference/sms/dev.jsonl \
  --old-unknown data/annotation/objective_v1/provisional_reference/sms/dev_unknown.jsonl \
  --new-cases artifacts/evaluations/week4_dev_20261111/pack_reviewed/sms.jsonl \
  --new-labels artifacts/evaluations/week4_dev_20261111/assistant_reference/labels.jsonl \
  --out NEW_COHORT_AUDIT

.venv/bin/python scripts/evaluation/benchmark_url_runtime.py --profile stable --trials 100 --cpu-cores 4 --out NEW_STABLE_BENCHMARK
.venv/bin/python scripts/evaluation/benchmark_url_runtime.py --profile focused --trials 100 --cpu-cores 4 --out NEW_FOCUSED_BENCHMARK
.venv/bin/python scripts/evaluation/check_runtime_ui.py --base-url http://127.0.0.1:8001 --out NEW_BROWSER_CHECK
```

Benchmark dùng model thật, ba warmup và 100 batch, mỗi batch năm URL tổng hợp với query khác nhau. Gửi ở mode text vì tab URL lõi nhận một URL. Đo API in-process sau khi model đã nạp, gồm trích xuất/suy luận/serialization, không đo mạng HTTP vật lý hoặc LLM. Mọi model lỗi/provider call khiến benchmark thất bại, không được tính như một lượt nhanh. Tệp protocol ghi máy/affinity, không giả lập giới hạn RAM 8 GB. Phần precheck ban đầu dùng nhầm mode URL bị 422 được ghi riêng, chưa có mẫu hiệu năng; sửa đầu vào trước lượt benchmark chính.

Các test `tests/api/test_runtime.py` dùng provider giả, kiểm deadline rút ngắn để xác nhận hủy đúng bước, không cấp lại budget cho giải thích, không gửi lời gọi mới sau khi budget hết và không lẫn request đồng thời. Không suy từ test này rằng provider thật có SLA 45 giây. Runtime cấu hình tối đa 45 giây dùng chung và giữ kết quả URL/verdict phù hợp khi lỗi.

Browser check replay AI, chặn provider; kiểm trường kết nối ẩn, client không gửi credential/endpoint/model thay thế, tên miền nhận dữ liệu đúng cấu hình và trường hợp người dùng thêm PII trong bản sửa phải che/xem/xác nhận lại. Ma trận chức năng, giới hạn và phần còn thiếu ở [requirements.md](requirements.md); số test phần mềm không phải Accuracy phishing.

## Kiểm tra cách diễn giải lý do

`evaluation.messages.claim_audit` đọc toàn bộ journal đã khóa, kiểm hash/replay bằng parser gốc rồi áp dụng lớp trình bày mới trên bản sao. Mức kết luận, context, quote, mã lý do gốc, hành động và lỗi kỹ thuật phải giữ nguyên; khác bất kỳ trường quyết định nào khiến audit thất bại. Profile khác và lỗi vẫn có trong mẫu số. Không gọi API hoặc tạo nhãn.

```bash
.venv/bin/python -B -m evaluation.messages.claim_audit \
  --study artifacts/evaluations/recovery_20261113/combined \
  --out NEW_PRESENTATION_AUDIT
```

Số phản hồi thiếu cue không phải số lỗi giải thích đã được xác minh. Bộ quy tắc chỉ kiểm điều kiện từ vựng cần có trong một mệnh đề; không chứng minh entailment, ý định hay scam. Phủ định/trích dẫn và các cách viết lược bỏ vẫn có thể bị gắn cờ quá thận trọng. Lượt QA ban đầu ngày 14/11 đã bỏ sót cách viết thông thường “để nhận”; bổ sung cue và ca regression, giữ cả hai đầu ra/hai phiên bản nguồn, ghi rõ phát triển trên dev đã xem. Không chọn phiên bản theo F1 và không tuyên bố kiểm tra độc lập.

`review.csv` là phiếu người chấm mở, rubric 0–2 cho mức cơ chế được trích dẫn hỗ trợ. Chưa chấm thì không có điểm semantic hoặc nhãn người. Đây là rubric lời giải thích, khác relevance của RAG và khác nhãn phishing toàn thông điệp.

## Trace retrieval, parity và injection ngày 16/11

Ba công cụ mới dùng dữ liệu cũ hoặc phản hồi kiểm soát; không gọi provider thật, không tạo nhãn và không suy luận reserve:

```bash
.venv/bin/python -B -m evaluation.rag.filter_trace --out NEW_RETRIEVAL_TRACE
.venv/bin/python -B -m evaluation.messages.runtime_parity \
  --dev-pack artifacts/evaluations/week4_dev_20261111/pack_reviewed --out NEW_PARITY_AUDIT
.venv/bin/python -B -m evaluation.messages.injection_pairs \
  --run artifacts/evaluations/week4_dev_20261111/classification_results --out NEW_INJECTION_PAIRS
```

Trace retrieval kiểm hash đầu vào rồi xuất ứng viên, rank/score trước và sau ngưỡng, lý do loại và toàn bộ relevance grid. Chỉ 36 ứng viên top-3 có score đã lưu; tài liệu ngoài pool không được bịa rank hoặc gán lý do “dưới ngưỡng”. Nhãn relevance AI UNKNOWN vẫn giữ nguyên. Không đổi ngưỡng để cứu một query đã xem.

Parity gọi đúng API preview và analyze của focused runtime với model URL thật; LLM và retriever rỗng là fixture. Bản sửa được che/chuẩn hóa lại và phải được callback chấp thuận lại khi thay đổi, giống bước xác nhận cuối trên UI. Adapter không tự phục dựng URL hoặc đặc trưng theo một pipeline riêng. Model chấm URL của input gốc, còn payload/retrieval chỉ dùng bản được duyệt. Các check không đạt được giữ trong `summary.json`; số test phần mềm đạt không biến check ứng dụng thất bại thành đạt. Hash vector sparse được dựng lại từ cùng vectorizer sau prediction, không phải hook bên trong inference. Lượt này không kiểm chất lượng provider hoặc toàn nhánh giải thích khi có nguồn.

Injection replay lại parser/checkpoint và đối chiếu decision từng mẫu trước khi ghép cặp. Có 16 biến thể trên 8 nhóm tình huống tự soạn, 64 cặp×arm nhưng chỉ 61 request vật lý cho 128 ô ở hai vế. URL minh họa trong stress không được model chấm nên LLM và +URL dùng chung phản hồi. Báo riêng đúng→sai hợp lệ, đúng→UNKNOWN ngữ nghĩa và đúng→lỗi kỹ thuật. Chưa chấm tuân chỉ dẫn thì ASR phải N/A; không suy từ không có flip hợp lệ rằng chống injection thành công.

[Kết quả audit trước sửa runtime](../artifacts/evaluations/evaluation_audit_20261116/README.md).

### Sửa che dữ liệu và metadata sau audit

`app/services/url/approved_metadata.py` ghép score cục bộ với URL còn nhìn thấy trong bản được duyệt. Chỉ coi hoa/thường của scheme/hostname và IDNA theo policy authority là tương đương; giữ nguyên việc có scheme, cách viết port, path, query và fragment. Không phục dựng URL defang, ký tự ẩn hoặc authority cần NFKC. Nhiều URL gốc khác nhau bị gộp sau che dữ liệu, hoặc các dòng metadata mâu thuẫn, sẽ không được đưa vào context. URL gửi AI luôn dùng đúng cách viết trong bản đã duyệt, không dùng URL gốc có giá trị riêng tư. Ghép metadata không thay score, đặc trưng hoặc ngưỡng model.

Quy tắc OTP giữ scheme/domain và từ tiếng Việt đầy đủ, thay vì nhận nhầm tiền tố ASCII làm mã. Thông tin đăng nhập trong URL được che bằng userinfo `***@`, giữ hostname và không làm hỏng URL khi che lại. Kiểm regression bao gồm che mã thật, dữ liệu người dùng thêm sau preview, URL bị xóa, collision sau che và nội dung hướng dẫn có phủ định. Che theo quy tắc vẫn có giới hạn; người dùng cần xem lại nội dung gửi.

Lượt sau sửa dùng nguyên bộ 16 ca của audit trước và chạy model URL thật; response AI và retrieval vẫn là fixture. Manifest mới khóa toàn bộ source app/static, cấu hình runtime, model/preprocessing và đầu ra. Bảng 80 SMS chỉ kiểm intake/metadata trên dev đã biết, không chạy lại LLM hoặc tạo Accuracy/F1. [Minh chứng sau sửa](../artifacts/evaluations/privacy_metadata_fix_20261116/README.md).

Hai journal lịch sử 212 và 199 request khóa phiên bản privacy/client cũ. Sau thay source, phải chạy `verify` từ source snapshot hoặc checkout đúng checkpoint; xem [tái lập lịch sử](development.md#tai-lap-lich-su). Không sửa hash cũ để chấp nhận source mới.

## Rà trích xuất URL trong văn bản ngày 17/11

Candidate/focused dùng intake 2.2: miền trần trong văn bản cần hậu tố thuộc bản IANA root đã khóa. Chuỗi chưa đủ căn cứ được xuất riêng ở `unscored_candidates`, không chấm model và không đưa vào danh sách URL lỗi. URL tường minh `http(s)://`, `www.` và tab nhập URL riêng vẫn theo chính sách cú pháp hiện có. Đây là tín hiệu trích xuất, không phải kiểm DNS, đăng ký tên miền hoặc uy tín. Bản stable giữ extractor cũ.

Tham chiếu có 1.436 TLD, phiên bản `2026111600`, tải từ [IANA](https://data.iana.org/TLD/tlds-alpha-by-domain.txt); file nằm trong `app/services/url/resources/` và được kiểm SHA-256 khi nạp. Request không tải danh sách hay mở URL. Miền riêng, miền đặc biệt và TLD mới hơn snapshot có thể cần nhập riêng ở tab URL. Quy trình cập nhật thủ công nằm trong [resource README](../app/services/url/resources/README.md).

Ưu tiên giữ token có authority hợp lệ nguyên vẹn trước khi tách dấu phân cách rõ như `|`, ngoặc vuông/ngoặc nhọn và mũi tên. Không cắt tùy ý tiền tố Unicode, không sửa authority tường minh sai cú pháp, không thay path/query hợp lệ để cứu mẫu đã xem. Mã metadata kiểm ranh giới literal để tránh regex lấy tiền tố ASCII rồi phục hồi authority có ký tự ẩn. Chuỗi trần mơ hồ không chiếm giới hạn năm URL, kể cả ở bước tạo metadata.

`data/evaluation/url_intake_boundary_v1.jsonl` gồm 32 ca do trợ lý soạn cho chính sách này. Các ca là regression phát triển, không phải benchmark độc lập hoặc nhãn phishing. Runner `evaluation.url.intake_audit` đối chiếu kết quả intake cũ đúng hash và mã hiện tại; lưu từng ca, thay đổi trên đúng 80 SMS dev đã biết, source/reference/input hashes và cả lỗi. Kết quả cũ không bị sửa; 120 SMS reserve không được suy luận. Rà ngữ cảnh 10 SMS khác intake là nhận định AI về trích URL, có phiếu người còn trống, không tạo nhãn phishing mới.

TLD hợp lệ vẫn có thể trùng viết tắt hoặc tên tệp. Bộ ca kiểm hợp đồng đạt không chứng minh Precision/Recall trích xuất ngoài thực tế; thay đổi số URL/metadata càng không phải thay đổi F1 phishing. [Đầu ra và giới hạn](../artifacts/evaluations/url_intake_audit_20261117/README.md).

## Đối chứng điểm URL và kiểm tra lại cảnh báo ngày 18/11

`evaluation.messages.url_score_control` khóa đúng 80 SMS dev tuần 4 và reference AI có sẵn (4 dương, 54 âm, 22 UNKNOWN). Ba arm dùng cùng core prompt/schema/model/thông số/cap 2.048 token; chỉ metadata URL thay đổi: không cấp, cấp thật, hoặc hoán đổi cả bộ score/risk/ngưỡng từ một URL khác. Giữ URL/ID của mẫu nhận. Phép hoán đổi có seed cố định trước suy luận, không dùng nhãn hay score để chọn donor. Arm hoán đổi là đối chứng cố ý đưa bằng chứng sai, không dùng trong app.

Intake hiện có metadata ở 33 SMS: 22 âm và 11 UNKNOWN theo reference AI, **không có dương**. Lượt này đo độ nhạy với metadata và thay đổi báo nhầm; không thể chứng minh URL tăng Recall phishing. Các payload giống hệt nhau dùng chung phản hồi: 240 ô logic, 146 request vật lý. Báo riêng 58 nhãn nhị phân, 22 UNKNOWN, nhóm có metadata và các chuyển đổi cặp; phân biệt cảnh báo sai thành LOW với thành UNKNOWN/lỗi. Các kết quả trên nhãn AI hành vi không phải độ chính xác phishing toàn thông điệp.

Mỗi payload khác nhau chỉ có một phản hồi; temperature 0,1 không bảo đảm tất định và chưa có đối chứng lặp để ước lượng dao động sinh. Hoán đổi giữ nguyên mức risk ở 17/33 URL dù mọi score đều đổi. Vì vậy chênh lệch nhỏ không tự chứng minh phụ thuộc sai vào score; bảng cặp là chẩn đoán, không phải bằng chứng nhân quả độc lập.

`evaluation.messages.verifier_study` chuẩn bị lượt riêng sau khi lượt đối chứng đã chốt. Chỉ cảnh báo HIGH/WARNING hợp lệ được xét lại; verifier chỉ thấy text đã duyệt và schema, không thấy điểm URL, kết luận/lý do lượt đầu, arm hoặc nhãn tham chiếu. Cùng text trong nhiều arm dùng chung phản hồi. `ordinary_content` chuyển bản chiếu thử nghiệm về LOW; `supported_alarm` giữ mức; thiếu thông tin hoặc lỗi giữ cảnh báo và yêu cầu review. Mọi request/response ban đầu vẫn nguyên trạng. Báo cả FP→LOW, TP→LOW, bốn ca dương và lỗi, không chỉ tỷ lệ trên nhóm được chọn. Cùng nhà cung cấp chấm lần hai không tạo nhãn độc lập; quote tồn tại trong text không chứng minh kết luận ngữ nghĩa đúng.

Hai giai đoạn dùng một worker, cách thời điểm bắt đầu tối thiểu bốn giây, timeout 45 giây; pilot lần lượt 12 và tối đa bốn request. Chỉ xem trạng thái kỹ thuật để quyết định tiếp tục những request chưa gửi, không thay prompt/tham số theo dự đoán pilot. Dừng khi gặp HTTP fatal (gồm 429), ba lỗi truyền liên tiếp hoặc tổng token đã ghi đạt 300.000; không retry/sửa JSON. Đây là giới hạn token quan sát, không phải trần tiền: thiếu usage và request đang chạy có thể làm vượt phần quan sát. Không chạy 120 reserve, tạo nhãn gold hoặc tự đưa verifier vào app.

Lượt thật dừng sau 139/146 yêu cầu vì ba lỗi kết nối liên tiếp. Sau kiểm DNS/TLS, đã đăng ký amendment và lượt bổ sung riêng cho đúng bảy key chưa từng gửi; dùng cơ chế `evaluation.common.continuation`, giữ timeout/thông số và cả ba lỗi ban đầu. Run bị dừng giữ nguyên. `combined` là bản gộp có provenance, không phải lượt sạch mới hoặc thực thi liên tục. Không dùng cơ chế này vượt HTTP 429/quyền/hạn mức và không chạy lại key lỗi. Verifier nhận bản gộp đã kiểm hash, giữ các lỗi lượt đầu ngoài gate.

Ở đây “không URL” trong tên arm nghĩa là không thêm **metadata model URL**; LLM vẫn đọc nguyên URL trong text. UNKNOWN/lỗi ở mẫu âm không được tính là TN hoặc FP, nên làm giảm coverage/accuracy nhưng có thể không đổi F1. Mẫu dương UNKNOWN/lỗi vẫn làm giảm Recall và được tính là bỏ sót trong F1. Công thức là `2TP / (2TP + FP + FN + unknown_positive)`; báo coverage và lỗi cùng F1 để tránh hiểu nhầm.

```bash
.venv/bin/python -B -m evaluation.messages.url_score_control prepare --out NEW_CONTROL
.venv/bin/python -B -m evaluation.messages.url_score_control run --out NEW_CONTROL
.venv/bin/python -B -m evaluation.messages.url_score_control run --out NEW_CONTROL --live --limit 12
# Chỉ sau khi kiểm pilot kỹ thuật; chạy tiếp những key chưa từng gửi:
.venv/bin/python -B -m evaluation.messages.url_score_control run --out NEW_CONTROL --live
.venv/bin/python -B -m evaluation.messages.url_score_control report --out NEW_CONTROL
.venv/bin/python -B -m evaluation.messages.verifier_study prepare --control-run NEW_CONTROL --out NEW_VERIFIER
# Chạy pilot với metadata.pilot_unique_requests của registration, rồi tiếp phần chưa gửi.
.venv/bin/python -B -m evaluation.messages.verifier_study run --out NEW_VERIFIER --live --limit 4
.venv/bin/python -B -m evaluation.messages.verifier_study run --out NEW_VERIFIER --live
.venv/bin/python -B -m evaluation.messages.verifier_study report --out NEW_VERIFIER
```

Nếu số request verifier dưới bốn, dùng đúng cỡ pilot đã đăng ký; không có cảnh báo thì không cần API. Source snapshot, protocol, nhật ký và bảng từng mẫu tại [lượt 18/11](../artifacts/evaluations/url_score_control_20261118/README.md). Cần mã đúng snapshot khi kiểm lại source hash; không sửa registration cũ để chấp nhận mã mới.
