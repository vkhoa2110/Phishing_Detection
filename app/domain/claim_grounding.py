"""Conservative presentation checks; lexical cues never establish scam truth.

Keep the classifier's level, context and reason code intact. This layer prevents
a deterministic reason template from asserting a mechanism absent from its
quote. It cannot resolve impersonation, quotation roles or semantic entailment.
"""
from copy import deepcopy
import re
import unicodedata

from app.domain.validation import REDACTION_PATTERN
from app.services.url.parsing import URL_PATTERN

VERSION = "reason-presentation-1.0"
NEUTRAL_SUMMARY = (
    "AI đưa ra cảnh báo, nhưng trích dẫn chưa thể hiện đủ cơ chế cụ thể mà AI chọn. "
    "Cần đối chiếu yêu cầu với người gửi qua kênh đã biết."
)
NEUTRAL_REASON = "Trích đoạn AI dùng làm căn cứ; chưa đủ dấu hiệu để nêu cơ chế lừa đảo cụ thể."
REVIEW_NOTICE = "Lý do cụ thể AI chọn chưa khớp đủ dấu hiệu trong trích dẫn. Mức cảnh báo vẫn là nhận định của AI; cần xác minh thêm."

# Necessary surface cues, not sufficient evidence of maliciousness. No score or
# inherited label participates. Prefer a neutral explanation when in doubt.
TRANSFER = r"\b(gui|doc|chia se|cung cap|chuyen tiep|nhan lai)\b"
SECRET = r"\b(otp|mat khau|ma xac thuc|ma xac nhan|ma pin|pin|cvv|cvc|seed phrase|khoa bi mat)\b"
PAY = r"\b(nop|dong|chuyen|tra|thanh toan)\b"
MONEY = r"\b(tien|phi|coc|vnd|dong|usd|hoa don|thanh toan)\b"
CONTROL = r"\b(dieu khien tu xa|anydesk|teamviewer|quyen dieu khien|chia se man hinh)\b"
PERMISSION = r"\b(cap quyen|cho phep|uy quyen|chap thuan quyen|trao quyen)\b"

RULES = {
    "secret_request": {"secret": SECRET, "sharing_action": TRANSFER},
    "remote_control": {"control": CONTROL, "grant_or_install": r"\b(cap|bat|cai|cho phep|chap nhan|chia se|trao)\b"},
    "advance_fee": {
        "payment_action": PAY, "fee_or_deposit": r"\b(phi|coc|bao hiem|thue|ung truoc)\b",
        "promised_benefit": r"\b(de nhan|nhan viec|nhan thuong|nhan qua|nhan giai|rut tien|giai ngan|nhan lai|hoan tien|hoan thue|mo khoa tien)\b",
    },
    "payment_redirection": {
        "money": MONEY, "changed_destination": r"\b(thay doi|doi sang|chuyen sang|tai khoan moi|noi nhan moi|so tai khoan moi)\b",
        "bypass_verification": r"\b(bo qua xac minh|khong can xac minh|dung goi|khong goi|dung xac minh|khong can goi)\b",
    },
    "account_access": {"permission": PERMISSION, "account_or_access": r"\b(tai khoan|dang nhap|truy cap|hop thu|email)\b"},
    "coercive_request": {
        "coercion_or_secrecy": r"\b(de doa|bat giu|khoa tai khoan|phong toa|giu bi mat|khong duoc ke|khong bao cho|dung bao)\b",
        "asset": rf"(?:{SECRET}|{MONEY}|{CONTROL}|{PERMISSION})",
        "action": rf"(?:{TRANSFER}|{PAY}|{PERMISSION})",
    },
}
TEMPLATES = {
    "secret_request": "AI nghi ngờ yêu cầu chia sẻ bí mật hoặc mã xác thực; cần kiểm tra bên nhận và mục đích.",
    "remote_control": "AI nghi ngờ yêu cầu liên quan quyền điều khiển từ xa; cần xác minh quyền được cấp và bên nhận.",
    "advance_fee": "AI nghi ngờ yêu cầu trả phí trước để nhận lợi ích; cần xác minh điều kiện và bên nhận tiền.",
    "payment_redirection": "AI nghi ngờ yêu cầu đổi nơi nhận tiền kèm bỏ qua xác minh; cần liên hệ lại qua kênh đã biết.",
    "account_access": "AI nghi ngờ yêu cầu cấp quyền tài khoản; cần kiểm tra quyền được cấp và bên nhận.",
    "coercive_request": "AI nghi ngờ yêu cầu liên quan tiền hoặc quyền truy cập kèm đe dọa hay giữ bí mật; cần xác minh thêm.",
}
NEGATION = re.compile(
    r"\b(?:khong|dung|cho|tuyet doi khong)(?: bao gio| nen| duoc| can| phai)? "
    r"(?:gui|doc|chia se|cung cap|chuyen|nop|dong|tra|cap quyen|cai)\b|"
    r"\bkhong (?:can|thu|yeu cau|phai)(?: dong|tra|nop)? (?:phi|coc|tien)\b|"
    r"\bkhong yeu cau (?:gui|doc|cung cap|cap quyen)\b"
)
PREVENTIVE = re.compile(r"\b(canh bao|khuyen cao|vi du|tinh huong mo phong|bai hoc)\b")


def normalized_quote(quote):
    value = REDACTION_PATTERN.sub(" ", URL_PATTERN.sub(" ", quote))
    value = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9.!?;\n]+", " ", value).strip()


def check_quote(reason_code, quote):
    """Require all cues in one clause; do not combine unrelated evidence spans."""
    requirements = RULES[reason_code]
    clauses = [c.strip() for c in re.split(r"[.!?;\n]+", normalized_quote(quote)) if c.strip()]
    checks = []
    for clause in clauses:
        missing = [name for name, pattern in requirements.items() if not re.search(pattern, clause)]
        cautions = []
        if NEGATION.search(clause): cautions.append("NEGATED_ACTION")
        if PREVENTIVE.search(clause): cautions.append("PREVENTIVE_OR_EXAMPLE_LANGUAGE")
        checks.append({"missing_cues": missing, "caution_flags": cautions})
    best = min(checks, key=lambda c: (len(c["missing_cues"]) + len(c["caution_flags"]), len(c["missing_cues"]))) if checks else {
        "missing_cues": list(requirements), "caution_flags": []}
    return {"status": "lexical_cues_present" if not best["missing_cues"] and not best["caution_flags"] else "needs_review", **best}


def guard_presentation(result):
    """Return a copy; idempotent, no change to classification or technical status."""
    output = deepcopy(result)
    if output.get("status") != "ok" or not isinstance(output.get("core_decision"), dict):
        return output
    core = output["core_decision"]
    verdict = output["verdict"]
    code = core.get("reason_code")
    audit = {"version": VERSION, "reason_code": code, "method": "necessary_lexical_cues_only",
             "semantic_support_verified": False, "decision_changed": False, "quote_checks": []}
    if verdict.get("risk_level") not in {"HIGH", "WARNING"} or code not in RULES:
        output["claim_grounding"] = {**audit, "status": "not_applicable"}
        return output
    text = output.get("input_used")
    for index, item in enumerate(verdict["evidence"]):
        check = check_quote(code, item["quote"])
        # Normal parsing establishes exactness. Also enforce it here for tools
        # invoking this layer on external records rather than a parsed response.
        if text is not None and item["quote"] not in text:
            check = {"status": "needs_review", "missing_cues": [], "caution_flags": ["QUOTE_NOT_IN_INPUT"]}
        audit["quote_checks"].append({"index": index, **check})
        item["reason"] = TEMPLATES[code] if check["status"] == "lexical_cues_present" else NEUTRAL_REASON
    present = any(c["status"] == "lexical_cues_present" for c in audit["quote_checks"])
    audit["status"] = "lexical_cues_present" if present else "needs_review"
    verdict["summary"] = TEMPLATES[code] if present else NEUTRAL_SUMMARY
    if not present:
        warnings = output.setdefault("warnings", [])
        if REVIEW_NOTICE not in warnings: warnings.append(REVIEW_NOTICE)
    output["validation"] = {**output.get("validation", {}), "summary_origin": VERSION,
                            "semantic_support_verified": False}
    output["claim_grounding"] = audit
    return output
