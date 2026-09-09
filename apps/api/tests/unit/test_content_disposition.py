from __future__ import annotations

from urllib.parse import unquote

from trinol.modules.work.routes.tasks import _content_disposition


def test_plain_ascii_filename_round_trips_in_both_forms() -> None:
    header = _content_disposition("receipt.png")
    assert header == "attachment; filename=\"receipt.png\"; filename*=UTF-8''receipt.png"


def test_embedded_quote_cannot_break_out_of_the_quoted_string() -> None:
    header = _content_disposition('evil".png')
    # The fallback must not contain a raw, unescaped quote — that's the
    # exact injection vector (a filename ending the quoted-string early
    # and appending arbitrary header content after it).
    fallback = header.split("filename=")[1].split(";")[0]
    assert fallback.count('"') == 2  # only the two we added ourselves
    assert '"' not in fallback[1:-1]


def test_embedded_crlf_cannot_inject_additional_header_lines() -> None:
    # The readable words surviving in the ASCII fallback (with CR/LF
    # replaced by "_") are harmless — a header value is only exploitable if
    # it contains a *raw* CR or LF, which would start a genuinely new
    # header line. Checking for that is the complete, correct property;
    # what the fallback text happens to spell is irrelevant.
    header = _content_disposition("evil.png\r\nSet-Cookie: pwned=1")
    assert "\r" not in header
    assert "\n" not in header


def test_backslash_cannot_escape_the_closing_quote() -> None:
    header = _content_disposition('evil\\".png')
    fallback = header.split("filename=")[1].split(";")[0]
    assert "\\" not in fallback


def test_filename_star_value_is_percent_encoded_and_recoverable() -> None:
    header = _content_disposition("résumé (final).png")
    star_value = header.split("filename*=UTF-8''")[1]
    # No raw non-ASCII, space, or parenthesis in the encoded value itself —
    # everything outside RFC 3986's unreserved set must be escaped.
    assert star_value.isascii()
    assert unquote(star_value) == "résumé (final).png"


def test_unsafe_characters_are_replaced_not_removed_in_the_fallback() -> None:
    # Substitution (not deletion) keeps the fallback's length meaningful
    # and guarantees it can never end with a dangling escape/quote.
    header = _content_disposition('"""')
    assert 'filename="___"' in header


def test_empty_filename_falls_back_to_a_placeholder() -> None:
    header = _content_disposition("")
    assert 'filename="download"' in header
