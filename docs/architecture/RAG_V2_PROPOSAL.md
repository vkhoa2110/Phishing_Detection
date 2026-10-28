# Đề xuất mở rộng RAG theo kịch bản và quy trình đối chứng

Triển khai sau đề xuất: đã thu thập 12 nguồn, dựng corpus 37 tài liệu và chạy 100 truy vấn. Xem [kết quả thực tế](../evaluation/RAG_RETRIEVAL_V2.md); nội dung dưới giữ vai trò bản đề xuất ban đầu.

Ngày rà soát: 28/10/2026. Đây là đề xuất và danh mục nguồn ứng viên, chưa phải corpus/chỉ mục đã được thu thập, biên tập và kiểm định. Nguồn được tìm qua tìm kiếm web/trang gốc; chưa có snapshot/hash hay quyền suy diễn rằng mọi ví dụ cùng chủ đề đều là lừa đảo.

## Kho hiện tại và khoảng thiếu

Corpus v1 có 25 tóm lược: 15 cảnh báo, 7 quy trình hợp lệ, 2 xử lý sự cố và 1 hướng dẫn kết hợp. Đã có deepfake, VNeID giả, đầu tư, tuyển cộng tác viên, lấy lại tiền, giao hàng và cảnh báo cho sinh viên. Ưu tiên bổ sung tài liệu chuyên biệt và đối chứng thay vì nhân bản nhiều tin cảnh báo tương tự. Nhiều chủ đề rộng đã xuất hiện trong bài tổng hợp; một đoạn tổng hợp chưa thay thế được kiến thức về quy trình của từng dịch vụ.

Danh mục máy đọc được: [rag_v2_sources.json](../../data/knowledge/proposals/rag_v2_sources.json). Các ID `CANDIDATE-*` không phải ID tài liệu đang được ứng dụng truy xuất.

## Các nhóm ưu tiên

| Nhóm | Trường hợp cần phân biệt | Nguồn chính |
|---|---|---|
| Chiếm Zalo bằng QR | Quét để bình chọn nhưng lại phê duyệt đăng nhập thiết bị khác; đối chiếu tự quét để đăng nhập máy của mình | [Zalo Help](https://help.zalo.me/huong-dan/chuyen-muc/bao-mat-va-rieng-tu/an-toan-hon-khi-quet-ma-qr-dang-nhap-tren-zalo/) |
| Lạm dụng device code | URL đăng nhập chính thức nhưng mã/yêu cầu do bên tấn công khởi tạo; đối chiếu đăng nhập thiết bị do chính người dùng khởi tạo | [Microsoft nghiên cứu 2026](https://www.microsoft.com/en-us/security/blog/2026/04/06/ai-enabled-device-code-phishing-campaign-april-2026/), [luồng hợp lệ](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code) |
| Email doanh nghiệp/BEC | Thư giao dịch bị giả mạo hoặc chiếm quyền, đổi tài khoản thụ hưởng; cũng cần ca thay đổi thông tin được xác minh độc lập | [Techcombank](https://techcombank.com/thong-tin/thong-bao/canh-giac-truoc-nhung-hanh-vi-lua-dao-qua-email-doanh-nghiep) |
| Đặt phòng/vé giả | Có mã giữ chỗ chưa chứng minh đã xuất vé/thanh toán; đối chiếu quy trình thanh toán trả sau hợp lệ | [Cục Hàng không](https://caa.gov.vn/hoat-dong-nganh/canh-bao-hinh-thuc-lua-mua-ve-may-bay-gia-re-de-chiem-doat-tai-san-20240820085544856.htm), [Vietnam Airlines](https://www.vietnamairlines.com/vn/vi/help-desk/common-topics/purchase-tickets-payment-VAT-invoice/online-payment-methods) |
| Giả điện lực | Yêu cầu cài ứng dụng từ người gọi/dọa cắt điện; đối chiếu việc ngành điện thực sự triển khai ứng dụng và quy trình thanh toán | [EVN cảnh báo](https://evn.com.vn/d/vi-VN/news/Khuyen-cao-nguoi-dan-canh-giac-truoc-chieu-tro-lua-dao-cai-dat-ung-dung-dien-luc-moi-60-134-500858), [EVNSPC thông báo 18/06/2026](https://cskh.evnspc.vn/TinTuc/TinTucChiTiet?LoaiTinBai=ALL&MaTinBai=2919), [hướng dẫn thanh toán](https://cskh.evnspc.vn/ThanhToanTienDien/HuongDanThanhToan) |
| Cô lập/tống tiền trực tuyến | Giả cơ quan chức năng, ép giữ bí mật/cắt liên lạc rồi gây sức ép tiền với gia đình; xem diễn biến hội thoại, không chỉ một câu | [Bộ Công an](https://www.bocongan.gov.vn/bai-viet/canh-giac-thu-doan-bat-coc-online-gia-danh-cong-an-co-lap-sinh-vien-de-chiem-doat-tien-1791168262) |
| Tống tiền bằng ảnh ghép | Đe dọa phát tán hình ảnh để ép tiền; phân biệt nội dung đe dọa với người bị hại đang báo cáo/xin hỗ trợ | [Bộ Công an](https://www.bocongan.gov.vn/bai-viet/canh-giac-voi-thu-doan-ghep-anh-tong-tien-tren-khong-gian-mang-1791190146) |
| Phí mở khóa/hoàn tiền/lấy lại tiền | Đã có nhóm recovery trong v1; mở rộng chuỗi yêu cầu nộp thêm để nhận lại tiền và đối chiếu xử lý giao dịch thật | [Công an Khánh Hòa](https://congan.khanhhoa.gov.vn/vi/canh-bao-thu-doan-lua-dao-gia-danh-ho-tro-lay-lai-tien-bi-treo-hoan-tien-bi-loi) |

Đây là các vấn đề để kiểm tra, không phải quy tắc tự gán nhãn. Đổi tài khoản nhận tiền, giữ chỗ chưa thanh toán, QR, OTP hay thiếu xác minh danh tính riêng lẻ chưa đủ kết luận. Ca thiếu dữ kiện phải có lựa chọn UNKNOWN. Ứng dụng hiện đọc văn bản, không giám định deepfake, giải mã QR từ ảnh hoặc xác minh nội dung cuộc gọi.

## Quy mô và nội dung đề xuất

Đích thử nghiệm nhỏ: **60–80 nguồn sau kiểm định**, triển khai trước một đợt khoảng 15–20 nguồn mới. Đây là mục tiêu thiết kế, không phải số nguồn đã thu thập. Ưu tiên nguồn chính thức của dịch vụ, cơ quan chức năng và tài liệu quy trình. Hạn chế các bài báo sao chép cùng một thông cáo.

Ba vai trò cần có: thủ đoạn/cảnh báo; quy trình hợp lệ/điều kiện áp dụng; xử lý sự cố/xác minh. Mỗi nhóm nên có cả tài liệu cảnh báo và tài liệu quy trình nếu tìm được. Không ép tỷ lệ vai trò trong kết quả truy xuất bằng cách đưa thêm nguồn không liên quan.

Mỗi đơn vị kiến thức cần nêu rõ: thực thể/dịch vụ, hành động đang được nói tới, điều kiện áp dụng, dấu hiệu có căn cứ, điều chưa thể kết luận, cách xác minh, nguồn và mục tham chiếu. Tóm lược phải ghi rõ là biên tập; quote khớp tóm lược chưa chứng minh claim được bài gốc hỗ trợ.

Metadata đề xuất: `scenario`, `entity`, `document_role`, `published_at` (null khi chưa xác minh), `retrieved_at`, `reviewed_at`, `valid_from` nếu được nguồn nêu, phạm vi địa lý/dịch vụ, và quan hệ cập nhật/thay thế tài liệu. Ngày tải không thay cho ngày hiệu lực. Ví dụ EVNSPC công bố vận hành thử nghiệm ứng dụng dùng chung từ 15/06/2026; không suy diễn từ một cảnh báo app giả cũ rằng mọi ứng dụng mới về sau đều giả.

Không thêm 200 SMS chờ review, nhãn gold, đáp án hoặc biến thể của tin nhắn test vào kho. Kho lưu kiến thức có nguồn, benchmark đo trên nội dung độc lập theo nhóm/chiến dịch.

## Truy xuất cần được đánh giá lại

Giữ E5-small làm mốc. Thử BM25 + E5 rồi xếp hạng lại trên dev mới, không mặc định Hybrid tốt hơn từ 12 câu test đã xem. Truy xuất theo hai góc: tài liệu thủ đoạn và quy trình hợp lệ; lọc thực thể/phạm vi khi đầu vào có căn cứ, cho phép không có nguồn phù hợp. Không suy diễn danh tính thật từ tên thương hiệu tự xưng.

Tạo relevance dev/test mới có câu gần chủ đề nhưng không được nguồn hỗ trợ, phiên bản cũ, thực thể khác, ca bình thường và câu ngoài miền. Gán nguồn hỗ trợ tới cấp đoạn/claim, báo precision từng nguồn và tỷ lệ trả rỗng đúng, không chỉ hit@3. Sau đổi corpus phải dựng chỉ mục và chọn ngưỡng lại trên dev; không giữ ngưỡng cosine cũ như một hằng số bảo đảm chất lượng.

## Làm tình huống khó hơn một cách hợp lệ

Với mỗi nhóm, chuẩn bị tin đáng ngờ, quy trình hợp lệ gần giống, trường hợp thiếu ngữ cảnh, và nội dung giảng dạy/báo cáo sự cố. Không coi nội dung do trợ lý viết là tin thực hoặc nhãn người kiểm chứng.

Đa dạng cách viết: tiếng Việt không dấu/viết tắt, lời văn lịch sự không đe dọa, không có từ OTP/mật khẩu, không URL, URL dịch vụ hợp lệ, và hội thoại nhiều bước. Khi cắt hội thoại ở từng thời điểm, nhãn chỉ dựa trên dữ kiện đã xuất hiện; không dùng kiến thức về bước lừa đảo xảy ra sau để gán nhãn sớm.

Với nội dung báo cáo sự cố, chốt trước mục tiêu nhãn: phân loại thông điệp đang yêu cầu hành động hay nguy cơ của sự cố được kể lại. Không gán người xin trợ giúp là kẻ lừa đảo hoặc tự coi sự cố an toàn chỉ vì họ đang kể lại. Đây là phần cần làm rõ trong hướng dẫn gán nhãn trước khi bổ sung loại ca đó.

## Chứng minh phần nào của RAG hữu ích

Ngoài bốn arm chính, chạy trên một tập dev chẩn đoán cố định:

| Đối chứng | Ý nghĩa |
|---|---|
| LLM + nguồn được truy xuất | Hệ thống RAG thực tế |
| LLM + nguồn không liên quan, độ dài tương đương | Kiểm tra tác động của việc thêm context và thiên kiến cảnh báo |
| LLM + nguồn liên quan do người đánh giá chọn | Chẩn đoán giới hạn của retrieval; không phải phương án triển khai hoặc kết quả benchmark chính |

Nếu nguồn chọn đúng giúp nhưng retrieval thực không giúp, ưu tiên retriever. Nếu chỉ dẫn nguồn tốt hơn nhưng F1 không tăng, ghi nhận lợi ích giải thích theo rubric. Nếu nguồn không liên quan làm đổi nhãn, xem lại cách LLM sử dụng tài liệu. Không hứa hoặc thiết kế nhãn chỉ để buộc RAG thắng LLM thuần.

Đợt ưu tiên đề xuất: **Zalo QR, device code, BEC, điện lực và đặt vé/phòng**, vì có nguồn chuyên biệt và nhiều quy trình hợp lệ để đối chiếu. Các nhóm cô lập/tống tiền bổ sung sau, với giới hạn rõ của đầu vào văn bản.
