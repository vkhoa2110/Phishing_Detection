# RAG v1 — E5-small cục bộ

Ứng dụng truy xuất tóm lược tiếng Việt từ kho 25 nguồn bằng `intfloat/multilingual-e5-small`. Model revision ghim tại `614241f622f53c4eeff9890bdc4f31cfecc418b3`; không fine-tune. Model và chỉ mục nằm trên máy, không có dịch vụ embedding trả phí và không gửi nội dung người dùng tới Hugging Face.

## Cài đặt và chuẩn bị

Chạy từ Git root bằng Python 3.11/3.12. Linux CPU dùng lệnh sau trước khi cài profile RAG để tránh kéo gói CUDA:

```bash
.venv/bin/python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements/rag.txt
.venv/bin/python scripts/rag/prepare_index.py --download
.venv/bin/python -m evaluation.retrieval
.venv/bin/python run.py
```

`--download` là bước duy nhất cho phép tải model công khai. Các tệp cần thiết (trong đó có safetensors) được ghim revision và ghi SHA-256 vào `models/embeddings/multilingual-e5-small/phishlens_model.json`. Runtime chỉ đọc tệp cục bộ với `local_files_only=True`, `trust_remote_code=False` và không dùng pickle để tải trọng số/chỉ mục.

Chỉ mục nằm ở `artifacts/rag/e5-small-v1/`: `chunks.jsonl`, `embeddings.npy`, `manifest.json`, sau chọn ngưỡng có thêm `calibration.json`. Kết quả kiểm tra nằm ở `artifacts/rag-evaluation/e5-small-v1/`. Những thư mục này được Git bỏ qua; tài liệu báo cáo học phần cũng tiếp tục chỉ giữ cục bộ.

Các biến tùy chọn: `RAG_MODEL_DIR`, `RAG_INDEX_DIR`, `RAG_CORPUS`. Nếu thay đường dẫn khi chuẩn bị, cấu hình cùng vị trí trong `.env`. Để tạo lại, chọn thư mục mới qua `--out`/`--index`, không ghi đè snapshot đang dùng. Không cần tải model lần nữa nếu thư mục model đã có và hash hợp lệ.

Lượt so sánh cũ ở 4.096 token đã có bốn phản hồi RAG bị cắt. Lượt diagnostic v2 dùng 8.192 token và timeout 90 giây, 24/24 phản hồi hợp lệ trên sáu mẫu đã biết; không bảo đảm ngân sách này đủ cho mọi đầu vào. Chọn ngân sách trên dev theo tỷ lệ lỗi/token/latency và ghi nhận giới hạn thật. `.env.example` gợi ý 8.192 token; timeout ứng dụng mặc định 45 giây có thể điều chỉnh có kiểm soát. Các số đo diagnostic không tự đại diện cấu hình vận hành khác.

## Cách hoạt động

1. Kiểm tra hash corpus, model và chỉ mục. Corpus thay đổi thì từ chối dùng index cũ.
2. Tokenize tóm lược; giữ nguyên khi ngắn, chia tối đa 300 token/đoạn với overlap 40 khi cần. Không ghép hai nguồn. Bản corpus hiện tại tạo 25 đoạn.
3. Thêm `passage: ` cho tài liệu, `query: ` cho bản nội dung đã che. Mean pooling có attention mask và chuẩn hóa L2; vector 384 chiều. Không cắt ngầm đầu vào quá 512 token; truy vấn dài cũng được chia cửa sổ.
4. Tìm kiếm cosine chính xác bằng NumPy, tối đa ba tài liệu khác nhau. Với quy mô 25 đoạn, chưa cần FAISS hoặc server vector. Nhiều cửa sổ truy vấn lấy điểm lớn nhất; điểm tương tự không phải xác suất đúng hoặc xác suất phishing.
5. Chọn ngưỡng bằng tập dev, lọc nguồn dưới ngưỡng. Không có nguồn thì trả `empty` và dùng prompt baseline. Lỗi/thiếu index trả `unavailable`; không bịa nguồn.
6. Chỉ khi người dùng bật LLM và đồng ý mới gọi FPT. Khi bật RAG, các tóm lược và metadata công khai được bổ sung vào payload; truy xuất không đọc score hoặc kết luận ML. URL đã bị xóa khỏi bản gửi không được đưa trở lại qua metadata ML.

Chế độ URL riêng lẻ không dùng kho hướng dẫn để kết luận danh tiếng miền. Tìm thủ đoạn chung từ một URL trần dễ tạo căn cứ không liên quan, nên RAG trả rỗng với lý do rõ ràng. Không dùng RAG thì không tải encoder vào bộ nhớ; thiếu phụ thuộc RAG không chặn ứng dụng baseline.

Theo [model card E5](https://huggingface.co/intfloat/multilingual-e5-small), các tiền tố vẫn cần cho ngôn ngữ ngoài tiếng Anh; giới hạn chuỗi là 512 token và điểm cosine nên được hiểu như xếp hạng. Cài đặt ở đây dùng trực tiếp Transformers/AutoModel theo cách pooling của model card, không cần SentenceTransformers để tạo cùng kiểu vector.

## Ngưỡng và phép kiểm tra bước đầu

Bộ `data/evaluation/rag_retrieval_dev_v1.jsonl` có 40 câu, gồm 26 câu có tài liệu liên quan và 14 câu ngoài phạm vi. Bộ `rag_retrieval_test_v1.jsonl` có 12 câu khác câu chữ, gồm 8 có nguồn và 4 ngoài phạm vi. Tất cả do trợ lý soạn theo chủ đề kho, chưa có nhãn độc lập của con người; chủ đề test vẫn chia sẻ với dev. Không coi đây là benchmark ngoài thực tế.

Chọn ngưỡng tối đa hóa trung bình hit@3 và tỷ lệ từ chối câu ngoài phạm vi, với ràng buộc hit@3 dev ≥ 90%; hòa thì chọn precision nguồn cao hơn, rồi ngưỡng cao hơn. Chỉ dùng dev, lưu `calibration.json` trước khi tính kết quả test. Ngưỡng hiện tại **0,849416**, top-k tối đa 3.

| Phép đo | Dev | Test |
|---|---:|---:|
| Tìm được ít nhất một nguồn đúng trong top 3 sau lọc | 24/26 | 7/8 |
| Trả rỗng đúng ở câu ngoài phạm vi | 14/14 | 4/4 |
| Tỷ lệ nguồn trả về khớp bộ ID đã gán | 46,30% | 41,18% |

Hit@3 chỉ cần một nguồn liên quan, nên không dùng nó để che việc các nguồn còn lại có thể không liên quan. ID gán nhãn cũng chưa được rà soát đầy đủ bởi người độc lập. Tỷ lệ từ chối đang đo với câu ngoài miền khá dễ; chưa đủ để khẳng định xử lý tốt những yêu cầu sát chủ đề nhưng không được nguồn hỗ trợ. Không tiếp tục chọn lại ngưỡng bằng test đã xem.

Đây là chỉ số retrieval, không phải Precision/Recall/F1 phát hiện phishing. Đã chạy [bốn cấu hình trên 100 thông điệp mô phỏng và đối chiếu BM25/E5/Hybrid](../evaluation/RAG_ABLATION.md). Chưa có bộ 100–200 thông điệp thực được gán nhãn độc lập hoặc chấm rubric con người; khớp quote không thay thế kiểm tra ngữ nghĩa.

## Nguồn dẫn và giới hạn

Ứng dụng text hiện dùng `message-2.0` khi không có tài liệu, `message-rag-2.0` khi có nguồn, tập trung vào hành vi trong thông điệp. Các prompt `baseline-1.0`/`rag-1.0` vẫn giữ cho thí nghiệm v1. Nhánh RAG thêm `knowledge_support` tách khỏi `evidence`:

- `evidence.quote` phải xuất hiện trong bản text người dùng đã xác nhận.
- `knowledge_support.document_id` phải thuộc tập được truy xuất; `source_quote` phải là chuỗi con nguyên văn trong text tóm lược của đúng nguồn.
- Mã nguồn bịa, quote sai hoặc nguồn trùng bị loại và ghi cảnh báo. URL bài gốc chỉ lấy từ corpus, không nhận URL do LLM sinh.
- Các nguồn được tìm thấy nhưng LLM không trích dùng được hiển thị rõ, không gọi chúng là nguồn đã hỗ trợ lập luận.

Kiểm tra ID/quote không phải kiểm tra entailment: LLM vẫn có thể lập luận sai từ trích đoạn có thật. UI ghi rõ cần đối chiếu và phân biệt tóm lược biên tập với lời trích bài gốc. Không dùng cảnh báo chung hoặc bài cũ làm bằng chứng một URL hiện tại lừa đảo.

Hệ thống không cấp công cụ mở URL/thực thi cho LLM và tách chỉ dẫn khỏi nội dung/tài liệu không tin cậy. Có test hợp đồng cho nguồn giả, quote sai, thiếu bằng chứng, retrieval rỗng/lỗi và phản hồi API bất thường. Đây là biện pháp giảm rủi ro, chưa phải chứng nhận chống prompt injection. Cần bổ sung gán nhãn relevance, ca ngoài phạm vi khó và rubric giải thích trước khi kết luận về chất lượng RAG.
