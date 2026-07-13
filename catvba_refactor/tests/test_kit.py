from __future__ import annotations

import hashlib
import io
import json
import math
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
from catvba_refactor.macro_build.generator import generate_sources
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


def _git_blob_oid(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _member(
    path: str,
    data: bytes,
    *,
    role: str = "source",
    blob_oid: str | None = "auto",
) -> SourceMember:
    return SourceMember(
        path=path,
        blob_oid=_git_blob_oid(data) if blob_oid == "auto" else blob_oid,
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
        encoding_decision=None,
    )


def _form() -> Component:
    frm = (
        b"VERSION 5.00\r\n"
        b"Begin VB.Form SafeForm\r\n"
        b'OleObjectBlob = "SafeForm.frx":0000\r\n'
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
        encoding_decision=None,
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
        encoding_decision=None,
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


def test_explicit_encoding_decision_is_bound_into_verifiable_kit(
    tmp_path: Path,
) -> None:
    data = (
        b'Attribute VB_Name = "SafeModule"\r\n'
        b"Option Explicit\r\n"
        b"'\xc2\xa9\r\n"
        b"Public Sub Run()\r\n"
        b"End Sub\r\n"
    )
    kit_ids: list[str] = []
    for decision in ("cp936", "utf-8"):
        component = replace(
            _module(),
            members=(
                _member("catvba_refactor/vba/new/SafeModule.bas", data),
            ),
            encoding_decision=decision,
        )
        catalog = assemble_catalog(
            _snapshot(),
            ResolvedSourceSet(
                components=(component,),
                quarantined=(),
                report=ValidationReport(),
            ),
            GeneratedSourceSet(components=(), report=ValidationReport()),
            _manifests(),
        )
        assert catalog.report.ok

        receipt = stage_build_kit(catalog, tmp_path / decision)
        kit_dir = Path(receipt.kit_dir)
        catalog_record = _json(kit_dir / "catalog.json")["components"][0]
        hash_record = _json(kit_dir / "receipts/hashes.json")["members"][0]

        assert catalog_record["encoding_decision"] == decision
        assert hash_record["encoding_decision"] == decision
        assert verify_build_kit(kit_dir).ok
        kit_ids.append(receipt.kit_id)

    assert len(set(kit_ids)) == 2


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


def _write_zip_sidecar(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.with_name(path.name + ".sha256").write_bytes(
        f"{hashlib.sha256(data).hexdigest()}  {path.name}\n".encode("ascii")
    )


def _fixed_zip(files: dict[str, bytes], names: list[str] | None = None) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in names or sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.extra = b""
            info.comment = b""
            archive.writestr(info, files[name])
    return stream.getvalue()


def _rebind_catalog_identity(kit_dir: Path, mutator: Any) -> str:
    catalog_path = kit_dir / "catalog.json"
    catalog = _json(catalog_path)
    mutator(catalog)
    catalog_bytes = canonical_json_bytes(catalog)
    kit_id = "kit-" + hashlib.sha256(catalog_bytes).hexdigest()[:20]
    catalog_path.write_bytes(catalog_bytes)

    manifest = _json(kit_dir / "kit-manifest.json")
    manifest["kit_id"] = kit_id
    manifest["identity_sha256"] = hashlib.sha256(catalog_bytes).hexdigest()
    manifest["manifest_digest"] = catalog["snapshot"].get("manifest_digest")
    (kit_dir / "kit-manifest.json").write_bytes(canonical_json_bytes(manifest))

    resolution = _json(kit_dir / "receipts/source-resolution.json")
    resolution["kit_id"] = kit_id
    resolution["components"] = catalog.get("components", [])
    (kit_dir / "receipts/source-resolution.json").write_bytes(
        canonical_json_bytes(resolution)
    )
    evidence = _json(kit_dir / "evidence-templates/target-verification.json")
    evidence["kit_id"] = kit_id
    (kit_dir / "evidence-templates/target-verification.json").write_bytes(
        canonical_json_bytes(evidence)
    )
    _rewrite_integrity(kit_dir, kit_id)
    return kit_id


def _attack_container(
    kit_dir: Path, kit_id: str, kind: str, root: Path
) -> Path:
    bound = kit_dir.with_name(kit_id)
    kit_dir.rename(bound)
    if kind == "directory":
        return bound

    files = {
        path.relative_to(bound).as_posix(): path.read_bytes()
        for path in bound.rglob("*")
        if path.is_file()
    }
    archive_root = root / "archive"
    archive_root.mkdir()
    archive = archive_root / f"{kit_id}.zip"
    _write_zip_sidecar(archive, _fixed_zip(files))
    return archive


def _set_receipt_digest(kit_dir: Path, staged_path: str, digest: str) -> None:
    path = kit_dir / "receipts/hashes.json"
    receipt = _json(path)
    matches = [
        member
        for member in receipt["members"]
        if member["staged_path"] == staged_path
    ]
    assert len(matches) == 1
    matches[0]["raw_sha256"] = digest
    path.write_bytes(canonical_json_bytes(receipt))


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
    assert order == b"SafeForm.frm\nSafeModule.bas\n"
    assert b"\r" not in order

    catalog_bytes = (kit_dir / "catalog.json").read_bytes()
    identity = json.loads(catalog_bytes)
    assert catalog_bytes == canonical_json_bytes(identity)
    expected_identity = {
        "schema_version": 1,
        "snapshot": {
            "mode": "candidate",
            "upstream_commit": "1" * 40,
            "fork_dev_commit": "2" * 40,
            "work_commit": "3" * 40,
            "work_tree": "4" * 40,
            "manifest_digest": "5" * 64,
            "tool_version": "0.1.0",
            "formal_eligible": True,
        },
        "components": [
            {
                "source_id": "core.safe-form",
                "origin": "new",
                "component_type": "user_form",
                "vb_name": "SafeForm",
                "package_id": "core",
                "disposition": "candidate",
                "encoding_decision": None,
                "members": [
                    {
                        "path": "catvba_refactor/vba/new/SafeForm.frm",
                        "blob_oid": _git_blob_oid(
                            by_path["catvba_refactor/vba/new/SafeForm.frm"]
                        ),
                        "raw_sha256": hashlib.sha256(
                            by_path["catvba_refactor/vba/new/SafeForm.frm"]
                        ).hexdigest(),
                        "role": "frm",
                    },
                    {
                        "path": "catvba_refactor/vba/new/SafeForm.frx",
                        "blob_oid": _git_blob_oid(
                            by_path["catvba_refactor/vba/new/SafeForm.frx"]
                        ),
                        "raw_sha256": hashlib.sha256(
                            by_path["catvba_refactor/vba/new/SafeForm.frx"]
                        ).hexdigest(),
                        "role": "frx",
                    },
                ],
            },
            {
                "source_id": "core.safe-module",
                "origin": "new",
                "component_type": "standard_module",
                "vb_name": "SafeModule",
                "package_id": "core",
                "disposition": "candidate",
                "encoding_decision": None,
                "members": [
                    {
                        "path": "catvba_refactor/vba/new/SafeModule.bas",
                        "blob_oid": _git_blob_oid(
                            by_path["catvba_refactor/vba/new/SafeModule.bas"]
                        ),
                        "raw_sha256": hashlib.sha256(
                            by_path["catvba_refactor/vba/new/SafeModule.bas"]
                        ).hexdigest(),
                        "role": "source",
                    }
                ],
            },
        ],
        "packages": [
            {
                "package_id": "core",
                "classification": "CORE_CANDIDATE",
                "reference_allowlist": ["VBA", "CATIA V5 Interfaces"],
            },
            {
                "package_id": "fleet-spa",
                "classification": "FLEET_EXTENSION_SPA",
            },
        ],
        "tools": [_tool()],
        "policy_evidence": {"compile_status": "not-run", "diagnostics": []},
    }
    assert identity == expected_identity
    independent_id = "kit-" + hashlib.sha256(catalog_bytes).hexdigest()[:20]
    assert independent_id == "kit-4a6b9ce405d1f9b0a5ec"
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
    with pytest.warns(UserWarning, match="Duplicate name"):
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


@pytest.mark.parametrize(
    "invalid",
    [b"secret", Path("/secret"), object(), math.nan, {1: "not-a-string-key"}],
)
def test_manual_catalog_rejects_noncanonical_or_secret_package_fields(
    tmp_path: Path, invalid: Any
) -> None:
    catalog, _ = _catalog()
    package = dict(catalog.packages[0])
    package["secret_path"] = invalid
    bypass = replace(
        catalog,
        packages=(package, *catalog.packages[1:]),
        report=ValidationReport(),
    )

    with pytest.raises(SourceError, match="CATALOG_RECORD_INVALID"):
        stage_build_kit(bypass, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_id", "Bad ID"),
        ("package_id", "Bad/Package"),
        ("vb_name", "9BadName"),
        ("component_type", "document_module"),
    ],
)
def test_manual_component_identity_is_revalidated_before_output(
    tmp_path: Path, field: str, value: str
) -> None:
    catalog, _ = _catalog()
    bad_component = replace(catalog.components[0], **{field: value})
    bypass = replace(
        catalog,
        components=(bad_component,),
        tools=(),
        report=ValidationReport(),
    )

    with pytest.raises(SourceError, match="CATALOG_RECORD_INVALID"):
        stage_build_kit(bypass, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "path",
    [
        "new/Bad:Name.bas",
        "new/Bad<Name.bas",
        "new/control\x80.bas",
        "C:/absolute.bas",
        "//server/share/SafeModule.bas",
    ],
)
def test_creator_rejects_windows_unsafe_member_names(
    tmp_path: Path, path: str
) -> None:
    catalog, _ = _catalog()
    bypass = _replace_first_member_path(catalog, path)

    with pytest.raises(SourceError, match="PATH_"):
        stage_build_kit(bypass, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("kind", ["missing-frx", "wrong-role", "wrong-stem"])
def test_creator_rejects_malformed_form_bundles(
    tmp_path: Path, kind: str
) -> None:
    catalog, _ = _catalog(with_form=True)
    form = catalog.components[0]
    if kind == "missing-frx":
        form = replace(form, members=(form.members[0],))
    elif kind == "wrong-role":
        form = replace(
            form,
            members=(form.members[0], replace(form.members[1], role="source")),
        )
    else:
        form = replace(
            form,
            members=(
                form.members[0],
                replace(form.members[1], path="new/Other.frx"),
            ),
        )
    bypass = replace(
        catalog,
        components=(form, *catalog.components[1:]),
        report=ValidationReport(),
    )

    with pytest.raises(SourceError, match="FORM_BINDING_INVALID"):
        stage_build_kit(bypass, tmp_path / "out")


def test_snapshot_repository_labels_do_not_change_immutable_kit_identity(
    tmp_path: Path,
) -> None:
    first, _ = _catalog()
    noisy_snapshot = replace(
        first.snapshot,
        upstream_repository="/home/alice/private/upstream",
        upstream_ref="refs/users/alice/private",
        fork_repository="C:/Users/Alice/fork",
        work_repository="//server/private/work",
        work_branch="secret-user-branch",
    )
    second = replace(first, snapshot=noisy_snapshot)

    first_receipt = stage_build_kit(first, tmp_path / "one")
    second_receipt = stage_build_kit(second, tmp_path / "two")
    assert second_receipt.kit_id == first_receipt.kit_id
    assert Path(second_receipt.zip_path).read_bytes() == Path(
        first_receipt.zip_path
    ).read_bytes()


def test_directory_and_zip_container_names_are_bound_to_catalog_id(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "out")
    renamed_dir = tmp_path / "renamed-directory"
    shutil.copytree(receipt.kit_dir, renamed_dir)
    assert "WRONG_CONTAINER_NAME" in _codes(renamed_dir)

    original_zip = Path(receipt.zip_path)
    renamed_zip = tmp_path / "renamed.zip"
    _write_zip_sidecar(renamed_zip, original_zip.read_bytes())
    assert "WRONG_CONTAINER_NAME" in _codes(renamed_zip)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["snapshot"].update(mode="worktree"),
        lambda value: value["snapshot"].update(formal_eligible=False),
        lambda value: value["snapshot"].update(work_branch="secret"),
        lambda value: value.update(components=[]),
        lambda value: value["packages"][0].update(secret="/private"),
        lambda value: value["tools"][0].update(module_name="9Bad"),
        lambda value: value["tools"][0].update(entrypoint="Missing"),
        lambda value: value["components"][0]["members"][0].update(
            path="new/Re\u0301sume\u0301.bas"
        ),
        lambda value: value["policy_evidence"].update(extra="pass"),
    ],
)
def test_verifier_rejects_self_consistent_untrusted_catalogs(
    tmp_path: Path, mutator: Any
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    candidate = tmp_path / "candidate"
    shutil.copytree(receipt.kit_dir, candidate)
    kit_id = _rebind_catalog_identity(candidate, mutator)
    bound = tmp_path / kit_id
    candidate.rename(bound)

    assert "CATALOG_MALFORMED" in _codes(bound)


def test_manual_and_embedded_type_confusion_fail_closed(tmp_path: Path) -> None:
    catalog, _ = _catalog()
    package = dict(catalog.packages[0])
    package["classification"] = []
    bypass = replace(
        catalog,
        packages=(package, *catalog.packages[1:]),
        report=ValidationReport(),
    )
    with pytest.raises(SourceError, match="CATALOG_RECORD_INVALID"):
        stage_build_kit(bypass, tmp_path / "manual")

    receipt = stage_build_kit(catalog, tmp_path / "seed")
    candidate = tmp_path / "candidate"
    shutil.copytree(receipt.kit_dir, candidate)
    kit_id = _rebind_catalog_identity(
        candidate,
        lambda value: value["packages"][0].update(classification=[]),
    )
    bound = tmp_path / kit_id
    candidate.rename(bound)
    assert "CATALOG_MALFORMED" in _codes(bound)


def test_verifier_reruns_static_policy_on_self_consistent_sources(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    candidate = tmp_path / "candidate"
    shutil.copytree(receipt.kit_dir, candidate)
    source = candidate / "packages/core/source/SafeModule.bas"
    denied = (
        b'Attribute VB_Name = "SafeModule"\r\n'
        b"Option Explicit\r\n"
        b"Public Sub Run()\r\n"
        b'    Shell "forbidden"\r\n'
        b"End Sub\r\n"
    )
    source.write_bytes(denied)
    digest = hashlib.sha256(denied).hexdigest()

    def mutate(value: dict[str, Any]) -> None:
        value["components"][0]["members"][0]["raw_sha256"] = digest

    kit_id = _rebind_catalog_identity(candidate, mutate)
    hashes = _json(candidate / "receipts/hashes.json")
    hashes["members"][0]["raw_sha256"] = digest
    (candidate / "receipts/hashes.json").write_bytes(canonical_json_bytes(hashes))
    _rewrite_integrity(candidate, kit_id)
    bound = tmp_path / kit_id
    candidate.rename(bound)

    assert "CATALOG_POLICY_INVALID" in _codes(bound)


@pytest.mark.parametrize("container_kind", ["directory", "zip"])
def test_verifier_rejects_resigned_noncanonical_component_order(
    tmp_path: Path, container_kind: str
) -> None:
    catalog, _ = _catalog(with_form=True)
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    candidate = tmp_path / "candidate"
    shutil.copytree(receipt.kit_dir, candidate)

    def reverse_components(value: dict[str, Any]) -> None:
        value["components"].reverse()

    kit_id = _rebind_catalog_identity(candidate, reverse_components)
    (candidate / "import-order/core.txt").write_bytes(
        b"SafeModule.bas\nSafeForm.frm\n"
    )
    _rewrite_integrity(candidate, kit_id)
    attack = _attack_container(candidate, kit_id, container_kind, tmp_path)

    report = verify_build_kit(attack)
    assert not report.ok
    assert "CATALOG_NONCANONICAL" in {item.code for item in report.diagnostics}


@pytest.mark.parametrize("container_kind", ["directory", "zip"])
def test_verifier_rejects_resigned_staged_vb_name_identity(
    tmp_path: Path, container_kind: str
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    candidate = tmp_path / "candidate"
    shutil.copytree(receipt.kit_dir, candidate)
    source = candidate / "packages/core/source/SafeModule.bas"
    forged = source.read_bytes().replace(b'"SafeModule"', b'"ForgedModule"')
    source.write_bytes(forged)
    digest = hashlib.sha256(forged).hexdigest()

    def forge_identity(value: dict[str, Any]) -> None:
        component = value["components"][0]
        component["vb_name"] = "ForgedModule"
        component["members"][0]["raw_sha256"] = digest
        value["tools"][0]["module_name"] = "ForgedModule"

    kit_id = _rebind_catalog_identity(candidate, forge_identity)
    hashes = _json(candidate / "receipts/hashes.json")
    hashes["members"][0]["raw_sha256"] = digest
    (candidate / "receipts/hashes.json").write_bytes(canonical_json_bytes(hashes))
    _rewrite_integrity(candidate, kit_id)
    attack = _attack_container(candidate, kit_id, container_kind, tmp_path)

    report = verify_build_kit(attack)
    assert not report.ok
    assert "COMPONENT_IDENTITY_MISMATCH" in {
        item.code for item in report.diagnostics
    }


@pytest.mark.parametrize("container_kind", ["directory", "zip"])
@pytest.mark.parametrize("attack_kind", ["vb-name", "ole-object-blob"])
def test_verifier_parses_resigned_staged_component_semantics(
    tmp_path: Path, container_kind: str, attack_kind: str
) -> None:
    catalog, _ = _catalog(with_form=attack_kind == "ole-object-blob")
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    candidate = tmp_path / "candidate"
    shutil.copytree(receipt.kit_dir, candidate)
    if attack_kind == "vb-name":
        staged_path = "packages/core/source/SafeModule.bas"
        source = candidate / staged_path
        forged = source.read_bytes().replace(b'"SafeModule"', b'"OtherModule"')
        source_id = "core.safe-module"
    else:
        staged_path = "packages/core/source/SafeForm.frm"
        source = candidate / staged_path
        forged = source.read_bytes().replace(b'"SafeForm.frx"', b'"OtherForm.frx"')
        source_id = "core.safe-form"
    source.write_bytes(forged)
    digest = hashlib.sha256(forged).hexdigest()
    oid = _git_blob_oid(forged)

    def resign_source_bytes(value: dict[str, Any]) -> None:
        component = next(
            item for item in value["components"] if item["source_id"] == source_id
        )
        member = next(
            item
            for item in component["members"]
            if item["path"].endswith(Path(staged_path).name)
        )
        member["raw_sha256"] = digest
        member["blob_oid"] = oid

    kit_id = _rebind_catalog_identity(candidate, resign_source_bytes)
    _set_receipt_digest(candidate, staged_path, digest)
    _rewrite_integrity(candidate, kit_id)
    attack = _attack_container(candidate, kit_id, container_kind, tmp_path)

    assert "COMPONENT_IDENTITY_MISMATCH" in _codes(attack)


@pytest.mark.parametrize("container_kind", ["directory", "zip"])
def test_verifier_rebuilds_resigned_generated_source(
    tmp_path: Path, container_kind: str
) -> None:
    resolved = ResolvedSourceSet(
        components=(_module(),), quarantined=(), report=ValidationReport()
    )
    manifests = _manifests()
    generated = generate_sources(resolved, manifests)
    assert generated.report.ok and len(generated.components) == 1
    catalog = assemble_catalog(_snapshot(), resolved, generated, manifests)
    assert catalog.report.ok
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    candidate = tmp_path / "candidate"
    shutil.copytree(receipt.kit_dir, candidate)
    staged_path = "packages/core/source/MM_GeneratedCatalog.bas"
    source = candidate / staged_path
    forged = source.read_bytes().replace(b'"Safe"', b'"Forged"')
    assert forged != source.read_bytes()
    source.write_bytes(forged)
    digest = hashlib.sha256(forged).hexdigest()

    def resign_generated_bytes(value: dict[str, Any]) -> None:
        component = next(
            item
            for item in value["components"]
            if item["source_id"] == "generated.tool-catalog"
        )
        component["members"][0]["raw_sha256"] = digest

    kit_id = _rebind_catalog_identity(candidate, resign_generated_bytes)
    _set_receipt_digest(candidate, staged_path, digest)
    _rewrite_integrity(candidate, kit_id)
    attack = _attack_container(candidate, kit_id, container_kind, tmp_path)

    assert "COMPONENT_IDENTITY_MISMATCH" in _codes(attack)


def test_creator_authenticates_source_hash_before_output(tmp_path: Path) -> None:
    catalog, _ = _catalog()
    component = catalog.components[0]
    member = replace(component.members[0], raw_sha256="0" * 64)
    bypass = replace(
        catalog,
        components=(replace(component, members=(member,)),),
        report=ValidationReport(),
    )
    with pytest.raises(SourceError, match="SOURCE_HASH_MISMATCH"):
        stage_build_kit(bypass, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_creator_authenticates_git_blob_identity_before_output(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    component = catalog.components[0]
    member = replace(component.members[0], blob_oid="0" * 40)
    bypass = replace(
        catalog,
        components=(replace(component, members=(member,)),),
        report=ValidationReport(),
    )

    with pytest.raises(SourceError, match="COMPONENT_IDENTITY_MISMATCH"):
        stage_build_kit(bypass, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_verifier_rejects_bad_windows_name_in_directory_and_zip(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    kit_dir = Path(receipt.kit_dir)
    bad = kit_dir / "Bad:Name"
    bad.write_bytes(b"bad")
    assert "PATH_INVALID_CHARACTER" in _codes(kit_dir)

    files = {
        path.relative_to(kit_dir).as_posix(): path.read_bytes()
        for path in kit_dir.rglob("*")
        if path.is_file()
    }
    archive = tmp_path / f"{receipt.kit_id}.zip"
    _write_zip_sidecar(archive, _fixed_zip(files))
    assert "PATH_INVALID_CHARACTER" in _codes(archive)


def test_zip_verifier_requires_exact_canonical_container_bytes(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog(with_form=True)
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    source_zip = Path(receipt.zip_path)
    with zipfile.ZipFile(source_zip) as archive:
        files = {info.filename: archive.read(info) for info in archive.infolist()}

    mutations: dict[str, bytes] = {
        "reverse": _fixed_zip(files, list(reversed(sorted(files)))),
        "prefix": b"self-extract-prefix" + source_zip.read_bytes(),
        "trailing": source_zip.read_bytes() + b"trailing-garbage",
    }
    local_header = bytearray(source_zip.read_bytes())
    assert local_header[:4] == b"PK\x03\x04"
    local_header[10] = 2
    mutations["local-header"] = bytes(local_header)

    for label, data in mutations.items():
        parent = tmp_path / label
        parent.mkdir()
        path = parent / f"{receipt.kit_id}.zip"
        _write_zip_sidecar(path, data)
        assert "ZIP_NOT_CANONICAL" in _codes(path), label


def test_verifier_rejects_symlinked_zip_sidecar_and_ancestor(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    receipt = stage_build_kit(catalog, tmp_path / "seed")
    original = Path(receipt.zip_path)

    symlink_zip = tmp_path / f"{receipt.kit_id}.zip"
    symlink_zip.symlink_to(original)
    assert "SYMLINK_ENTRY" in _codes(symlink_zip)

    copied_zip = tmp_path / "copy" / f"{receipt.kit_id}.zip"
    copied_zip.parent.mkdir()
    copied_zip.write_bytes(original.read_bytes())
    copied_zip.with_name(copied_zip.name + ".sha256").symlink_to(
        original.with_name(original.name + ".sha256")
    )
    assert "SYMLINK_ENTRY" in _codes(copied_zip)

    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(Path(receipt.kit_dir).parent, target_is_directory=True)
    linked_dir = linked_parent / receipt.kit_id
    assert "SYMLINK_ANCESTOR" in _codes(linked_dir)


def test_existing_primary_kit_resumes_missing_deterministic_derivatives(
    tmp_path: Path,
) -> None:
    catalog, _ = _catalog()
    first = stage_build_kit(catalog, tmp_path / "out")
    archive = Path(first.zip_path)
    sidecar = archive.with_name(archive.name + ".sha256")
    archive_bytes = archive.read_bytes()
    sidecar_bytes = sidecar.read_bytes()
    archive.unlink()
    sidecar.unlink()

    resumed = stage_build_kit(catalog, tmp_path / "out")
    assert resumed == first
    assert archive.read_bytes() == archive_bytes
    assert sidecar.read_bytes() == sidecar_bytes


def test_destination_race_never_overwrites_dangling_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _ = _catalog()
    output = tmp_path / "out"
    original = kit_module._publish_directory_noreplace

    def race(source: Path, destination: Path) -> None:
        destination.symlink_to("missing-target", target_is_directory=True)
        original(source, destination)

    monkeypatch.setattr(kit_module, "_publish_directory_noreplace", race)
    with pytest.raises(InfrastructureError, match="KIT_OUTPUT_COLLISION"):
        stage_build_kit(catalog, output)
    symlinks = [path for path in output.iterdir() if path.is_symlink()]
    assert len(symlinks) == 1
    assert os.readlink(symlinks[0]) == "missing-target"


def test_replaced_lock_is_not_deleted_and_ownership_loss_surfaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _ = _catalog()
    output = tmp_path / "out"
    original = kit_module._write_layout

    def replace_lock(root: Path, files: Any) -> None:
        lock = next((output / ".locks").glob("*.lock"))
        lock.unlink()
        lock.write_text("replacement", encoding="ascii")
        original(root, files)

    monkeypatch.setattr(kit_module, "_write_layout", replace_lock)
    with pytest.raises(InfrastructureError, match="KIT_LOCK_OWNERSHIP_LOST"):
        stage_build_kit(catalog, output)
    lock = next((output / ".locks").glob("*.lock"))
    assert lock.read_text(encoding="ascii") == "replacement"


def test_post_commit_derivative_failure_leaves_valid_primary_for_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _ = _catalog()
    output = tmp_path / "out"
    original = kit_module._publish_file_noreplace
    attempts = 0

    def fail_first(source: Path, destination: Path) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise InfrastructureError("INJECTED_DERIVATIVE_FAILURE")
        original(source, destination)

    monkeypatch.setattr(kit_module, "_publish_file_noreplace", fail_first)
    with pytest.raises(InfrastructureError, match="INJECTED_DERIVATIVE_FAILURE"):
        stage_build_kit(catalog, output)

    primary = next(path for path in output.glob("kit-*") if path.is_dir())
    assert verify_build_kit(primary).ok
    monkeypatch.setattr(kit_module, "_publish_file_noreplace", original)
    resumed = stage_build_kit(catalog, output)
    assert Path(resumed.zip_path).is_file()


def test_cleanup_failure_is_not_silently_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, _ = _catalog()
    original_write = kit_module._write_file

    def fail_write(path: Path, data: bytes) -> None:
        if path.name == "catalog.json":
            raise OSError("write failed")
        original_write(path, data)

    def fail_cleanup(path: Path) -> None:
        raise OSError("cleanup failed")

    monkeypatch.setattr(kit_module, "_write_file", fail_write)
    monkeypatch.setattr(kit_module, "_remove_tree", fail_cleanup)
    with pytest.raises(InfrastructureError, match="KIT_CLEANUP_FAILED"):
        stage_build_kit(catalog, tmp_path / "out")


def test_lock_directory_is_private_and_owned(tmp_path: Path) -> None:
    catalog, _ = _catalog()
    output = tmp_path / "out"
    stage_build_kit(catalog, output)

    status = (output / ".locks").stat()
    assert stat.S_IMODE(status.st_mode) == 0o700
    assert status.st_uid == os.geteuid()
