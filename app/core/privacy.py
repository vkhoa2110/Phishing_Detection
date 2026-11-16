import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from app.services.url.parsing import URL_PATTERN, trim_url


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
                # A bracketed user marker is parsed as an invalid IPv6 host on
                # the next preview pass. This marker is valid URL userinfo and
                # cannot be mistaken for an email address by the rule below.
                netloc = "***@" + netloc.rsplit("@", 1)[1]
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

    def mask_otp(match: re.Match) -> str:
        # A bare domain/path is a URL too; it does not have an HTTP prefix
        # for the negative lookahead below to reject.
        if URL_PATTERN.fullmatch(trim_url(match.group(2))):
            return match.group()
        changed.add("Mã xác thực / thông tin truy cập")
        return match.group(1) + " [SECRET]"

    value_connector = r"(?:của\s+(?:bạn|tôi)\s+)?(?:là|is)(?:\s*[:=]\s*|\s+)"
    explicit_value = rf"(?:\s*[:=]\s*(?:{value_connector})?|\s+{value_connector})"

    patterns = [
        (r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[EMAIL]", "Địa chỉ email"),
        (r"(?<!\w)(?:\+?84|0)[\d .-]{8,16}\d(?!\w)", "[PHONE]", "Số điện thoại"),
        # Keep complete URLs and Vietnamese prose after an OTP label intact.
        # In particular, an ASCII token must not match only the `chuy` prefix
        # of `chuyển`. Short, bounded connectors cover common value notation
        # without searching through arbitrary sentences for a possible secret.
        (r"(?i)\b(OTP|mã xác thực|mã xác minh)\s*[:=]?\s*"
         rf"(?:{value_connector})?"
         r"(?!https?://|www\.)([A-Za-z0-9_./+\-=]{4,})(?![\w\u0300-\u036f])",
         mask_otp, None),
        # Explicit value syntax can introduce Unicode or punctuation-only
        # credentials. Adjacent Vietnamese prose remains intact unless the
        # writer actually supplied a separator or a bounded value connector.
        (r"(?i)\b(mật khẩu|password|api[_ -]?key|bearer)"
         rf"{explicit_value}(?!https?://|www\.)([^\s<>\"']+)",
         r"\1 [SECRET]", "Mã xác thực / thông tin truy cập"),
        # Preserve legacy bare ASCII credentials (notably Bearer/API keys),
        # while preventing partial matches inside Unicode words or passwords.
        (r"(?i)\b(mật khẩu|password|api[_ -]?key|bearer)\s*[:=]?\s*"
         r"(?!https?://|www\.)([A-Za-z0-9_./+\-=]{4,})(?![\w\u0300-\u036f])",
         r"\1 [SECRET]", "Mã xác thực / thông tin truy cập"),
        (r"(?<!\w)\d{9,19}(?!\w)", "[NUMBER]", "Dãy số có thể là thông tin cá nhân"),
    ]
    for pattern, replacement, label in patterns:
        text, count = re.subn(pattern, replacement, text)
        if count and label:
            changed.add(label)
    return text, sorted(changed)

