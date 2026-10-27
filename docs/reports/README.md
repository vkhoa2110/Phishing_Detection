# Báo cáo đã xuất

## Bản ngày 26/10/2026

- [Word để chỉnh sửa](2026-10-26/Bao_cao_Phishing_ML_LLM_RAG_Le_Van_Khoa.docx).
- [PDF để xem](2026-10-26/Bao_cao_Phishing_ML_LLM_RAG_Le_Van_Khoa.pdf).
- `2026-10-26/assets/`: hình tự vẽ và ảnh giao diện dùng trong báo cáo.
- `2026-10-26/evidence/`: số đo và kiểm tra bàn giao đi kèm báo cáo.

Bản đã xuất giữ nguyên byte và nội dung hiện trạng ngày 26/10. Các đường dẫn trong báo cáo, `GHI_CHU.txt` và evidence là đường dẫn lúc tạo; vị trí mới ở [PROJECT_STRUCTURE.md](../PROJECT_STRUCTURE.md#đối-chiếu-đường-dẫn-cũmới).

Mã dựng được tách sang `scripts/reporting/`. Để tạo bản làm việc mới:

Cần gói model cục bộ như hướng dẫn tại `models/README.md` để ghi hash cấu hình đầu vào của bản dựng.

```bash
.venv/bin/python -m pip install -r requirements/reporting.txt
.venv/bin/python scripts/reporting/build_report.py
```

Đầu ra tại `artifacts/report-builds/2026-10-26/`, không ghi đè bản công bố. Mở bản Word mới bằng Word/LibreOffice Writer để cập nhật mục lục và xuất PDF. `scripts/reporting/finalize_report.py` hỗ trợ tự động hóa qua Python hệ thống có UNO và LibreOffice Writer listener ở cổng cục bộ 20173; nhận đường dẫn thư mục bản dựng làm đối số.
