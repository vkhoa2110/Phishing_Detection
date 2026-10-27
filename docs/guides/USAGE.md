# PhishLens — Phishing Detection & Analysis

Bản cơ bản cho dự án của **Lê Văn Khoa**: giao diện tiếng Việt kiểm tra URL, email và tin nhắn, kết hợp mô hình ML đã huấn luyện với DeepSeek-V4-Flash qua API FPT. **Chưa sử dụng RAG.**

Báo cáo dự án, cập nhật theo hiện trạng ngày 26/10/2026:

- [Bản Word để chỉnh sửa](../reports/2026-10-26/Bao_cao_Phishing_ML_LLM_RAG_Le_Van_Khoa.docx)
- [Bản PDF để xem](../reports/2026-10-26/Bao_cao_Phishing_ML_LLM_RAG_Le_Van_Khoa.pdf)

Báo cáo gồm kết quả PhishVN đã đo, thiết kế RAG và danh mục 25 nguồn tài liệu; phần RAG chưa tích hợp runtime được ghi riêng là công việc cần hoàn thiện.

Ứng dụng gồm FastAPI và giao diện HTML/CSS/JavaScript, chạy cùng một địa chỉ. Không cần Node.js, npm, GPU hoặc cơ sở dữ liệu. Các tệp giao diện và biểu tượng nằm sẵn trong dự án, không dùng CDN.

## 1. Đặt thư mục mô hình

Giải nén dự án, sau đó giải nén **inference_XGBoost_d6_s42.zip** bạn đã tải từ Colab. Đặt thư mục con đó trong **`models/`** ở thư mục gốc repository. Các đường dẫn phải có dạng:

```text
Phishing_Detection/run.py
Phishing_Detection/models/inference_XGBoost_d6_s42/model.ubj
Phishing_Detection/models/inference_XGBoost_d6_s42/config.json
Phishing_Detection/models/inference_XGBoost_d6_s42/predict_url.py
Phishing_Detection/models/inference_XGBoost_d6_s42/url_features.py
Phishing_Detection/models/inference_XGBoost_d6_s42/url_preprocessing.py
```

Gói bạn xuất ở cell trước đã có đủ các tệp này. Nếu giải nén thêm một tầng thư mục, hãy đưa thư mục chứa trực tiếp `config.json` về vị trí trên. Ứng dụng cũng nhận gói cũ dùng `run.json` nếu `predict_url.py` đi kèm đọc đúng tệp đó.

Muốn dùng nơi khác: chép `.env.example` thành `.env`, sửa `MODEL_DIR` thành đường dẫn thư mục model. Sau khi thêm hoặc thay model, bấm **↻ Nạp lại mô hình** trên giao diện. Tên lượt huấn luyện, số feature và ngưỡng được đọc từ gói thật; ứng dụng không giả lập dự đoán khi thiếu model.

Chỉ nạp gói mô hình do bạn tự xuất hoặc đã kiểm tra: các tệp Python trong gói sẽ được import. Mô hình XGBoost chạy inference trên CPU. Bản này không nạp BERT; gói Random Forest/Logistic Regression được hỗ trợ nếu dùng cùng định dạng. Nếu dùng LightGBM, cài thêm `lightgbm==4.6.0`.

## 2. Cài đặt và chạy

Khuyến nghị **Python 3.11 hoặc 3.12**, môi trường mới, không cài chung với môi trường Colab cũ. Mở terminal tại thư mục gốc repository, nơi có `run.py`.

**Windows / PowerShell:**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements/base.txt
.venv\Scripts\python run.py
```

**Linux / macOS:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements/base.txt
.venv/bin/python run.py
```

Mở **http://127.0.0.1:8000**. Có thể dùng `localhost:8000`. Trên Linux x86_64, dự án cài `xgboost-cpu` cùng phiên bản 3.0.5 để tránh tải thư viện GPU. Các nền tảng khác dùng gói `xgboost` tiêu chuẩn. Không cần cài lại `requirements.txt` bên trong thư mục model.

Ứng dụng chỉ lắng nghe tại máy cục bộ. Bản này chưa có tài khoản, phân quyền hay giới hạn kinh phí theo người dùng; chưa được thiết kế để đưa công khai lên Internet.

## 3. Kết nối LLM theo hướng dẫn FPT

Trong giao diện, mở **Kết nối LLM**:

| Trường | Giá trị mặc định theo ảnh bạn cung cấp |
|---|---|
| API endpoint | `https://mkp-api.fptcloud.com/v1/chat/completions` |
| Tên model | `DeepSeek-V4-Flash` |
| API key | Key của tài khoản FPT được cấp quyền sử dụng model |

Có thể nhập endpoint đầy đủ hoặc URL gốc `https://mkp-api.fptcloud.com`; ứng dụng tự bổ sung đường dẫn. Không dán đường dẫn trang giới thiệu model vào ô endpoint. Nếu tài khoản cung cấp endpoint khác, sửa cả `FPT_ENDPOINT` và `LLM_ALLOWED_HOSTS` trong `.env` rồi khởi động lại.

Nếu không muốn nhập key mỗi lần tải lại trang, tạo `.env` từ `.env.example` và đặt `FPT_API_KEY`. Đừng commit `.env` lên GitHub. Key nhập trên giao diện được giữ trong phiên đang mở, không lưu xuống tệp hay lịch sử trình duyệt; key trong `.env` không được trả về giao diện.

Request gửi `Authorization: Bearer ...`, `model`, `messages`, `temperature=0.1`, `top_p=1`, `top_k=40`, `max_tokens=1024`. Dùng **`stream=false`** để nhận một JSON hoàn chỉnh rồi kiểm tra cấu trúc. Đây là chế độ không streaming của API chat completions; không cần OpenAI SDK.

Giới hạn chờ mặc định 45 giây cho toàn bộ lượt LLM, tối đa hai lượt đồng thời. Không tự động gọi lại khi lỗi để tránh phát sinh phí ngoài ý muốn. Có thể chỉnh `LLM_TIMEOUT_SECONDS`, `LLM_MAX_TOKENS` trong `.env`; ứng dụng chưa tự kiểm tra được số dư hoặc trừ chi phí theo USD. Nếu model dùng hết token trước khi hoàn tất JSON, giao diện thông báo rõ thay vì chấp nhận kết luận dang dở.

Tài liệu đối chiếu:

- [FPT: Call the Inference API](https://docs.fptcloud.com/docs/fpt-ai-factory/services/serverless-inference/tutorials/call-the-api/)
- [FPT: ví dụ tích hợp API, gồm chế độ không streaming](https://github.com/fpt-corp/ai-marketplace/blob/main/API%20Integration%20-%20Large%20Language%20Model.md)

## 4. Cách sử dụng

1. Chọn **Email / tin nhắn** hoặc **URL riêng lẻ**, dán dữ liệu. Giới hạn 8.000 ký tự và 5 URL khác nhau mỗi lượt.
2. Nếu chỉ muốn chạy ML, tắt **Phân tích thêm bằng LLM**. Phần này không gọi API và không tự truy cập URL.
3. Khi bật LLM, có thể chọn cung cấp hoặc không cung cấp kết quả ML cho LLM. Dữ liệu không có URL vẫn được phân tích bằng LLM.
4. Bấm **Phân tích nội dung**. Khi dùng LLM, ứng dụng mở bản xem trước đã che một số thông tin. Kiểm tra, sửa thêm nếu cần, đánh dấu đồng ý rồi gửi.
5. Xem cảnh báo tổng hợp, kết quả từng URL, nhận định LLM, bằng chứng và hướng dẫn. Có thể tải kết quả JSON về máy.

Việc che dữ liệu dùng quy tắc cho email, số điện thoại, mã xác thực/thông tin truy cập, dãy số dài, giá trị query, fragment và tài khoản trong URL. Quy tắc có thể bỏ sót hoặc che thừa; bản xem trước để bạn kiểm tra. Không có bước bảo đảm tự động che hết tên, địa chỉ hoặc mọi thông tin cá nhân. Khi bạn sửa bản gửi, LLM phân tích **bản đã sửa**; ML vẫn phân loại các URL trong bản gốc tại máy chạy ứng dụng.

Ứng dụng không lưu lịch sử nội dung vào cơ sở dữ liệu hoặc tệp log. Dữ liệu tồn tại tạm thời trong bộ nhớ để xử lý và trên giao diện cho đến khi bạn xóa/đóng trang. File JSON bạn chủ động tải có thể chứa URL gốc của lượt kiểm tra. Chính sách lưu dữ liệu tại FPT phụ thuộc dịch vụ và tài khoản của bạn.

## 5. Luồng xử lý và baseline hiện tại

- Trích xuất URL → sinh feature bằng đúng mã trong gói → mô hình ML → điểm và ngưỡng từ `config.json`.
- Che dữ liệu → người dùng xác nhận → LLM đọc văn bản và, nếu được bật, kết quả ML. Không gửi nguyên tham số nhạy cảm trong URL qua phần metadata ML.
- Kiểm tra JSON, giá trị cảnh báo, trích đoạn bằng chứng. Quote không xuất hiện trong bản đã gửi bị loại. Nhận định HIGH/WARNING thiếu bằng chứng hợp lệ chuyển thành UNKNOWN.
- Tổng hợp cảnh báo theo quy tắc trong `app/fusion.py`, hiển thị riêng ML/LLM khi hai bên khác nhau.

Prompt và dữ liệu được tách thành system/user message. LLM không có công cụ mở URL, tra WHOIS, thực thi lệnh hay tải tệp. Prompt injection được giảm thiểu bằng chỉ dẫn và kiểm tra đầu ra, chưa thể xem là đã giải quyết hoàn toàn. Bản này chưa có RAG, nguồn dẫn, blacklist thời gian thực, phân tích HTML hay xác minh tên miền ngân hàng.

| Tình huống | Kết quả tổng hợp |
|---|---|
| ML có URL HIGH | HIGH, kể cả khi LLM nhận định LOW hoặc API lỗi |
| LLM HIGH có bằng chứng hợp lệ | HIGH, kể cả khi URL có điểm thấp |
| ML WARNING hoặc LLM WARNING hợp lệ | Ít nhất WARNING |
| Có URL chưa đánh giá được, chưa có cảnh báo khác | UNKNOWN |
| URL riêng lẻ có ML LOW | LOW cho URL đó, kèm lưu ý phạm vi phân tích |
| Email/tin nhắn chỉ có ML LOW, LLM tắt/lỗi/UNKNOWN | UNKNOWN cho toàn bộ thông điệp |
| Không có URL, LLM hợp lệ | Dùng nhận định LLM |

**LOW** nghĩa là chưa phát hiện dấu hiệu rõ ràng qua phần đã phân tích; không đồng nghĩa chắc chắn an toàn. Điểm ML chưa được hiệu chỉnh thành xác suất. Không thay đổi ngưỡng hoặc tự huấn luyện lại khi khởi động ứng dụng.

## 6. Cấu trúc mã nguồn

| Vị trí | Vai trò |
|---|---|
| `run.py` | Chạy ứng dụng tại 127.0.0.1:8000 |
| `app/main.py` | API, phối hợp xử lý và phản hồi lỗi |
| `app/ml_service.py` | Tìm, nạp gói model, suy luận URL |
| `app/llm_service.py` | Prompt, API FPT, kiểm tra JSON và quote |
| `app/privacy.py` | Che dữ liệu trước khi gửi API |
| `app/urls.py` | Nhận diện, kiểm tra và gộp URL trùng |
| `app/fusion.py` | Quy tắc cảnh báo cuối |
| `app/static/` | Giao diện; không có bước build frontend |
| `tests/` | Kiểm thử quy tắc và API với phản hồi giả lập |
| `docs/architecture/BASELINE.md` | Phạm vi hiện tại, điểm cần đánh giá tiếp |

API chính: `GET /api/status`, `POST /api/model/reload`, `POST /api/preview`, `POST /api/analyze`. Tài liệu tương tác tự sinh tại `/docs` nếu cần thử bằng tay. Lưu ý không nhập key thật vào ảnh chụp hoặc commit kết quả request lên Git.

## 7. Kiểm thử và giới hạn xác minh

```bash
python -m pip install -r requirements/dev.txt
python -m pytest -q
```

Các test không gọi FPT thật và không phát sinh phí. Chúng kiểm tra tách URL, che dữ liệu, sự đồng ý gửi API, cấu trúc LLM, quy tắc kết hợp và giữ kết quả ML khi API lỗi. Giao diện được kiểm tra riêng ở kích thước máy tính và điện thoại.

Đã bổ sung kiểm thử với trọng số `models/inference_XGBoost_d6_s42` thật và API FPT thật. Model được đánh giá trên tập test PhishVN chính thức; hai cấu hình LLM được so sánh trên cùng 100 URL test. Xem [báo cáo PhishVN](../evaluation/PHISHVN.md) để đọc phương pháp, ngưỡng, số đo và giới hạn. Khi cài trên máy khác, vẫn cần đặt gói model và cấu hình API key riêng.

## 8. Xử lý lỗi thường gặp

- **Chưa tìm thấy model:** kiểm tra vị trí `config.json`/`predict_url.py`, sửa `MODEL_DIR`, bấm nạp lại. Không đổi tên tệp trong gói.
- **Thiếu thư viện khi nạp:** chạy lại `python -m pip install -r requirements/base.txt` bằng đúng Python đang chạy `run.py`. Nếu model khác loại, xem mục 1.
- **401/403:** key chưa hợp lệ hoặc chưa có quyền dùng model. **402:** kiểm tra số dư. **404:** kiểm tra chính xác endpoint/model trong tài khoản. **429:** đang giới hạn lượt gọi hoặc hạn mức.
- **JSON không hoàn chỉnh/hết token:** tăng `LLM_MAX_TOKENS` có kiểm soát rồi khởi động lại; không hạ mức cảnh báo dựa vào phản hồi lỗi.
- **Máy công ty bắt buộc proxy:** `httpx.AsyncClient` đang đặt `trust_env=False` trong `app/main.py`. Cấu hình proxy phù hợp môi trường của bạn trước khi gọi API; không tắt kiểm tra HTTPS.
- **Cổng 8000 bận:** đặt `PORT=8001` trong `.env` rồi mở đúng cổng. Mặc định không bind `0.0.0.0`.

## 9. Đánh giá có và không có model URL

**Đánh giá URL trên PhishVN:** xem [kết quả trên tập test chính thức](../evaluation/PHISHVN.md). Lượt này kiểm tra đúng phiên bản dữ liệu, fingerprint và feature của notebook; chạy ML trên toàn bộ 8.941 URL test và so sánh hai cấu hình LLM trên cùng 100 URL test có nhãn.

Đã có bộ chẩn đoán **60 email/tin nhắn tiếng Việt có URL**, cân bằng 30 phishing / 30 thông thường, và công cụ chạy hai cấu hình LLM thật với cùng prompt. Kết quả model URL, nhận định LLM và quy tắc fusion được đo riêng để phân biệt tác động của từng thành phần.

Xem [đánh giá và diễn giải kết quả](../evaluation/SYNTHETIC.md), [phương pháp và cách chạy](../evaluation/METHODS.md), [kết quả từng mẫu](../../artifacts/evaluations/url_model_ablation_v1/comparison.csv) và [báo cáo lần chạy](../../artifacts/evaluations/url_model_ablation_v1/report.md). Đây là dữ liệu mô phỏng tự gán nhãn, phục vụ chẩn đoán; không phải số đo Accuracy/F1 trên dữ liệu ngoài thực tế. Chạy `--live` sử dụng API key và token tài khoản FPT.

## 10. Kho tài liệu chuẩn bị cho RAG

Đã thu thập **25 nguồn riêng biệt từ 11 đơn vị**, gồm 15 cảnh báo thủ đoạn, 7 hướng dẫn/quy trình hợp lệ, 2 hướng dẫn xử lý sự cố và 1 tài liệu kết hợp. [Hướng dẫn kho tài liệu](../../data/knowledge/README.md), [danh mục nguồn CSV](../../data/knowledge/corpus_v1/sources.csv) và [corpus tóm lược có provenance](../../data/knowledge/corpus_v1/documents.jsonl) được lưu trong dự án. Nội dung là bản tóm lược biên tập có nguồn dẫn; 14 nguồn có ngày công bố được xác minh, các nguồn còn lại để trống thay vì đoán. Giai đoạn này chuẩn bị tài liệu; ứng dụng vẫn chạy baseline chưa dùng truy xuất RAG.
