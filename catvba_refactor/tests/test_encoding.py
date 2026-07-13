import pytest

from catvba_refactor.macro_build.encoding import DecodedVba, decode_vba
from catvba_refactor.macro_build.errors import SourceError


def test_ascii_has_a_stable_classification() -> None:
    assert decode_vba(b'Attribute VB_Name = "Module1"\r\n') == DecodedVba(
        kind="ascii",
        text='Attribute VB_Name = "Module1"\r\n',
        encoding="ascii",
    )


def test_utf8_bom_is_removed_before_strict_decoding() -> None:
    assert decode_vba(b"\xef\xbb\xbf\xe4\xb8\xad") == DecodedVba(
        kind="utf8-bom",
        text="中",
        encoding="utf-8",
    )


def test_utf8_only_chinese_is_classified_without_replacement() -> None:
    assert decode_vba(b"\xe4\xb8\xad\xe6\x96\x87") == DecodedVba(
        kind="utf8",
        text="中文",
        encoding="utf-8",
    )


def test_cp936_only_chinese_is_classified_without_replacement() -> None:
    assert decode_vba(b"\xd6\xd0\xce\xc4") == DecodedVba(
        kind="cp936",
        text="中文",
        encoding="cp936",
    )


def test_different_successful_decodings_require_an_explicit_decision() -> None:
    with pytest.raises(SourceError, match=r"^ENC_AMBIGUOUS$"):
        decode_vba(b"\xc2\xa9")


@pytest.mark.parametrize(
    ("declared_encoding", "expected"),
    [("utf-8", "©"), ("cp936", "漏")],
)
def test_explicit_decision_uses_exactly_the_declared_strict_decoder(
    declared_encoding: str, expected: str
) -> None:
    result = decode_vba(b"\xc2\xa9", declared_encoding)

    assert result == DecodedVba(
        kind="utf8" if declared_encoding == "utf-8" else "cp936",
        text=expected,
        encoding=declared_encoding,
    )


def test_bytes_invalid_under_both_decoders_are_rejected() -> None:
    with pytest.raises(SourceError, match=r"^ENC_INVALID$"):
        decode_vba(b"\x81")


@pytest.mark.parametrize(
    ("data", "declared_encoding"),
    [(b"\xd6\xd0\xce\xc4", "utf-8"), (b"\xe4\xb8\xad", "cp936")],
)
def test_explicit_decisions_remain_strict(
    data: bytes, declared_encoding: str
) -> None:
    with pytest.raises(SourceError, match=r"^ENC_INVALID$"):
        decode_vba(data, declared_encoding)
