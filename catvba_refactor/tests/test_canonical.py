import pytest

from catvba_refactor.macro_build import canonical
from catvba_refactor.macro_build.canonical import (
    CanonicalJsonError,
    canonical_json_bytes,
    parse_canonical_json_bytes,
    sha256_bytes,
)


def test_canonical_json_is_key_order_independent() -> None:
    left = canonical_json_bytes({"b": 2, "a": "中"})
    right = canonical_json_bytes({"a": "中", "b": 2})
    assert left == right == b'{"a":"\\u4e2d","b":2}\n'
    assert sha256_bytes(left) == sha256_bytes(right)


def test_parse_canonical_json_bytes_round_trips_ascii_document() -> None:
    value = {"schema_version": 1, "session_id": "session-001"}

    assert parse_canonical_json_bytes(canonical_json_bytes(value)) == value


def test_parse_canonical_json_bytes_rejects_duplicate_keys() -> None:
    with pytest.raises(CanonicalJsonError, match="DUPLICATE_JSON_KEY"):
        parse_canonical_json_bytes(b'{"a":1,"a":2}\n')


def test_parse_canonical_json_bytes_rejects_noncanonical_bytes() -> None:
    with pytest.raises(CanonicalJsonError, match="NONCANONICAL_JSON"):
        parse_canonical_json_bytes(b'{"schema_version": 1}\n')


def test_parse_canonical_json_bytes_rejects_non_ascii_bytes() -> None:
    with pytest.raises(CanonicalJsonError, match="NONCANONICAL_JSON"):
        parse_canonical_json_bytes('{"name":"中"}\n'.encode())


@pytest.mark.parametrize(
    "constant", [b"NaN\n", b"Infinity\n", b"-Infinity\n", b"1e400\n"]
)
def test_parse_canonical_json_bytes_rejects_non_finite_numbers(
    constant: bytes,
) -> None:
    with pytest.raises(CanonicalJsonError):
        parse_canonical_json_bytes(constant)


def test_parse_canonical_json_bytes_wraps_non_builtin_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(canonical.json, "loads", lambda *_args, **_kwargs: object())

    with pytest.raises(CanonicalJsonError):
        parse_canonical_json_bytes(b"{}\n")
