import re
from urllib.parse import urlsplit

# Không phân giải tên miền, không gọi WHOIS và không mở URL được kiểm tra.
URL_PATTERN = re.compile(
    r"(?i)(?:https?://|www\.)[^\s<>\"']+|"
    r"(?<![\w@/.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,63}(?::\d{1,5})?(?:[/?#][^\s<>\"']*)?"
)


def trim_url(value: str) -> str:
    value = value.rstrip(".,;!?:。。，；！")
    for left, right in [("(", ")"), ("[", "]"), ("{", "}")]:
        while value.endswith(right) and value.count(right) > value.count(left):
            value = value[:-1]
    return value


def valid_url(value: str) -> bool:
    try:
        parsed = urlsplit(value if "://" in value else "http://" + value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        if any(c.isspace() for c in value) or len(value) > 4096:
            return False
        _ = parsed.port
        host = parsed.hostname
        return "." in host or ":" in host
    except ValueError:
        return False


def extract_urls(text: str, mode: str) -> tuple[list[str], list[str]]:
    candidates = [text.strip()] if mode == "url" else [trim_url(m.group()) for m in URL_PATTERN.finditer(text)]
    good, invalid = [], []
    for item in dict.fromkeys(candidates):
        (good if valid_url(item) else invalid).append(item)
    if mode == "url" and invalid:
        raise ValueError("Nhập một URL HTTP/HTTPS hợp lệ, ví dụ https://example.org/.")
    if len(good) + len(invalid) > 5:
        raise ValueError("Mỗi lần kiểm tra hỗ trợ tối đa 5 URL khác nhau.")
    return good, invalid

