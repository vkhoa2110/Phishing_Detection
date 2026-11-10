# Cài đặt RAG

## Thành phần

Embedding dùng `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`. Không fine-tune. Encoder và index chạy tại máy; nội dung không gửi tới dịch vụ embedding. Corpus v1 có 25 nguồn, v2 có 37 nguồn; [dữ liệu và nguồn gốc](../../data/knowledge/README.md).

## Chuẩn bị

Chạy từ root. Trên Linux CPU có thể cài Torch CPU trước:

```bash
.venv/bin/python -m pip install torch==2.9.1 --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements/rag.txt
.venv/bin/python scripts/rag/prepare_index.py --download
.venv/bin/python -m evaluation.rag.metrics
.venv/bin/python run.py
```

`--download` cho phép tải model revision cố định. Runtime chỉ dùng file local, `trust_remote_code=False`, safetensors và NumPy; kiểm hash trước khi nạp. Nếu đã có model/index/calibration hợp lệ, không cần chạy lại. Lệnh metrics chọn ngưỡng bằng dev rồi chấm truy vấn test; không dùng test đã xem để tối ưu ngưỡng.

Cấu hình mặc định trong `.env.example`:

```dotenv
RAG_MODEL_DIR=models/embeddings/multilingual-e5-small
RAG_INDEX_DIR=artifacts/rag/e5-small-v1
RAG_CORPUS=data/knowledge/corpus_v1/documents.jsonl
```

`prepare_index.py --corpus FILE --out NEW_INDEX` dựng index cho corpus khác. `evaluation.rag.metrics --index NEW_INDEX --corpus FILE --dev DEV --test TEST --out NEW_RESULT` phải dùng cùng bộ phiên bản. Chọn thư mục mới để tránh ghi đè snapshot đã chốt; sau đó đặt cấu hình khớp trong `.env`.

## Cơ chế truy xuất

Tóm lược chia tối đa 300 token, overlap 40 khi cần; không ghép hai nguồn. E5 thêm `passage: ` và `query: `, mean pooling có attention mask, chuẩn hóa L2, vector 384 chiều. Tìm cosine chính xác bằng NumPy, tối đa ba nguồn khác nhau. Ngưỡng từ dev; cosine không là xác suất phishing.

Corpus, encoder, index hoặc calibration sai hash sẽ trả unavailable. Không có nguồn đạt ngưỡng thì trả empty. Đầu vào URL đơn lẻ không dùng kho hướng dẫn để suy danh tiếng miền. Khi chưa dùng RAG, encoder không được tải vào RAM.

Stable có thể thêm tài liệu vào prompt phân loại; candidate chạy RAG sau verdict và không cho đổi kết luận. Mode free-text và span-selection phải đánh giá riêng; [luồng kiến trúc](../architecture.md).

## Cập nhật kho

```bash
.venv/bin/python scripts/rag/collect_rag_sources.py --out NEW_SNAPSHOT
.venv/bin/python scripts/rag/assemble_corpus.py --help
.venv/bin/python scripts/rag/validate_rag_corpus.py --help
```

Nguồn mới cần URL gốc, thời điểm, snapshot/hash và tóm lược có provenance; giữ cảnh báo, quy trình hợp lệ và hướng xử lý. Corpus thay đổi thì tạo snapshot/index/calibration mới. Không chèn đáp án test hoặc kết luận theo từng SMS vào corpus.

Trích dẫn trong app là trích từ tóm lược biên tập, không tự là lời trích nguyên văn bài gốc. ID/quote hợp lệ không chứng minh nguồn hỗ trợ đúng ngữ nghĩa. [Rubric đánh giá](../evaluation.md) và [kết quả/giới hạn](../results.md#rag).
