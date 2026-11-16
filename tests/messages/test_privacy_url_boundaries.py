import unicodedata
from urllib.parse import urlsplit

import pytest

from app.core.privacy import redact
from app.services.url.parsing import extract_urls


SECRET_FIELD = "Mã xác thực / thông tin truy cập"


@pytest.mark.parametrize("text", [
    "Hãy gửi mã OTP https://example.org",
    "OTP: https://EXAMPLE.org/path",
    "mã xác thực www.example.org/path",
    "mã xác minh example.org/path",
    "OTP chuyển cho tôi",
    "mã xác thực chuyển tới ngân hàng",
    "OTP không chia sẻ",
    "OTP của bạn chưa được cung cấp",
    "OTP cập nhật",
    "OTP hết hạn",
    unicodedata.normalize("NFD", "OTP chuyển cho tôi"),
])
def test_otp_rule_preserves_urls_and_complete_vietnamese_words(text):
    masked, fields = redact(text)
    assert masked == text
    assert SECRET_FIELD not in fields


def test_uppercase_scheme_is_normalized_without_consuming_it_as_an_otp():
    masked, fields = redact("OTP HTTPS://EXAMPLE.org/path")
    assert masked == "OTP https://EXAMPLE.org/path"
    assert SECRET_FIELD not in fields


@pytest.mark.parametrize("label,value", [
    ("OTP:", "123456"),
    ("OTP", "ABCDEF"),
    ("OTP", "abcdef"),
    ("OTP=", "12AB34"),
    ("mã xác thực là", "123456"),
    ("mã xác thực là:", "123456"),
    ("mã xác minh của bạn là", "654321"),
    ("mã xác minh của bạn là:", "654321"),
    ("OTP is", "A1b2C3"),
    ("password:", "abcDEF12!"),
    ("mật khẩu là", "mậtKhẩu123!"),
    ("mật khẩu:", "không"),
    ("mật khẩu là:", "không"),
    ("mật khẩu của bạn là:", "mậtKhẩu123!"),
    ("password:", "!?"),
    ("password:", "mật"),
    ("password của tôi là", "secretValue"),
    ("API key:", "sk-123456789ABCDE"),
    ("api_key=", "abCDef+/="),
    ("Bearer", "eyJhbGciOiJIUzI1NiJ9.abc.signature"),
])
def test_adjacent_secret_values_remain_masked(label, value):
    text = f"{label} {value}"
    masked, fields = redact(text)
    assert value not in masked
    assert "[SECRET]" in masked
    assert SECRET_FIELD in fields
    assert redact(masked)[0] == masked


@pytest.mark.parametrize("text", [
    "mật khẩu không chia sẻ cho ai",
    "mật khẩu chuyển cho tôi",
    "password không được chia sẻ",
    "API key không gửi qua email",
    "Bearer không có giá trị cụ thể",
    "mật khẩu của bạn chưa được cung cấp",
    unicodedata.normalize("NFD", "password chuyển cho tôi"),
])
def test_credential_prose_keeps_unicode_words_and_negation(text):
    masked, fields = redact(text)
    assert masked == text
    assert SECRET_FIELD not in fields


@pytest.mark.parametrize("text,value", [
    ("mã xác thực là:123456", "123456"),
    ("mã xác minh của bạn là:654321", "654321"),
    ("mật khẩu là:không", "không"),
])
def test_connector_colon_does_not_require_whitespace_before_value(text, value):
    masked, fields = redact(text)
    assert value not in masked
    assert "[SECRET]" in masked
    assert SECRET_FIELD in fields


@pytest.mark.parametrize("text,host", [
    ("https://demo:synthetic-pass@example.org/path", "example.org"),
    ("https://demo:synthetic-pass@EXAMPLE.org/path?token=synthetic-token#synthetic-fragment", "example.org"),
    ("https://demo:synthetic-pass@[2001:db8::1]/path", "2001:db8::1"),
])
def test_url_auth_redaction_is_parseable_and_idempotent(text, host):
    masked, fields = redact(text)
    assert "demo" not in masked and "synthetic-" not in masked
    assert "***@" in masked
    assert "Thông tin đăng nhập trong URL" in fields
    assert urlsplit(masked).hostname == host
    assert extract_urls(masked, "text") == ([masked], [])
    assert redact(masked)[0] == masked


def test_otp_url_redaction_keeps_scheme_and_masks_all_url_values():
    text = "OTP https://demo:synthetic-pass@example.org/path?token=synthetic-token#synthetic-fragment"
    masked, fields = redact(text)
    assert masked == "OTP https://***@example.org/path?token=REDACTED#REDACTED"
    assert SECRET_FIELD not in fields
    assert len(fields) == 3
    assert redact(masked)[0] == masked
