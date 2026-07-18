#!/usr/bin/env python3
"""Select the single authenticated CURRENT operator bundle for CI upload."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path


_BUNDLE = re.compile(r"^bundle-[0-9a-f]{24}$")
_HANDOFF = re.compile(r"^handoff-[a-z0-9][a-z0-9._-]{2,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_SOURCE = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
_CURRENT_FIELDS = frozenset(
    {"schema_version", "bundle_id", "bundle_sha256", "handoff_id"}
)
_LEDGER_FIELDS = frozenset(
    {"schema_version", "captured_at", "source", "active_handoff_ids", "withdrawn_handoff_ids"}
)
_LEDGER_MAX_AGE = timedelta(hours=24)
_INACTIVE_CONTROL_ERRORS = frozenset(
    {
        "ACTIVE_CONTROL_STALE",
        "ACTIVE_CONTROL_EXPIRED",
        "ACTIVE_CONTROL_WITHDRAWN",
        "ACTIVE_CONTROL_NOT_ACTIVE",
    }
)
_FORBIDDEN_SUFFIXES = (".catvba", ".bas", ".cls", ".frm", ".frx")
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)
_STABLE_READ_HOOK = None


class SelectionError(RuntimeError):
    """A stable fail-closed bundle selection error."""


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SelectionError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reparse(status: os.stat_result) -> bool:
    return bool(
        getattr(status, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _signature(status: os.stat_result) -> tuple[int, ...]:
    return (
        status.st_dev, status.st_ino, status.st_mode, status.st_nlink,
        status.st_size, status.st_mtime_ns,
        getattr(status, "st_file_attributes", 0),
    )


def _stable_read(path: Path) -> bytes:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or _reparse(before)
            or before.st_nlink != 1
        ):
            raise SelectionError("BUNDLE_FILE_UNSAFE")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if _signature(opened) != _signature(before):
                raise SelectionError("BUNDLE_FILE_CHANGED")
            data = stream.read()
            hook = _STABLE_READ_HOOK
            if hook is not None:
                hook(path)
            opened_after = os.fstat(stream.fileno())
        after = path.lstat()
    except SelectionError:
        raise
    except OSError as error:
        raise SelectionError("BUNDLE_FILE_READ_FAILED") from error
    if _signature(before) != _signature(opened_after) or _signature(before) != _signature(after):
        raise SelectionError("BUNDLE_FILE_CHANGED")
    return data


def _path_chain(path: Path, root: Path) -> tuple[tuple[Path, tuple[int, ...]], ...]:
    try:
        relative = path.relative_to(root)
        current = root
        records: list[tuple[Path, tuple[int, ...]]] = []
        for component in (Path("."), *relative.parts):
            if component != Path("."):
                current = current / component
            status = current.lstat()
            if stat.S_ISLNK(status.st_mode) or _reparse(status):
                raise OSError
            records.append((current, _signature(status)))
    except (OSError, ValueError) as error:
        raise SelectionError("BUNDLE_PATH_CHAIN_UNSAFE") from error
    return tuple(records)


def _chain_unchanged(records: tuple[tuple[Path, tuple[int, ...]], ...]) -> None:
    try:
        if any(_signature(path.lstat()) != signature for path, signature in records):
            raise SelectionError("BUNDLE_PATH_CHAIN_CHANGED")
    except OSError as error:
        raise SelectionError("BUNDLE_PATH_CHAIN_CHANGED") from error


def _canonical_bytes(data: bytes) -> dict[str, object]:
    try:
        document = json.loads(data.decode("ascii"), object_pairs_hook=_unique)
        expected = (
            json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("ascii")
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise SelectionError("CANONICAL_JSON_INVALID") from error
    if not isinstance(document, dict) or data != expected:
        raise SelectionError("CANONICAL_JSON_INVALID")
    return document


def _utc(value: object, code: str) -> datetime:
    if type(value) is not str or _UTC.fullmatch(value) is None:
        raise SelectionError(code)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(UTC)
    except ValueError as error:
        raise SelectionError(code) from error


def _validate_active_control(
    repo: Path, *, provenance: dict[str, object], handoff: dict[str, object], now: datetime
) -> None:
    ledger = repo / "artifacts/b28-discovery/active-handoff-ledger.json"
    ledger_chain = _path_chain(ledger, repo)
    document = _canonical_bytes(_stable_read(ledger))
    _chain_unchanged(ledger_chain)
    handoff_id = provenance.get("handoff_id")
    source = provenance.get("active_ledger_source")
    if (
        frozenset(document) != _LEDGER_FIELDS
        or document.get("schema_version") != 1
        or type(document.get("schema_version")) is not int
        or type(source) is not str
        or _SOURCE.fullmatch(source) is None
        or document.get("source") != source
        or handoff.get("handoff_id") != handoff_id
        or handoff.get("revocation_status") != "active"
    ):
        raise SelectionError("ACTIVE_CONTROL_INVALID")
    expires_at = _utc(handoff.get("expires_at"), "HANDOFF_INVALID")
    active = document.get("active_handoff_ids")
    withdrawn = document.get("withdrawn_handoff_ids")
    if (
        type(active) is not list
        or type(withdrawn) is not list
        or not all(type(value) is str and _HANDOFF.fullmatch(value) for value in active + withdrawn)
        or len(active) != len(set(active))
        or len(withdrawn) != len(set(withdrawn))
        or set(active) & set(withdrawn)
    ):
        raise SelectionError("ACTIVE_CONTROL_INVALID")
    captured_at = _utc(document.get("captured_at"), "ACTIVE_CONTROL_INVALID")
    if captured_at > now:
        raise SelectionError("ACTIVE_CONTROL_FUTURE")
    if expires_at <= now:
        raise SelectionError("ACTIVE_CONTROL_EXPIRED")
    if now - captured_at > _LEDGER_MAX_AGE:
        raise SelectionError("ACTIVE_CONTROL_STALE")
    if handoff_id in withdrawn:
        raise SelectionError("ACTIVE_CONTROL_WITHDRAWN")
    if handoff_id not in active:
        raise SelectionError("ACTIVE_CONTROL_NOT_ACTIVE")


def _write_outputs(path: Path, result: dict[str, object]) -> None:
    available = "true" if result["available"] else "false"
    payload = (
        f"available={available}\npath={result['path']}\n"
        f"bundle_id={result['bundle_id']}\nsha256={result['sha256']}\n"
    ).encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.is_symlink():
            raise OSError
        with path.open("ab") as stream:
            stream.write(payload)
    except OSError as error:
        raise SelectionError("GITHUB_OUTPUT_INVALID") from error


def _regular_tree(root: Path) -> tuple[tuple[str, bytes], ...]:
    try:
        root_status = root.lstat()
        if (
            not stat.S_ISDIR(root_status.st_mode)
            or stat.S_ISLNK(root_status.st_mode)
            or _reparse(root_status)
        ):
            raise OSError
        directories = {root: _signature(root_status)}
        records: list[tuple[str, bytes]] = []
        portable_paths: dict[str, str] = {}
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            status = path.lstat()
            if stat.S_ISLNK(status.st_mode):
                raise OSError
            if _reparse(status):
                raise OSError
            if not stat.S_ISDIR(status.st_mode) and not stat.S_ISREG(status.st_mode):
                raise OSError
            relative = path.relative_to(root).as_posix()
            relative.encode("ascii")
            for component in relative.split("/"):
                if (
                    not component
                    or component.endswith((" ", "."))
                    or ":" in component
                    or any(ord(character) < 32 for character in component)
                    or component.partition(".")[0].casefold() in _WINDOWS_RESERVED
                ):
                    raise SelectionError("BUNDLE_PORTABLE_PATH_INVALID")
            portable_key = relative.casefold()
            if portable_key in portable_paths:
                raise SelectionError("BUNDLE_PORTABLE_PATH_COLLISION")
            portable_paths[portable_key] = relative
            if stat.S_ISDIR(status.st_mode):
                directories[path] = _signature(status)
                continue
            if relative.casefold().endswith(_FORBIDDEN_SUFFIXES):
                raise SelectionError("BUNDLE_FORBIDDEN_PAYLOAD")
            records.append((relative, _stable_read(path)))
        for directory, signature in directories.items():
            if _signature(directory.lstat()) != signature:
                raise SelectionError("BUNDLE_PATH_CHAIN_CHANGED")
    except SelectionError:
        raise
    except (OSError, UnicodeError) as error:
        raise SelectionError("BUNDLE_REGULAR_TREE_INVALID") from error
    return tuple(records)


def canonical_bundle_tree_digest(root: Path | str) -> str:
    """Digest the complete regular bundle tree, including SHA256SUMS."""

    return _bundle_tree_digest(_regular_tree(Path(root)))


def _bundle_tree_digest(files: tuple[tuple[str, bytes], ...]) -> str:
    records = [
        {
            "path": path,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }
        for path, data in files
    ]
    canonical = (
        json.dumps(records, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _zip_bytes(files: tuple[tuple[str, bytes], ...]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True) as archive:
        for path, data in files:
            info = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            info.flag_bits = 0x800
            archive.writestr(info, data)
    return stream.getvalue()


def _publish_snapshot(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    linked = False
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        linked = True
        temporary.unlink()
        path.chmod(0o444)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        cleanup = (path, temporary) if linked else (temporary,)
        for candidate in cleanup:
            try:
                candidate.chmod(0o600)
            except OSError:
                pass
            try:
                candidate.unlink()
            except OSError:
                pass
        raise


def select_operator_bundle(
    repo_root: Path | str,
    github_output: Path | str,
    snapshot_root: Path | str,
    *,
    inactive_as_unavailable: bool = False,
) -> dict[str, object]:
    repo = Path(repo_root).resolve()
    current = repo / "artifacts/b28-discovery/CURRENT.json"
    if not current.exists():
        result: dict[str, object] = {
            "available": False, "path": "", "bundle_id": "", "sha256": ""
        }
        _write_outputs(Path(github_output), result)
        return result
    current_chain = _path_chain(current, repo)
    document = _canonical_bytes(_stable_read(current))
    _chain_unchanged(current_chain)
    if (
        frozenset(document) != _CURRENT_FIELDS
        or document.get("schema_version") != 1
        or type(document.get("schema_version")) is not int
        or type(document.get("bundle_id")) is not str
        or _BUNDLE.fullmatch(str(document["bundle_id"])) is None
        or type(document.get("bundle_sha256")) is not str
        or _SHA.fullmatch(str(document["bundle_sha256"])) is None
        or type(document.get("handoff_id")) is not str
        or _HANDOFF.fullmatch(str(document["handoff_id"])) is None
    ):
        raise SelectionError("CURRENT_INVALID")
    bundle_id = str(document["bundle_id"])
    relative = Path("artifacts/b28-discovery/bundles") / bundle_id
    bundle = repo / relative
    if not bundle.exists():
        raise SelectionError("BUNDLE_MISSING")
    bundle_chain = _path_chain(bundle, repo)
    files = _regular_tree(bundle)
    _chain_unchanged(bundle_chain)
    file_map = dict(files)
    if "provenance.json" not in file_map or "SHA256SUMS" not in file_map:
        raise SelectionError("BUNDLE_REQUIRED_FILE_MISSING")
    provenance_bytes = file_map["provenance.json"]
    provenance = _canonical_bytes(provenance_bytes)
    provenance_digest = hashlib.sha256(provenance_bytes).hexdigest()
    if (
        bundle_id != "bundle-" + provenance_digest[:24]
        or document["bundle_sha256"] != provenance_digest
        or provenance.get("handoff_id") != document["handoff_id"]
    ):
        raise SelectionError("BUNDLE_PROVENANCE_MISMATCH")
    try:
        handoff = _canonical_bytes(file_map["handoff.json"])
    except KeyError as error:
        raise SelectionError("BUNDLE_REQUIRED_FILE_MISSING") from error
    expected_sums = b"".join(
        f"{hashlib.sha256(data).hexdigest()}  {path}\n".encode("ascii")
        for path, data in files
        if path != "SHA256SUMS"
    )
    if file_map["SHA256SUMS"] != expected_sums:
        raise SelectionError("BUNDLE_SHA256SUMS_INVALID")
    content_files = tuple(
        (path, data)
        for path, data in files
        if path not in {"provenance.json", "SHA256SUMS"}
    )
    if (
        type(provenance.get("bundle_content_sha256")) is not str
        or _SHA.fullmatch(str(provenance["bundle_content_sha256"])) is None
        or _bundle_tree_digest(content_files) != provenance["bundle_content_sha256"]
    ):
        raise SelectionError("BUNDLE_CONTENT_DIGEST_MISMATCH")
    try:
        _validate_active_control(
            repo, provenance=provenance, handoff=handoff, now=datetime.now(UTC)
        )
    except SelectionError as error:
        if not inactive_as_unavailable or str(error) not in _INACTIVE_CONTROL_ERRORS:
            raise
        result = {"available": False, "path": "", "bundle_id": "", "sha256": ""}
        _write_outputs(Path(github_output), result)
        return result
    snapshot_directory = Path(snapshot_root).resolve()
    try:
        snapshot_relative = snapshot_directory.relative_to(repo)
    except ValueError as error:
        raise SelectionError("SNAPSHOT_ROOT_OUTSIDE_REPOSITORY") from error
    snapshot = snapshot_directory / "operator-bundle-upload.zip"
    archive_bytes = _zip_bytes(files)
    try:
        _publish_snapshot(snapshot, archive_bytes)
    except OSError as error:
        raise SelectionError("SNAPSHOT_PUBLISH_FAILED") from error
    result = {
        "available": True,
        "path": (snapshot_relative / snapshot.name).as_posix(),
        "bundle_id": bundle_id,
        "sha256": hashlib.sha256(archive_bytes).hexdigest(),
    }
    _write_outputs(Path(github_output), result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument(
        "--inactive-as-unavailable",
        action="store_true",
        help="Return available=false for stale, expired, withdrawn, or inactive delivery control",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        select_operator_bundle(
            args.repo_root,
            args.github_output,
            args.snapshot_root,
            inactive_as_unavailable=args.inactive_as_unavailable,
        )
    except SelectionError as error:
        print(str(error), file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
