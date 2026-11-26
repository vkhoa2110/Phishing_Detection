# PhishLens Browser Extension — bản cục bộ 0.12.0

Extension Manifest V3 với bảng bên cạnh trang, sáng/tối và ba thẻ Đường dẫn / Tin nhắn / Hình ảnh, dùng với PhishLens đang chạy trên máy, không cần đăng nhập. Model URL, RAG và kết nối LLM nằm ở backend; extension không chứa API key và không tự đọc toàn trang.

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

URL HIGH/WARNING có dấu `!` trên biểu tượng; UNKNOWN có `?`. Nếu có nút nổi, cảnh báo hiện tại chỗ, có thể đóng hoặc mở chi tiết. LOW ghi “URL đã kiểm tra”, không chứng nhận trang an toàn. Mất kết nối/lỗi dịch vụ hiển thị chưa kiểm tra được, không tạo điểm thấp. Không chặn điều hướng hoặc kiểm nội dung website đích, nên đây là hỗ trợ sau khi mở trang, không phải bộ lọc chống truy cập.

Lưu điểm gần nhất tối đa 5 phút theo tab, kiểm lỗi không lặp trong 15 giây; tối đa hai lượt URL đồng thời, timeout 12 giây. Bản ghi phiên chỉ chứa hash URL, thời điểm, trạng thái và score; không lưu URL gốc trong cache nền. Hash không bảo đảm ẩn danh. Tạm nghỉ/ẩn website/tắt tự kiểm/đổi kết nối hủy tác vụ đang chờ và bỏ kết quả muộn. Không tự chạy lại sau khi backend vừa mở; chọn lại tab, điều hướng hoặc kiểm thủ công để thử lại.

Kết quả có thang cảnh báo Thấp / Cần kiểm tra / Cao. Điểm URL hợp lệ được hiển thị dạng phần trăm (score × 100), kèm nhãn **Điểm mô hình URL** và giới hạn chưa phải xác suất lừa đảo đã kiểm chứng. Mỗi URL giữ điểm riêng; không lấy trung bình hoặc điểm URL làm % cho cả thông điệp. AI hiện chỉ trả mức cảnh báo; giải thích về điểm nằm trong **Cách đọc kết quả**, không tự quy HIGH thành 90% hoặc UNKNOWN thành 0%. Không có URL/điểm lỗi thì không hiển thị % URL.

## Khoanh ngay trên trang — mới ở 0.3

1. Bấm biểu tượng PhishLens trên **tab web cần kiểm tra** → **Khoanh vùng trên trang**. Cũng có thể chuột phải trên trang/ảnh → **Khoanh vùng trên trang để kiểm tra**, hoặc **Alt+Shift+S**.
2. Kéo chuột bao quanh tin nhắn/đoạn ảnh ngay trên trang, thả chuột. **Esc** hủy; cuộn/đổi kích thước trang làm hủy vùng chọn để tránh chụp sai.
3. Extension tự cắt vùng và đọc chữ bằng OCR tại máy, rồi mở bản chữ đã che để duyệt. Kiểm tra/sửa chữ → đánh dấu đồng ý → **Đồng ý và phân tích**. Chưa đồng ý thì chưa gọi AI.
4. **Tải ảnh từ máy** là chức năng riêng ở thẻ Hình ảnh: chọn/kéo thả/Ctrl+V → có thể cắt lại → Đọc chữ từ ảnh.

Muốn gọi thao tác nhanh trên các trang, vào **Trợ lý → Hiện nút PhishLens trên trang**. Chrome hỏi quyền truy cập trang; sau khi cấp, nút nổi xuất hiện trên HTTP/HTTPS. Tắt tùy chọn để gỡ nút; quyền đã cấp có thể thu hồi trong phần chi tiết extension của Chrome. Bật nút nổi riêng không tự phân tích URL/nội dung. Trình duyệt có thể hạn chế các trang hệ thống, cửa hàng extension, PDF/viewer hoặc trang đặc biệt.

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
