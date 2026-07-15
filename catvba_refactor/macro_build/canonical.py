import hashlib
import json
import math
from typing import Any


class CanonicalJsonError(ValueError):
    """Raised when bytes do not contain one strict canonical JSON value."""


def canonical_json_bytes(value: Any) -> bytes:
    text = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (text + "\n").encode("ascii")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CanonicalJsonError(f"DUPLICATE_JSON_KEY: {key}")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> Any:
    raise CanonicalJsonError(f"NONFINITE_JSON_NUMBER: {value}")


def _require_builtin_json_value(value: Any) -> None:
    value_type = type(value)
    if value is None or value_type in {bool, int, str}:
        return
    if value_type is float:
        if not math.isfinite(value):
            raise CanonicalJsonError("NONFINITE_JSON_NUMBER")
        return
    if value_type is list:
        for item in value:
            _require_builtin_json_value(item)
        return
    if value_type is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise CanonicalJsonError("NON_BUILTIN_JSON_VALUE")
            _require_builtin_json_value(item)
        return
    raise CanonicalJsonError("NON_BUILTIN_JSON_VALUE")


def parse_canonical_json_bytes(data: bytes) -> Any:
    """Parse one ASCII JSON value and require its exact canonical encoding."""
    try:
        text = data.decode("ascii")
    except (AttributeError, UnicodeDecodeError) as error:
        raise CanonicalJsonError("NONCANONICAL_JSON") from error

    try:
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite,
        )
    except CanonicalJsonError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError) as error:
        raise CanonicalJsonError("INVALID_JSON") from error

    try:
        _require_builtin_json_value(value)
        canonical = canonical_json_bytes(value)
    except CanonicalJsonError:
        raise
    except (RecursionError, TypeError, ValueError) as error:
        raise CanonicalJsonError("NON_BUILTIN_JSON_VALUE") from error
    if canonical != data:
        raise CanonicalJsonError("NONCANONICAL_JSON")
    return value


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
