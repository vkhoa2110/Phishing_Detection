# PhishLens Browser Extension — bản cục bộ 0.18.0

Extension Manifest V3 với bảng bên cạnh trang, sáng/tối và ba thẻ Đường dẫn / Tin nhắn / Hình ảnh, dùng với PhishLens đang chạy trên máy, không cần đăng nhập. Model URL, RAG và kết nối LLM nằm ở backend; extension không chứa API key và không tự đọc toàn trang.

## Mới ở 0.18: Gần đây, tiếp tục dùng khi chờ và bản in kết quả

- **Gần đây:** danh sách tối đa 40 lượt URL, nội dung, ảnh, email và hội thoại trong phiên. Lọc Tất cả / Đang chạy / Cần chú ý / Đã xong; mở lại kết quả hoặc về tab nguồn. Email và các lượt kiểm tra trong bảng dùng chung danh sách. Không gọi lại AI để xem, làm mới hoặc dọn danh sách.
- **Tiếp tục dùng · nhận kết quả sau:** khi AI đã nhận lượt kiểm tra, có thể rời màn hình chờ để mở kết quả khác hoặc nhập nội dung mới. Chỉ ngừng chờ ở giao diện, không hủy tác vụ trên máy chủ. Phần đã gửi được xóa khỏi ô nhập để tránh gửi lại ngoài ý muốn. Đóng/mở bảng vẫn giữ các mã lượt trong phiên.
- **Hàng chờ:** cùng một phiên extension/tài khoản xử lý lần lượt, tối đa ba lượt đang chạy/chờ. Lượt thứ hai chờ thay vì gặp lỗi xung đột với lượt trước. Có thể hủy lượt chưa bắt đầu ngay trong tiến trình hoặc Gần đây; không gửi nội dung tới AI và không trừ hạn mức AI cho lượt đã hủy trước khi xử lý. Các giới hạn người dùng/hệ thống và ngân sách provider vẫn áp dụng; không tự gọi lại khi có lỗi.
- **Kết luận dễ đối chiếu:** đưa hướng xử lý đầu tiên vào phần kết luận; giải thích ngay trường hợp nội dung LOW nhưng URL HIGH, nội dung HIGH nhưng URL LOW, hoặc chưa dùng/AI gặp lỗi. Giữ nguyên các verdict, điểm số và ngưỡng. Báo số URL đã chấm/tổng số có cả URL không hợp lệ.
- **In / lưu PDF:** dùng hộp thoại in của trình duyệt trên bảng hiện tại; bản in bỏ nút điều khiển, có kết luận, bằng chứng, danh sách URL, thời điểm và định danh AI/prompt nếu có. Không gọi AI thêm. In PDF không đồng nghĩa đã kiểm thử hộp thoại in native trên mọi hệ điều hành.
- Đóng tab nguồn không chặn đọc kết quả còn hạn. Đối chiếu/tô lại nguồn vẫn kiểm tra tab, document và snapshot; không tô dữ liệu của thư/hội thoại khác. Khi nguồn đã điều hướng, nút về tab không tự mở một URL cũ.
- Nhận diện email mới không tự chuyển khỏi Gần đây, Trợ lý hoặc Cài đặt. Lỗi kỹ thuật của AI được ghi rõ **AI chưa hoàn tất**, phân biệt với thiếu ngữ cảnh trong nội dung.

Danh sách chỉ lưu mã tác vụ, tham chiếu nguồn, thời gian, loại đầu vào, nhãn nền tảng cố định và trạng thái giới hạn trong `storage.session`; không lưu nội dung, tiêu đề email, URL trang nguồn, trích dẫn hoặc kết quả đầy đủ. Ghi đồng thời được tuần tự hóa để không mất lượt. Các kết nối tài khoản/khách được phân biệt bằng hash, không lưu token thêm vào index. Danh sách không thay thế lịch sử tài khoản; **Reload/cập nhật extension hoặc đóng trình duyệt sẽ xóa phiên**, và khởi động lại máy chủ làm mất kết quả RAM. Nút dọn chỉ xóa mục đã hoàn tất/lỗi/hết hạn, không dừng tác vụ đang chạy.

Tham chiếu trong danh sách có trần một giờ từ khi tạo để hỗ trợ hàng chờ; kết quả đầy đủ trên máy chủ vẫn hết hạn 15 phút sau hoàn tất. Việc một mã còn trong danh sách không bảo đảm kết quả còn tồn tại; giao diện báo hết hạn khi máy chủ không còn kết quả. Dọn danh sách ngăn mở lại tự động các mục đã xóa.

Focused/shadow dùng `message-core-1.2`, hội thoại dùng `conversation-core-1.1`: JSON schema và prompt công bố rõ giới hạn 240 ký tự cho mỗi trích dẫn và yêu cầu `missing_context=[]` khi không phải UNKNOWN. Giữ nguyên kiểm tra schema/quote và các ràng buộc phân loại; phản hồi không đạt vẫn là lỗi kỹ thuật. Chẩn đoán chỉ trả tên trường nằm trong allowlist. Thay đổi này chưa chứng minh cải thiện chất lượng phát hiện và không đổi các số liệu/prompt lịch sử thành kết quả của phiên bản mới. Cách biểu diễn giới hạn dựa trên [Pydantic Field constraints](https://docs.pydantic.dev/latest/concepts/fields/).

Thiết kế dựa trên [vòng đời service worker](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle), [storage.session và giới hạn truy cập](https://developer.chrome.com/docs/extensions/reference/api/storage#property-session) và [hướng dẫn thông báo trạng thái của W3C](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html). Không giữ worker sống bằng vòng lặp; chỉ theo dõi tác vụ khi bảng tương ứng đang hiển thị. Lượt đã xong không bị tải lại liên tục ở mỗi nhịp theo dõi.

Kiểm luồng mới: `.venv/bin/python scripts/evaluation/check_extension_activity_ui.py --out <thư-mục-mới>`. Dùng Chromium, hộp thư dựng, provider giả và xuất PDF thật bằng bộ in Chromium; không lấy dữ liệu hộp thư thật. API/hàng chờ có kiểm riêng trong `tests/api/test_extension_job_queue.py`, hợp đồng schema trong `tests/messages/test_core_schema_contract.py`.

**Cập nhật từ 0.17:** khởi động lại máy chủ để nạp hàng chờ/prompt, cập nhật ZIP/thư mục mới, Reload extension rồi F5 các tab đang dùng. `/api/extension/session` công bố `analysis_queue` để phân biệt backend đã cập nhật.

## Sửa ở 0.17.1: kết nối ngay từ nút kiểm tra email

Nút **Kiểm tra email này** tự tìm ứng dụng tại địa chỉ đã cấu hình, rồi cổng localhost 8001/8000 khi chưa có kết nối khách hoặc kết nối khách hết hạn. Không còn phải mở bảng PhishLens trước để khởi tạo kết nối. Bước tìm ứng dụng chỉ gửi yêu cầu trạng thái rỗng; nội dung vẫn theo chế độ duyệt/gửi đã chọn.

Nút **Thử lại kiểm tra email** thực sự thử lại thao tác sau khi mở ứng dụng, thay vì chỉ hỏi trạng thái một lượt chưa được tạo. Nếu lượt trước đã gửi và còn chạy, dùng lại lượt đó. Không tự bật lại kết nối đã tạm ngừng hoặc tự chuyển tài khoản hết hạn sang khách.

Cập nhật ZIP hoặc thư mục đã cài, **Reload** extension tại `brave://extensions` / `chrome://extensions`, rồi **F5 Gmail/Outlook** để thay nút cũ trong trang. Khởi động ứng dụng bằng `.venv/bin/python launch.py --profile focused --port 8001`.

Kiểm hồi quy: `.venv/bin/python scripts/evaluation/check_extension_mail_connection_ui.py --baseline <ZIP-0.17.0> --out <thư-mục-mới>`. Dùng Chromium, giao diện hộp thư dựng và provider giả; không đọc hộp thư thật hoặc gọi AI bên ngoài.

## Sửa ở 0.17: tải lịch sử Zalo và Messenger

Bản 0.16 có hai lỗi đã tái hiện: Zalo có thể chỉ lấy 15 tin rồi báo không tìm thấy vùng cuộn; Messenger có thể nhầm ID của hàng giao diện bị tái sử dụng thành ID tin nhắn, dẫn tới báo “Có tin bị sửa”. Bộ fixture trước chưa bao phủ hai cấu trúc này.

- **Zalo:** nhận đúng `messageViewScroll` là danh sách tin bên trong `messageView`, chọn viewport native `overflow:auto/scroll` của custom Scrollbars; không bỏ cuộc khi gặp nhiều lớp cuộn lồng nhau. Nhận bubble cũ/mới và sender theo marker của renderer công khai. Header Zalo nằm trước `article#chatView` được dùng để phát hiện đổi hội thoại.
- **Messenger:** không dùng DOM `id`/`data-id` chung làm ID tin. Tin không có ID riêng được ghép theo thứ tự chồng lấn giữa các đợt tải; không khử trùng toàn lịch sử chỉ theo chữ. Các câu giống nhau ở những đoạn khác nhau được giữ riêng khi phân biệt được vị trí. Vẫn báo hạn chế nếu toàn bộ chuỗi tin giống nhau không có ID.
- Timestamp, trạng thái đã đọc, avatar hoặc tên hiện/ẩn theo nhóm không bị xem là sửa nội dung. Khi một tin có ID ổn định cập nhật trong lúc tải, giữ bản mới nhất và báo số tin cập nhật. Sau khi khóa bản để duyệt, thay đổi nội dung của tin đang tải vẫn làm mất hiệu lực xác nhận.
- Hỗ trợ viewport cuộn ngược dùng `column-reverse`/`scrollTop` âm, chờ các đợt tải chậm và danh sách rỗng tạm thời. Không mở API riêng hoặc đọc store của nền tảng.
- Nếu chưa tải đủ, hiển thị rõ **đã lấy bao nhiêu/số yêu cầu**. Nếu chưa điều khiển được vùng cuộn, dành thời gian nhận diện lại và cho phép người dùng cuộn trong khung chat để tiếp tục gom tin. Mục **Thông tin tải hội thoại** có nút sao chép chẩn đoán chỉ chứa thông số cuộn, số lượng và trạng thái; không chứa tin nhắn, tên hoặc URL hội thoại.

Kiểm hồi quy cấu trúc bị bỏ sót: `scripts/evaluation/check_extension_history_recycling_ui.py --baseline <ZIP-0.16> --out <thư-mục-mới>`. Chạy baseline tái hiện đúng lỗi rồi đối chiếu code hiện tại với nhiều trang 15 tin, ID hàng tái sử dụng, metadata thay đổi, tin lặp, viewport ngược và tải chậm. Đây là thử nghiệm bằng DOM dựng trong Chromium; chưa xác minh toàn bộ trên tài khoản thật. Marker Zalo được đối chiếu từ [asset renderer công khai của Zalo](https://zalo-chat-static.zadn.vn/v1/lazy/2.21dd5856eb8f1d31f964.js); không dùng dữ liệu tài khoản.

**Cập nhật từ bản cũ:** Reload extension rồi **F5 cả tab Messenger/Zalo** để bỏ reader cũ đang nằm trong trang. Không cần khởi động lại backend nếu đã chạy bản 0.15 trở lên.

## Mới ở 0.16: nhận diện chat rộng hơn và cảnh báo yên lặng

Messenger/Facebook Tin nhắn nhận thêm danh sách không có nhãn, `role=log`, marker `messages_table`, grid lồng và danh sách cuộn có marker tin nhắn. Đợi tối đa hai giây khi khung chat mới đang tải. Không lấy danh sách liên hệ/tìm kiếm hoặc ô soạn; nếu có nhiều khung chat phù hợp ngang nhau thì yêu cầu giữ lại một khung. Đây là adapter DOM, chưa chứng nhận tương thích mọi đợt cập nhật giao diện hoặc kiểm thử tài khoản thật.

Phạm vi có nút **50 / 200 / 500 tin**, nhớ chế độ và số tin lần trước theo nền tảng. Chỉ lưu các tùy chọn này, không lưu tên cuộc trò chuyện/nội dung. Lỗi đọc hiện ngay trong phần chọn phạm vi để thử lại, không thêm banner ở đầu bảng.

**Tự kiểm URL** hoạt động độc lập với **Luôn hiện nút công cụ**. Mặc định không ghim nút trên trang; cấu hình nút nổi cũ được chuyển sang cách hiển thị yên lặng. Khi người dùng đã bật tự kiểm, chỉ URL HIGH có score ≥0,85 mới đủ điều kiện thông báo nền. Mốc này là quy tắc hiển thị để giảm gián đoạn, chưa được hiệu chỉnh thành xác suất hoặc chứng minh chất lượng phát hiện. Kiểm tra thủ công giữ ngưỡng/kết quả model hiện có.

Thông báo và nút tạm thời **tự ẩn sau tám giây**; nút × hoặc Esc đóng ngay. Khi rê chuột/đặt focus trong thông báo thì chờ người dùng đọc xong. Cùng hostname chỉ nhắc tối đa một lần trong 30 phút, kể cả tải lại hoặc chuyển tab. Dấu `!` nhỏ vẫn ở biểu tượng extension để mở lại. Bộ nhớ phiên giữ tối đa 100 hash hostname và thời điểm; không lưu địa chỉ hoặc nội dung trang cho chống lặp.

Địa chỉ giao diện ứng dụng chính xác như `drive.google.com/drive/…`, Gmail, Outlook Mail, luồng Messenger/Facebook Tin nhắn, Zalo và Telegram được bỏ qua ở lần chấm URL nền. Google root/search cũng được bỏ qua. Không suy ra nội dung/tệp/thư trong đó an toàn; URL ngoài và thao tác kiểm tra thủ công vẫn được chấm. Chỉ so exact hostname + route, không bỏ qua tên miền giả như `drive.google.com.attacker.example`. Model URL hiện có thể báo nhầm trên các địa chỉ hợp lệ; thay đổi này xử lý cách thông báo, không phải cải thiện đã đo của model.

Kiểm fixture: `scripts/evaluation/check_extension_quiet_chat_ui.py --out <thư-mục-mới>`. Dùng extension/backend thật, score URL giả và DOM Messenger mô phỏng; không đăng nhập tài khoản thật hoặc gọi provider.

Cập nhật: **Reload extension rồi F5 tab đang mở**. Nếu backend đang là bản trước 0.15 thì cần khởi động lại để dùng quét nhiều phần.

## Mới ở 0.15: quét theo số tin, ngày hoặc lịch sử tải được

Mở cuộc trò chuyện → PhishLens → **Chọn tin trong hội thoại** → chọn phạm vi rồi bấm **Tải hội thoại**:

- **Các tin gần nhất:** nhập số tin, mặc định 100. Tiện ích đi tới cuối phần chat đang tải rồi cuộn ngược để lấy thêm tin.
- **Theo khoảng ngày:** chọn từ ngày, có thể thêm ngày kết thúc. Hai ngày đều được tính trong phạm vi. Chỉ những tin đọc được ngày mới được lọc; ngày không rõ được báo riêng, không tự đoán năm.
- **Toàn bộ lịch sử tải được:** tiếp tục cuộn tới khi trang không tải thêm hoặc chạm giới hạn đã chọn. Đây là lịch sử ứng dụng web cung cấp qua giao diện, không chứng nhận đã lấy toàn bộ dữ liệu trên máy chủ.
- **Chọn tin đang hiển thị:** giữ cách chọn thủ công cũ cho đoạn ngắn.

Ba chế độ tải lịch sử cho chọn **1–2.000 tin mỗi lần**, giới hạn bản chữ gửi **200.000 ký tự**. Bộ thu có trần dung lượng, 120 giây/240 lượt cuộn; không quét vô hạn. Giao diện báo số tin, lý do dừng, ngày lọc và ngày không đọc được. Có thể bấm **Dừng tải · giữ phần đã lấy**, bỏ chọn tin hoặc sửa người nói trước khi phân tích. Trang không có ID tin ổn định có thể làm thiếu các tin giống nhau khi khử trùng; giao diện báo hạn chế này.

Với đoạn dài, máy chủ che dữ liệu rồi chia thành các cửa sổ tối đa **7.600 ký tự**, chồng lấn tối đa **1.200 ký tự** từ phần trước; không thay nội dung bằng tóm tắt. Duyệt gửi áp dụng cho toàn bản chữ, sau đó chạy từng phần với cùng prompt hội thoại, hạn mức và ngân sách chờ hiện có. Mỗi phần dùng một lượt hạn mức AI; phần giải thích có thể thêm request như luồng hiện tại. Không lưu lịch sử tài khoản cho lượt quét nhiều phần; kết quả RAM còn tối đa 15 phút sau khi hoàn tất.

Kết quả hiển thị **đã xử lý bao nhiêu/tổng bao nhiêu phần** và mở được kết quả từng phần. Tổng hợp giữ mức cảnh báo cao nhất đã thấy; nếu chưa xử lý đủ hoặc có phần UNKNOWN thì không đưa toàn phạm vi về LOW. Đây là tổng hợp các cửa sổ có chồng lấn, không phải một lượt LLM đọc đồng thời toàn lịch sử. Nút **Dừng sau phần đang xử lý** giữ các phần hoàn tất. Lỗi provider/hạn mức dừng các phần tiếp theo, không retry để thay kết quả lỗi. Đóng bảng khi AI đã bắt đầu vẫn có thể lấy lại job khi máy chủ còn chạy.

Lịch sử đã tải là snapshot: những tin bị ứng dụng gỡ khỏi DOM khi cuộn vẫn giữ trong RAM của tab chat để phân tích. Không xác minh được các chỉnh sửa phía máy chủ với tin không còn được trang tải. Đổi cuộc trò chuyện làm mất hiệu lực snapshot. **Xem tin gốc** chỉ tô khi tìm lại được đúng nội dung trong DOM; nếu tin chưa được tải, cần cuộn về đoạn đó để đối chiếu.

Kiểm thử lịch sử: `scripts/evaluation/check_extension_history_ui.py --platform zalo --out <thư-mục-mới>`. Hỗ trợ thêm `messenger`, `facebook`, `telegram-a`, `telegram-k`. Fixture dựng lịch sử phân trang và gỡ các trang cũ khỏi DOM, provider giả; chưa kiểm trên tài khoản chat thật. Kiểm API/chia phần/hạn mức/dừng: `tests/api/test_conversation_batch.py`.

Cập nhật từ 0.14: **khởi động lại backend**, Reload extension và tải lại tab chat. Backend cũ chưa có `conversation_batch_available` sẽ được báo trước khi gửi AI.

## Mới ở 0.14: hội thoại Zalo, Messenger và Telegram

Các nền tảng dưới đây dùng chung phần chọn phạm vi của bản 0.15. Nút **Chọn tin trong hội thoại** ghi tên nền tảng của tab hiện tại. Cấp quyền khi trình duyệt hỏi. Tiện ích chỉ đọc khung chat được chọn, không lấy danh sách bên trái, thông tin nhóm hoặc ô đang soạn. Bản 0.15 chỉ cuộn tải lịch sử sau khi bạn bấm Tải hội thoại.

| Nền tảng | Trang hỗ trợ | Phạm vi |
|---|---|---|
| Zalo Web | `https://chat.zalo.me/` | Khung hội thoại đang mở |
| Messenger | `https://www.messenger.com/`, `https://messenger.com/` | Trang hội thoại đầy đủ |
| Facebook Tin nhắn | `https://www.facebook.com/messages/`, `https://web.facebook.com/messages/` | Trang Tin nhắn; không đọc bảng tin hoặc cửa sổ chat nổi |
| Telegram Web | `https://web.telegram.org/a/`, `https://web.telegram.org/k/` | Hai bộ đọc riêng cho Web A / Web K |

Các ứng dụng desktop/điện thoại và website khác chưa có bộ đọc tự động. Có thể dán đoạn chat, bôi đen hoặc khoanh vùng ảnh trên trang web để kiểm tra.

**Ở lựa chọn Chọn tin đang hiển thị**, chọn/bỏ từng tin và kiểm tra nhãn **Bạn / Người 1 / Người 2 / Chưa rõ người gửi**. Tên người gửi đọc được từ vùng nhãn được thay bằng bí danh trong bản hội thoại; nội dung tin vẫn cần bạn kiểm tra thông tin riêng tư. Nếu không nhận diện được người nói, nhất là trên Messenger, tiện ích để **Chưa rõ người gửi**, cho người dùng sửa; không đoán theo màu bong bóng hoặc vị trí. Tối đa **30 tin và 8.000 ký tự**; số tin và số ký tự được hiển thị, không tự cắt để vừa hạn mức. Tin chứa ảnh/tệp có ghi chú; không tự đọc nội dung ảnh hoặc tải tệp đính kèm.

Bấm **Kiểm tra đoạn đã chọn**. Chế độ mặc định hiển thị bản chữ đã che và chờ đồng ý; lựa chọn Gửi ngay được áp dụng sau thao tác chọn tin này. Mở/chuyển chat, bật trợ lý hoặc mở bảng không tự gửi AI. Prompt `conversation-core-1.0` phân tích thứ tự/người nói và diễn biến nhiều lượt; đây là profile mới, chưa có đánh giá chất lượng độc lập. URL vẫn được chấm riêng. RAG chưa bật cho luồng hội thoại.

Kết quả ghi rõ phạm vi đoạn đã chọn. **Xem tin gốc** cuộn tới tin phù hợp và tô tin đó; đoạn đã che/sửa có thể không khớp để tô. Đổi cuộc trò chuyện, sửa hoặc gỡ tin đã chọn làm mất hiệu lực ngữ cảnh gửi/đối chiếu. Không tự gửi lại; đọc lại và chọn lại nếu cần. Đóng bảng trong lúc chờ vẫn có thể lấy lại job khi backend còn chạy và đoạn nguồn còn hợp lệ; extension chỉ giữ con trỏ job/ngữ cảnh trong session, không lưu transcript vào storage.

Muốn có nút trực tiếp trong trang chat, vào **Trợ lý**, bật riêng **Zalo Web**, **Messenger / Facebook** hoặc **Telegram Web**. Nút chỉ mở phần chọn tin. Có thể dùng menu chuột phải **Chọn hội thoại để kiểm tra bằng PhishLens** trên các trang hỗ trợ. Tắt từng tùy chọn để bỏ nút của nền tảng đó. Cấu hình Zalo cũ được giữ khi nâng cấp; hai nền tảng mới mặc định tắt.

Sau cập nhật: chạy backend hiện tại, **Reload** extension và tải lại tab chat. Backend cũ thiếu `conversation_analysis_available` sẽ được báo cập nhật trước khi gọi AI. Bộ đọc nhận diện DOM có giới hạn; nếu không nhận diện được đúng một khung chat sẽ báo lỗi và giữ cách bôi đen/khoanh vùng, không đọc toàn bộ trang làm phương án thay thế. Đã kiểm Chromium bằng DOM/AI mô phỏng; **chưa xác nhận bằng tài khoản thật trên các nền tảng**, bố cục có thể thay đổi. Messenger dùng cấu trúc accessibility của trang, mức tương thích cần kiểm tra trực tiếp.

Kiểm thử: `scripts/evaluation/check_extension_conversation_ui.py --platform zalo --out <thư-mục-mới>` chạy extension/backend thật trong profile/database tách biệt, mô phỏng trang chat và provider. Giá trị `--platform`: `zalo`, `messenger`, `facebook`, `telegram-a`, `telegram-k`. Không đăng nhập hoặc gửi nội dung chat thật; quyền host được cấp sẵn trong bản manifest tách biệt để chạy headless, chưa kiểm hộp thoại cấp quyền native.

Bộ đọc Telegram đối chiếu cấu trúc từ mã nguồn công khai [Web A](https://github.com/Ajaxy/telegram-tt/blob/master/src/components/middle/message/Message.tsx) và [Web K](https://github.com/morethanwords/tweb/blob/master/src/components/chat/bubbles.ts); không truy cập API nội bộ hay giải mã lịch sử. Quyền host của Chromium áp dụng theo host, không giới hạn đường dẫn; bộ phát hiện URL và content script của PhishLens giới hạn Facebook vào `/messages/`. Xem [tài liệu match patterns của Chrome](https://developer.chrome.com/docs/extensions/develop/concepts/match-patterns).

## Mới ở 0.12: email và kết quả cạnh nhau

Bấm **Chi tiết** mở bảng bên trong trình duyệt khi hỗ trợ. Thao tác mở bảng chạy ngay trong lần bấm, trước bước đọc/đối chiếu email để giữ quyền mở Side Panel. Vị trí bảng native tuân theo cài đặt trái/phải của trình duyệt.

Nếu không dùng được Side Panel (chẳng hạn trên một số cấu hình Brave), PhishLens tự xếp hai cửa sổ trong vùng cửa sổ mail hiện tại: **mail bên trái, kết quả bên phải**, cùng chiều cao. Không thêm quyền trình duyệt. Bấm lại Chi tiết dùng cùng cửa sổ và không thu nhỏ mail thêm lần nữa. Đóng cửa sổ kết quả khôi phục kích thước/trạng thái trước đó của cửa sổ mail; nếu bạn đã tự di chuyển hoặc đổi kích thước mail thì giữ bố cục bạn chọn. Cửa sổ hẹp dưới 900 px xếp hai vùng trên/dưới. Nút mở cửa sổ riêng trên header trả lại kích thước mail và giữ một cửa sổ PhishLens.

Kiểm bố cục và khôi phục: `scripts/evaluation/check_extension_docked_ui.py --out <thư-mục-mới>` dùng mã JS thật với browser-window API giả lập trong Chromium; chưa thay thế kiểm vị trí cửa sổ trên desktop/Brave thật.

## Mới ở 0.11: kiểm email gọn, dùng lại cửa sổ

- Với chế độ **Gửi ngay khi tôi yêu cầu kiểm tra**, bấm **Kiểm tra email này** để phân tích ngay trên thư: trạng thái chờ rồi mức cảnh báo, số dấu hiệu và liên kết. Kết quả không tự bật cửa sổ hoặc lấy focus. Bấm mức cảnh báo để xem thẻ dấu hiệu; **Chi tiết** mới mở bảng đầy đủ.
- Chế độ **Xem trước và xác nhận** vẫn mở bản duyệt và chờ bạn đồng ý. Không gửi AI chỉ vì mở hoặc chuyển email.
- Bảng chi tiết ưu tiên Side Panel khi trình duyệt hỗ trợ. Cửa sổ tách riêng, menu chuột phải và kết quả ảnh dùng lại một cửa sổ PhishLens; trình duyệt không mở được Side Panel cũng dùng cửa sổ này.
- Bấm lặp khi đang chạy sẽ dùng lượt đang chờ. Mở lại kết quả không gọi AI thêm; nút **↻ Kiểm tra lại email** chủ động chạy lượt mới. Đổi thư trong lúc chờ không tô kết quả vào thư khác. Cùng email/nội dung/đường dẫn hộp thư được kiểm lại bằng kết quả còn hạn, kể cả sau khi tải lại tab.
- Lượt AI chạy ở backend nên đóng bảng vẫn tiếp tục khi ứng dụng trên máy còn mở. Mở lại bảng lấy kết quả gần nhất. Kết quả tác vụ giữ trong RAM tối đa 15 phút sau khi hoàn tất, xóa khi backend dừng; không phải lịch sử lâu dài của khách. Extension chỉ giữ định danh tác vụ và dấu vân tay nội dung trong phiên trình duyệt, không lưu bản email hoặc kết quả đầy đủ vào storage. Tối đa 10 tham chiếu email gần đây mỗi tab. Đổi cài đặt phân tích rồi muốn đo lại cần bấm Kiểm tra lại.

Sau cập nhật, khởi động lại backend, **Reload** extension và tải lại tab Gmail/Outlook. Đóng những cửa sổ phiên bản cũ đang mở một lần. Kiểm luồng riêng: `scripts/evaluation/check_extension_quiet_mail_ui.py --out <thư-mục-mới>`; dùng Chromium với hộp thư/provider giả, chưa thay thế thử trực tiếp trên Brave hay hộp thư thật.

## Mới ở 0.10: chọn cách gửi AI

Vào **Cài đặt → Gửi nội dung tới AI**:

- **Xem trước và xác nhận** (mặc định): giữ bản duyệt, chỉnh sửa và ô đồng ý cho từng lượt.
- **Gửi ngay khi tôi yêu cầu kiểm tra**: đồng ý trước cho các thao tác kiểm tra chủ động. Bấm Phân tích ngay, Ctrl+Enter, Đọc email đang mở hoặc chủ động khoanh/chụp vùng → che nội dung tại máy chủ → gửi bản đã che tới AI, không hỏi lại từng lượt. Ảnh gốc vẫn chỉ đến OCR cục bộ. Chọn/tải ảnh hoặc chỉ bấm Đọc chữ vẫn chỉ chuẩn bị nội dung.

Lựa chọn được giữ trong `storage.local`, đồng bộ giữa các cửa sổ extension trên trình duyệt này, không thêm quyền. Thay cài đặt không tự gửi bản đang mở. Chế độ gửi ngay chỉ áp dụng khi có thao tác yêu cầu kiểm tra: mở extension, kết nối lại, bật trợ lý email hoặc chuyển thư không gọi AI; email mới chỉ điền vào ô nội dung chờ bấm Phân tích ngay. Tắt AI vẫn chỉ kiểm URL cục bộ. Nếu che nội dung thất bại thì không gửi; lỗi AI không tự retry. Có thể chọn lại Xem trước và xác nhận bất kỳ lúc nào.

Các bước duyệt/xác nhận trong hướng dẫn bên dưới mô tả chế độ mặc định; chế độ gửi ngay dùng sự đồng ý đã lưu và luôn che nội dung trước khi gọi AI. Backend vẫn yêu cầu `consent=true` và `llm_text` hợp lệ, không mở API bỏ qua điều kiện này. Kiểm luồng riêng: `scripts/evaluation/check_extension_send_mode_ui.py --out <thư-mục-mới>`.

## Mới ở 0.9: xem dấu hiệu ngay trên email

1. Mở một thư trên Gmail/Outlook → **Đọc email đang mở** (hoặc **Kiểm tra email này** khi đã bật trợ lý).
2. Duyệt chữ, đồng ý và phân tích. Khi có kết quả, những trích dẫn khớp phần nội dung thư được tô vàng ngay trên email. Bấm đoạn được tô để đọc giải thích; **Xem dấu hiệu trên thư** mở danh sách có thể thao tác bằng bàn phím.
3. Bấm liên kết trong thư đã đánh dấu để xem **chữ hiển thị → tên miền đích**, đường dẫn đầy đủ và mức URL đã chấm. Google redirect/Safe Links được giải mã bằng chuỗi, không truy cập trang đích. Khi đang đánh dấu, bấm liên kết mở thẻ đối chiếu; chọn **Ẩn đánh dấu** để dùng liên kết theo hành vi của hộp thư.

Đánh dấu dùng lại kết quả đã hoàn tất, không gọi AI thêm hoặc thêm quyền trình duyệt. Chỉ đối chiếu trích dẫn với chữ nhìn thấy trong phần thư đang mở; không tô inbox, thư ẩn, biểu mẫu hoặc đoạn đã bị sửa/xóa nên không còn khớp. Dùng CSS Highlight/Range, giữ nguyên HTML nội dung email. Tên miền khác chữ hiển thị là thông tin đối chiếu, không tự tạo kết luận lừa đảo.

Kết quả gắn với tab, document, route và nội dung email lúc lấy. Đổi thư, sửa nội dung hoặc thay đích liên kết sẽ xóa đánh dấu; phản hồi AI về muộn không được tô lên thư mới. Có nút Ẩn, Esc thu gọn thẻ giải thích; đánh dấu tự hết sau 15 phút. Từ 0.11, quay lại đúng email hoặc tải lại tab có thể dựng lại đánh dấu từ tác vụ còn hạn; các dấu Range/Highlight không lưu vào storage/lịch sử. Lượt kiểm chỉ URL vẫn có đối chiếu liên kết, không sinh dấu hiệu AI.

Kiểm Chromium bằng fixture Gmail/Outlook và provider giả: `scripts/evaluation/check_extension_mail_annotations_ui.py --out <thư-mục-mới>`. Chưa thay thế thử trực tiếp trên tài khoản Gmail/Outlook thật, Edge/Windows/macOS hoặc đánh giá độ đúng của model.

## Mới ở 0.8: thao tác liền mạch

- Màn hình chia ba bước: Nội dung → Duyệt gửi → Kết quả. Thanh thao tác luôn nằm dưới cửa sổ, có vùng riêng để không che ô nhập hoặc tùy chọn. Khoanh vùng và chụp vùng hiển thị nằm cạnh nhau; nút đọc thư hiện trước khi đang dùng Gmail/Outlook.
- Đổi thẻ giữ bản đang soạn và lựa chọn AI của từng thẻ trong bộ nhớ cửa sổ. Quay lại từ bản duyệt giữ phần chữ đã sửa; sửa chữ hoặc kết nối lại đều hủy consent cũ. Không tự gửi lại AI.
- Dán đoạn văn/email vào thẻ Đường dẫn tự chuyển sang Tin nhắn. Nếu bản Tin nhắn đang có nội dung khác thì hỏi trước khi thay. Dán quá 8.000 ký tự bị từ chối, giữ bản đang soạn.
- Kết quả có hai thao tác riêng: **Sửa nội dung** giữ bản hiện tại; **Kiểm tra nội dung khác** xóa bản nhập, ảnh, bản duyệt và consent. Danh sách trên năm URL có ô tìm kiếm cục bộ; không chạy lại model/AI.
- Ctrl/⌘+Enter chỉ áp dụng trong màn hình Kiểm tra; Esc quay lại từ bản duyệt và giữ chữ đã sửa. Dán ảnh không thay nội dung khi đang ở Trợ lý/Kết nối; thay ảnh trong bản duyệt/kết quả cần xác nhận.

Không lưu thêm nội dung vào storage và không thêm quyền trình duyệt trong bản này. Đã kiểm các luồng bằng Chromium và dữ liệu giả lập; chưa thay thế kiểm khả dụng với người dùng độc lập hoặc thử trên Edge/Windows/macOS.

Bản 0.7.1 cùng backend cập nhật hỗ trợ **50 URL khác nhau** trong một tin nhắn/email, thay giới hạn 5 trước đây; URL trùng chỉ tính một lần. Giới hạn nội dung vẫn là 8.000 ký tự; thẻ Đường dẫn nhận một URL. Khi vượt giới hạn, ứng dụng yêu cầu tách nội dung thay vì âm thầm bỏ URL. Nhãn giới hạn trong thẻ Tin nhắn lấy từ backend đang kết nối.

## Mới ở 0.7: giải thích, chụp nhanh và email

- **AI giải thích:** phần Dấu hiệu có đoạn tổng hợp và lý do riêng cho từng trích dẫn. Bản focused/shadow thêm tối đa một lượt AI sau phân loại, dùng cùng bản chữ đã duyệt và ngân sách chờ chung; không đổi mức cảnh báo/quote. Tắt **AI giải thích thêm từng dấu hiệu** trong tùy chọn nếu không cần. Lỗi giải thích vẫn giữ kết quả gốc. Đây là lời giải thích công khai do AI viết, chưa phải kiểm chứng ngữ nghĩa độc lập.
- **Khoanh ngay:** menu chuột phải, Alt+Shift+S hoặc nút nổi mở công cụ chọn trực tiếp trên trang, không mở bảng trước. Chọn xong mới mở cửa sổ đọc ảnh; nếu bắt đầu trong bảng đang mở thì kết quả về bảng đó. Esc hủy.
- **Chụp toàn vùng hiển thị:** bấm nút trên công cụ khoanh vùng, trên bảng hoặc menu nút nổi. Chỉ chụp vùng website đang nhìn thấy; không phải toàn desktop hay toàn trang cuộn dài. OCR tại máy; AI vẫn chờ duyệt chữ.
- **Gmail / Outlook:** mở một email rồi bấm **Đọc email đang mở** trong bảng PhishLens. Lấy tiêu đề, người gửi hiển thị, phần chữ của thư đã mở rộng và URL thực trong liên kết. Không mở URL đích, không đọc inbox/bản nháp, ảnh hay tệp đính kèm. Không xác minh danh tính người gửi.
- Bật **Trợ lý → Trợ lý Gmail / Outlook** và cấp quyền các host email để hiện nút **Kiểm tra email này** trên thư. Khi bảng đang mở, mở sang email khác sẽ tự chuẩn bị bản duyệt mới và hủy consent của thư cũ. Bản đang sửa được giữ để tránh mất nội dung. Khi đóng bảng, chỉ nhận diện thư và hiện nút; không gọi AI nền.

Hỗ trợ `mail.google.com`, `outlook.live.com`, `outlook.office.com`, `outlook.office365.com`. Quyền email là tùy chọn; chức năng đọc thủ công dùng quyền activeTab khi bấm extension. Trích xuất dựa trên DOM của thư đang mở, không dùng Gmail API/Graph hoặc mật khẩu hộp thư. Nhiều thư mở rộng cùng lúc, thư chưa nhận diện được hoặc vượt 8.000 ký tự sẽ yêu cầu chọn lại; không âm thầm lấy toàn inbox/cắt thư. Giới hạn URL của backend vẫn áp dụng. Layout webmail có thể thay đổi; đã kiểm bằng fixture DOM, cần thử thêm trên hộp thư thật.

## Dùng ngay, không cần mã hoặc tài khoản

Mở ứng dụng PhishLens trên máy, rồi bấm biểu tượng extension. Extension tự thử địa chỉ đã lưu và hai cổng mặc định `http://127.0.0.1:8001`, `http://127.0.0.1:8000`; không quét mạng. Không có bước lấy/dán mã ghép nối. Nếu chạy cổng khác, vào **Cài đặt**, nhập địa chỉ và bấm **Kết nối và dùng ngay**. Backend phải đang chạy.

**Chế độ khách** có kiểm URL, OCR và AI/RAG khi máy chủ đã cấu hình. AI dùng xác nhận mỗi lượt hoặc lựa chọn gửi ngay đã lưu. Không ghi lịch sử/nội dung khách vào cơ sở dữ liệu; tác vụ giữ kết quả trong RAM trong thời hạn nêu trên, tải JSON để giữ lâu hơn. Không tự tạo tài khoản hoặc nhận quyền của tài khoản đang đăng nhập web. Muốn lưu lịch sử riêng cho các lượt tiếp theo, đăng nhập trên web. Kết quả khách trước đó không được tự chuyển vào tài khoản.

**Tạm ngừng kết nối** được nhớ qua reload/mở lại trình duyệt; bấm Kết nối và dùng ngay để tiếp tục. Khởi động lại backend không cần mã hoặc đăng nhập lại. Extension chỉ nhớ địa chỉ/trạng thái khách, không cấp hay lưu token xác thực mới.

## Giao diện 0.6

Bỏ các banner/ghi chú lặp về khách, kết nối và AI; nhãn ngắn, cỡ chữ dễ đọc hơn, nút phân tích không che tùy chọn. **Kết nối → Dữ liệu và phiên bản** giữ thông tin tài khoản/quyền; **Cách đọc kết quả** giữ phạm vi điểm URL và mức AI. Preview/consent, lỗi thực và các cảnh báo cần xử lý vẫn hiển thị ở đúng bước. Không thêm quyền hoặc thay đổi model trong bản này.

## Bảng điều khiển và trợ lý

- **Kiểm tra:** Khoanh vùng và Vùng hiển thị ở cạnh nhau; trang hiện tại có nút Kiểm tra URL. Dán nội dung ở thẻ Tin nhắn, hoặc đọc thư đang mở trên Gmail/Outlook. Kết quả có Sửa nội dung/Kiểm tra nội dung khác và thao tác khoanh vùng khác.
- **Trợ lý:** bật riêng nút nổi hoặc tự kiểm URL; xem trạng thái, tạm nghỉ một giờ và khôi phục các website đã ẩn. Cả hai tùy chọn mặc định tắt.
- **Cài đặt:** chọn cách gửi AI, xem trạng thái ứng dụng, đổi địa chỉ/cổng và thử kết nối lại. Header giữ nút đổi sáng/tối và mở cửa sổ riêng; giao diện dùng được ở chiều rộng 320 px.

Nút nổi có thể **kéo đổi vị trí**, tự bám mép trái/phải và nhớ vị trí. Bấm phần chính để khoanh vùng; bấm dấu ba chấm để mở menu kiểm URL, mở bảng, tạm nghỉ hoặc ẩn trên website này. Menu hỗ trợ phím mũi tên/Esc. Website đã ẩn cũng được bỏ qua trong chế độ tự kiểm.

### Tự kiểm URL khi duyệt web

Vào **Trợ lý → Tự kiểm URL khi mở trang**, cấp quyền trang khi Chrome hỏi. Khi kết nối được ứng dụng, extension chấm **chuỗi URL HTTP/HTTPS** qua backend tại máy khi mở/đổi URL hoặc chọn tab, kể cả lúc đóng bảng. Không đọc DOM, chụp ảnh, OCR, gọi AI hoặc lưu lịch sử trong luồng tự động. URL gửi localhost bao gồm path/query; hãy cân nhắc nếu URL chứa thông tin riêng. Không gửi URL đến website đích hoặc provider. Bỏ qua tab ẩn danh và origin của chính ứng dụng đã kết nối.

Chỉ URL HIGH đủ điều kiện thông báo nền (xem chính sách 0.16 ở trên) có dấu `!` và cảnh báo tạm thời. LOW/UNKNOWN hoặc HIGH dưới mốc thông báo không bật khung cảnh báo; kết quả thủ công vẫn hiển thị đúng trạng thái của model. Mất kết nối/lỗi dịch vụ hiển thị chưa kiểm tra được, không tạo điểm thấp. Không chặn điều hướng hoặc kiểm nội dung website đích, nên đây là hỗ trợ sau khi mở trang, không phải bộ lọc chống truy cập.

Lưu điểm gần nhất tối đa 5 phút theo tab, kiểm lỗi không lặp trong 15 giây; tối đa hai lượt URL đồng thời, timeout 12 giây. Bản ghi phiên chỉ chứa hash URL, thời điểm, trạng thái và score; không lưu URL gốc trong cache nền. Hash không bảo đảm ẩn danh. Tạm nghỉ/ẩn website/tắt tự kiểm/đổi kết nối hủy tác vụ đang chờ và bỏ kết quả muộn. Không tự chạy lại sau khi backend vừa mở; chọn lại tab, điều hướng hoặc kiểm thủ công để thử lại.

Kết quả có thang cảnh báo Thấp / Cần kiểm tra / Cao. Điểm URL hợp lệ được hiển thị dạng phần trăm (score × 100), kèm nhãn **Điểm mô hình URL** và giới hạn chưa phải xác suất lừa đảo đã kiểm chứng. Mỗi URL giữ điểm riêng; không lấy trung bình hoặc điểm URL làm % cho cả thông điệp. AI hiện chỉ trả mức cảnh báo; giải thích về điểm nằm trong **Cách đọc kết quả**, không tự quy HIGH thành 90% hoặc UNKNOWN thành 0%. Không có URL/điểm lỗi thì không hiển thị % URL.

## Khoanh ngay trên trang — mới ở 0.3

1. Bấm biểu tượng PhishLens trên **tab web cần kiểm tra** → **Khoanh vùng trên trang**. Cũng có thể chuột phải trên trang/ảnh → **Khoanh vùng trên trang để kiểm tra**, hoặc **Alt+Shift+S**.
2. Kéo chuột bao quanh tin nhắn/đoạn ảnh ngay trên trang, thả chuột. **Esc** hủy; cuộn/đổi kích thước trang làm hủy vùng chọn để tránh chụp sai.
3. Extension tự cắt vùng và đọc chữ bằng OCR tại máy, rồi mở bản chữ đã che để duyệt. Kiểm tra/sửa chữ → đánh dấu đồng ý → **Đồng ý và phân tích**. Chưa đồng ý thì chưa gọi AI.
4. **Tải ảnh từ máy** là chức năng riêng ở thẻ Hình ảnh: chọn/kéo thả/Ctrl+V → có thể cắt lại → Đọc chữ từ ảnh.

Muốn gọi thao tác nhanh trên các trang, vào **Trợ lý → Luôn hiện nút công cụ**. Chrome hỏi quyền truy cập trang; sau khi cấp, nút nổi xuất hiện trên HTTP/HTTPS. Tắt tùy chọn để gỡ nút; quyền đã cấp có thể thu hồi trong phần chi tiết extension của Chrome. Bật nút nổi riêng không tự phân tích URL/nội dung. Trình duyệt có thể hạn chế các trang hệ thống, cửa hàng extension, PDF/viewer hoặc trang đặc biệt.

Kết nối tài khoản từ phiên bản cũ vẫn được hỗ trợ đến khi thu hồi/hết hạn. Bạn có thể thu hồi chúng trong Tài khoản trên web. Giao diện mới không tạo mã hoặc kết nối tài khoản; mặc định dùng khách. Nếu token cũ hết hạn lúc mở extension, extension chuyển sang khách và ghi rõ trạng thái.

Extension hoạt động theo sự kiện của trình duyệt, không cần giữ bảng luôn mở. **Backend PhishLens phải đang chạy** để OCR/chấm/phân tích; tắt terminal backend thì cần mở ứng dụng lại. Không tự cài dịch vụ chạy cùng hệ điều hành.

## Giao diện và cách cập nhật

Nếu đã cài bản cũ, mở `chrome://extensions` / `edge://extensions` / `brave://extensions`, bấm **Reload** trên thẻ PhishLens, đóng bảng cũ và tải lại tab web. **Khởi động lại backend** để nạp API tác vụ. Cần Chromium 116+; khi không mở được Side Panel, extension dùng một cửa sổ tách. Không thêm quyền trình duyệt ở 0.11; quyền toàn trang vẫn tùy chọn.

- Bấm biểu tượng mở bảng bên cạnh trang. Nút mở rộng trên header mở cửa sổ riêng.
- Thẻ Hình ảnh: **khoanh trực tiếp trên trang** hoặc chọn/kéo thả/Ctrl+V ảnh có sẵn. Hai thao tác độc lập.
- OCR tiếng Việt/Anh chạy tại máy; ảnh gốc không gửi AI hoặc lưu server/lịch sử. Sửa chữ nhận dạng, xem bản đã che và đồng ý trước khi phân tích. [Cài OCR / giới hạn](../../docs/guides/OCR.md).
- Thẻ Tin nhắn/ảnh chọn sẵn AI để đánh giá hành vi, nhưng chưa gọi provider. Vẫn phải duyệt và đồng ý. URL mặc định chỉ chạy tại máy.
- Kết quả có hai nhận định, dấu hiệu và việc nên làm, chi tiết URL/nguồn mở thêm. Nút Kiểm tra nội dung khác để quay lại.
- Nút trăng đổi sáng/tối, giữ lựa chọn; Ctrl+Enter thao tác chính. Trong bước duyệt chỉ gửi nếu đã chọn đồng ý. Mẫu Thử nhanh chỉ điền dữ liệu tự soạn, chưa chạy.

## Cài và kết nối

1. Mở `start_phishlens.sh` / `start_phishlens.bat` hoặc `make demo`; mặc định launcher mở `http://127.0.0.1:8001`. Giữ backend chạy.
2. Tải ZIP ngay ở trang kiểm tra khách, hoặc dùng thư mục `extensions/chromium` trong repository. Không cần tài khoản để tải ZIP.
3. Giải nén, mở `chrome://extensions`, bật **Chế độ nhà phát triển**, chọn **Load unpacked** thư mục có `manifest.json`. Chưa phát hành trên store.
4. Bấm biểu tượng PhishLens để dùng ngay. Khi cần, đổi địa chỉ ứng dụng trong **Kết nối**; không nhập mật khẩu/API key/mã.

## Sử dụng

- Chuột phải vào link HTTP/HTTPS → **Kiểm tra đường dẫn bằng PhishLens**. Link được lấy để chấm chuỗi, không được extension mở đến website đích.
- Bôi đen văn bản → chuột phải → **Phân tích đoạn chọn bằng PhishLens**.
- Bấm biểu tượng extension để lấy URL tab HTTP/HTTPS hiện tại. Trên trang hệ thống như `chrome://`, có thể dán nội dung cần kiểm tra vào cửa sổ.
- Ở thẻ Đường dẫn mặc định chỉ kiểm tra URL cục bộ; Tin nhắn/ảnh chọn sẵn AI nhưng luôn yêu cầu duyệt/đồng ý trước gửi. Muốn đánh giá hành vi thông điệp, bật **Phân tích thêm bằng AI**, xem/sửa bản đã che rồi xác nhận. Khi sửa bản duyệt, phải đồng ý lại; che thêm sau khi sửa cũng cần xem lại.
- Có thể bật điểm URL/RAG. Cấu hình backend quyết định RAG trước/sau kết luận và số lượt AI. Mức URL và nhận định nội dung hiển thị riêng.
- Khách không lưu lịch sử. Lượt web sau khi đăng nhập có lịch sử riêng và lựa chọn lưu nội dung đã che; mở lịch sử để phản hồi/xóa kết quả.

## Dữ liệu và quyền

Quyền bắt buộc: `activeTab`, `contextMenus`, `storage`, `sidePanel`, `scripting`, `alarms`, kết nối backend HTTP tại `127.0.0.1` / `localhost`. `activeTab` cho phép chọn vùng từ biểu tượng/menu/phím tắt. Quyền host `<all_urls>` chỉ xin khi bật nút nổi hoặc tự kiểm URL; capture từ nút trên trang cần quyền này. Helper động chỉ đăng ký HTTP/HTTPS và duy trì qua phiên. Worker chạy theo sự kiện; chỉ khi có tác vụ người dùng đã gửi, bảng/email đang hiện mới hỏi trạng thái trong lúc chờ, không giữ heartbeat thường trực. Alarm chỉ dùng một lần cho tạm nghỉ. Tự kiểm URL không chặn trang và chỉ hoạt động khi người dùng bật.

Địa chỉ, theme, trạng thái khách/tạm ngừng, tùy chọn trợ lý, vị trí nút và hash hostname đã ẩn (tối đa 100) nằm trong `storage.local`; cache URL nền và đầu vào menu chờ dùng `storage.session`. Hai storage giới hạn `TRUSTED_CONTEXTS`; helper trên trang không đọc được thông tin kết nối. Không đồng bộ Chrome. Token tài khoản cũ nếu có vẫn giữ trong local/session theo lựa chọn cũ, có hạn và có thể thu hồi; token sai/hết hạn không được server âm thầm coi thành khách trong cùng yêu cầu.

API khách vẫn kiểm ID/Origin extension và giới hạn ảnh/JSON. POST trên web vẫn cần CSRF token cấp tự động. API lịch sử/tài khoản/quản trị vẫn yêu cầu đăng nhập; extension khách không nhận cookie web. Giới hạn AI khách dùng chung web/extension theo địa chỉ client, tối đa số lượt `PHISHLENS_DAILY_AI_LIMIT` trong cửa sổ 24 giờ (mặc định 100); không tạo user/ai_usage cá nhân. Xóa cookie/đổi ID extension không tạo quota khách riêng. OCR giới hạn 30/giờ theo client. Launcher không tin proxy header; triển khai qua proxy phải cấu hình riêng và nhiều người chung địa chỉ có thể chia sẻ quota. Tài khoản có quota riêng theo cơ chế cũ.

Ảnh toàn viewport chỉ ở bộ nhớ worker để cắt, crop chờ nhận tối đa 30 giây trong RAM; chỉ crop đến OCR localhost. Không lưu screenshot trong storage/server. Đầu vào menu quá 8.000 ký tự bị từ chối; chờ tối đa 10 phút. Ảnh/bản nháp trên bảng mất khi đóng/reload. Kết quả AI có thể lấy lại từ RAM backend trong 15 phút sau hoàn tất; tải JSON là thao tác chủ động để giữ kết quả lâu hơn. Tác vụ dùng khóa phiên riêng, ràng buộc với danh tính khách/tài khoản và origin extension; phiên khác không đọc được chỉ bằng ID tác vụ.

Backend phải đang chạy. Đây là bản demo cục bộ; chưa kiểm nghiệm triển khai công khai, chưa phát hành Chrome/Edge store. LOW không chứng nhận URL/người gửi an toàn. Cài extension không làm tăng độ chính xác mô hình hoặc biến nhãn AI thành nhãn người.

Tài liệu API trình duyệt: [activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab), [contextMenus](https://developer.chrome.com/docs/extensions/reference/api/contextMenus), [storage](https://developer.chrome.com/docs/extensions/reference/api/storage), [nhận diện trang thuộc extension](https://developer.chrome.com/docs/extensions/reference/api/runtime#method-getContexts), [kết nối khác origin](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests).

Khi thả vùng chọn, OCR tự chạy tại máy; gọi LLM luôn chờ duyệt/đồng ý. Ảnh tĩnh PNG/JPEG/WebP tối đa 5 MiB/12 triệu điểm ảnh; OCR chưa phân tích thị giác hoặc QR. Chưa kiểm Edge/Windows/macOS.

Tham khảo: [scripting](https://developer.chrome.com/docs/extensions/reference/api/scripting), [captureVisibleTab](https://developer.chrome.com/docs/extensions/reference/api/tabs#method-captureVisibleTab), [vòng đời worker MV3](https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle).
