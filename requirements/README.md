# Phụ thuộc theo mục đích

Tất cả lệnh chạy từ thư mục gốc repository.

| Profile | Cài đặt | Nội dung |
|---|---|---|
| Ứng dụng | `python -m pip install -r requirements.txt` | Dẫn tới `base.txt`: FastAPI, suy luận ML, API LLM |
| Phát triển/kiểm thử | `python -m pip install -r requirements/dev.txt` | Base, pytest và phụ thuộc thu thập RAG |
| Đánh giá | `python -m pip install -r requirements/evaluation.txt` | Dev và Matplotlib |
| Chỉ thu thập nguồn | `python -m pip install -r requirements/rag-collection.txt` | HTTPX, BeautifulSoup, Trafilatura |

Các lệnh dùng cùng môi trường Python đã chọn; trên máy hiện tại là `.venv/bin/python`. Các phụ thuộc phục vụ biên soạn báo cáo được giữ riêng trên máy cục bộ.
