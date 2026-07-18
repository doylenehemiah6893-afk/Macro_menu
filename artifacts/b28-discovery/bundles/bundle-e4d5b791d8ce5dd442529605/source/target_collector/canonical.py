"""Small canonical JSON and bounded hashing helpers for the target collector."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any


MAX_JSON_DEPTH = 64
MAX_JSON_INTEGER_DIGITS = 128
MAX_JSON_NODES = 100_000


class CollectorError(Exception):
    """A fail-closed collector condition identified by a stable code."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}:{detail}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CollectorError("COLLECTOR_JSON_DUPLICATE_KEY", key)
        result[key] = value
    return result


def _bounded_integer(text: str) -> int:
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > MAX_JSON_INTEGER_DIGITS:
        raise ValueError("JSON integer too large")
    return int(text)


def _validate_structure(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while pending:
        child, depth = pending.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise CollectorError("COLLECTOR_JSON_LIMIT_EXCEEDED")
        if type(child) is dict:
            pending.extend((item, depth + 1) for item in child.values())
        elif type(child) is list:
            pending.extend((item, depth + 1) for item in child)


def canonical_json_bytes(value: object) -> bytes:
    """Return the repository canonical ASCII JSON representation."""

    try:
        text = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise CollectorError("COLLECTOR_JSON_INVALID") from error
    return (text + "\n").encode("ascii")


def parse_canonical_json_bytes(data: bytes) -> object:
    """Parse JSON while rejecting duplicate keys and non-canonical bytes."""

    try:
        text = data.decode("ascii")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_int=_bounded_integer,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("constant")),
        )
        _validate_structure(value)
    except CollectorError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError, RecursionError) as error:
        raise CollectorError("COLLECTOR_JSON_INVALID") from error
    if canonical_json_bytes(value) != data:
        raise CollectorError("COLLECTOR_NONCANONICAL_JSON")
    return value


def _reject_unsafe_stat(path: Path, info: os.stat_result) -> None:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise CollectorError("COLLECTOR_FILE_UNSAFE", str(path))
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    attributes = getattr(info, "st_file_attributes", 0)
    if attributes & reparse_flag:
        raise CollectorError("COLLECTOR_FILE_UNSAFE", str(path))


def sha256_file(path: Path, *, max_bytes: int) -> tuple[str, int]:
    """Hash one bounded, non-linked regular file without following symlinks."""

    path = Path(path)
    try:
        before = path.lstat()
        _reject_unsafe_stat(path, before)
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            _reject_unsafe_stat(path, opened)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise CollectorError("COLLECTOR_FILE_UNSAFE", str(path))
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise CollectorError("COLLECTOR_FILE_TOO_LARGE", str(path))
                digest.update(chunk)
    except CollectorError:
        raise
    except OSError as error:
        raise CollectorError("COLLECTOR_FILE_READ_ERROR", str(path)) from error
    return digest.hexdigest(), size


def read_canonical_json(path: Path, *, max_bytes: int) -> object:
    path = Path(path)
    try:
        before = path.lstat()
        _reject_unsafe_stat(path, before)
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            _reject_unsafe_stat(path, opened)
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise CollectorError("COLLECTOR_FILE_UNSAFE", str(path))
            data = stream.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise CollectorError("COLLECTOR_FILE_TOO_LARGE", str(path))
    except CollectorError:
        raise
    except OSError as error:
        raise CollectorError("COLLECTOR_FILE_READ_ERROR", str(path)) from error
    return parse_canonical_json_bytes(data)
