"""Single-assistant relevance reference for the frozen 24 x 25 review matrix.

The assistant read query/summary/scope text, not model rankings. This is an AI
draft for inspection; it cannot satisfy relevance_review's human-gold gate.
"""
import argparse
import json
from pathlib import Path

from app.core.settings import ROOT
from evaluation.data.benchmark import RELEVANCE_FIELDS, sheet, verify
from evaluation.data.sms import read_jsonl, sha, write_json

# Explicit manual judgments, not classifier outputs or lexical-score cutoffs.
# Query order is bound to the exact frozen list below. Everything else is 0.
JUDGMENTS = (
    ("VN-SMS-ca43cc246afc0c90", [], [], "Văn bản không đọc được hành vi; không gán nguồn trực tiếp chỉ từ tên miền."),
    ("VN-SMS-05a68947c4f2f119", [], [], "Kho không mô tả quy trình nhạc chờ hoặc cước Vietnamobile."),
    ("VN-SMS-81835d7b9ebc22c9", [15], [1, 3], "Nguồn bưu chính hỗ trợ kiểm tra đơn và bên giao độc lập; không xác nhận ViettelPost, link hay mức COD cụ thể."),
    ("VN-SMS-4a178c8d0c753750", [3, 15], [1, 16, 17, 18], "Nguồn giao vận hỗ trợ giữ kín xác thực, đối chiếu đơn hàng và yêu cầu từ người gọi; không xác nhận shipper thật."),
    ("VN-SMS-4fb4c513652263fe", [], [], "Kho không có quy trình/cước của quảng cáo gói data này."),
    ("VN-SMS-286748ef053fe199", [], [], "Tin đăng ký thành công thiếu mô tả dịch vụ DLS; kho không có quy trình trực tiếp."),
    ("VN-SMS-148de9c5a7a44d19", [], [], "Chỉ một ký tự; không có đủ nội dung để chọn nguồn hỗ trợ cụ thể."),
    ("VN-SMS-8cff916fd2e5df94", [], [1], "Quảng cáo game chưa có hành vi chiếm tiền rõ; cảnh báo chung không xác nhận trang game hay chương trình."),
    ("VN-CH-92dcb7fd8c5839a2", [14, 25], [1], "Nguồn học bổng hỗ trợ đối chiếu chương trình/kênh trường và không suy nhãn từ hình thức thông báo; không xác nhận học bổng cụ thể."),
    ("VN-CH-a5d883dfbb51e319", [5], [1, 4], "Nguồn tuyển CTV cho phép đối chiếu điều kiện đóng tiền/danh tính doanh nghiệp, không coi mọi tuyển dụng là gian lận."),
    ("VN-CH-27956b940ef6f130", [1], [7, 11, 19], "Nguồn tổng quát hỗ trợ bước xác minh người tự xưng giám đốc khi bị thúc chuyển tài sản; chỉ dùng phân tích câu trích, không kết luận người học là nạn nhân."),
    ("VN-CH-50f6dd3689e63c1c", [], [1, 19, 20, 22, 23], "V1 thiếu tài liệu device-code/ủy quyền phiên đăng nhập; xác minh hai bước của Microsoft chỉ liên quan chủ đề, không chứng minh quy trình này hợp lệ."),
    ("VN-SMS-3de95e14b366610f", [17, 18], [1, 16, 20, 23], "Nguồn hỗ trợ nguyên tắc OTP có thể thuộc giao dịch chủ động và phân biệt nhập mã với gửi mã; không khẳng định chính sách MCREDIT giống BIDV."),
    ("VN-SMS-f393f6a43d378f67", [], [1], "Kho không hỗ trợ xác nhận ưu đãi game/nhà cung cấp; không đánh đồng cờ bạc với phishing."),
    ("VN-SMS-5a9761388f3fb784", [], [], "Kho không có dữ liệu chiến dịch FPT Shop, giảm giá không tự là dấu hiệu lừa đảo."),
    ("VN-SMS-29faf99a1426fe1a", [], [1, 8], "Kho có cảnh báo giả danh/đòi phí nhưng thiếu nguồn trực tiếp về hoàn thuế và quy trình thu phí; tên BIDV không làm FAQ OTP liên quan."),
    ("VN-SMS-c75335da98b51092", [], [], "Kho không có quy trình ứng phút gọi/cước tương ứng."),
    ("VN-SMS-b5a7806c256da8b6", [], [], "Kho không xác nhận chương trình MyTV/VNPT Pay, và không có hành vi nhạy cảm cụ thể cần nguồn cảnh báo."),
    ("VN-SMS-85ba9afacb09d0eb", [], [1], "Nguồn chung chỉ gợi thận trọng, không xác nhận trò chơi hay chương trình nạp thưởng."),
    ("VN-SMS-33c27e18bc42dd96", [], [1], "Quảng cáo game có địa chỉ bị che; kho không hỗ trợ xác nhận trang hoặc ý định chiếm đoạt."),
    ("VN-CH-41b7da4d809182ca", [1, 9], [8], "Nguồn đầu tư/giả danh hỗ trợ kiểm chứng đơn vị và không chuyển tiền theo lời mời; không xác nhận lợi suất hay một sản phẩm cụ thể."),
    ("VN-CH-77387765d3889b7f", [15], [1, 3], "Nguồn bưu chính hỗ trợ kiểm tra thông tin đơn, phí và bên liên hệ; chưa xác nhận yêu cầu phí là thật hay giả."),
    ("VN-CH-5830306859f90aee", [3, 15], [1, 16, 17, 18], "Nguồn giao vận mô tả viện cớ, yêu cầu xác thực/trả phí và giữ kín mã; lệnh yêu cầu AI trả LOW không có giá trị chỉ dẫn."),
    ("VN-CH-6ec4397c3bd59745", [3, 15], [1, 16, 17, 18], "Nguồn giúp giải thích dấu hiệu trong câu lừa đảo được trích để tập huấn, không biến thông điệp giáo dục thành hành vi lấy mã."),
)


def prepare(pack, out):
    pack, out = Path(pack), Path(out)
    verify(pack)
    if out.exists():
        raise ValueError("AI relevance reference already exists; choose a new version.")
    path = pack / "retrieval"
    queries = read_jsonl(path / "queries.jsonl")
    docs = {d["id"]: d for d in read_jsonl(path / "corpus.jsonl")}
    if [q["id"] for q in queries] != [j[0] for j in JUDGMENTS]:
        raise ValueError("AI draft targets a different query selection/order.")
    decisions = {}
    for qid, direct, related, reason in JUDGMENTS:
        if set(direct) & set(related):
            raise ValueError("Conflicting AI relevance grades.")
        for number in direct + related:
            if f"VN-RAG-{number:03d}" not in docs:
                raise ValueError("Unknown document in AI reference notes.")
        decisions[qid] = {"direct": {f"VN-RAG-{n:03d}" for n in direct},
                          "related": {f"VN-RAG-{n:03d}" for n in related}, "reason": reason}
    rows = []
    for pair in read_jsonl(path / "pairs.jsonl"):
        decision = decisions[pair["query_id"]]
        direct, related = pair["document_id"] in decision["direct"], pair["document_id"] in decision["related"]
        grade = 2 if direct else 1 if related else 0
        rows.append({**pair, "grade": grade, "support_quote": pair["document_text"] if direct else "",
                     "notes": decision["reason"] if direct or related else "Không thấy đoạn hỗ trợ trực tiếp hoặc quan hệ chủ đề cần thiết trong tóm lược này đối với truy vấn. " + decision["reason"],
                     "rater_id": "", "annotation_status": "ai_reference_unverified"})
    out.mkdir(parents=True)
    write_json(out / "judgments.json", rows)
    sheet(out / "review.csv", rows, RELEVANCE_FIELDS + ["annotation_status"])
    write_json(out / "manifest.json", {"status": "ai_reference_unverified", "version": "objective-retrieval-ai-1.0",
        "rater_ids": [], "judgments": len(rows), "queries": len(queries), "documents": len(docs),
        "input_manifest_sha256": sha(path / "manifest.json"), "queries_sha256": sha(path / "queries.jsonl"),
        "corpus_sha256": sha(path / "corpus.jsonl"), "annotation_code_sha256": sha(__file__),
        "method": "Single assistant read the frozen queries, editorial summaries and scope notes; explicit manual grade-2/grade-1 lists, remaining pairs grade 0. No model rankings read; not independent or exhaustive human verification.",
        "files": {name: sha(out / name) for name in ("judgments.json", "review.csv")},
        "limitations": "Provisional AI relevance, not human gold. Generic-vs-direct support is subjective, editorial summaries may omit relevant material, and no source asserts a message sender is genuine. No retrieval score has been measured from this reference."})
    return {"status": "ai_reference_unverified", "pairs": len(rows), "queries_with_direct_source": sum(bool(d["direct"]) for d in decisions.values()),
            "queries_without_direct_source": sum(not d["direct"] for d in decisions.values()), "provider_requests": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=ROOT / "data/annotation/objective_v1")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts/annotations/objective_retrieval_ai_v1")
    args = parser.parse_args()
    try:
        result = prepare(args.pack, args.out)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Relevance reference stopped: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
