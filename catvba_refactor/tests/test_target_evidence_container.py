from __future__ import annotations

import errno
import os
import stat
import struct
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.errors import EvidenceError, InfrastructureError
from catvba_refactor.macro_build.target_evidence import container
from catvba_refactor.macro_build.target_evidence.container import (
    canonical_evidence_zip_bytes,
    canonical_payload_manifest,
    publish_evidence_artifacts,
    read_evidence_container,
)
from catvba_refactor.macro_build.target_evidence.model import EvidencePhase


FILES = {
    "environment.json": b'{"schema_version":1}\n',
    "operator/compile.json": b'{"status":"not-run"}\n',
}


def _write_tree(root: Path, files: dict[str, bytes] = FILES) -> None:
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _zip_bytes(
    files: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_STORED,
    comment: bytes = b"",
    extra: bytes = b"",
    mode: int = 0o100644,
) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        archive.comment = comment
        for name, data in files.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = mode << 16
            info.compress_type = compression
            info.extra = extra
            archive.writestr(info, data)
    return output.getvalue()


def _patch_general_purpose_flag(data: bytes, flag: int) -> bytes:
    result = bytearray(data)
    local = result.index(b"PK\x03\x04")
    central = result.index(b"PK\x01\x02")
    current_local = struct.unpack_from("<H", result, local + 6)[0]
    current_central = struct.unpack_from("<H", result, central + 8)[0]
    struct.pack_into("<H", result, local + 6, current_local | flag)
    struct.pack_into("<H", result, central + 8, current_central | flag)
    return bytes(result)


def _codes(snapshot: object) -> set[str]:
    return {item.code for item in snapshot.diagnostics}  # type: ignore[attr-defined]


def test_payload_manifest_is_canonical_path_sorted_and_independent() -> None:
    manifest, digest, members = canonical_payload_manifest(
        {"z.txt": b"z", "a.txt": b"alpha"}
    )

    expected = canonical_json_bytes(
        {
            "members": [
                {"path": "a.txt", "sha256": sha256_bytes(b"alpha"), "size": 5},
                {"path": "z.txt", "sha256": sha256_bytes(b"z"), "size": 1},
            ],
            "schema_version": 1,
        }
    )
    assert manifest == expected
    assert digest == sha256_bytes(expected)
    assert [member.path for member in members] == ["a.txt", "z.txt"]


@pytest.mark.parametrize(
    "name",
    [
        "/absolute.txt",
        "../traversal.txt",
        "a\\b.txt",
        "caf\N{LATIN SMALL LETTER E WITH ACUTE}.txt",
        "CON.txt",
        "a//b.txt",
        "a./b.txt",
    ],
)
def test_file_maps_reject_nonportable_names(name: str) -> None:
    with pytest.raises(EvidenceError):
        canonical_payload_manifest({name: b"x"})


@pytest.mark.parametrize(
    "files",
    [
        {"A.txt": b"a", "a.TXT": b"b"},
        {"A.txt": b"a", "\N{FULLWIDTH LATIN CAPITAL LETTER A}.txt": b"b"},
        {"a": b"a", "a/b.txt": b"b"},
    ],
)
def test_file_maps_reject_portable_collisions(files: dict[str, bytes]) -> None:
    with pytest.raises(EvidenceError):
        canonical_payload_manifest(files)


def test_directory_and_canonical_zip_have_equal_snapshots(tmp_path: Path) -> None:
    directory = tmp_path / "capture"
    directory.mkdir()
    _write_tree(directory)
    archive = tmp_path / "capture.zip"
    archive.write_bytes(canonical_evidence_zip_bytes(FILES))

    from_directory = read_evidence_container(directory, phase=EvidencePhase.CAPTURE)
    from_zip = read_evidence_container(archive, phase=EvidencePhase.CAPTURE)

    assert from_directory.diagnostics == ()
    assert from_zip.diagnostics == ()
    assert from_directory.files == from_zip.files == tuple(sorted(FILES.items()))
    assert from_directory.container_sha256 is None
    assert from_zip.container_sha256 == sha256_bytes(archive.read_bytes())


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_directory_rejects_unsafe_members(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    safe = root / "safe.txt"
    safe.write_bytes(b"safe")
    unsafe = root / "unsafe.txt"
    if kind == "symlink":
        unsafe.symlink_to(safe)
    elif kind == "hardlink":
        os.link(safe, unsafe)
    else:
        os.mkfifo(unsafe)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert _codes(snapshot) & {
        "EVIDENCE_SYMLINK_FORBIDDEN",
        "EVIDENCE_HARDLINK_FORBIDDEN",
        "EVIDENCE_NONREGULAR_FILE",
    }


def test_directory_rejects_symlinked_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    _write_tree(real)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    snapshot = read_evidence_container(linked, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_SYMLINK_FORBIDDEN" in _codes(snapshot)


def test_directory_rejects_empty_extra_directory(tmp_path: Path) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    _write_tree(root)
    (root / "empty").mkdir()

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_EXTRA_DIRECTORY" in _codes(snapshot)


def test_directory_rejects_undecodable_filename_without_crashing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    raw_path = os.fsencode(root) + b"/\xff.txt"
    fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "PATH_INVALID_UTF8" in _codes(snapshot)


@pytest.mark.parametrize(
    ("constant", "value", "code"),
    [
        ("MAX_EVIDENCE_ENTRIES", 0, "EVIDENCE_ENTRY_LIMIT"),
        ("MAX_EVIDENCE_FILE_BYTES", 0, "EVIDENCE_FILE_SIZE_LIMIT"),
        ("MAX_EVIDENCE_TOTAL_BYTES", 0, "EVIDENCE_TOTAL_SIZE_LIMIT"),
    ],
)
def test_directory_enforces_limits_before_returning_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
    value: int,
    code: str,
) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    _write_tree(root, {"member.txt": b"x"})
    monkeypatch.setattr(container, constant, value)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert code in _codes(snapshot)


def test_directory_entry_limit_stops_before_pinning_excess_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    _write_tree(root, {"a.txt": b"a", "b.txt": b"b"})
    monkeypatch.setattr(container, "MAX_EVIDENCE_ENTRIES", 1)
    original = container.os.open
    evidence_opens = 0

    def guard_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal evidence_opens
        if isinstance(path, str) and path.endswith(".txt"):
            evidence_opens += 1
            if evidence_opens > 1:
                raise AssertionError("scanner pinned a file beyond the entry limit")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(container.os, "open", guard_open)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert _codes(snapshot) == {"EVIDENCE_ENTRY_LIMIT"}


def test_raw_entry_budget_is_reserved_across_recursive_siblings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "capture"
    child = root / "a"
    child.mkdir(parents=True)
    os.mkfifo(child / "x.fifo")
    os.mkfifo(root / "z.fifo")
    monkeypatch.setattr(container, "MAX_EVIDENCE_ENTRIES", 1)
    monkeypatch.setattr(container, "MAX_EVIDENCE_DIRECTORIES", 1)
    original = container.os.stat

    def guard_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if path == "x.fifo":
            raise AssertionError("scanner descended beyond reserved raw budget")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(container.os, "stat", guard_stat)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_ENTRY_LIMIT" in _codes(snapshot)


def test_directory_and_zip_entry_budgets_have_logical_file_parity(
    tmp_path: Path,
) -> None:
    files = {
        f"shared/member-{number:03}.txt": b"x"
        for number in range(container.MAX_EVIDENCE_ENTRIES)
    }
    directory = tmp_path / "capture"
    directory.mkdir()
    _write_tree(directory, files)
    archive = tmp_path / "capture.zip"
    archive.write_bytes(canonical_evidence_zip_bytes(files))

    from_directory = read_evidence_container(
        directory, phase=EvidencePhase.CAPTURE
    )
    from_zip = read_evidence_container(archive, phase=EvidencePhase.CAPTURE)

    assert from_directory.diagnostics == ()
    assert from_zip.diagnostics == ()
    assert from_directory.files == from_zip.files


def test_directory_closes_file_fd_when_post_open_fstat_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    _write_tree(root, {"member.txt": b"x"})
    original_open = container.os.open
    original_fstat = container.os.fstat
    member_fd: int | None = None

    def track_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal member_fd
        fd = original_open(path, flags, *args, **kwargs)
        if path == "member.txt":
            member_fd = fd
        return fd

    def fail_member_fstat(fd: int) -> os.stat_result:
        if fd == member_fd:
            raise OSError(errno.EIO, "injected fstat failure")
        return original_fstat(fd)

    monkeypatch.setattr(container.os, "open", track_open)
    monkeypatch.setattr(container.os, "fstat", fail_member_fstat)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)
    monkeypatch.setattr(container.os, "fstat", original_fstat)

    assert "EVIDENCE_MEMBER_RACE" in _codes(snapshot)
    assert member_fd is not None
    with pytest.raises(OSError):
        original_fstat(member_fd)


def test_directory_closes_child_fd_when_post_open_fstat_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "capture"
    child = root / "child"
    child.mkdir(parents=True)
    _write_tree(root, {"child/member.txt": b"x"})
    original_open = container.os.open
    original_fstat = container.os.fstat
    child_fd: int | None = None

    def track_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal child_fd
        fd = original_open(path, flags, *args, **kwargs)
        if path == "child":
            child_fd = fd
        return fd

    def fail_child_fstat(fd: int) -> os.stat_result:
        if fd == child_fd:
            raise OSError(errno.EIO, "injected child fstat failure")
        return original_fstat(fd)

    monkeypatch.setattr(container.os, "open", track_open)
    monkeypatch.setattr(container.os, "fstat", fail_child_fstat)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)
    monkeypatch.setattr(container.os, "fstat", original_fstat)

    assert "EVIDENCE_MEMBER_RACE" in _codes(snapshot)
    assert child_fd is not None
    with pytest.raises(OSError):
        original_fstat(child_fd)


@pytest.mark.parametrize(
    ("archive_bytes", "code"),
    [
        (
            _zip_bytes({"a.txt": b"a"}, compression=zipfile.ZIP_DEFLATED),
            "EVIDENCE_ZIP_COMPRESSION",
        ),
        (_zip_bytes({"a.txt": b"a"}, comment=b"comment"), "EVIDENCE_ZIP_COMMENT"),
        (_zip_bytes({"a.txt": b"a"}, extra=b"\xfe\xca\x00\x00"), "EVIDENCE_ZIP_EXTRA"),
        (_zip_bytes({"folder/": b""}, mode=0o040755), "EVIDENCE_ZIP_DIRECTORY_ENTRY"),
    ],
)
def test_zip_rejects_noncanonical_metadata(
    tmp_path: Path, archive_bytes: bytes, code: str
) -> None:
    path = tmp_path / "bad.zip"
    path.write_bytes(archive_bytes)

    snapshot = read_evidence_container(path, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert code in _codes(snapshot)


def test_zip_rejects_duplicate_names(tmp_path: Path) -> None:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("same.txt", (1980, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, b"first")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(info, b"second")
    path = tmp_path / "duplicate.zip"
    path.write_bytes(output.getvalue())

    snapshot = read_evidence_container(path, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_ZIP_DUPLICATE" in _codes(snapshot)


def test_zip_rejects_noncanonical_member_order(tmp_path: Path) -> None:
    path = tmp_path / "out-of-order.zip"
    path.write_bytes(_zip_bytes({"z.txt": b"z", "a.txt": b"a"}))

    snapshot = read_evidence_container(path, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_ZIP_NONCANONICAL" in _codes(snapshot)


@pytest.mark.parametrize(
    "name",
    [
        "/absolute.txt",
        "../traversal.txt",
        "a\\b.txt",
        "caf\N{LATIN SMALL LETTER E WITH ACUTE}.txt",
        "CON.txt",
    ],
)
def test_zip_rejects_nonportable_member_names(tmp_path: Path, name: str) -> None:
    path = tmp_path / "bad-name.zip"
    path.write_bytes(_zip_bytes({name: b"x"}))

    snapshot = read_evidence_container(path, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert any(code.startswith("PATH_") for code in _codes(snapshot))


def test_zip_rejects_case_colliding_names(tmp_path: Path) -> None:
    path = tmp_path / "collision.zip"
    path.write_bytes(_zip_bytes({"A.txt": b"a", "a.TXT": b"b"}))

    snapshot = read_evidence_container(path, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "PATH_COLLISION" in _codes(snapshot)


@pytest.mark.parametrize(
    ("flag", "code"),
    [
        (0x1, "EVIDENCE_ZIP_ENCRYPTED"),
        (0x8, "EVIDENCE_ZIP_DATA_DESCRIPTOR"),
    ],
)
def test_zip_rejects_dangerous_flags(tmp_path: Path, flag: int, code: str) -> None:
    path = tmp_path / "flags.zip"
    path.write_bytes(_patch_general_purpose_flag(_zip_bytes({"a": b"a"}), flag))

    snapshot = read_evidence_container(path, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert code in _codes(snapshot)


@pytest.mark.parametrize(
    ("constant", "value", "code"),
    [
        ("MAX_EVIDENCE_ENTRIES", 0, "EVIDENCE_ENTRY_LIMIT"),
        ("MAX_EVIDENCE_FILE_BYTES", 0, "EVIDENCE_FILE_SIZE_LIMIT"),
        ("MAX_EVIDENCE_TOTAL_BYTES", 0, "EVIDENCE_TOTAL_SIZE_LIMIT"),
        ("MAX_EVIDENCE_COMPRESSION_RATIO", 0.5, "EVIDENCE_COMPRESSION_RATIO"),
    ],
)
def test_zip_enforces_versioned_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    constant: str,
    value: object,
    code: str,
) -> None:
    monkeypatch.setattr(container, constant, value)
    path = tmp_path / "limited.zip"
    path.write_bytes(_zip_bytes({"a": b"a"}))

    snapshot = read_evidence_container(path, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert code in _codes(snapshot)


def test_nested_g2_zip_is_validated_once_and_no_deeper(tmp_path: Path) -> None:
    deepest = canonical_evidence_zip_bytes({"leaf.txt": b"leaf"})
    nested = canonical_evidence_zip_bytes({"prerequisites/g2-evidence.zip": deepest})
    outer = tmp_path / "outer.zip"
    outer.write_bytes(
        canonical_evidence_zip_bytes({"prerequisites/g2-evidence.zip": nested})
    )

    snapshot = read_evidence_container(outer, phase=EvidencePhase.SEALED)

    assert snapshot.files == ()
    assert "EVIDENCE_NESTING_DEPTH" in _codes(snapshot)


def test_zip_container_hardlink_is_rejected(tmp_path: Path) -> None:
    first = tmp_path / "first.zip"
    first.write_bytes(canonical_evidence_zip_bytes(FILES))
    linked = tmp_path / "linked.zip"
    os.link(first, linked)

    snapshot = read_evidence_container(linked, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_HARDLINK_FORBIDDEN" in _codes(snapshot)


def test_zip_final_path_stat_error_becomes_stable_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "capture.zip"
    archive.write_bytes(canonical_evidence_zip_bytes(FILES))
    original = container.os.stat
    leaf_stats = 0

    def fail_final_stat(
        path: object, *args: object, **kwargs: object
    ) -> os.stat_result:
        nonlocal leaf_stats
        if path == "capture.zip":
            leaf_stats += 1
            if leaf_stats == 2:
                raise OSError(errno.EIO, "injected final stat failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(container.os, "stat", fail_final_stat)

    snapshot = read_evidence_container(archive, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_CONTAINER_RACE" in _codes(snapshot)


def test_directory_detects_file_identity_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    _write_tree(root, {"member.txt": b"original"})
    original = container._read_file_record
    replaced = False

    def replace_before_read(record: object) -> bytes:
        nonlocal replaced
        if not replaced:
            replaced = True
            target = root / "member.txt"
            target.unlink()
            target.write_bytes(b"changed!")
        return original(record)

    monkeypatch.setattr(container, "_read_file_record", replace_before_read)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_MEMBER_RACE" in _codes(snapshot)


def test_directory_detects_root_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "capture"
    root.mkdir()
    _write_tree(root, {"member.txt": b"original"})
    displaced = tmp_path / "displaced"
    original = container._read_file_record
    replaced = False

    def replace_root(record: object) -> bytes:
        nonlocal replaced
        data = original(record)
        if not replaced:
            replaced = True
            root.rename(displaced)
            root.mkdir()
            _write_tree(root, {"member.txt": b"attacker"})
        return data

    monkeypatch.setattr(container, "_read_file_record", replace_root)

    snapshot = read_evidence_container(root, phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_ROOT_RACE" in _codes(snapshot)


def test_ancestor_symlink_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    capture = real / "capture"
    capture.mkdir(parents=True)
    _write_tree(capture)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    snapshot = read_evidence_container(
        linked / "capture", phase=EvidencePhase.CAPTURE
    )

    assert snapshot.files == ()
    assert "EVIDENCE_SYMLINK_FORBIDDEN" in _codes(snapshot)


def test_container_path_with_nul_is_a_stable_diagnostic() -> None:
    snapshot = read_evidence_container("bad\x00path", phase=EvidencePhase.CAPTURE)

    assert snapshot.files == ()
    assert "EVIDENCE_PATH_INVALID" in _codes(snapshot)


def test_canonical_zip_has_fixed_metadata_and_is_byte_identical() -> None:
    first = canonical_evidence_zip_bytes(dict(reversed(tuple(FILES.items()))))
    second = canonical_evidence_zip_bytes(FILES)

    assert first == second
    with zipfile.ZipFile(BytesIO(first)) as archive:
        assert archive.comment == b""
        assert archive.namelist() == sorted(FILES)
        for info in archive.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.create_system == 3
            assert stat.S_IFMT(info.external_attr >> 16) == stat.S_IFREG
            assert stat.S_IMODE(info.external_attr >> 16) == 0o644
            assert info.extra == b""
            assert info.comment == b""


def test_publish_is_deterministic_idempotent_and_no_replace(tmp_path: Path) -> None:
    first = publish_evidence_artifacts(
        FILES, bundle_name="bundle", output_root=tmp_path
    )
    second = publish_evidence_artifacts(
        FILES, bundle_name="bundle", output_root=tmp_path
    )

    assert first == second
    bundle_dir, zip_path, zip_digest = first
    assert (
        read_evidence_container(
            bundle_dir, phase=EvidencePhase.CAPTURE
        ).diagnostics
        == ()
    )
    assert zip_digest == sha256_bytes(zip_path.read_bytes())
    with pytest.raises((EvidenceError, InfrastructureError)):
        publish_evidence_artifacts(
            {**FILES, "new.txt": b"different"},
            bundle_name="bundle",
            output_root=tmp_path,
        )
    assert not list(tmp_path.glob(".bundle.*"))


def test_publish_rolls_back_zip_when_directory_no_replace_loses_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def lose_race(*args: object) -> None:
        raise FileExistsError("raced")

    monkeypatch.setattr(container, "_rename_directory_noreplace", lose_race)

    with pytest.raises((EvidenceError, InfrastructureError)):
        publish_evidence_artifacts(FILES, bundle_name="bundle", output_root=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_publish_rejects_existing_hardlinked_zip(tmp_path: Path) -> None:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    _write_tree(bundle_dir)
    external = tmp_path / "external.zip"
    external.write_bytes(canonical_evidence_zip_bytes(FILES))
    os.link(external, tmp_path / "bundle.zip")

    with pytest.raises(EvidenceError):
        publish_evidence_artifacts(FILES, bundle_name="bundle", output_root=tmp_path)


def test_publish_root_rename_cannot_redirect_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    displaced = tmp_path / "displaced"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    original = container._stage_file

    def replace_root(root_fd: int, name: str, data: bytes) -> None:
        original(root_fd, name, data)
        output.rename(displaced)
        output.symlink_to(attacker, target_is_directory=True)

    monkeypatch.setattr(container, "_stage_file", replace_root)

    with pytest.raises(InfrastructureError):
        publish_evidence_artifacts(FILES, bundle_name="bundle", output_root=output)

    assert list(attacker.iterdir()) == []
    assert list(displaced.iterdir()) == []


def test_publish_rechecks_root_after_final_path_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "output"
    output.mkdir()
    displaced = tmp_path / "displaced"
    attacker = tmp_path / "attacker"
    attacker.mkdir()
    original = container._existing_outputs_match

    def replace_after_validation(*args: object, **kwargs: object) -> bool:
        matched = original(*args, **kwargs)
        output.rename(displaced)
        output.symlink_to(attacker, target_is_directory=True)
        return matched

    monkeypatch.setattr(
        container, "_existing_outputs_match", replace_after_validation
    )

    with pytest.raises(InfrastructureError, match="EVIDENCE_OUTPUT_ROOT_RACE"):
        publish_evidence_artifacts(
            FILES, bundle_name="bundle", output_root=output
        )

    assert list(attacker.iterdir()) == []


def test_publish_rejects_invalid_nested_zip_before_writing(
    tmp_path: Path,
) -> None:
    leaf = canonical_evidence_zip_bytes({"leaf.txt": b"leaf"})
    invalid_nested = canonical_evidence_zip_bytes(
        {"prerequisites/g2-evidence.zip": leaf}
    )

    with pytest.raises(EvidenceError):
        publish_evidence_artifacts(
            {"prerequisites/g2-evidence.zip": invalid_nested},
            bundle_name="bundle",
            output_root=tmp_path,
        )

    assert list(tmp_path.iterdir()) == []


def test_publish_surfaces_temp_cleanup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = container.os.unlink
    failed = False

    def fail_once(path: str, *args: object, **kwargs: object) -> None:
        nonlocal failed
        if not failed and path.startswith(".bundle.") and path.endswith(".zip"):
            failed = True
            raise OSError(errno.EIO, "injected cleanup failure")
        original(path, *args, **kwargs)

    monkeypatch.setattr(container.os, "unlink", fail_once)

    with pytest.raises(InfrastructureError, match="EVIDENCE_TEMP_CLEANUP_FAILED"):
        publish_evidence_artifacts(FILES, bundle_name="bundle", output_root=tmp_path)


@pytest.mark.parametrize("failure_call", [1, len(FILES) + 1])
def test_publish_cleans_partial_staging_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_call: int
) -> None:
    original = container._write_all
    calls = 0

    def fail_write(fd: int, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError(errno.EIO, "injected stage failure")
        original(fd, data)

    monkeypatch.setattr(container, "_write_all", fail_write)

    with pytest.raises(InfrastructureError):
        publish_evidence_artifacts(FILES, bundle_name="bundle", output_root=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_publish_rejects_symlinked_output_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(InfrastructureError):
        publish_evidence_artifacts(FILES, bundle_name="bundle", output_root=linked)

    assert list(real.iterdir()) == []


def test_publish_fails_closed_without_dirfd_link_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    limited = frozenset(
        operation
        for operation in container.os.supports_dir_fd
        if operation is not container.os.link
    )
    monkeypatch.setattr(container.os, "supports_dir_fd", limited)

    with pytest.raises(
        InfrastructureError, match="EVIDENCE_ATOMIC_NOREPLACE_UNAVAILABLE"
    ):
        publish_evidence_artifacts(
            FILES, bundle_name="bundle", output_root=tmp_path
        )


def test_publish_rejects_nonportable_bundle_name(tmp_path: Path) -> None:
    with pytest.raises(EvidenceError):
        publish_evidence_artifacts(FILES, bundle_name="../escape", output_root=tmp_path)
