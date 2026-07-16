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
from pathlib import Path


_BUNDLE = re.compile(r"^bundle-[0-9a-f]{24}$")
_HANDOFF = re.compile(r"^handoff-[a-z0-9][a-z0-9._-]{2,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CURRENT_FIELDS = frozenset(
    {"schema_version", "bundle_id", "bundle_sha256", "handoff_id"}
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
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
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
    repo_root: Path | str, github_output: Path | str, snapshot_root: Path | str
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
        or provenance.get("handoff_id") != document["handoff_id"]
    ):
        raise SelectionError("BUNDLE_PROVENANCE_MISMATCH")
    expected_sums = b"".join(
        f"{hashlib.sha256(data).hexdigest()}  {path}\n".encode("ascii")
        for path, data in files
        if path != "SHA256SUMS"
    )
    if file_map["SHA256SUMS"] != expected_sums:
        raise SelectionError("BUNDLE_SHA256SUMS_INVALID")
    if _bundle_tree_digest(files) != document["bundle_sha256"]:
        raise SelectionError("BUNDLE_TREE_DIGEST_MISMATCH")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        select_operator_bundle(args.repo_root, args.github_output, args.snapshot_root)
    except SelectionError as error:
        print(str(error), file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
