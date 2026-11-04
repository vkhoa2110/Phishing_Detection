"""Structural checks for message-v3; these do not establish semantic truth."""
import re

from .schemas import MessageRAGVerdict, MessageVerdict
from .urls import URL_PATTERN


VALIDATION_VERSION = "message-structural-validation-1.0"
FALLBACK_ACTIONS = (
    "Chưa đủ căn cứ kết luận. Xác minh với người gửi qua một kênh liên hệ bạn đã biết.",
    "Chưa mở liên kết, chuyển tiền hoặc cung cấp mật khẩu, mã OTP khi chưa xác minh được yêu cầu.",
)
REDACTION_PATTERN = re.compile(
    r"\[(?:EMAIL|PHONE|SECRET|NUMBER|AUTH|URL_KHONG_PHAN_TACH_DUOC)\]|\bREDACTED\b",
    re.IGNORECASE,
)


def has_behavior_text(value: str) -> bool:
    """Require content beyond URLs, masking markers and punctuation, without a length rule.

    Passing this check does not mean the fragment proves a dangerous action.
    Semantic relevance still needs independent evaluation.
    """
    residual = REDACTION_PATTERN.sub("", URL_PATTERN.sub("", value))
    return any(character.isalnum() for character in residual)


def is_url_only(value: str) -> bool:
    return bool(URL_PATTERN.search(value)) and not has_behavior_text(value)


def validate_message_verdict(
    verdict: MessageVerdict,
    text: str,
    sources: list[dict] | None,
    *,
    context_explicit: bool,
) -> tuple[MessageVerdict, list[str], dict]:
    """Validate v3 output, preserve supported alarms, and record structural limitations."""
    original_level = verdict.risk_level
    warnings, codes = [], []
    must_abstain = False

    def issue(code: str, message: str) -> None:
        if code not in codes:
            codes.append(code)
            warnings.append(message)

    verdict.summary = verdict.summary.strip()
    if not verdict.summary:
        must_abstain = True
        issue("SUMMARY_BLANK", "Nhận định không có nội dung; cần kiểm tra lại.")

    evidence = []
    for item in verdict.evidence:
        quote, reason = item.quote.strip(), item.reason.strip()
        if not quote or not reason:
            issue("EVIDENCE_BLANK", "Đã loại bằng chứng có trích đoạn hoặc lý do trống.")
        elif quote not in text:
            issue("EVIDENCE_NOT_IN_INPUT", "Đã loại bằng chứng không xuất hiện trong bản nội dung gửi tới LLM.")
        elif not has_behavior_text(quote):
            issue("EVIDENCE_NO_BEHAVIOR_TEXT", "Đã loại bằng chứng chỉ có URL, ký hiệu che dữ liệu hoặc dấu câu.")
        else:
            evidence.append(item.model_copy(update={"quote": quote, "reason": reason}))
    verdict.evidence = evidence

    if isinstance(verdict, MessageRAGVerdict):
        allowed = {source["document_id"]: source for source in (sources or [])}
        support, seen = [], set()
        for item in verdict.knowledge_support:
            quote, claim = item.source_quote.strip(), item.claim.strip()
            source = allowed.get(item.document_id)
            if not quote or not claim:
                issue("SOURCE_SUPPORT_BLANK", "Đã loại nguồn dẫn có trích đoạn hoặc lập luận trống.")
            elif source is None or quote not in source["text"]:
                issue("SOURCE_SUPPORT_NOT_FOUND", "Đã loại nguồn dẫn không thuộc tập truy xuất hoặc có trích đoạn không khớp.")
            elif item.document_id in seen:
                issue("SOURCE_SUPPORT_DUPLICATE", "Đã loại nguồn dẫn lặp lại.")
            else:
                support.append(item.model_copy(update={"source_quote": quote, "claim": claim}))
                seen.add(item.document_id)
        verdict.knowledge_support = support

    if not context_explicit:
        must_abstain = True
        issue("CONTEXT_MISSING", "LLM chưa phân loại ngữ cảnh theo cấu trúc yêu cầu.")
    elif verdict.context_kind == "unclassified":
        must_abstain = True
        issue("CONTEXT_UNCLASSIFIED", "Ngữ cảnh chưa được phân loại; cần bổ sung thông tin.")
    elif verdict.context_kind == "insufficient":
        must_abstain = True
        issue("CONTEXT_INSUFFICIENT", "Ngữ cảnh chưa đủ thông tin để kết luận; hướng dẫn được giới hạn ở bước xác minh.")

    if verdict.risk_level == "UNKNOWN" and verdict.context_kind != "insufficient":
        must_abstain = True
        issue("MODEL_ABSTAINED", "LLM chưa đưa ra kết luận; chỉ giữ hướng dẫn xác minh thận trọng.")

    if is_url_only(text):
        must_abstain = True
        verdict.context_kind = "insufficient"
        issue("URL_ONLY_INPUT", "Nội dung chỉ có đường dẫn; chưa đủ ngữ cảnh đánh giá hành vi trong thông điệp.")
    if verdict.risk_level in {"HIGH", "WARNING"} and not evidence:
        must_abstain = True
        issue("ALARM_WITHOUT_BEHAVIOR_EVIDENCE", "Nhận định cảnh báo chưa có trích đoạn hành vi hợp lệ.")

    if must_abstain:
        verdict.risk_level = "UNKNOWN"
        verdict.summary = "Chưa đủ căn cứ đánh giá hành vi trong bản nội dung đã gửi; hãy kiểm tra lại thông tin và cảnh báo URL riêng."
        verdict.recommended_actions = list(FALLBACK_ACTIONS)
        if isinstance(verdict, MessageRAGVerdict):
            verdict.knowledge_support = []
    else:
        verdict.recommended_actions = [action.strip() for action in verdict.recommended_actions]
        if isinstance(verdict, MessageRAGVerdict) and verdict.knowledge_support:
            warnings.append("Đã kiểm tra mã và đoạn nguồn; chưa xác minh nguồn có thực sự hỗ trợ lập luận hay phạm vi áp dụng.")

    return verdict, warnings, {
        "version": VALIDATION_VERSION,
        "status": "abstained" if must_abstain else "filtered" if codes else "valid",
        "reason_codes": codes,
        "original_risk_level": original_level,
        "structural_only": True,
        "semantic_support_verified": False,
        "limitation": "Chỉ kiểm tra cấu trúc, sự hiện diện của trích đoạn và ngữ cảnh; chưa chứng minh ý nghĩa, nguồn hỗ trợ hay kết luận là đúng.",
    }
