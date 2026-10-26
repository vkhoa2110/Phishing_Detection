import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .urls import URL_PATTERN, trim_url


def redact(text: str) -> tuple[str, list[str]]:
    """Che theo quy tắc; người dùng vẫn phải kiểm tra bản gửi."""
    changed: set[str] = set()

    def mask_url(match: re.Match) -> str:
        raw = match.group()
        value = trim_url(raw)
        has_scheme = "://" in value
        try:
            parsed = urlsplit(value if has_scheme else "http://" + value)
            netloc = parsed.netloc
            if "@" in netloc:
                netloc = "[AUTH]@" + netloc.rsplit("@", 1)[1]
                changed.add("Thông tin đăng nhập trong URL")
            query = parsed.query
            if query:
                query = urlencode([(k, "REDACTED") for k, _ in parse_qsl(query, keep_blank_values=True)])
                changed.add("Giá trị tham số URL")
            fragment = "REDACTED" if parsed.fragment else ""
            if parsed.fragment:
                changed.add("Phần fragment của URL")
            result = urlunsplit((parsed.scheme, netloc, parsed.path, query, fragment))
            if not has_scheme:
                result = result.removeprefix("http://")
            return result + raw[len(value):]
        except ValueError:
            return "[URL_KHONG_PHAN_TACH_DUOC]"

    text = URL_PATTERN.sub(mask_url, text)
    patterns = [
        (r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[EMAIL]", "Địa chỉ email"),
        (r"(?<!\w)(?:\+?84|0)[\d .-]{8,16}\d(?!\w)", "[PHONE]", "Số điện thoại"),
        (r"(?i)\b(OTP|mã xác thực|mã xác minh|mật khẩu|password|api[_ -]?key|bearer)\s*[:=]?\s*([A-Za-z0-9_./+\-=]{4,})", r"\1 [SECRET]", "Mã xác thực / thông tin truy cập"),
        (r"(?<!\w)\d{9,19}(?!\w)", "[NUMBER]", "Dãy số có thể là thông tin cá nhân"),
    ]
    for pattern, replacement, label in patterns:
        text, count = re.subn(pattern, replacement, text)
        if count:
            changed.add(label)
    return text, sorted(changed)

