# Phát triển và bảo trì

## Quy ước tổ chức

`app` chứa mã chạy ứng dụng; `evaluation` chứa protocol và phép đo; `scripts` chứa các tác vụ vận hành. Kiểm thử nằm trong `tests/api`, `tests/messages`, `tests/url`, `tests/rag`, `tests/data`, `tests/evaluation`, `tests/maintenance`.

Dữ liệu đầu vào thuộc `data`; gói suy luận thuộc `models`; mọi đầu ra mới thuộc `artifacts`. Không đặt CSV, response JSON, ảnh thử nghiệm hoặc tài liệu học thuật ở root. Raw API/URL nguồn và thông tin cá nhân chỉ giữ cục bộ theo chính sách Git hiện có.

Tài liệu mới cập nhật vào trang chủ đề tương ứng trong `docs`, thay vì thêm ghi chú `NEXT_Vn` hoặc chép lại hướng dẫn cài đặt. Phiên bản prompt/protocol vẫn được ghi trong nội dung và manifest thực thi.

Chạy từ thư mục gốc bằng Python 3.11/3.12:

```bash
.venv/bin/python -m pip install -r requirements/dev.txt
make test
make clean
```

`make clean` chỉ xóa cache Python/pytest/linter, không đi vào `models`, `data`, `artifacts` hoặc môi trường ảo. Xem trước bằng `.venv/bin/python scripts/maintenance/clean.py`.

## Đường dẫn sau tổ chức lại

| Trước | Hiện tại |
|---|---|
| `app.settings`, `app.privacy` | `app.core.settings`, `app.core.privacy` |
| `app.schemas`, `app.fusion`, `app.verdict_validation` | `app.domain.schemas`, `app.domain.decisions`, `app.domain.validation` |
| `app.quality`, `app.candidate_v6` | `app.api.stable`, `app.api.interaction` |
| `app.ml_service`, `app.url_char_service` | `app.services.url.features`, `app.services.url.character` |
| `app.llm_service`, `app.message_service` | `app.services.llm.client`, `app.services.llm.message` |
| `app.rag_service` | `app.services.rag.retrieval` |
| `evaluation.message_data`, `evaluation.review` | `evaluation.data.sms`, `evaluation.data.review` |
| `evaluation.component_ablation`, `evaluation.v6_pilot` | `evaluation.messages.components`, `evaluation.messages.interaction_pilot` |
| `evaluation.url_char_baseline`, `evaluation.url_source_audit` | `evaluation.url.character_baseline`, `evaluation.url.source_audit` |
| `evaluation.retrieval`, `evaluation.rag_controlled_v1` | `evaluation.rag.metrics`, `evaluation.rag.controlled` |

Các runner còn lại chuyển tương tự theo chức năng; xem `python -m MODULE --help` và [danh sách công cụ](../scripts/README.md). Import cũ không được duy trì bằng hàng chục file trung gian. `python run.py` tiếp tục chạy bản v4; `app.main:app` nay là entry point ổn định thay cho entry point v3 cũ.

Mọi đường dẫn dữ liệu tương đối được giải theo `app.core.settings.ROOT`; không tính project root từ số tầng của file test/runner. Khi khóa mã nguồn, dùng đường dẫn đầy đủ và duyệt đệ quy các package cần thiết.

## Tính toàn vẹn khi chuyển cấu trúc

Không huấn luyện lại hoặc đổi ngưỡng vì đổi vị trí mã. Giữ nguyên dữ liệu, `.env`, notebook, trọng số và manifest thực nghiệm lịch sử. Bộ nạp URL ký tự kiểm tra hash source nên cần gói suy luận tương thích với layout mới tại `models/url_character/`.

Khi đã có snapshot dự đoán trước refactor, chuyển gói bằng:

```bash
.venv/bin/python scripts/maintenance/repackage_character.py \
  --source artifacts/evaluations/url_char_baseline_v1/deployment \
  --baseline-dir artifacts/maintenance/restructure_20261110
```

Lệnh sao chép nguyên byte trọng số/vocabulary, ghi provenance chuyển gói và chỉ hoàn tất khi toàn bộ score validation khớp bit. Không fit, mở test hoặc ghi lại manifest cũ. Snapshot dùng cho lần chuyển này giữ cục bộ; máy khác cần cài gói đã chuyển tương thích hoặc tạo snapshot trước khi refactor. Không chỉ thay hash trong export để ép model nạp.

## Tái lập lịch sử

<a id="tai-lap-lich-su"></a>

Các run đã khóa source hash sẽ chủ động từ chối mã sau refactor. Không sửa manifest cũ để làm lượt chạy có vẻ đã được tái lập. Dùng source trước lần chuyển cấu trúc trong worktree riêng:

```bash
git worktree add --detach ../phishlens-reproduction 479c96612ca79d3e1de2d37df22d82ce19e09f23
```

Cài đúng môi trường và cung cấp bản sao các asset cục bộ theo manifest; dùng hướng dẫn/lệnh trong worktree đó. Mốc này có source ngay trước refactor, không tự bảo đảm khớp mọi thí nghiệm còn cũ hơn; nếu validator báo sai hash, tìm đúng commit gốc của lần chạy.

Để tái sử dụng dữ liệu trong thí nghiệm mới, vẫn kiểm hash toàn bộ input, nhãn và split rồi đăng ký runtime mới. `evaluation.data.benchmark.verify(..., check_runtime=False)` chỉ xác nhận dữ liệu/artifact của gói; không xác nhận phát lại pipeline lịch sử. Runner component khóa runtime của riêng nó sau bước này. Mặc định `verify` vẫn kiểm source hash.

Ghi kết quả mới vào `--out` mới. Không sửa báo cáo cũ, đổi nhãn AI thành gold, bỏ lỗi hoặc chọn seed theo test để có bảng đẹp.
