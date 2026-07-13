from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build import kit as kit_module
from catvba_refactor.macro_build.canonical import canonical_json_bytes
from catvba_refactor.macro_build.errors import InfrastructureError, SourceError
from catvba_refactor.macro_build.kit import (
    assemble_catalog,
    stage_build_kit,
    verify_build_kit,
)
from catvba_refactor.macro_build.manifests import ManifestSet
from catvba_refactor.macro_build.model import (
    Component,
    Diagnostic,
    GeneratedSourceSet,
    InputSnapshot,
    Origin,
    ResolvedCatalog,
    ResolvedSourceSet,
    SnapshotMode,
    SourceMember,
    ValidationReport,
)


def _member(
    path: str,
    data: bytes,
    *,
    role: str = "source",
    blob_oid: str | None = "a" * 40,
) -> SourceMember:
    return SourceMember(
        path=path,
        blob_oid=blob_oid,
        raw_sha256=hashlib.sha256(data).hexdigest(),
        role=role,
        data=data,
    )


def _module(
    source_id: str = "core.safe-module",
    *,
    package_id: str = "core",
    vb_name: str = "SafeModule",
    path: str = "catvba_refactor/vba/new/SafeModule.bas",
) -> Component:
    data = (
        f'Attribute VB_Name = "{vb_name}"\r\n'
        "Option Explicit\r\n"
        "Public Sub Run()\r\n"
        "End Sub\r\n"
    ).encode("ascii")
    return Component(
        source_id=source_id,
        origin=Origin.NEW,
        component_type="standard_module",
        vb_name=vb_name,
        members=(_member(path, data),),
        package_id=package_id,
        disposition="candidate",
    )


def _form() -> Component:
    frm = (
        b"VERSION 5.00\r\n"
        b"Begin VB.Form SafeForm\r\n"
        b"End\r\n"
        b'Attribute VB_Name = "SafeForm"\r\n'
        b"Option Explicit\r\n"
    )
    frx = b"\x00\x01FRX-EXACT-BYTES\xff"
    return Component(
        source_id="core.safe-form",
        origin=Origin.NEW,
        component_type="user_form",
        vb_name="SafeForm",
        members=(
            _member(
                "catvba_refactor/vba/new/SafeForm.frm", frm, role="frm"
            ),
            _member(
                "catvba_refactor/vba/new/SafeForm.frx", frx, role="frx"
            ),
        ),
        package_id="core",
        disposition="candidate",
    )


def _snapshot(**changes: Any) -> InputSnapshot:
    values: dict[str, Any] = {
        "mode": SnapshotMode.CANDIDATE,
        "upstream_repository": "verysolecd/Macro_menu",
        "upstream_ref": "dev",
        "upstream_commit": "1" * 40,
        "fork_repository": "doylenehemiah6893-afk/Macro_menu",
        "fork_dev_commit": "2" * 40,
        "work_repository": "doylenehemiah6893-afk/Macro_menu",
        "work_branch": "codex/dev-review-report",
        "work_commit": "3" * 40,
        "work_tree": "4" * 40,
        "manifest_digest": "5" * 64,
        "tool_version": "0.1.0",
        "formal_eligible": True,
    }
    values.update(changes)
    return InputSnapshot(**values)


def _tool(tool_id: str = "core.safe") -> dict[str, Any]:
    return {
        "tool_id": tool_id,
        "caption": "Safe",
        "group_id": "core.general",
        "package_id": "core",
        "module_name": "SafeModule",
        "entrypoint": "Run",
        "document_types": ["none"],
        "required_capabilities": [],
        "risk_level": "read-only",
    }


def _manifests() -> ManifestSet:
    packages = [
        {"package_id": "fleet-spa", "classification": "FLEET_EXTENSION_SPA"},
        {
            "package_id": "core",
            "classification": "CORE_CANDIDATE",
            "reference_allowlist": ["VBA", "CATIA V5 Interfaces"],
        },
    ]
    return ManifestSet(
        project={"schema_version": 1},
        components={"schema_version": 1, "source_roots": [], "components": []},
        packages={"schema_version": 1, "packages": packages},
        tools={"schema_version": 1, "tools": [_tool()]},
        digest="5" * 64,
        report=ValidationReport(),
    )


def _catalog(*, with_form: bool = False) -> tuple[ResolvedCatalog, bytes]:
    module = _module()
    quarantine_data = b"QUARANTINE-MUST-NEVER-BE-STAGED"
    quarantine = Component(
        source_id="legacy.quarantine",
        origin=Origin.QUARANTINE,
        component_type="standard_module",
        vb_name="Legacy",
        members=(_member("Src/Legacy.bas", quarantine_data),),
        package_id=None,
        disposition="quarantine",
    )
    components = (module, _form()) if with_form else (module,)
    resolved = ResolvedSourceSet(
        components=tuple(reversed(components)),
        quarantined=(quarantine,),
        report=ValidationReport(),
    )
    generated = GeneratedSourceSet(components=(), report=ValidationReport())
    catalog = assemble_catalog(_snapshot(), resolved, generated, _manifests())
    assert catalog.report.ok
    return catalog, quarantine_data


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="ascii"))


def _codes(path: Path) -> set[str]:
    return {item.code for item in verify_build_kit(path).diagnostics}


def _rewrite_integrity(kit_dir: Path, kit_id: str) -> None:
    files = {
        path.relative_to(kit_dir).as_posix(): path.read_bytes()
        for path in kit_dir.rglob("*")
        if path.is_file() and path.name not in {"SHA256SUMS", "KIT_COMPLETE"}
    }
    sums = "".join(
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
        for name in sorted(files)
    ).encode("ascii")
    (kit_dir / "SHA256SUMS").write_bytes(sums)
    (kit_dir / "KIT_COMPLETE").write_bytes(
        canonical_json_bytes(
            {
                "complete": True,
                "kit_id": kit_id,
                "sha256sums_sha256": hashlib.sha256(sums).hexdigest(),
            }
        )
    )


def test_assemble_catalog_is_stable_and_excludes_quarantine() -> None:
    catalog, _quarantine_data = _catalog(with_form=True)

    assert [item.source_id for item in catalog.components] == [
        "core.safe-form",
        "core.safe-module",
    ]
    assert [item["package_id"] for item in catalog.packages] == [
        "core",
        "fleet-spa",
    ]
    assert [item["tool_id"] for item in catalog.tools] == ["core.safe"]
    assert all(item.origin is not Origin.QUARANTINE for item in catalog.components)


def test_stages_full_layout_exact_bytes_and_independent_identity_oracles(
    tmp_path: Path,
) -> None:
    catalog, quarantine_data = _catalog(with_form=True)
    receipt = stage_build_kit(catalog, tmp_path / "out")
    kit_dir = Path(receipt.kit_dir)

    required = {
        "kit-manifest.json",
        "catalog.json",
        "receipts/source-resolution.json",
        "receipts/hashes.json",
        "import-order/core.txt",
        "import-order/fleet-spa.txt",
        "references/core.json",
        "references/fleet-spa.json",
        "target-test-plan/target-test-plan.json",
        "evidence-templates/target-verification.json",
        "SHA256SUMS",
        "KIT_COMPLETE",
    }
    actual = {
        path.relative_to(kit_dir).as_posix()
        for path in kit_dir.rglob("*")
        if path.is_file()
    }
    assert required <= actual
    assert (kit_dir / "target-test-plan").is_dir()
    assert (kit_dir / "evidence-templates").is_dir()

    by_path = {
        member.path: member.data
        for component in catalog.components
        for member in component.members
    }
    assert (kit_dir / "packages/core/source/SafeModule.bas").read_bytes() == by_path[
        "catvba_refactor/vba/new/SafeModule.bas"
    ]
    assert (kit_dir / "packages/core/source/SafeForm.frm").read_bytes() == by_path[
        "catvba_refactor/vba/new/SafeForm.frm"
    ]
    assert (kit_dir / "packages/core/source/SafeForm.frx").read_bytes() == by_path[
        "catvba_refactor/vba/new/SafeForm.frx"
    ]
    assert all(quarantine_data not in path.read_bytes() for path in kit_dir.rglob("*") if path.is_file())

    order = (kit_dir / "import-order/core.txt").read_bytes()
    assert order == b"SafeForm.frm\nSafeForm.frx\nSafeModule.bas\n"
    assert b"\r" not in order

    catalog_bytes = (kit_dir / "catalog.json").read_bytes()
    identity = json.loads(catalog_bytes)
    assert catalog_bytes == canonical_json_bytes(identity)
    independent_id = "kit-" + hashlib.sha256(catalog_bytes).hexdigest()[:20]
    assert receipt.kit_id == independent_id

    manifest_bytes = (kit_dir / "kit-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    assert receipt.manifest_sha256 == hashlib.sha256(manifest_bytes).hexdigest()
    assert manifest["kit_id"] == independent_id
    assert manifest["target_build_required"] is True
    assert manifest["catvba_artifacts"] == []
    assert manifest["compile_status"] == "not-run"
    assert manifest["release_eligible"] is False
    assert identity["policy_evidence"] == {
        "compile_status": "not-run",
        "diagnostics": [],
    }
    serialized = catalog_bytes + manifest_bytes
    assert str(tmp_path).encode() not in serialized
    assert b"root" not in serialized

    sums = (kit_dir / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    names = [line.split("  ", 1)[1] for line in sums]
    assert names == sorted(names)
    assert "SHA256SUMS" not in names
    assert "KIT_COMPLETE" not in names
    for line in sums:
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((kit_dir / name).read_bytes()).hexdigest() == digest

    assert verify_build_kit(kit_dir).ok
    assert verify_build_kit(Path(receipt.zip_path)).ok


def test_completion_marker_is_the_last_staged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _ = _catalog()
    writes: list[Path] = []
    original = kit_module._write_file

    def observed(path: Path, data: bytes) -> None:
        writes.append(path)
        original(path, data)

    monkeypatch.setattr(kit_module, "_write_file", observed)
    stage_build_kit(catalog, tmp_path / "out")

    marker_index = next(
        index for index, path in enumerate(writes) if path.name == "KIT_COMPLETE"
    )
    assert all(
        path.name.endswith((".zip.sha256", ".zip"))
        for path in writes[marker_index + 1 :]
    )


def test_two_roots_produce_identical_zip_bytes_and_fixed_metadata(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog(with_form=True)
    first = stage_build_kit(catalog, tmp_path / "one")
    second = stage_build_kit(catalog, tmp_path / "two")
    first_zip = Path(first.zip_path)
    second_zip = Path(second.zip_path)

    assert first.zip_sha256 == second.zip_sha256
    assert first_zip.read_bytes() == second_zip.read_bytes()
    assert hashlib.sha256(first_zip.read_bytes()).hexdigest() == first.zip_sha256
    assert first_zip.with_name(first_zip.name + ".sha256").read_bytes() == (
        f"{first.zip_sha256}  {first_zip.name}\n".encode("ascii")
    )

    with zipfile.ZipFile(first_zip) as archive:
        infos = archive.infolist()
        assert [info.filename for info in infos] == sorted(
            info.filename for info in infos
        )
        assert all(not info.is_dir() for info in infos)
        assert archive.comment == b""
        for info in infos:
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.create_system == 3
            assert stat.S_IFMT(info.external_attr >> 16) == stat.S_IFREG
            assert stat.S_IMODE(info.external_attr >> 16) == 0o644
            assert info.extra == b""
            assert info.comment == b""


def test_identical_existing_kit_is_noop_but_tampered_same_id_refuses(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    output = tmp_path / "out"
    first = stage_build_kit(catalog, output)
    manifest = Path(first.kit_dir) / "kit-manifest.json"
    archive = Path(first.zip_path)
    before = (manifest.stat().st_mtime_ns, archive.stat().st_mtime_ns)

    second = stage_build_kit(catalog, output)
    assert second == first
    assert (manifest.stat().st_mtime_ns, archive.stat().st_mtime_ns) == before

    manifest.write_bytes(manifest.read_bytes() + b"tamper")
    with pytest.raises(InfrastructureError, match="KIT_ID_CONTENT_MISMATCH"):
        stage_build_kit(catalog, output)
    assert manifest.read_bytes().endswith(b"tamper")


@pytest.mark.parametrize("label", ["stale", "concurrent"])
def test_existing_lock_is_never_stolen_or_deleted(
    tmp_path: Path, label: str
) -> None:
    catalog, _ = _catalog()
    seed = stage_build_kit(catalog, tmp_path / "seed")
    output = tmp_path / label
    lock = output / ".locks" / f"{seed.kit_id}.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(label, encoding="ascii")

    with pytest.raises(InfrastructureError, match="KIT_LOCK_EXISTS"):
        stage_build_kit(catalog, output)
    assert lock.read_text(encoding="ascii") == label
    assert not (output / seed.kit_id).exists()


def test_staging_exception_removes_own_temp_and_lock_without_partial_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _ = _catalog()
    output = tmp_path / "out"
    original = kit_module._write_file

    def fail_catalog(path: Path, data: bytes) -> None:
        if path.name == "catalog.json":
            raise OSError("injected write failure")
        original(path, data)

    monkeypatch.setattr(kit_module, "_write_file", fail_catalog)
    with pytest.raises(InfrastructureError, match="KIT_STAGE_FAILED"):
        stage_build_kit(catalog, output)

    assert not any(output.glob(".kit-*.tmp-*"))
    assert not any((output / ".locks").glob("*.lock"))
    assert not any(path.name.startswith("kit-") for path in output.iterdir() if path.is_dir())


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (
            lambda catalog: replace(
                catalog,
                snapshot=replace(catalog.snapshot, formal_eligible=False),
            ),
            "SNAPSHOT_NOT_FORMAL",
        ),
        (
            lambda catalog: replace(
                catalog,
                snapshot=replace(catalog.snapshot, mode=SnapshotMode.WORKTREE),
            ),
            "SNAPSHOT_NOT_CANDIDATE",
        ),
        (
            lambda catalog: replace(
                catalog,
                report=ValidationReport(
                    (Diagnostic("BLOCKED", "x", "blocked"),)
                ),
            ),
            "CATALOG_DIAGNOSTICS",
        ),
        (
            lambda catalog: replace(
                catalog, components=(), tools=(), report=ValidationReport()
            ),
            "NO_BUILDABLE_COMPONENTS",
        ),
        (
            lambda catalog: _replace_first_member_path(catalog, "../SafeModule.bas"),
            "PATH_TRAVERSAL",
        ),
        (
            lambda catalog: _replace_first_member_path(catalog, "old.CaTvBa"),
            "CATVBA_FORBIDDEN",
        ),
    ],
)
def test_rejected_catalog_creates_no_output_directory(
    tmp_path: Path,
    mutator: Any,
    code: str,
) -> None:
    catalog, _ = _catalog()
    output = tmp_path / code

    with pytest.raises(SourceError, match=code):
        stage_build_kit(mutator(catalog), output)
    assert not output.exists()


def _replace_first_member_path(
    catalog: ResolvedCatalog, path: str
) -> ResolvedCatalog:
    component = catalog.components[0]
    member = replace(component.members[0], path=path)
    return replace(
        catalog,
        components=(replace(component, members=(member,)), *catalog.components[1:]),
    )


@pytest.mark.parametrize(
    "paths",
    [
        ("new/ReadMe.bas", "other/README.BAS"),
        ("new/R\u00e9sum\u00e9.bas", "other/Re\u0301sume\u0301.bas"),
    ],
)
def test_portable_output_collisions_fail_before_output_creation(
    tmp_path: Path, paths: tuple[str, str]
) -> None:
    catalog, _ = _catalog()
    first = _module("core.first", vb_name="First", path=paths[0])
    second = _module("core.second", vb_name="Second", path=paths[1])
    colliding = replace(
        catalog,
        components=(first, second),
        tools=(),
        report=ValidationReport(),
    )
    output = tmp_path / "collision"

    with pytest.raises(SourceError, match="PATH_COLLISION"):
        stage_build_kit(colliding, output)
    assert not output.exists()


def test_directory_verifier_reports_tampering_extra_files_and_wrong_status(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "out")
    kit_dir = Path(receipt.kit_dir)
    source = kit_dir / "packages/core/source/SafeModule.bas"
    source.write_bytes(source.read_bytes() + b"tamper")
    (kit_dir / "unexpected.txt").write_text("extra", encoding="ascii")
    manifest = _json(kit_dir / "kit-manifest.json")
    manifest["compile_status"] = "passed"
    manifest["kit_id"] = "kit-00000000000000000000"
    (kit_dir / "kit-manifest.json").write_bytes(canonical_json_bytes(manifest))

    codes = _codes(kit_dir)
    assert {
        "HASH_MISMATCH",
        "EXTRA_FILE",
        "IMMUTABLE_STATUS_INVALID",
        "WRONG_KIT_ID",
    } <= codes


def test_directory_verifier_rejects_malformed_hashes_forbidden_catvba_and_symlink(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "out")
    kit_dir = Path(receipt.kit_dir)
    (kit_dir / "SHA256SUMS").write_text("not a hash line\n", encoding="ascii")
    (kit_dir / "OLD.CATVBA").write_bytes(b"legacy")
    os.symlink("catalog.json", kit_dir / "catalog-link.json")

    codes = _codes(kit_dir)
    assert {
        "HASH_MANIFEST_MALFORMED",
        "CATVBA_FORBIDDEN",
        "SYMLINK_ENTRY",
    } <= codes


def test_verifier_reconstructs_required_graph_even_if_hashes_are_repaired(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "out")
    kit_dir = Path(receipt.kit_dir)
    (kit_dir / "packages/core/source/SafeModule.bas").unlink()
    (kit_dir / "import-order/core.txt").unlink()
    hashes = _json(kit_dir / "receipts/hashes.json")
    hashes["members"] = []
    (kit_dir / "receipts/hashes.json").write_bytes(canonical_json_bytes(hashes))
    references = _json(kit_dir / "references/core.json")
    references["reference_allowlist"] = []
    (kit_dir / "references/core.json").write_bytes(
        canonical_json_bytes(references)
    )
    (kit_dir / "unexpected-empty").mkdir()
    _rewrite_integrity(kit_dir, receipt.kit_id)

    codes = _codes(kit_dir)
    assert "MISSING_FILE" in codes
    assert "CATALOG_CONTENT_MISMATCH" in codes
    assert "EXTRA_DIRECTORY" in codes


def test_zip_verifier_rejects_duplicate_unsafe_non_nfc_and_symlink_entries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "malicious.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("duplicate.txt", b"one")
        archive.writestr("duplicate.txt", b"two")
        archive.writestr("../escape.txt", b"escape")
        archive.writestr("/absolute.txt", b"absolute")
        archive.writestr("back\\slash.txt", b"backslash")
        archive.writestr("Re\u0301sume\u0301.txt", b"non-nfc")
        archive.writestr("OLD.CATVBA", b"forbidden")
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, b"catalog.json")

    codes = _codes(path)
    assert {
        "DUPLICATE_ENTRY",
        "PATH_TRAVERSAL",
        "PATH_ABSOLUTE",
        "PATH_BACKSLASH",
        "PATH_NOT_NFC",
        "CATVBA_FORBIDDEN",
        "SYMLINK_ENTRY",
    } <= codes


def test_zip_verifier_checks_sidecar_and_does_not_extract_entries(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "out")
    archive = Path(receipt.zip_path)
    sidecar = archive.with_name(archive.name + ".sha256")
    sidecar.write_text("0" * 64 + f"  {archive.name}\n", encoding="ascii")
    extraction_candidate = tmp_path / "escape.txt"

    assert "ZIP_SIDECAR_MISMATCH" in _codes(archive)
    assert not extraction_candidate.exists()


def test_manifest_digest_mismatch_is_carried_as_stable_catalog_diagnostic() -> None:
    manifests = _manifests()
    catalog = assemble_catalog(
        _snapshot(manifest_digest="0" * 64),
        ResolvedSourceSet((_module(),), (), ValidationReport()),
        GeneratedSourceSet((), ValidationReport()),
        manifests,
    )

    assert [item.code for item in catalog.report.diagnostics] == [
        "MANIFEST_DIGEST_MISMATCH"
    ]
