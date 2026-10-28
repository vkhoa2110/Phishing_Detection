# RAG v2: kho mở rộng và kiểm tra retrieval

Ngày chốt: 28/10/2026. **Đã thu thập 12/12 nguồn ứng viên, ghép với 25 nguồn cũ thành 37 tài liệu từ 19 đơn vị.** Ứng dụng vẫn dùng corpus/index v1; v2 được dựng, chọn ngưỡng và chạy thử riêng. Không gọi API LLM trong đợt này.

## Kho và nguồn đã bàn giao

- Corpus: [documents.jsonl](../../data/knowledge/corpus_v2/documents.jsonl); danh mục dễ mở: [sources.csv](../../data/knowledge/corpus_v2/sources.csv).
- Snapshot bổ sung: [collections/v2_additions_20261028](../../data/knowledge/collections/v2_additions_20261028/); có hash HTML/văn bản nguồn, robots, kết quả tải, công cụ và phiên bản gói. Chỉ phân phối các tóm lược tiếng Việt, không toàn bộ bài gốc.
- Phân bố: 20 cảnh báo, 11 quy trình hợp lệ, 2 xử lý sự cố và 4 hướng dẫn kết hợp. 22 nguồn có ngày công bố xác minh; 15 nguồn chưa xác minh được ngày. Ngày tải không thay ngày công bố.
- 25 tài liệu cũ được giữ nguyên từng trường. Mã mới `101–112` giữ riêng dải ID cũ, kể cả ứng viên `026` từng bị loại trùng.
- [source_review.json](../../data/knowledge/corpus_v2/source_review.json) ghi việc rà soát của trợ lý; chưa phải thẩm định độc lập. Metadata nguồn mới có scenario, entity, scope, vai trò và lưu ý thời gian; `valid_from` chỉ có khi nguồn nêu rõ.

| ID mới | Nhóm | Vai trò | Nguồn gốc | Ngày công bố |
|---|---|---|---|---|
| VN-RAG-101 | zalo_qr | mixed_guidance | [Zalo](https://help.zalo.me/huong-dan/chuyen-muc/bao-mat-va-rieng-tu/an-toan-hon-khi-quet-ma-qr-dang-nhap-tren-zalo/) | 2023-04-26 |
| VN-RAG-102 | device_code | scam_warning | [Microsoft](https://www.microsoft.com/en-us/security/blog/2026/04/06/ai-enabled-device-code-phishing-campaign-april-2026/) | 2026-04-06 |
| VN-RAG-103 | device_code | legitimate_workflow | [Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code) | Chưa xác minh |
| VN-RAG-104 | business_email_compromise | scam_warning | [Techcombank](https://techcombank.com/thong-tin/thong-bao/canh-giac-truoc-nhung-hanh-vi-lua-dao-qua-email-doanh-nghiep) | Chưa xác minh |
| VN-RAG-105 | travel_booking | scam_warning | [Cục Hàng không Việt Nam](https://caa.gov.vn/hoat-dong-nganh/canh-bao-hinh-thuc-lua-mua-ve-may-bay-gia-re-de-chiem-doat-tai-san-20240820085544856.htm) | 2024-08-20 |
| VN-RAG-106 | travel_booking | legitimate_workflow | [Vietnam Airlines](https://www.vietnamairlines.com/vn/vi/help-desk/common-topics/purchase-tickets-payment-VAT-invoice/online-payment-methods) | Chưa xác minh |
| VN-RAG-107 | electricity_service | scam_warning | [EVN](https://evn.com.vn/d/vi-VN/news/Khuyen-cao-nguoi-dan-canh-giac-truoc-chieu-tro-lua-dao-cai-dat-ung-dung-dien-luc-moi-60-134-500858) | 2024-12-31 |
| VN-RAG-108 | electricity_service | legitimate_workflow | [EVNSPC](https://cskh.evnspc.vn/TinTuc/TinTucChiTiet?LoaiTinBai=ALL&MaTinBai=2919) | 2026-06-18 |
| VN-RAG-109 | electricity_service | legitimate_workflow | [EVNSPC](https://cskh.evnspc.vn/ThanhToanTienDien/HuongDanThanhToan) | Chưa xác minh |
| VN-RAG-110 | online_coercion | mixed_guidance | [Bộ Công an](https://www.bocongan.gov.vn/bai-viet/canh-giac-thu-doan-bat-coc-online-gia-danh-cong-an-co-lap-sinh-vien-de-chiem-doat-tien-1791168262) | 2026-10-05 |
| VN-RAG-111 | image_based_extortion | mixed_guidance | [Bộ Công an](https://www.bocongan.gov.vn/bai-viet/canh-giac-voi-thu-doan-ghep-anh-tong-tien-tren-khong-gian-mang-1791190146) | 2026-10-05 |
| VN-RAG-112 | recovery_refund_scam | scam_warning | [Công an tỉnh Khánh Hòa](https://congan.khanhhoa.gov.vn/vi/canh-bao-thu-doan-lua-dao-gia-danh-ho-tro-lay-lai-tien-bi-treo-hoan-tien-bi-loi) | 2025-05-23 |

EVN là trường hợp đối chứng thời gian: cảnh báo ngày 31/12/2024 nói về app giả và bối cảnh năm 2024; thông báo EVNSPC ngày 18/06/2026 ghi vận hành thử ứng dụng dùng chung từ 15/06/2026, đồng thời duy trì ứng dụng cũ trong giai đoạn đó. Không suy diễn trạng thái triển khai cuối cùng hoặc một link cài đặt cá nhân từ các bài này.

Lần tải đầu có 7 nguồn đạt, 5 nguồn bị hoãn vì HTTP 429, chọn sai tiêu đề, thiếu nội dung FAQ hoặc metadata múi giờ lỗi. Đã sửa bộ trích xuất theo selector đã xem và thử lại có kiểm tra robots; snapshot cuối đủ 12 nguồn, không nguồn bị hoãn. Toàn bộ văn bản dùng để rà soát chỉ nằm ở `data/raw/` cục bộ.

## Tập kiểm tra và quy tắc chọn ngưỡng

100 truy vấn mới: **dev 60 = 40 có nguồn + 20 không có nguồn; test 40 = 24 + 16**. Bao gồm kịch bản mới, quy trình thật, không dấu, nhầm thực thể, sai phạm vi thời gian, xác minh cá nhân vượt khả năng kho và ngoài miền.

Đây là **stress test retrieval do trợ lý biên soạn**, không phải tin nhắn thực hoặc gold do con người gán nhãn. Dev/test khác câu chữ nhưng chia sẻ chủ đề và một số ý kiến thức; không phải chia độc lập theo chiến dịch. Các nguồn được đánh dấu hỗ trợ ý đích, kèm đoạn trích khớp tóm lược để rà soát; kiểm tra trích dẫn chỉ chứng minh khớp chuỗi, không tự chứng minh diễn giải đúng. Relevance chưa được gán vét cạn cho mọi tài liệu: nguồn ngoài nhãn có thể vẫn chứa bối cảnh hữu ích.

Với truy vấn không có nguồn: nhãn rỗng nghĩa là kho không hỗ trợ **kết luận cụ thể về dịch vụ/thời điểm/cá nhân được hỏi**, dù có thể có tài liệu liên quan chủ đề. Không đồng nghĩa tin nhắn an toàn; một tài liệu nền được trả về chưa chứng minh LLM sẽ suy diễn sai. Vì thế không dùng tỷ lệ này như tỷ lệ cảnh báo nhầm của ứng dụng.

Dữ liệu được chốt trước lượt chạy chính; [manifest truy vấn](../../data/evaluation/rag_retrieval_v2_manifest.json) giữ hash, hạn chế và quy tắc đánh giá. Bản thử đầu dùng dải ID tạm; đã lưu nguyên inputs cạnh kết quả, chỉ đổi ID sang dải dành riêng trước lượt chốt. Biên bản `id_reservation_verification.json` xác nhận 300 ranking/nhãn tương ứng không đổi nội dung, điểm số hay ngưỡng.

Ba phương pháp cố định: BM25 k1=1.2, b=0.75; E5-small cùng revision hiện có; Hybrid RRF k=60. Cùng 37 đoạn, chỉ dùng text, top-3 và một đoạn mỗi tài liệu. Chọn ngưỡng trên dev để tối đa trung bình hit@3 và từ chối không nguồn, với ràng buộc hit@3 dev ≥90%; hòa thì ưu tiên precision theo nhãn rồi ngưỡng cao hơn. Không sửa nhãn hoặc ngưỡng sau khi xem lỗi test.

## Kết quả test sau lọc ngưỡng

| Phương pháp | Có nguồn đúng trong top-3 | Từ chối đúng khi thiếu nguồn | Vẫn trả khi thiếu nguồn | Precision theo tập nguồn đã gán nhãn | Ngưỡng dev |
|---|---:|---:|---:|---:|---:|
| bm25 | 22/24 (91.67%) | 4/16 (25.00%) | 12/16 | 25.00% | 7.608979 |
| e5 | 21/24 (87.50%) | 10/16 (62.50%) | 6/16 | 43.75% | 0.860279 |
| hybrid_rrf | 20/24 (83.33%) | 4/16 (25.00%) | 12/16 | 57.14% | 0.032522 |

Không lọc ngưỡng: cả ba đạt 23/24 hit@3 và đều trả tài liệu ở 16/16 câu không được hỗ trợ. Chỉ tăng số nguồn trả về không giải quyết việc thiếu căn cứ. Precision trong bảng là phép đếm theo các nguồn đã gán nhãn, có thể đánh giá thấp tài liệu hữu ích chưa được gán; chưa phải kết luận mọi tài liệu ngoài nhãn đều sai.

Không so trực tiếp tỷ lệ này với bộ 12 câu cũ để suy ra chất lượng tăng/giảm: cả corpus và tập kiểm tra đã thay đổi. Kết quả cũng không phải Precision/Recall/F1 phát hiện lừa đảo.

### Các lỗi đáng chú ý của E5

| Case | Nội dung | Kết quả |
|---|---|---|
| RAG-V2-TEST-003 | Máy in chỉ hiện mã người dùng Microsoft, tôi tự mở trình duyệt trên laptop để cấp truy cập cho máy in của mình. | Bỏ sót nguồn đã gán nhãn: VN-RAG-103 |
| RAG-V2-TEST-015 | Google yeu cau xac minh sau khi toi tu dang nhap, khac voi nguoi la xin gui ma ra sao | Bỏ sót nguồn đã gán nhãn: VN-RAG-020 |
| RAG-V2-TEST-024 | anh nhay cam bi ghep, doi tuong doa gui cho dong nghiep neu toi khong tra tien | Bỏ sót nguồn đã gán nhãn: VN-RAG-111 |
| RAG-V2-TEST-025 | Techcombank có sử dụng đúng Smart OTP theo thông báo BIDV không? | Trả VN-RAG-017, VN-RAG-018 dù không hỗ trợ ý đích |
| RAG-V2-TEST-027 | Công ty cấp nước miền Nam có phải đang triển khai chính app EVN CSKH không? | Trả VN-RAG-108 dù không hỗ trợ ý đích |
| RAG-V2-TEST-029 | Ứng dụng EVNSPC cũ chắc chắn đã ngừng vào tháng 9/2026 đúng không? | Trả VN-RAG-108, VN-RAG-107 dù không hỗ trợ ý đích |
| RAG-V2-TEST-030 | EVN CSKH đã hoàn tất triển khai cuối cùng toàn quốc trước 28/10/2026 chưa? | Trả VN-RAG-108 dù không hỗ trợ ý đích |
| RAG-V2-TEST-031 | Học bổng Goertek 2025 có cùng điều kiện với thông báo 2027 không? | Trả VN-RAG-025 dù không hỗ trợ ý đích |
| RAG-V2-TEST-034 | Có thể xác thực người đang gọi video là công an thật bằng đoạn văn này không? | Trả VN-RAG-111 dù không hỗ trợ ý đích |

Hai câu không dấu trong test đều bị E5/BM25 bỏ sót sau lọc; mẫu rất nhỏ, chưa thể ước lượng hiệu quả trên mọi tin không dấu. E5 còn bỏ sót luồng đăng nhập máy in hợp lệ. Hybrid có precision theo nhãn cao hơn nhưng hit thấp hơn E5 và trả nguồn ở nhiều câu không được hỗ trợ hơn. Chưa có cơ sở thay E5 bằng Hybrid.

## Quyết định và việc tiếp theo

**Giữ v2 ở chế độ thử nghiệm; chưa đổi mặc định ứng dụng.** Chỉ mục v2 có calibration E5 riêng, ngưỡng 0.860279, top-3; v1 giữ nguyên ngưỡng 0.849416. Đã kiểm tra `RAGService` có thể mở v2 và truy xuất tài liệu Zalo mới, không gọi LLM.

Ưu tiên tiếp theo: thẩm định relevance bằng người và gán đầy đủ các nguồn cùng hỗ trợ; thử chuẩn hóa/truy vấn phụ cho tiếng Việt không dấu; xét thực thể và phạm vi ngày khi diễn giải hoặc xếp hạng, đồng thời cho phép từ chối kết luận. Không dùng tài liệu cảnh báo cũ để khẳng định quy trình hiện tại. Mọi thử nghiệm phát sinh từ phân tích test này phải chọn tham số bằng dev mới; cần test mới trước khi gọi đó là cải thiện độc lập.

200 SMS bên ngoài vẫn chờ hai người gán nhãn; chưa tạo gold hay báo F1 trên tập này. Sau review, mới so sánh LLM / LLM+URL / LLM+RAG / LLM+URL+RAG và chấm giải thích. Không thêm SMS, nhãn hoặc đáp án test vào corpus.

## Kiểm chứng và chạy lại

Đã chạy **123 test tự động đạt**, có một cảnh báo deprecation của Starlette/httpx. Verifier độc lập đối chiếu hash đầu vào, ID nguồn, phép đếm và tối ưu ngưỡng chỉ bằng dev. Đây là kiểm chứng số học, không phải xác nhận ngữ nghĩa nhãn. Model URL, corpus/index/calibration v1, hai phiếu SMS và các kết quả LLM cũ giữ nguyên.

Kết quả cục bộ:

- `artifacts/rag-evaluation/retrieval_comparison_v2_r1/`: report, predictions, summary, calibration, test_slices, verification và kiểm tra runtime.
- `artifacts/rag/e5-small-v2-r1/`: 37 embeddings/đoạn và calibration E5.
- `artifacts/rag-evaluation/e5-small-v2-r1/`: kết quả hiệu chỉnh E5 dành cho runtime.

Dựng lại với thư mục đầu ra mới:

```bash
.venv/bin/python scripts/rag/prepare_index.py --corpus data/knowledge/corpus_v2/documents.jsonl --out artifacts/rag/e5-small-v2-rebuild
.venv/bin/python -m evaluation.retrieval_comparison --corpus data/knowledge/corpus_v2/documents.jsonl --index artifacts/rag/e5-small-v2-rebuild --dev data/evaluation/rag_retrieval_dev_v2.jsonl --test data/evaluation/rag_retrieval_test_v2.jsonl --out artifacts/rag-evaluation/retrieval-v2-rebuild
.venv/bin/python -m evaluation.retrieval --corpus data/knowledge/corpus_v2/documents.jsonl --index artifacts/rag/e5-small-v2-rebuild --dev data/evaluation/rag_retrieval_dev_v2.jsonl --test data/evaluation/rag_retrieval_test_v2.jsonl --out artifacts/rag-evaluation/e5-v2-rebuild
```

Để chạy riêng ứng dụng với v2 ở một phiên thử nghiệm, đặt `RAG_CORPUS=data/knowledge/corpus_v2/documents.jsonl` và `RAG_INDEX_DIR=artifacts/rag/e5-small-v2-r1` trước khi khởi động. Không trộn corpus v2 với chỉ mục/ngưỡng v1.
