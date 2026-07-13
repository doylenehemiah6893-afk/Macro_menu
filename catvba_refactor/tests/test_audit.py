from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePath
from typing import Any

import pytest
import olefile

from catvba_refactor.macro_build import audit as audit_module
from catvba_refactor.macro_build.audit import audit_catvba
from catvba_refactor.macro_build.canonical import canonical_json_bytes
from catvba_refactor.macro_build.errors import VerificationError
from catvba_refactor.macro_build.kit import stage_build_kit
from catvba_refactor.macro_build.model import (
    Component,
    InputSnapshot,
    Origin,
    ResolvedCatalog,
    SnapshotMode,
    SourceMember,
    ValidationReport,
)


KNOWN_CATVBA_SHA256 = (
    "b09195d5bf2787715cf4e8a50c840b0ce256a2408c83038149e1853e27906ba5"
)
MAX_CAPTURE = 1024 * 1024


def _repository_catvba() -> Path:
    return Path(__file__).resolve().parents[2] / "CATIA_V5_SimpleMacroMenu.catvba"


def _git_blob_oid(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _stage_audit_kit(
    tmp_path: Path,
    package_sources: dict[str, list[tuple[str, bytes]]],
    *,
    references: dict[str, list[str]] | None = None,
    decisions: dict[tuple[str, str], str | None] | None = None,
) -> Path:
    references = references or {}
    decisions = decisions or {}
    components: list[Component] = []
    for package_id, sources in sorted(package_sources.items()):
        for index, (name, data) in enumerate(sources):
            path = f"inputs/{package_id}/{name}"
            components.append(
                Component(
                    source_id=f"{package_id}.source-{index}",
                    origin=Origin.NEW,
                    component_type="standard_module",
                    vb_name=PurePath(name).stem,
                    members=(
                        SourceMember(
                            path=path,
                            blob_oid=_git_blob_oid(data),
                            raw_sha256=hashlib.sha256(data).hexdigest(),
                            role="source",
                            data=data,
                        ),
                    ),
                    package_id=package_id,
                    disposition="candidate",
                    encoding_decision=decisions.get((package_id, name)),
                )
            )
    package_records = tuple(
        {
            "package_id": package_id,
            "classification": (
                "CORE_CANDIDATE"
                if package_id == "core"
                else "FLEET_EXTENSION_SPA"
            ),
            "reference_allowlist": references.get(package_id, []),
        }
        for package_id in sorted(package_sources)
    )
    snapshot = InputSnapshot(
        mode=SnapshotMode.CANDIDATE,
        upstream_repository="verysolecd/Macro_menu",
        upstream_ref="dev",
        upstream_commit="1" * 40,
        fork_repository="doylenehemiah6893-afk/Macro_menu",
        fork_dev_commit="2" * 40,
        work_repository="doylenehemiah6893-afk/Macro_menu",
        work_branch="codex/dev-review-report",
        work_commit="3" * 40,
        work_tree="4" * 40,
        manifest_digest="5" * 64,
        tool_version="0.1.0",
        formal_eligible=True,
    )
    catalog = ResolvedCatalog(
        snapshot=snapshot,
        components=tuple(components),
        packages=package_records,
        tools=(),
        report=ValidationReport(),
    )
    receipt = stage_build_kit(catalog, tmp_path / "kit-output")
    return Path(receipt.kit_dir) / "kit-manifest.json"


def _mutated_frx_stream(
    tmp_path: Path,
    form_name: str,
    stream_path: str | list[str],
    mutate: Any,
) -> bytes:
    original = (_repository_catvba().parent / "Src" / f"{form_name}.frx").read_bytes()
    ole_offset = original.find(olefile.MAGIC, 0, min(len(original), 4096))
    assert ole_offset >= 0
    payload = tmp_path / f"{form_name}.ole"
    payload.write_bytes(original[ole_offset:])
    compound = olefile.OleFileIO(payload, write_mode=True)
    try:
        stream = bytearray(compound.openstream(stream_path).read())
        mutate(stream)
        compound.write_stream(stream_path, bytes(stream))
    finally:
        compound.close()
    return original[:ole_offset] + payload.read_bytes()


def _copy_legacy(tmp_path: Path) -> Path:
    source = _repository_catvba()
    target = tmp_path / "returned.catvba"
    target.write_bytes(source.read_bytes())
    target.chmod(0o444)
    return target


def _completed(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


def _capture(
    returncode: int | None = 0,
    stdout: bytes = b"",
    stderr: bytes = b"",
    *,
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
    timed_out: bool = False,
) -> Any:
    return audit_module._ProcessCapture(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        timed_out=timed_out,
    )


def _success_pcode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audit_module,
        "_run_bounded_process",
        lambda args, **kwargs: _capture(stdout=b"diagnostic p-code"),
    )


def _codes(report: Any) -> set[str]:
    return {item.code for item in report.diagnostics}


def _decompressed_reference_dir() -> bytes:
    with audit_module.olefile.OleFileIO(_repository_catvba()) as ole:
        entry = next(
            item
            for item in ole.listdir(streams=True, storages=False)
            if len(item) >= 2
            and item[-1].casefold() == "dir"
            and item[-2].casefold() == "vba"
        )
        return audit_module.decompress_stream(
            bytearray(ole.openstream(entry).read())
        )


def test_audits_a_readonly_copy_without_mutating_repository_catvba(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_file = _repository_catvba()
    repository_before = hashlib.sha256(repository_file.read_bytes()).hexdigest()
    returned = _copy_legacy(tmp_path)
    returned_before = returned.read_bytes()
    returned_mode = stat.S_IMODE(returned.stat().st_mode)
    observed: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> Any:
        readonly_copy = Path(args[-1])
        observed["args"] = args
        observed["kwargs"] = kwargs
        observed["copy"] = readonly_copy
        observed["mode"] = stat.S_IMODE(readonly_copy.stat().st_mode)
        observed["sha256"] = hashlib.sha256(readonly_copy.read_bytes()).hexdigest()
        return _capture(stdout=b"p-code is diagnostic only")

    monkeypatch.setattr(audit_module, "_run_bounded_process", fake_run)
    report = audit_catvba(returned)

    assert report.file_sha256 == KNOWN_CATVBA_SHA256
    assert len(report.streams) == 165
    assert len(report.modules) == 77
    assert len(report.references) == 105
    msforms = [item for item in report.references if item["name"] == "MSForms"]
    assert len(msforms) == 1
    assert msforms[0]["guid"] == "{0D452EE1-E08F-101A-852E-02608C4D0BB4}"
    assert report.pcode.status == "ok"
    assert report.pcode.diagnostic_only is True
    assert "CFB_INVALID" not in _codes(report)
    assert "VBA_PARSE_FAILED" not in _codes(report)
    assert all(set(item) == {"path", "size", "sha256"} for item in report.streams)
    assert all(
        {"name", "stream_path", "source_sha256"} <= set(item)
        for item in report.modules
    )
    form_modules = [
        item for item in report.modules if item["name"].casefold().endswith(".frm")
    ]
    assert len(form_modules) == 4
    assert all("form_storage_sha256" in item for item in form_modules)
    assert all("form_designer_sha256" in item for item in form_modules)
    assert all("path" not in item and "libid" not in item for item in report.references)
    assert report.streams == tuple(sorted(report.streams, key=lambda item: item["path"]))
    assert report.modules == tuple(
        sorted(
            report.modules,
            key=lambda item: (item["name"], item["stream_path"], item["source_sha256"]),
        )
    )
    assert observed["args"][:-1] == [
        audit_module.sys.executable,
        "-m",
        "pcodedmp.pcodedmp",
        "-d",
    ]
    assert observed["kwargs"] == {
        "timeout": 60,
        "env": {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONNOUSERSITE": "1",
        },
    }
    assert observed["copy"] != returned
    assert observed["mode"] == 0o444
    assert observed["sha256"] == KNOWN_CATVBA_SHA256
    assert not observed["copy"].exists()
    assert returned.read_bytes() == returned_before
    assert stat.S_IMODE(returned.stat().st_mode) == returned_mode
    assert hashlib.sha256(repository_file.read_bytes()).hexdigest() == repository_before
    assert repository_before == KNOWN_CATVBA_SHA256
    assert str(tmp_path) not in repr(report)


def test_audit_rejects_internal_form_storages_without_source_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)
    _success_pcode(monkeypatch)

    report = audit_catvba(returned)

    orphans = [
        item for item in report.diagnostics if item.code == "FORM_STORAGE_ORPHAN"
    ]
    assert [(item.path, item.details["storage_name"]) for item in orphans] == [
        ("apc/The VBA Project/_VBA_Project/UserForm1", "UserForm1"),
        ("apc/The VBA Project/_VBA_Project/askdir", "askdir"),
    ]


def test_reference_parser_is_structural_and_preserves_duplicate_names() -> None:
    decompressed = _decompressed_reference_dir()
    duplicated = decompressed.replace(b"CATRsc2", b"MSForms").replace(
        "CATRsc2".encode("utf-16le"), "MSForms".encode("utf-16le")
    )

    records = audit_module._parse_logical_references(duplicated)

    assert len(records) == 105
    assert sum(item["name"] == "MSForms" for item in records) == 2


def test_reference_parser_uses_declared_codepage_and_unicode_name() -> None:
    decompressed = _decompressed_reference_dir()
    renamed = decompressed.replace(b"CATRsc2", b"Caf\xe9Lib").replace(
        "CATRsc2".encode("utf-16le"), "CaféLib".encode("utf-16le")
    )

    records = audit_module._parse_logical_references(renamed)

    assert any(item["name"] == "CaféLib" for item in records)


def test_reference_parser_fails_closed_on_unknown_record_type() -> None:
    corrupted = bytearray(_decompressed_reference_dir())
    reader = audit_module._DirReader(bytes(corrupted))
    audit_module._skip_project_information(reader)
    corrupted[reader.offset : reader.offset + 2] = b"\xff\xff"

    with pytest.raises(ValueError, match="reference record type"):
        audit_module._parse_logical_references(bytes(corrupted))


def test_reference_parser_fails_closed_on_malformed_libid_guid() -> None:
    corrupted = _decompressed_reference_dir().replace(
        b"{B691E011-1797-432E-907A-4D8C69339129}",
        b"{Z691E011-1797-432E-907A-4D8C69339129}",
        1,
    )

    with pytest.raises(ValueError, match="LIBID"):
        audit_module._parse_logical_references(corrupted)


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"not an OLE compound file", "CFB_INVALID"),
        (_repository_catvba().read_bytes()[:2048], "CFB_INVALID"),
    ],
)
def test_malformed_compound_files_fail_closed_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
    expected_code: str,
) -> None:
    candidate = tmp_path / "returned.catvba"
    candidate.write_bytes(payload)
    candidate.chmod(0o444)
    _success_pcode(monkeypatch)

    report = audit_catvba(candidate)

    assert expected_code in _codes(report)
    assert "VBA_PARSE_FAILED" in _codes(report)
    assert report.streams == ()
    assert report.modules == ()
    assert all(str(tmp_path) not in item.message for item in report.diagnostics)


def test_expected_mapping_compares_file_modules_frx_references_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)
    _success_pcode(monkeypatch)
    expected = {
        "file_sha256": "0" * 64,
        "modules": ["MissingModule.bas"],
        "frx": ["MissingForm.frx"],
        "references": ["{00000000-0000-0000-0000-000000000001}"],
        "hashes": {"DRW_ExPDF.bas": "f" * 64},
    }

    report = audit_catvba(returned, expected_manifest=expected)

    assert {
        "EXPECTED_FILE_HASH_MISMATCH",
        "EXPECTED_MODULE_MISMATCH",
        "EXPECTED_FRX_MISMATCH",
        "EXPECTED_REFERENCE_MISMATCH",
        "EXPECTED_SOURCE_HASH_MISMATCH",
    } <= _codes(report)


def test_expected_mapping_can_match_observed_readonly_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)
    _success_pcode(monkeypatch)
    baseline = audit_catvba(returned)
    modules = [item["name"] for item in baseline.modules]
    frx = sorted(
        PurePath(item["name"]).with_suffix(".frx").name
        for item in baseline.modules
        if item["name"].casefold().endswith(".frm")
    )
    references = [item["name"] for item in baseline.references]
    source = next(item for item in baseline.modules if item["name"] == "DRW_ExPDF.bas")
    expected = {
        "file_sha256": baseline.file_sha256,
        "modules": modules,
        "frx": frx,
        "references": references,
        "hashes": {source["name"]: source["source_sha256"]},
    }

    matched = audit_catvba(returned, expected_manifest=expected)

    assert not any(code.startswith("EXPECTED_") for code in _codes(matched)), _codes(
        matched
    )


def test_expected_reference_comparison_is_one_to_one() -> None:
    diagnostics: list[Any] = []
    duplicate_name_references = (
        {
            "name": "MSForms",
            "guid": "{0D452EE1-E08F-101A-852E-02608C4D0BB4}",
            "description": "Microsoft Forms 2.0 Object Library",
            "version": "2.0",
            "libid_sha256": "1" * 64,
        },
        {
            "name": "MSForms",
            "guid": "{00000000-0000-0000-0000-000000000001}",
            "description": "Polluted Library",
            "version": "1.0",
            "libid_sha256": "2" * 64,
        },
    )

    audit_module._compare_expected(
        audit_module._Expected(references=("MSForms",)),
        "0" * 64,
        (),
        {},
        {},
        {},
        duplicate_name_references,
        diagnostics,
    )

    assert "EXPECTED_REFERENCE_MISMATCH" in {
        item.code for item in diagnostics
    }


def test_expected_kit_requires_selector_for_multiple_nonempty_packages(
    tmp_path: Path,
) -> None:
    core = b'Attribute VB_Name = "CoreOnly"\r\nOption Explicit\r\n'
    fleet = b'Attribute VB_Name = "FleetOnly"\r\nOption Explicit\r\n'
    manifest = _stage_audit_kit(
        tmp_path,
        {
            "core": [("CoreOnly.bas", core)],
            "fleet-spa": [("FleetOnly.bas", fleet)],
        },
        references={"core": ["VBA"], "fleet-spa": ["SPATypeLib"]},
    )

    with pytest.raises(audit_module._ExpectedPackageSelectionError) as required:
        audit_module._kit_expected(manifest, package_id=None)
    assert required.value.code == "EXPECTED_PACKAGE_REQUIRED"

    core_expected = audit_module._kit_expected(manifest, package_id="core")
    fleet_expected = audit_module._kit_expected(
        manifest, package_id="fleet-spa"
    )

    assert core_expected.package_id == "core"
    assert core_expected.modules == ("CoreOnly.bas",)
    assert core_expected.references == ("VBA",)
    assert all(path.startswith("packages/core/") for path, _ in core_expected.hashes)
    assert fleet_expected.package_id == "fleet-spa"
    assert fleet_expected.modules == ("FleetOnly.bas",)
    assert fleet_expected.references == ("SPATypeLib",)
    assert all(
        path.startswith("packages/fleet-spa/")
        for path, _ in fleet_expected.hashes
    )


def test_audit_report_binds_selected_package_and_fails_closed_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)
    _success_pcode(monkeypatch)
    core = b'Attribute VB_Name = "CoreOnly"\r\nOption Explicit\r\n'
    fleet = b'Attribute VB_Name = "FleetOnly"\r\nOption Explicit\r\n'
    manifest = _stage_audit_kit(
        tmp_path,
        {
            "core": [("CoreOnly.bas", core)],
            "fleet-spa": [("FleetOnly.bas", fleet)],
        },
    )

    required = audit_catvba(returned, expected_manifest=manifest)
    selected = audit_catvba(
        returned, expected_manifest=manifest, package_id="core"
    )

    assert required.package_id is None
    assert "EXPECTED_PACKAGE_REQUIRED" in _codes(required)
    assert selected.package_id == "core"
    assert "EXPECTED_PACKAGE_REQUIRED" not in _codes(selected)
    assert "EXPECTED_MANIFEST_INVALID" not in _codes(selected)


def test_audit_rejects_tamper_in_nonselected_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)
    _success_pcode(monkeypatch)
    source = b'Attribute VB_Name = "Shared"\r\nOption Explicit\r\n'
    manifest = _stage_audit_kit(
        tmp_path,
        {
            "core": [("Shared.bas", source)],
            "fleet-spa": [("Shared.bas", source)],
        },
    )
    fleet_reference = manifest.parent / "references/fleet-spa.json"
    fleet_reference.write_bytes(b"{}")

    report = audit_catvba(
        returned, expected_manifest=manifest, package_id="core"
    )

    assert report.package_id is None
    assert "EXPECTED_MANIFEST_INVALID" in _codes(report)


def test_expected_kit_auto_selects_only_nonempty_package_and_rejects_empty(
    tmp_path: Path,
) -> None:
    core = b'Attribute VB_Name = "Shared"\r\nOption Explicit\r\n'
    manifest = _stage_audit_kit(
        tmp_path,
        {"core": [("Shared.bas", core)], "fleet-spa": []},
    )

    expected = audit_module._kit_expected(manifest, package_id=None)
    assert expected.package_id == "core"
    assert expected.modules == ("Shared.bas",)

    with pytest.raises(audit_module._ExpectedPackageSelectionError) as empty:
        audit_module._kit_expected(manifest, package_id="fleet-spa")
    assert empty.value.code == "EXPECTED_PACKAGE_EMPTY"


def test_expected_kit_allows_same_module_name_in_independent_packages(
    tmp_path: Path,
) -> None:
    shared = b'Attribute VB_Name = "Shared"\r\nOption Explicit\r\n'
    manifest = _stage_audit_kit(
        tmp_path,
        {
            "core": [("Shared.bas", shared)],
            "fleet-spa": [("Shared.bas", shared)],
        },
    )

    assert audit_module._kit_expected(
        manifest, package_id="core"
    ).modules == ("Shared.bas",)
    assert audit_module._kit_expected(
        manifest, package_id="fleet-spa"
    ).modules == ("Shared.bas",)


def test_expected_kit_uses_catalog_bound_encoding_decision(
    tmp_path: Path,
) -> None:
    ambiguous = (
        b'Attribute VB_Name = "Ambiguous"\r\n'
        b"Option Explicit\r\n"
        b"' \xc2\xa9\r\n"
    )
    manifest = _stage_audit_kit(
        tmp_path,
        {"core": [("Ambiguous.bas", ambiguous)], "fleet-spa": []},
        decisions={("core", "Ambiguous.bas"): "cp936"},
    )

    expected = audit_module._kit_expected(manifest, package_id=None)

    assert expected.package_id == "core"
    assert dict(expected.source_semantic_hashes)[
        "packages/core/source/Ambiguous.bas"
    ] == tuple(
        sorted(
            audit_module._semantic_source_hashes(
                ambiguous,
                declared_encoding="cp936",
                source_kind=".bas",
            )
        )
    )


def test_expected_kit_rejects_code_hidden_before_standard_module_identity(
    tmp_path: Path,
) -> None:
    prefixed = (
        b"Option Private Module\r\n"
        b'Attribute VB_Name = "CoreOnly"\r\n'
        b"Option Explicit\r\n"
    )
    manifest = _stage_audit_kit(
        tmp_path,
        {"core": [("CoreOnly.bas", prefixed)], "fleet-spa": []},
    )

    with pytest.raises(ValueError, match="standard module export header"):
        audit_module._kit_expected(manifest, package_id=None)


def test_source_semantic_hash_preserves_behavioral_class_attributes() -> None:
    source = (_repository_catvba().parent / "Src/Cls_DynaWD.cls").read_bytes()
    changed = source.replace(
        b"Attribute VB_PredeclaredId = False",
        b"Attribute VB_PredeclaredId = True ",
        1,
    )

    assert audit_module._semantic_source_hashes(
        source, source_kind=".cls"
    ).isdisjoint(
        audit_module._semantic_source_hashes(changed, source_kind=".cls")
    )


@pytest.mark.parametrize(
    "injected",
    [
        b'Attribute VB_Base = "attacker-controlled"\r\n',
        b'Attribute VB_Base = "0{FCFB3D2A-A0FA-1068-A738-08002B3371B5}"\r\n',
        b"Attribute VB_TemplateDerived = False\r\n",
        b"Attribute VB_Customizable = False\r\n",
    ],
)
def test_staged_source_rejects_extraction_only_metadata(
    injected: bytes,
) -> None:
    source = (_repository_catvba().parent / "Src/Cls_DynaWD.cls").read_bytes()
    changed = source.replace(
        b'Attribute VB_Name = "Cls_DynaWD"\n',
        b'Attribute VB_Name = "Cls_DynaWD"\n' + injected,
        1,
    )

    with pytest.raises(ValueError, match="extraction-only"):
        audit_module._semantic_source_hashes(changed, source_kind=".cls")


def test_staged_class_source_requires_canonical_export_header() -> None:
    source = (_repository_catvba().parent / "Src/Cls_DynaWD.cls").read_bytes()
    body_only = source[source.index(b"Attribute VB_Name") :]

    with pytest.raises(ValueError, match="class module export header"):
        audit_module._semantic_source_hashes(body_only, source_kind=".cls")


def test_extracted_source_rejects_malformed_extraction_metadata() -> None:
    source = (
        b'Attribute VB_Name = "Cls_DynaWD"\r\n'
        b'Attribute VB_Base = "attacker-controlled"\r\n'
        b"Option Explicit\r\n"
    )

    with pytest.raises(ValueError, match="extraction-only"):
        audit_module._semantic_source_hashes(
            source, source_kind=".cls", extracted=True
        )


def test_source_semantic_hash_rejects_noncanonical_class_instancing() -> None:
    source = (_repository_catvba().parent / "Src/Cls_DynaWD.cls").read_bytes()
    changed = source.replace(
        b"  MultiUse = -1  'True", b"  MultiUse = 0  'False", 1
    )

    with pytest.raises(ValueError, match="class module export header"):
        audit_module._semantic_source_hashes(changed, source_kind=".cls")


def test_expected_kit_manifest_loads_contained_companions_and_rejects_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)
    _success_pcode(monkeypatch)
    safe = b'Attribute VB_Name = "Safe"\r\nOption Explicit\r\n'
    manifest_path = _stage_audit_kit(
        tmp_path,
        {"core": [("Safe.bas", safe)], "fleet-spa": []},
        references={"core": ["Missing Library"]},
    )
    kit = manifest_path.parent
    staged_source = kit / "packages/core/source/Safe.bas"
    hashes_path = kit / "receipts/hashes.json"
    hashes_bytes = hashes_path.read_bytes()

    report = audit_catvba(returned, expected_manifest=manifest_path)
    assert {
        "EXPECTED_MODULE_MISMATCH",
        "EXPECTED_FRX_MISMATCH",
        "EXPECTED_REFERENCE_MISMATCH",
        "EXPECTED_SOURCE_HASH_MISMATCH",
    } <= _codes(report)
    assert "EXPECTED_MANIFEST_INVALID" not in _codes(report)

    original_semantic_hashes = audit_module._semantic_source_hashes
    staged_source_before = staged_source.read_bytes()
    mutated = False

    def mutate_staged_after_read(
        source: str | bytes,
        declared_encoding: str | None = None,
        *,
        source_kind: str | None = None,
    ) -> frozenset[str]:
        nonlocal mutated
        result = original_semantic_hashes(
            source, declared_encoding, source_kind=source_kind
        )
        if isinstance(source, bytes) and source == staged_source_before and not mutated:
            mutated = True
            staged_source.write_bytes(source.replace(b"Safe", b"Sxfe", 1))
        return result

    monkeypatch.setattr(
        audit_module, "_semantic_source_hashes", mutate_staged_after_read
    )
    raced = audit_catvba(returned, expected_manifest=manifest_path)
    assert "EXPECTED_MANIFEST_INVALID" in _codes(raced)
    monkeypatch.setattr(
        audit_module, "_semantic_source_hashes", original_semantic_hashes
    )
    staged_source.write_bytes(staged_source_before)

    original_read_directory = audit_module._ExpectedKitReader.read_directory
    late_reference = kit / "references/late.json"

    def add_entry_after_listing(
        reader: Any, path: PurePath
    ) -> tuple[tuple[str, bytes], ...]:
        result = original_read_directory(reader, path)
        if path == PurePath("references") and not late_reference.exists():
            late_reference.write_bytes(b"{}")
        return result

    monkeypatch.setattr(
        audit_module._ExpectedKitReader, "read_directory", add_entry_after_listing
    )
    directory_raced = audit_catvba(returned, expected_manifest=manifest_path)
    assert "EXPECTED_MANIFEST_INVALID" in _codes(directory_raced)
    monkeypatch.setattr(
        audit_module._ExpectedKitReader,
        "read_directory",
        original_read_directory,
    )
    late_reference.unlink()

    hashes_path.unlink()
    hashes_path.symlink_to(tmp_path / "outside.json")
    (tmp_path / "outside.json").write_bytes(hashes_bytes)
    rejected = audit_catvba(returned, expected_manifest=manifest_path)
    assert "EXPECTED_MANIFEST_INVALID" in _codes(rejected)


def test_expected_json_rejects_duplicate_keys_and_unknown_mapping_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)
    _success_pcode(monkeypatch)
    duplicate = tmp_path / "kit-manifest.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    from_file = audit_catvba(returned, expected_manifest=duplicate)
    from_mapping = audit_catvba(returned, expected_manifest={"unknown": []})

    assert "EXPECTED_MANIFEST_INVALID" in _codes(from_file)
    assert "EXPECTED_MANIFEST_INVALID" in _codes(from_mapping)


def test_pcode_timeout_and_nonzero_are_diagnostic_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)

    def timeout(args: list[str], **kwargs: Any) -> Any:
        return _capture(
            None, b"partial", b"timeout", timed_out=True
        )

    monkeypatch.setattr(audit_module, "_run_bounded_process", timeout)
    timed_out = audit_catvba(returned)
    assert timed_out.pcode.status == "timeout"
    assert timed_out.pcode.returncode is None
    assert timed_out.pcode.diagnostic_only is True
    assert timed_out.pcode.stdout_sha256 == hashlib.sha256(b"partial").hexdigest()
    assert "PCODE_TIMEOUT" in _codes(timed_out)

    monkeypatch.setattr(
        audit_module,
        "_run_bounded_process",
        lambda args, **kwargs: _capture(7, b"out", b"failure"),
    )
    nonzero = audit_catvba(returned)
    assert nonzero.pcode.status == "nonzero"
    assert nonzero.pcode.returncode == 7
    assert nonzero.pcode.diagnostic_only is True
    assert "PCODE_NONZERO" in _codes(nonzero)

    def unavailable(args: list[str], **kwargs: Any) -> Any:
        raise OSError("spawn failed")

    monkeypatch.setattr(audit_module, "_run_bounded_process", unavailable)
    unavailable_report = audit_catvba(returned)
    assert unavailable_report.pcode.status == "unavailable"
    assert unavailable_report.pcode.diagnostic_only is True
    assert "PCODE_UNAVAILABLE" in _codes(unavailable_report)


def test_pcode_output_is_truncated_before_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)
    stdout = b"x" * MAX_CAPTURE
    stderr = b"y" * MAX_CAPTURE
    monkeypatch.setattr(
        audit_module,
        "_run_bounded_process",
        lambda args, **kwargs: _capture(
            0,
            stdout,
            stderr,
            stdout_truncated=True,
            stderr_truncated=True,
        ),
    )

    report = audit_catvba(returned)

    assert report.pcode.stdout_sha256 == hashlib.sha256(b"x" * MAX_CAPTURE).hexdigest()
    assert report.pcode.stderr_sha256 == hashlib.sha256(b"y" * MAX_CAPTURE).hexdigest()
    assert "PCODE_OUTPUT_TRUNCATED" in _codes(report)
    assert repr(stdout) not in repr(report)
    assert repr(stderr) not in repr(report)


def test_bounded_process_discards_output_after_one_mib() -> None:
    payload_size = MAX_CAPTURE + 65537
    capture = audit_module._run_bounded_process(
        [
            sys.executable,
            "-c",
            (
                "import os;"
                f"os.write(1,b'x'*{payload_size});"
                f"os.write(2,b'y'*{payload_size})"
            ),
        ],
        env={"PATH": os.environ.get("PATH", "")},
        timeout=10,
    )

    assert capture.returncode == 0
    assert len(capture.stdout) == MAX_CAPTURE
    assert len(capture.stderr) == MAX_CAPTURE
    assert capture.stdout_truncated is True
    assert capture.stderr_truncated is True


def test_bounded_process_timeout_is_not_held_open_by_descendant_pipes() -> None:
    started = time.monotonic()
    capture = audit_module._run_bounded_process(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys,time;"
                "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                "time.sleep(30)"
            ),
        ],
        env={"PATH": os.environ.get("PATH", "")},
        timeout=0.1,
    )

    assert capture.timed_out is True
    assert time.monotonic() - started < 3


@pytest.mark.skipif(os.name != "posix", reason="POSIX detached process-group test")
def test_bounded_process_timeout_closes_pipes_held_by_detached_descendant() -> None:
    started = time.monotonic()
    capture = audit_module._run_bounded_process(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys,time;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],"
                "start_new_session=True);"
                "print(p.pid,flush=True);"
                "time.sleep(30)"
            ),
        ],
        env={"PATH": os.environ.get("PATH", "")},
        timeout=0.1,
    )
    detached_pid = int(capture.stdout.strip())
    try:
        assert capture.timed_out is True
        assert time.monotonic() - started < 3
    finally:
        try:
            os.killpg(detached_pid, audit_module.signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize(
    "form_name",
    [
        "Cat_Macro_Menu_View",
        "CAT_springWD",
        "FrmFlower",
        "VbaModuleManegerView",
    ],
)
def test_expected_frx_matches_real_compound_form_storage(form_name: str) -> None:
    diagnostics: list[Any] = []
    streams, references, form_storages = audit_module._audit_ole(
        _repository_catvba(), diagnostics
    )
    assert streams and references and not diagnostics
    expected_frx = (_repository_catvba().parent / "Src" / f"{form_name}.frx").read_bytes()
    expected = audit_module._frx_semantic_sha256(expected_frx)
    storage = next(
        item for item in form_storages if item.name == form_name
    )

    assert expected == storage.sha256
    expected_frm = (
        _repository_catvba().parent / "Src" / f"{form_name}.frm"
    ).read_bytes()
    assert (
        audit_module._form_designer_sha256(
            expected_frm, expected_frx_name=f"{form_name}.frx"
        )
        == storage.designer_sha256
    )
    assert audit_module._combined_form_sha256(
        expected,
        audit_module._form_designer_sha256(
            expected_frm, expected_frx_name=f"{form_name}.frx"
        ),
    ) == audit_module._combined_form_sha256(
        storage.sha256, storage.designer_sha256
    )


def test_form_designer_fingerprint_detects_caption_change() -> None:
    source = (_repository_catvba().parent / "Src/FrmFlower.frm").read_bytes()
    changed = source.replace(b'Caption         =   "Flower"', b'Caption         =   "Garden"')

    assert audit_module._form_designer_sha256(
        changed, expected_frx_name="FrmFlower.frx"
    ) != audit_module._form_designer_sha256(
        source, expected_frx_name="FrmFlower.frx"
    )


def test_form_designer_rejects_cross_bound_frx_name() -> None:
    source = (_repository_catvba().parent / "Src/FrmFlower.frm").read_bytes()
    crossed = source.replace(b"FrmFlower.frx", b"OtherForm.frx")

    with pytest.raises(ValueError, match="FRM/FRX bundle"):
        audit_module._form_designer_sha256(
            crossed, expected_frx_name="FrmFlower.frx"
        )


@pytest.mark.parametrize("padding_offset", [61, 391])
def test_frx_fingerprint_ignores_only_documented_padding(
    tmp_path: Path, padding_offset: int
) -> None:
    source = (_repository_catvba().parent / "Src/FrmFlower.frx").read_bytes()
    expected = audit_module._frx_semantic_sha256(source)
    mutated = _mutated_frx_stream(
        tmp_path,
        "FrmFlower",
        "f",
        lambda stream: stream.__setitem__(
            padding_offset, stream[padding_offset] ^ 0x5A
        ),
    )

    assert audit_module._frx_semantic_sha256(mutated) == expected


@pytest.mark.parametrize(
    ("stream_path", "semantic_offset"),
    [("f", 394), ("o", 1000)],
)
def test_frx_fingerprint_detects_semantic_and_picture_changes(
    tmp_path: Path, stream_path: str, semantic_offset: int
) -> None:
    source = (_repository_catvba().parent / "Src/FrmFlower.frx").read_bytes()
    expected = audit_module._frx_semantic_sha256(source)
    mutated = _mutated_frx_stream(
        tmp_path,
        "FrmFlower",
        stream_path,
        lambda stream: stream.__setitem__(
            semantic_offset, stream[semantic_offset] ^ 0x01
        ),
    )

    try:
        actual = audit_module._frx_semantic_sha256(mutated)
    except ValueError:
        return
    assert actual != expected


def test_frx_fingerprint_rejects_unknown_control_class(tmp_path: Path) -> None:
    mutated = _mutated_frx_stream(
        tmp_path,
        "FrmFlower",
        "f",
        lambda stream: stream.__setitem__(slice(83, 85), b"\xfe\x7f"),
    )

    with pytest.raises(ValueError, match="control class"):
        audit_module._frx_semantic_sha256(mutated)


def test_frx_fingerprint_rejects_changed_compobj_progid(tmp_path: Path) -> None:
    def change_progid(stream: bytearray) -> None:
        offset = stream.index(b"Forms.Form.1")
        stream[offset] = ord("X")

    mutated = _mutated_frx_stream(
        tmp_path, "FrmFlower", "\x01CompObj", change_progid
    )

    with pytest.raises(ValueError, match="logical Form CompObj"):
        audit_module._frx_semantic_sha256(mutated)


def test_frx_fingerprint_rejects_truncated_form_payload() -> None:
    source = (_repository_catvba().parent / "Src/FrmFlower.frx").read_bytes()

    with pytest.raises((ValueError, OSError, IOError)):
        audit_module._frx_semantic_sha256(source[:-4096])


@pytest.mark.parametrize(
    "mutated",
    [
        lambda source: b"X" + source,
        lambda source: source + b"EVILPAYLOAD",
        lambda source: source + bytes(512),
    ],
)
def test_frx_fingerprint_rejects_bytes_outside_declared_payload(
    mutated: Any,
) -> None:
    source = (_repository_catvba().parent / "Src/FrmFlower.frx").read_bytes()

    with pytest.raises(ValueError, match="FRX wrapper"):
        audit_module._frx_semantic_sha256(mutated(source))


def test_source_semantic_hash_matches_all_historical_exports() -> None:
    parser = audit_module.VBA_Parser(
        os.fspath(_repository_catvba()), relaxed=True, disable_pcode=True
    )
    try:
        extracted = {item[2]: item[3] for item in parser.extract_macros()}
    finally:
        parser.close()
    assert len(extracted) == 77
    for name, actual in sorted(extracted.items()):
        expected = (_repository_catvba().parent / "Src" / name).read_bytes()
        assert audit_module._semantic_source_hashes(
            expected, source_kind=PurePath(name).suffix
        ) & audit_module._semantic_source_hashes(
            actual,
            source_kind=PurePath(name).suffix,
            extracted=True,
        ), name


def test_source_semantic_hash_does_not_accept_cp1252_mojibake_for_cp936() -> None:
    expected = audit_module._semantic_source_hashes("' 中\r\n".encode("cp936"))
    actual = audit_module._semantic_source_hashes("' ÖÐ\r\n")

    assert expected == audit_module._semantic_source_hashes("' 中\r\n")
    assert expected.isdisjoint(actual)


def test_source_semantic_hash_respects_explicit_encoding_decision() -> None:
    ambiguous = b"' \xc2\xa9\r\n"

    assert not audit_module._semantic_source_hashes(ambiguous)
    assert audit_module._semantic_source_hashes(
        ambiguous, declared_encoding="cp936"
    ) == audit_module._semantic_source_hashes("' 漏\r\n")


def test_input_symlink_is_rejected(tmp_path: Path) -> None:
    target = _copy_legacy(tmp_path)
    link = tmp_path / "link.catvba"
    link.symlink_to(target)

    with pytest.raises(VerificationError, match="AUDIT_INPUT_SYMLINK"):
        audit_catvba(link)


def test_input_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "returned.catvba"
    os.mkfifo(fifo)
    started = time.monotonic()

    with pytest.raises(VerificationError, match="AUDIT_INPUT_INVALID"):
        audit_catvba(fifo)

    assert time.monotonic() - started < 1


def test_input_size_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "returned.catvba"
    candidate.write_bytes(b"12345")
    monkeypatch.setattr(audit_module, "_MAX_CATVBA_FILE", 4)

    with pytest.raises(VerificationError, match="AUDIT_INPUT_TOO_LARGE"):
        audit_catvba(candidate)


def test_expected_reader_rejects_regular_file_to_fifo_race(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kit"
    root.mkdir()
    (root / "victim").write_bytes(b"regular")
    original_stat = audit_module.os.stat
    raced = False

    def replace_after_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal raced
        result = original_stat(path, *args, **kwargs)
        if path == "victim" and not raced:
            raced = True
            descriptor = kwargs["dir_fd"]
            os.unlink(path, dir_fd=descriptor)
            os.mkfifo(path, dir_fd=descriptor)
        return result

    monkeypatch.setattr(audit_module.os, "stat", replace_after_stat)
    with audit_module._ExpectedKitReader(root) as reader:
        started = time.monotonic()
        with pytest.raises(ValueError, match="regular file"):
            reader.snapshot_tree()
        assert time.monotonic() - started < 1


def test_expected_reader_bounds_all_tree_entries_and_depth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "kit"
    root.mkdir()
    for name in ("one", "two", "three"):
        (root / name).mkdir()
    monkeypatch.setattr(audit_module, "_MAX_EXPECTED_ENTRIES", 2)

    with audit_module._ExpectedKitReader(root) as reader:
        with pytest.raises(ValueError, match="bounded audit limits"):
            reader.snapshot_tree()


def test_input_symlink_ancestor_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    target = real / "returned.catvba"
    target.write_bytes(_repository_catvba().read_bytes())
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real, target_is_directory=True)

    with pytest.raises(VerificationError, match="AUDIT_INPUT_SYMLINK"):
        audit_catvba(linked_parent / "returned.catvba")


def test_original_change_during_audit_raises_verification_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)

    def mutate_original(args: list[str], **kwargs: Any) -> Any:
        returned.chmod(0o644)
        returned.write_bytes(b"changed during audit")
        return _capture()

    monkeypatch.setattr(audit_module, "_run_bounded_process", mutate_original)

    with pytest.raises(VerificationError, match="AUDIT_INPUT_CHANGED"):
        audit_catvba(returned)


def test_original_metadata_change_during_audit_raises_verification_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returned = _copy_legacy(tmp_path)

    def touch_original(args: list[str], **kwargs: Any) -> Any:
        data = returned.read_bytes()
        returned.chmod(0o644)
        returned.write_bytes(data)
        returned.chmod(0o444)
        return _capture()

    monkeypatch.setattr(audit_module, "_run_bounded_process", touch_original)

    with pytest.raises(VerificationError, match="AUDIT_INPUT_CHANGED"):
        audit_catvba(returned)


def test_reports_are_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    returned = _copy_legacy(tmp_path)
    _success_pcode(monkeypatch)

    first = audit_catvba(returned)
    second = audit_catvba(returned)

    assert first == second
    assert first.diagnostics == tuple(sorted(first.diagnostics))
