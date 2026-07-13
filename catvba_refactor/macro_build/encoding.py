from __future__ import annotations

from dataclasses import dataclass

from .errors import SourceError


@dataclass(frozen=True)
class DecodedVba:
    kind: str
    text: str
    encoding: str


def _try_decode(data: bytes, encoding: str) -> str | None:
    try:
        return data.decode(encoding, errors="strict")
    except UnicodeDecodeError:
        return None


def _decode_declared(data: bytes, encoding: str) -> DecodedVba:
    if encoding not in {"utf-8", "cp936"}:
        raise SourceError("ENC_INVALID")
    try:
        text = data.decode(encoding, errors="strict")
    except UnicodeDecodeError as error:
        raise SourceError("ENC_INVALID") from error
    kind = "utf8" if encoding == "utf-8" else "cp936"
    return DecodedVba(kind=kind, text=text, encoding=encoding)


def decode_vba(
    data: bytes, declared_encoding: str | None = None
) -> DecodedVba:
    """Decode VBA source bytes without replacement or heuristic guessing."""
    if declared_encoding is not None:
        return _decode_declared(data, declared_encoding)

    if data.startswith(b"\xef\xbb\xbf"):
        try:
            text = data[3:].decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise SourceError("ENC_INVALID") from error
        return DecodedVba("utf8-bom", text, "utf-8")
    if data.isascii():
        return DecodedVba("ascii", data.decode("ascii"), "ascii")

    utf8 = _try_decode(data, "utf-8")
    cp936 = _try_decode(data, "cp936")
    if utf8 is not None and cp936 is None:
        return DecodedVba("utf8", utf8, "utf-8")
    if cp936 is not None and utf8 is None:
        return DecodedVba("cp936", cp936, "cp936")
    if utf8 is not None and cp936 is not None and utf8 != cp936:
        raise SourceError("ENC_AMBIGUOUS")
    raise SourceError("ENC_INVALID")
