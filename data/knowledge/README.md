# Kho tài liệu tiếng Việt cho RAG — bản đầu

**Cập nhật 28/10/2026:** đã bàn giao [corpus v2 gồm 37 nguồn](corpus_v2/README.md), thêm 12 tài liệu cho 8 nhóm kịch bản. [Kết quả 100 truy vấn BM25/E5/Hybrid](../../docs/evaluation/RAG_RETRIEVAL_V2.md). Ứng dụng mặc định vẫn dùng v1. Phần dưới ghi nguồn gốc và trạng thái bản v1.

Đã thu thập và rà soát **25 nguồn nội dung riêng biệt từ 11 đơn vị**, chốt ngày **26/10/2026**. Đầu vào ban đầu có 26 URL; một URL Microsoft trả về cùng nội dung với nguồn đã có nên được loại trùng. Tất cả nguồn được giữ trong corpus đã tải thành công bằng HTTPS, trích được nội dung và kiểm tra chủ đề. Robots.txt được kiểm tra trước khi thu thập.

Kho hiện là **các bản tóm lược biên tập có provenance**, không phải bản sao nguyên văn bài báo hoặc tài liệu nhà cung cấp. Mỗi bản có khoảng 80–100 từ theo cách đếm khoảng trắng, mã nguồn riêng, URL bài gốc, đơn vị công bố, nhóm chủ đề, ngày thu thập và hash. Phần `context_note` ghi giới hạn sử dụng và lưu ý của người biên tập, được tách khỏi `text` tóm lược nguồn.

## Thành phần

| Loại tài liệu | Số nguồn | Vai trò |
|---|---:|---|
| Cảnh báo thủ đoạn (`scam_warning`) | 15 | Giải thích hành vi mạo danh và dẫn dụ |
| Quy trình hợp lệ (`legitimate_workflow`) | 7 | Đối chiếu xác thực, thông báo và cập nhật thật |
| Xử lý sự cố (`incident_response`) | 2 | Hỗ trợ khi chuyển nhầm tiền hoặc tài khoản bị chiếm |
| Hướng dẫn kết hợp (`mixed_guidance`) | 1 | Nhận diện và báo cáo email giả mạo |

Nguồn gồm Bộ Công an, Công an tỉnh Tuyên Quang, Chống Lừa Đảo, các đơn vị thuộc ĐHQGHN, Vietnam Post, Vietcombank, BIDV, Google và Microsoft. Nội dung bao phủ giả danh công an/phạt nguội, VNeID, bảo hiểm, OTP, tuyển dụng, đầu tư, hoàn tiền, giao hàng, deepfake, email trường học, học bổng và khôi phục tài khoản.

Một số nhóm theo mã tài liệu:

- Mạo danh cơ quan và dữ liệu cá nhân: `VN-RAG-001`, `002`, `006`, `010`.
- Việc làm, tiền đầu tư và thu hồi tiền: `004`, `005`, `007`, `008`, `009`.
- Đơn hàng và giao nhận: `003`, `015`.
- Sinh viên, phụ huynh và học bổng: `012`, `013`, `014`, `025`.
- Bảo mật ngân hàng, OTP và sinh trắc học: `016`, `017`, `018`, `024`.
- Email, tài khoản và MFA: `019`, `020`, `021`, `022`, `023`.
- Giả hình ảnh/giọng nói: `011`.

Các nhóm có thể giao nhau. Đây là chủ đề tài liệu, không phải nhãn phishing/benign cho email hoặc URL của người dùng.

## Các tệp bàn giao

- [corpus_v1/documents.jsonl](corpus_v1/documents.jsonl): 25 bản tóm lược cùng metadata; đây là vị trí duy nhất chứa nội dung biên tập chính thức.
- [corpus_v1/sources.csv](corpus_v1/sources.csv): danh mục tiêu đề, đơn vị, chủ đề, URL và ngày; mở được bằng Excel.
- [source_catalog.json](source_catalog.json): danh sách URL đã chọn, điều kiện kiểm tra nguồn và tham chiếu tới ghi chú bằng `notes_ref`. Mã `VN-RAG-026` là ứng viên trùng `VN-RAG-023`, không được tính thành tài liệu mới.
- [corpus_v1/collection_report.json](corpus_v1/collection_report.json): số lượng, phân bố chủ đề, đơn vị và trạng thái thu thập.
- [corpus_v1/deferred_sources.jsonl](corpus_v1/deferred_sources.jsonl): ghi nhận URL bị loại do trùng nội dung.
- [corpus_v1/manifest.json](corpus_v1/manifest.json): hash nguồn cấu hình, công cụ và các tệp corpus; giữ riêng thông tin lần tải và lần chốt nội dung biên tập.
- [corpus_v1/validation.json](corpus_v1/validation.json): kiểm tra cấu trúc, ID, hash, sự nhất quán và tình trạng ngày công bố.

`html_sha256` là hash phản hồi nhận được; `source_text_sha256` là hash văn bản trích xuất trước khi tóm lược; `summary_sha256` là hash ghi chú được đưa vào corpus. Không phân phối lại toàn bộ HTML/bài viết. Quyền đối với tài liệu gốc thuộc bên công bố; các ghi chú không được trình bày như lời trích nguyên văn của họ.

## Ngày và giới hạn sử dụng

**14 nguồn xác minh được ngày công bố**, 11 nguồn để `published_at=null`. Không suy ngày công bố từ ngày thu thập, số trong URL, ngày xảy ra sự kiện, menu hoặc chân trang. `date_status` ghi cách lấy ngày; nguồn có sửa đổi metadata được lưu riêng ở `last_modified_at` khi thấy. Thời gian kỹ thuật là ISO 8601 UTC, ngày chốt dùng múi giờ Việt Nam.

Các hướng dẫn từ năm 2023–2024 được dùng cho mô tả thủ đoạn hoặc ví dụ quy trình, không dùng trực tiếp làm bảng phí, hotline, hạn mức, danh sách chi nhánh hay yêu cầu pháp lý hiện hành. Thông báo học bổng chỉ là ví dụ thông báo có nguồn để đối chiếu, không khẳng định còn nhận hồ sơ.

`review_status=assistant_curated` nghĩa là đã có kiểm tra nội dung/nguồn phục vụ dự án, chưa phải thẩm định độc lập của chuyên gia. Một số bài là thông báo hoặc cảnh báo được đơn vị đăng lại; số lượng URL không tương đương số sự kiện hay số nghiên cứu độc lập. Kho này cung cấp kiến thức về hành vi và hướng xử lý, không xác nhận danh tiếng thời gian thực của tên miền.

## Dùng cho bước RAG tiếp theo

Chỉ lập chỉ mục `text` cùng tiêu đề/chủ đề cần thiết. Đính kèm `id`, URL, đơn vị và ngày làm metadata để dẫn nguồn. Hiển thị nội dung truy xuất dưới nhãn **tóm lược từ nguồn**, không ghi là trích nguyên văn bài gốc. Giữ `context_note` để kiểm soát phạm vi sử dụng.

Cập nhật 27/10/2026: đã tạo chỉ mục E5-small gồm 25 đoạn, mỗi đoạn từ một nguồn; các tóm lược đều nằm trong ngân sách 300 token nên chưa cần cắt nhỏ. Corpus chốt giữ nguyên byte. Runtime và công cụ dựng ở [hướng dẫn RAG](../../docs/guides/RAG.md); model và chỉ mục đặt cục bộ, không commit. Khi nội dung thay đổi phải dựng và chọn ngưỡng lại; không dùng chỉ mục cũ với corpus mới.

Không đưa email người dùng, mẫu test PhishVN hoặc bộ 200 thông điệp đánh giá vào chỉ mục. Nếu xây tình huống dựa trên một cảnh báo trong kho, cần ghi nguồn gốc và tránh dùng bản gần như sao chép làm test độc lập. Những bài cảnh báo có nêu URL hoặc email độc hại không được dùng làm bằng chứng danh tiếng hiện tại chỉ vì chúng xuất hiện trong nguồn cũ.

## Tái thu thập và kiểm tra

Từ thư mục chứa `run.py`:

```bash
.venv/bin/python -m pip install -r requirements/rag-collection.txt
.venv/bin/python scripts/rag/validate_rag_corpus.py
.venv/bin/python -m pytest -q tests/test_rag_collection.py
```

Để tải lại, chọn thư mục snapshot mới nhằm giữ nguyên bản đã chốt:

```bash
.venv/bin/python scripts/rag/collect_rag_sources.py --out data/knowledge/corpus_refresh
```

Collector chỉ tải các URL trong danh mục đã duyệt và từ chối redirect ra ngoài danh sách host. Không đi theo các liên kết nghi vấn nằm trong bài, không tải ứng dụng hay tệp đính kèm và không gọi LLM. Khi nội dung gốc thay đổi, bản tóm lược cũ cần được rà soát lại; tải thành công và khớp chủ đề không tự chứng minh tóm lược vẫn đầy đủ hoặc chính xác.

## Nguồn đề xuất mở rộng

Ngày 28/10/2026 đã lập [12 nguồn ứng viên cho 8 nhóm kịch bản](proposals/rag_v2_sources.json), kèm [đề xuất tổ chức và đánh giá](../../docs/architecture/RAG_V2_PROPOSAL.md). Đây là danh mục tìm kiếm để biên tập/kiểm định tiếp, không phải corpus đã nhập chỉ mục. ID `CANDIDATE-*` không dùng làm nguồn dẫn trong ứng dụng. Ưu tiên Zalo QR, device code, email doanh nghiệp, điện lực, đặt vé/phòng; ghép cảnh báo với quy trình hợp lệ và hướng dẫn xử lý.

Đợt triển khai sau đề xuất đã thu thập đủ 12 nguồn; [bảng ánh xạ](corpus_v2/ingestion_map.json) nối ID ứng viên với `VN-RAG-101–112`. Danh mục đề xuất giữ nguyên như tài liệu lịch sử, trạng thái thực nghiệm mới xem ở corpus v2.
