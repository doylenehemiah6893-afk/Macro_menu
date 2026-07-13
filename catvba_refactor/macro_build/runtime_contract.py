import hashlib
import re
import unicodedata
from typing import Final


PROTOCOL_VERSION: Final = "MM/1"
MAX_DEPTH: Final = 8
MAX_STRING_LENGTH: Final = 4096
MAX_ARRAY_ITEMS: Final = 256
MAX_TOTAL_NODES: Final = 2048
MAX_DISPLAY_LINES: Final = 500

ERROR_CODES: Final = {
    0: "OK",
    10: "CANCELLED",
    20: "NOT_APPLICABLE",
    30: "CAPABILITY_UNAVAILABLE",
    40: "VALIDATION_FAILED",
    50: "STATE_CHANGED",
    60: "TOOL_FAILED",
    70: "INTERNAL_ERROR",
    80: "LIMIT_REACHED",
    90: "UNKNOWN_COMMAND",
}

CORE_STATES: Final = ("READY", "BLOCKED")
EXTENSION_STATES: Final = ("NOT_PROBED", "READY", "UNAVAILABLE", "BROKEN")
FLEET_STATES: Final = ("READY", "DEGRADED", "BLOCKED")

_STABLE_ID = re.compile(r"^[a-z][a-z0-9._-]{2,63}$")
_OUTPUT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def canonical_runtime_id(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("runtime ID must be a string")
    canonical = unicodedata.normalize("NFKC", value).casefold()
    if not canonical.strip():
        raise ValueError("runtime ID must not be empty")
    return canonical


def _runtime_name(prefix: str, stable_id: str) -> str:
    if not isinstance(stable_id, str) or _STABLE_ID.fullmatch(stable_id) is None:
        raise ValueError("runtime stable ID does not match the required schema")

    canonical_id = stable_id.lower()
    slug = re.sub(r"[^a-z0-9_]", "_", canonical_id)
    digest = hashlib.sha256(canonical_id.encode("utf-8")).hexdigest()[:8]
    name = f"{prefix}{slug[:26]}_{digest}"
    if len(name) > 40 or _OUTPUT_NAME.fullmatch(name) is None:
        raise ValueError("generated runtime name is illegal")
    return name


def control_name(tool_id: str) -> str:
    return _runtime_name("btn_", tool_id)


def page_name(group_id: str) -> str:
    return _runtime_name("pg_", group_id)
