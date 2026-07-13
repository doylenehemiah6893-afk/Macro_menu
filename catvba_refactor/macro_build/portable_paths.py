from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .errors import SourceError
from .model import Diagnostic, ValidationReport


_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")
_RESERVED_BASENAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class _PortablePath:
    stored: str
    key: str


_PATH_MESSAGES = {
    "PATH_ABSOLUTE": "path must be relative and cannot use a drive or UNC prefix",
    "PATH_EMPTY": "path must not be empty",
    "PATH_EMPTY_SEGMENT": "path must not contain an empty segment",
    "PATH_INVALID_UTF8": "path must be valid UTF-8",
    "PATH_RESERVED_NAME": "path contains a Windows reserved basename",
    "PATH_TRAILING_DOT_SPACE": "path segments must not end in a dot or space",
    "PATH_TRAVERSAL": "path must not contain dot traversal segments",
}


def _normalized_path(path: str) -> str:
    return unicodedata.normalize("NFC", path.replace("\\", "/"))


def _portable_path(path: str) -> _PortablePath:
    stored = _normalized_path(path)
    try:
        stored.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise SourceError("PATH_INVALID_UTF8") from error
    if not stored:
        raise SourceError("PATH_EMPTY")
    if stored.startswith("/") or _DRIVE_PREFIX.match(stored):
        raise SourceError("PATH_ABSOLUTE")

    segments = stored.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise SourceError("PATH_TRAVERSAL")
    if any(not segment for segment in segments):
        raise SourceError("PATH_EMPTY_SEGMENT")
    if any(segment.endswith((".", " ")) for segment in segments):
        raise SourceError("PATH_TRAILING_DOT_SPACE")

    key = unicodedata.normalize("NFKC", stored).casefold()
    key_segments = key.split("/")
    if any(
        segment.split(".", 1)[0] in _RESERVED_BASENAMES
        for segment in key_segments
    ):
        raise SourceError("PATH_RESERVED_NAME")
    return _PortablePath(stored=stored, key=key)


def portable_key(path: str) -> str:
    """Return the Windows-portable collision key for a valid relative path."""
    return _portable_path(path).key


def _invalid_path_diagnostic(path: str, error: SourceError) -> Diagnostic:
    code = str(error)
    return Diagnostic(
        code=code,
        path=_normalized_path(path),
        message=_PATH_MESSAGES.get(code, "path is not portable"),
    )


def _collision_diagnostics(paths: tuple[_PortablePath, ...]) -> list[Diagnostic]:
    by_key: dict[str, list[_PortablePath]] = defaultdict(list)
    for path in paths:
        by_key[path.key].append(path)

    diagnostics: list[Diagnostic] = []
    for key in sorted(by_key):
        matches = by_key[key]
        if len(matches) < 2:
            continue
        stored_paths = tuple(sorted(match.stored for match in matches))
        diagnostics.append(
            Diagnostic(
                code="PATH_COLLISION",
                path=stored_paths[0],
                message="paths collide after NFKC normalization and case folding",
                details={"paths": stored_paths},
            )
        )
    return diagnostics


def _file_directory_diagnostics(
    paths: tuple[_PortablePath, ...],
) -> list[Diagnostic]:
    by_key: dict[str, list[_PortablePath]] = defaultdict(list)
    for path in paths:
        by_key[path.key].append(path)

    nested_by_prefix: dict[str, list[_PortablePath]] = defaultdict(list)
    prefix_display: dict[str, set[str]] = defaultdict(set)
    for path in paths:
        key_segments = path.key.split("/")
        stored_segments = path.stored.split("/")
        for length in range(1, len(key_segments)):
            prefix_key = "/".join(key_segments[:length])
            if prefix_key not in by_key:
                continue
            nested_by_prefix[prefix_key].append(path)
            prefix_display[prefix_key].add("/".join(stored_segments[:length]))

    diagnostics: list[Diagnostic] = []
    for prefix_key in sorted(nested_by_prefix):
        file_paths = tuple(sorted(path.stored for path in by_key[prefix_key]))
        nested_paths = tuple(
            sorted(path.stored for path in nested_by_prefix[prefix_key])
        )
        directory_path = sorted(prefix_display[prefix_key])[0]
        diagnostics.append(
            Diagnostic(
                code="PATH_FILE_DIR_COLLISION",
                path=file_paths[0],
                message="a path is both a file and a directory prefix",
                details={
                    "directory_path": directory_path,
                    "file_path": file_paths[0],
                    "nested_paths": nested_paths,
                },
            )
        )
    return diagnostics


def validate_portable_paths(paths: Iterable[str]) -> ValidationReport:
    """Validate paths and report deterministic Windows portability conflicts."""
    valid_paths: list[_PortablePath] = []
    diagnostics: list[Diagnostic] = []
    for path in paths:
        try:
            valid_paths.append(_portable_path(path))
        except SourceError as error:
            diagnostics.append(_invalid_path_diagnostic(path, error))

    stable_paths = tuple(valid_paths)
    diagnostics.extend(_collision_diagnostics(stable_paths))
    diagnostics.extend(_file_directory_diagnostics(stable_paths))
    return ValidationReport(tuple(diagnostics)).sorted()
