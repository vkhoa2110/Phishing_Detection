"""Bounded, user-reported context; questions never ask for personal secrets."""
from app.core.privacy import redact

QUESTIONS = {
    "initiated_by_user": ("Bạn có chủ động yêu cầu thao tác này không?", {
        "yes": "Tôi chủ động khởi tạo thao tác này.", "no": "Tôi không chủ động yêu cầu thao tác này.",
        "unsure": "Tôi chưa rõ ai khởi tạo thao tác."}),
    "secret_destination": ("Mã hoặc thông tin xác thực được yêu cầu sử dụng như thế nào?", {
        "self": "Tôi tự nhập mã trong quy trình do mình mở.",
        "third_party": "Người liên hệ yêu cầu tôi đọc hoặc gửi mã cho họ.",
        "unsure": "Tôi chưa rõ mã sẽ được nhập hoặc gửi cho ai."}),
    "payment_purpose": ("Khoản tiền được yêu cầu có mục đích gì?", {
        "unlock": "Họ yêu cầu đóng thêm phí để nhận việc, giải ngân, rút hoặc lấy lại tiền.",
        "known_order": "Đây là khoản thanh toán của đơn hàng hoặc dịch vụ tôi đã đặt.",
        "unsure": "Tôi chưa xác định được mục đích khoản tiền."}),
    "remote_permissions": ("Bên hỗ trợ muốn được cấp quyền gì?", {
        "bank_control": "Họ muốn điều khiển thiết bị hoặc thao tác ứng dụng ngân hàng.",
        "limited": "Tôi đặt lịch hỗ trợ, chỉ chia sẻ phần việc cần thiết và có thể dừng.",
        "unsure": "Tôi chưa biết phạm vi quyền họ yêu cầu."}),
    "sender_verification": ("Bạn đã xác minh người liên hệ bằng kênh nào?", {
        "known_channel": "Tôi đã xác minh qua kênh liên hệ biết từ trước.",
        "not_verified": "Tôi chưa xác minh được người liên hệ.",
        "unsure": "Tôi chưa rõ việc xác minh đã đủ hay chưa."}),
    "requested_action": ("Thông điệp yêu cầu bạn làm gì cụ thể?", {
        "secret": "Có yêu cầu gửi thông tin xác thực cho bên liên hệ.",
        "money_or_access": "Có yêu cầu chuyển tiền hoặc cấp quyền truy cập.",
        "not_stated": "Chưa có yêu cầu hành động cụ thể trong thông điệp.",
        "unsure": "Tôi chưa xác định được hành động được yêu cầu."}),
}


def plan(llm):
    if llm.get("status") != "ok" or llm.get("verdict", {}).get("risk_level") != "UNKNOWN":
        return {"status": "not_needed", "questions": []}
    codes = llm.get("core_decision", {}).get("missing_context") or ["requested_action", "initiated_by_user"]
    codes = list(dict.fromkeys(c for c in codes if c in QUESTIONS))[:2]
    return {"status": "available", "questions": [{"code": code, "text": QUESTIONS[code][0],
        "choices": [{"value": value, "label": label} for value, label in QUESTIONS[code][1].items()]} for code in codes],
        "notice": "Bạn có thể bổ sung ngữ cảnh. Nội dung sẽ được xem lại trước khi gửi AI; không cần nhập mã, mật khẩu hay số tài khoản."}


def preview(text, answers):
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ValueError("Nội dung cần bổ sung không hợp lệ.")
    if not isinstance(answers, list) or not 1 <= len(answers) <= 2:
        raise ValueError("Chọn từ một đến hai thông tin bổ sung.")
    selected, codes = [], set()
    for answer in answers:
        if not isinstance(answer, dict) or set(answer) != {"code", "value"}:
            raise ValueError("Lựa chọn không hợp lệ.")
        code, value = answer["code"], answer["value"]
        if not isinstance(code, str) or not isinstance(value, str) or code in codes or code not in QUESTIONS or value not in QUESTIONS[code][1]:
            raise ValueError("Lựa chọn không hợp lệ hoặc bị lặp.")
        codes.add(code)
        selected.append(QUESTIONS[code][1][value])
    masked, fields = redact(text.strip())
    result = masked + "\n\nThông tin người nhận tự bổ sung (chưa xác minh độc lập):\n" + "\n".join("- " + v for v in selected)
    if len(result) > 8000:
        raise ValueError("Nội dung sau bổ sung vượt 8.000 ký tự; hãy rút gọn trước.")
    return {"text": result, "masked_fields": fields, "requires_confirmation": True,
            "provider_calls": 0, "context_is_user_reported": True}
