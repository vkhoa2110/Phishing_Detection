import pytest

from app.url_intake_v2 import extract_urls_v2, inspect_url_intake


@pytest.mark.parametrize(("text", "expected", "change"), [
    ("Xem h\u200bttps://example.com/login", "https://example.com/login", "removed_format_character"),
    ("Xem example[.]com/login", "example.com/login", "restored_defanged_dot"),
    ("Xem https://ｅｘａｍｐｌｅ．ｃｏｍ/login", "https://example.com/login", "unicode_nfkc"),
    ("Xem vídụ.vn/xac-nhan", "xn--vd-nja3081a.vn/xac-nhan", "idna_ascii_host"),
])
def test_recovers_documented_obfuscations_without_opening(text, expected, change):
    result = inspect_url_intake(text, "text")
    assert result["recovered_urls"] == [expected]
    assert change in result["findings"][0]["transformations"]
    assert result["findings"][0]["original"] in text
    assert result["findings"][0]["requires_user_review"] is True
    assert result["findings"][0]["opened"] is False


def test_keeps_strict_urls_and_does_not_turn_email_into_url():
    result = inspect_url_intake("Liên hệ khoa@example.org hoặc https://example.org/a", "text")
    assert result["strict_urls"] == ["https://example.org/a"]
    assert not result["recovered_urls"]
    assert extract_urls_v2("Liên hệ khoa@example.org", "text") == ([], [])


def test_does_not_interpret_vietnamese_sentence_endings_as_domains():
    result = inspect_url_intake("Bạn đã thử việc. Tôi nhận rồi. Hãy xác minh.", "text")
    assert result["urls"] == []


def test_recovery_preserves_path_query_and_fragment_spelling():
    original = "https://ｅｘａｍｐｌｅ．ｃｏｍ/Ａ[.]Ｂ?q=Ｃ#Ｄ"
    result = inspect_url_intake(original, "text")
    assert result["recovered_urls"] == ["https://example.com/Ａ[.]Ｂ?q=Ｃ#Ｄ"]
    assert result["findings"][0]["transformations"] == ["unicode_nfkc"]


def test_url_mode_recovers_documented_form_but_still_rejects_non_url():
    result = inspect_url_intake("example[.]com/login", "url")
    assert result["urls"] == ["example.com/login"] and result["invalid_urls"] == []
    with pytest.raises(ValueError, match="URL HTTP/HTTPS hợp lệ"):
        inspect_url_intake("javascript:alert(1)", "url")


def test_limit_counts_recovered_and_strict_urls_together():
    text = " ".join(["https://one.example"] + [f"site{i}[.]example/a" for i in range(5)])
    with pytest.raises(ValueError, match="tối đa 5"):
        inspect_url_intake(text, "text")


@pytest.mark.parametrize("host,ascii_host", [
    ("bücher.de", "xn--bcher-kva.de"), ("faß.de", "xn--fa-hia.de"),
    ("example.com\u200b", "example.com"),
])
def test_scheme_does_not_bypass_authority_inspection(host, ascii_host):
    for prefix in ("", "https://"):
        text = prefix + host + "/Login?x=Ａ#ß"
        result = inspect_url_intake(text, "text")
        assert result["urls"] == [prefix + ascii_host + "/Login?x=Ａ#ß"]
        assert result["strict_urls"] == []
        assert result["findings"][0]["original"] == text
        assert result["idna_policy"] == "uts46-nontransitional-std3"


@pytest.mark.parametrize("text", ["https://a..com/", "https://example.com\\@evil.com/login",
                                  "https://user@example.com/", "https://-bad.example/"])
def test_ambiguous_or_invalid_urls_are_kept_out_of_model_input(text):
    assert extract_urls_v2(text, "text") == ([], [text])
    with pytest.raises(ValueError):
        inspect_url_intake(text, "url")
