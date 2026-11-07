# Khóa bộ URL mới trước khi đánh giá

Đã có **công cụ**, chưa có bộ calibration/test mới được xác minh. Công cụ này thực thi kế hoạch thu thập trong [URL_CALIBRATION_V1.md](URL_CALIBRATION_V1.md); không tải trang nghi ngờ, tạo nhãn, gọi API, huấn luyện hoặc chọn ngưỡng. Không thay các thí nghiệm đã khóa.

## Quy trình

1. Chuẩn bị danh mục URL/miền/campaign đã sử dụng, gồm đủ bốn nhóm `train`, `validation`, `historical_test`, `adaptive`. Bao gồm dữ liệu URL cũ, các ca đã dùng sửa prompt/model, kho reputation và URL trong tài liệu RAG. Công cụ kiểm tra các nhóm đã được khai báo nhưng **không tự chứng minh danh mục đầy đủ**.
2. `register` khóa danh mục đó, model, corpus, ngưỡng, mã chuẩn hóa và snapshot PSL. Thời điểm đăng ký phải trước mốc bắt đầu test. Có thể dùng calibration đã thu trước đó để quyết định chính sách, rồi đăng ký chính sách trước test tương lai; không sửa các tệp đã khóa.
3. Thu dữ liệu có bằng chứng; tạo JSONL đầu vào, sau đó `prepare` sang thư mục mới. Trước cutoff là calibration; từ cutoff là test. Ngày thu không được nằm ngoài cửa sổ đã đăng ký hoặc ở tương lai so với lúc nhập.
4. Review bằng bản sao các phiếu mù. Sau review, tạo đầu vào và pack phiên bản mới, giữ nguyên provenance; không sửa phiếu trong pack đã khóa. `verify` phát hiện thay đổi các tệp đầu vào, bằng chứng, model, corpus và pack.
5. Chỉ báo test sau khi đủ điều kiện cả hai giai đoạn. `report` đọc score đã lưu và áp chính sách đã đăng ký, không chạy model hoặc tìm ngưỡng. Dùng công cụ hiện hành để quản lý lượt suy luận riêng; không gửi nhãn/nguồn/phiếu review vào model.

Mỗi phần cần ít nhất **200 dương, 400 âm đã review**, từ ít nhất hai nguồn cho từng lớp. Một URL trên mỗi registrable domain; mỗi miền/campaign thuộc một phần và không giao lịch sử. Campaign chưa xác định được giữ `null` và chặn trạng thái ready. Quota là điều kiện tổ chức dữ liệu, không chứng minh tính đại diện hay đủ lực thống kê cho từng nhóm nhỏ.

`external_source_provisional` luôn là nhãn nguồn sơ bộ, không tính vào quota người review. `human_verified` cần hai ID người review khác nhau và lý do; ID chỉ là khai báo, không xác thực danh tính. Không tạo hai danh tính AI để qua điều kiện này. Nguồn chính thức vẫn có thể có lỗi hoặc nhãn abuse rộng hơn phishing; giữ cùng định nghĩa lớp URL fraud/abuse của lượt so sánh, báo riêng nếu thay định nghĩa.

## Đầu vào

Exclusions JSONL: mỗi dòng có `exposure` thuộc bốn nhóm ở trên và ít nhất một trường `url`, `domain`, `campaign`. Miền khai báo phải là registrable domain đã chuẩn hóa. Các ca giao lịch sử được ghi vào `excluded_regression.jsonl`, **không đổi tên thành future test**. Phần này có thể dùng làm regression ở một lượt khác.

Ví dụ cấu trúc một dòng exclusion (chỉ minh họa schema): `{"exposure":"train","url":"https://example.org/path","campaign":"source-campaign-id"}`. `url` tự sinh khóa miền; nếu thêm `domain`, giá trị đó phải khớp registrable domain chuẩn hóa. Không cần có campaign khi dữ liệu lịch sử chưa cung cấp, nhưng phải ghi nhận giới hạn này khi diễn giải độ độc lập.

Chuẩn hóa chạy offline với private PSL, IDNA, scheme/host/port chuẩn và bỏ fragment; giữ path/query có ý nghĩa. Suffix chưa biết được gom thận trọng theo hai nhãn cuối. Các cách viết IPv4 rút gọn/hex/octal không chuẩn và IPv6 có zone ID bị từ chối thay vì gán khóa miền có thể sai; IPv4-mapped IPv6 dùng cùng khóa miền với IPv4. Source/campaign/reviewer ID không được có khoảng trắng đầu/cuối. Campaign/source được so không phân biệt hoa thường khi kiểm tra nhóm; hai reviewer ID chỉ khác hoa thường cũng không được tính hai người.

Incoming JSONL yêu cầu:

| Trường | Ý nghĩa |
|---|---|
| `id`, `url`, `domain` | ID duy nhất, URL HTTP(S) đầy đủ và registrable domain đúng với URL |
| `campaign` | Mã nhóm campaign/template đã kiểm tra hoặc `null` nếu chưa rõ |
| `collected_at` | Thời điểm UTC rõ ràng, kết thúc bằng `Z` hoặc `+00:00` |
| `source` | Mã nguồn dữ liệu; không sử dụng prediction để phân nhóm nguồn |
| `label` | `0`, `1` hoặc `null`; nhãn URL-risk, không phải nhãn spam của tin nhắn |
| `label_status` | `external_source_provisional` hoặc `human_verified` |
| `label_scope` | `url_risk` hoặc `official_origin_reference` |
| `reviewer_ids` | Danh sách ID đã khai báo; nhãn người review cần ít nhất hai ID khác nhau |
| `rationale` | Lý do, bắt buộc với nhãn người review |
| `tier` | Tùy chọn, giữ tier nguồn; không tự nâng tier |
| `evidence` | Các trường ở dưới |

`evidence` có đúng sáu trường: `url` (HTTPS, không userinfo), `publisher`, `kind="primary"`, `published_at` (UTC, không muộn hơn ngày thu), `snapshot_path` và `snapshot_sha256`. Snapshot cục bộ phải tồn tại, có nội dung và khớp hash. Đường dẫn tương đối tính từ thư mục incoming. Đây là kiểm tra tính toàn vẹn; **không tự xác nhận nội dung nguồn đúng hay URL đang an toàn**.

Một tuyến được công bố trên nguồn chính thức có thể ghi `label_scope="official_origin_reference"`, nhưng **`label` bắt buộc `null`**. Không đưa tuyến này vào mẫu âm hoặc mẫu số FPR chỉ vì hostname chính thức. Muốn có nhãn URL-risk cần review và bằng chứng đúng nhiệm vụ riêng.

Không chấp nhận trường score/prediction trong incoming. Phiếu CSV mù không chứa nhãn nguồn, score, model hay trạng thái nhãn; vẫn có URL và bằng chứng để review nên không gọi là mù hoàn toàn. Các ô có nguy cơ công thức spreadsheet được escape.

## Lệnh

Khởi tạo tệp ngưỡng JSON cho đúng tên model, ví dụ chính sách candidate đã khóa:

```json
{"char": {"low": 0.5, "high": 0.5259423981707284}}
```

Các đường dẫn và thời gian dưới đây là **ví dụ cách gọi**, không phải dữ liệu đã thu hay một đăng ký đã hoàn tất:

```bash
.venv/bin/python -B -m evaluation.prospective_url_benchmark register \
  --exclusions /path/to/complete_exposure_index.jsonl \
  --model-lock char=artifacts/evaluations/url_char_baseline_v1/deployment \
  --corpus-lock data/knowledge/corpus_v1/documents.jsonl \
  --thresholds /path/to/frozen_thresholds.json \
  --collection-start 2026-11-07T00:00:00Z \
  --cutoff 2026-11-21T00:00:00Z \
  --out artifacts/evaluations/prospective_url_registration_v1

.venv/bin/python -B -m evaluation.prospective_url_benchmark prepare \
  --protocol artifacts/evaluations/prospective_url_registration_v1 \
  --incoming /path/to/collected_urls.jsonl \
  --out artifacts/evaluations/prospective_url_pack_v1

.venv/bin/python -B -m evaluation.prospective_url_benchmark verify \
  --pack artifacts/evaluations/prospective_url_pack_v1
```

`--model-lock NAME=PATH` và `--exclusions PATH` nhận nhiều lần. Model có thể là tệp hoặc thư mục; thư mục khóa mọi file trọng số/vocabulary và danh mục file. Không chỉ khóa manifest rồi bỏ qua weights. Corpus, code và dữ liệu phải còn nguyên khi verify; đổi pipeline cần đăng ký phiên bản mới trước test mới.

`report --pack DIR --predictions FILE --stage calibration|test --out NEW` nhận JSONL score đã lưu: mỗi dòng có đúng `id`, `model`, `score`, `status`. `status="ok"` cần score hữu hạn 0–1; lỗi có `status="error", score=null`. Cần đúng một dòng cho từng ID có nhãn nhị phân của stage và từng model đã đăng ký. Không đưa mẫu `official_origin_reference` hoặc UNKNOWN tham chiếu vào score file cho lượt report này.

Report tách nhãn nguồn sơ bộ/người review, báo theo nguồn, giữ lỗi ở UNKNOWN, Recall toàn mẫu, FPR, coverage, Wilson 95% và PPV ở các prior **giả định** 0,1%/1%/5%. Nhóm chỉ một lớp không báo Precision/F1. Wilson giả định độc lập, có thể quá hẹp khi campaign chứa nhiều miền; không thể hiện sai nhãn hay chuyển nguồn. PPV chỉ phân tích độ nhạy nếu Recall/FPR chuyển nguyên sang quần thể khác, không là tỷ lệ phishing thực đo hoặc xác suất riêng của một URL. Không gộp các lớp nhãn hoặc lấy kết quả tốt nhất để tuyên bố thắng.

Score file do bên chạy thí nghiệm cung cấp; công cụ này kiểm schema, ID, hash và chính sách chấm nhưng chưa tự chứng minh score được sinh bởi đúng model/code đã đăng ký. Lượt suy luận cần journal/hash và kiểm chứng riêng. Các sidecar SHA-256 phát hiện sửa nhầm metadata, không phải chữ ký số hoặc ranh giới bảo mật trước người có thể sửa cả dữ liệu lẫn hash.

## Trạng thái hiện tại

Sau [lượt phát triển nguồn/dữ liệu v2](../architecture/SOURCE_AND_DATA_V2.md), dùng [đăng ký v2](../../artifacts/evaluations/prospective_url_registration_v2/protocol.json) cho lượt thu tiếp theo. V2 bổ sung 236 dòng adaptive: 36 tuyến chính thức đã được chọn và 200 URL feed đã chấm. [Pack v2](../../artifacts/evaluations/prospective_url_pack_v2/manifest.json) đã verify, vẫn 0 mẫu đủ điều kiện, `ready=false`. V1 bên dưới giữ như mốc lịch sử, không bị sửa dữ liệu hoặc dùng lại để bỏ qua exposure mới.

Ngày 07/11 đã tạo [đăng ký cục bộ](../../artifacts/evaluations/prospective_url_registration_v1/protocol.json) với cutoff **14/11/2026 00:00 UTC**, khóa model ký tự/XGBoost và hai chính sách vận hành riêng hiện có. Đây là chuẩn bị phép so sánh pipeline, không phải đối chứng cùng ngưỡng hoặc một calibrator mới được học. [Index và provenance](../../artifacts/evaluations/prospective_url_inputs_v1/provenance.json) có 60.453 dòng URL theo exposure: 36.909 train, 7.266 validation, 8.941 test lịch sử, 7.337 adaptive. URL có thể lặp giữa nhóm exposure; không gọi tổng này là số URL độc lập hoặc dữ liệu mới. Đọc metadata URL lịch sử để loại trừ, không mở SMS holdout hoặc chạy inference mới. Danh mục campaign lịch sử chưa đầy đủ, completeness vẫn là khai báo.

[Pack khởi tạo](../../artifacts/evaluations/prospective_url_pack_v1/manifest.json) đã verify: **0 mẫu mới, `ready=false`**. Không cho xuất số đo test khi chưa đủ dữ liệu, nguồn/bằng chứng và review thực. Các fixture trong unit test là dữ liệu nhân tạo dùng kiểm tra hợp đồng phần mềm, **không xuất thành corpus hoặc bằng chứng chất lượng model**. Không đổi tên test PhishVN đã xem thành holdout mới. Protocol khóa toàn bộ file trong model bundle; các thay đổi bundle hoặc code cần một đăng ký mới trước test mới.
