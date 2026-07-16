from __future__ import annotations

import json
import hashlib
import zipfile
import inspect
from pathlib import Path

import pytest

from catvba_refactor.target_collector.canonical import canonical_json_bytes
from catvba_refactor.target_collector.cli import main
from catvba_refactor.target_collector.finalize import (
    _checksum_bytes,
    _manifest,
    _zip_bytes,
    finalize_raw,
)
from catvba_refactor.target_collector.records import stable_reference_id
from catvba_refactor.target_collector.raw_validation import TARGET_CASE_IDS
from catvba_refactor.macro_build.target_evidence.model import EvidencePhase
from catvba_refactor.macro_build.target_evidence.validator import validate_raw_capture


def _write_json(root: Path, name: str, value: object) -> None:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_json_bytes(value))


def _complete_capture(
    root: Path, *, operator_count: int = 1, operator_suffix: str = ".txt"
) -> Path:
    root.mkdir()
    envelope = {
        "schema_version": 1,
        "trust_level": "raw-untrusted",
        "mode": "discovery",
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
    }
    _write_json(root, "session.json", {
        **envelope,
        "session_id": "session-20260715120000-raw",
        "created_at": "2026-07-15T12:00:00Z",
        "capture_status": "in-progress",
        "package_id": "core",
        "profile_id": "DISCOVERY",
        "bundle_id": "bundle-" + "1" * 24,
        "kit_id": "kit-" + "2" * 20,
        "handoff_id": "handoff-discovery-example",
    })
    _write_json(root, "environment.json", {
        **envelope,
        "windows": {"edition": "Windows 11 Enterprise", "build": "22631", "architecture": "Win64"},
        "catia": {"release": "V5-6R2018", "revision": "R28", "build": "B28"},
        "vba": {"generation": "VBA7", "win64": True},
        "pollution_scan": {key: "absent" for key in ("B30", "x86", "VBA6", "Temp", "user-profile")},
    })
    _write_json(root, "entitlements.json", {
        **envelope,
        "qualification_expression": "(AB3 OR HD2 OR MD2) AND SPA AND FTA",
        "licenses": {
            license_id: {"availability": "observed-available", "checkout": "observed-checked-out"}
            for license_id in ("AB3", "HD2", "MD2", "SPA", "FTA")
        },
    })
    guid = "{00020430-0000-0000-C000-000000000046}"
    reference = {
        "stable_reference_id": stable_reference_id(guid, 2, 0),
        "guid": guid, "major": 2, "minor": 0, "display_name": "VBA", "missing": False,
        "architecture": "x64", "source_class": "system", "root_kind": "CATIA_INSTALL",
        "basename": "vbe7.dll", "relative_path": "win_b64/code/bin/vbe7.dll",
        "path_sha256": "3" * 64,
    }
    _write_json(root, "references.json", {
        **envelope,
        "point_order": [
            "blank-project", "post-form-import", "post-all-import", "post-save", "post-restart"
        ],
        "observations": [
            {"point_id": point, "status": "observed", "references": [reference]}
            for point in (
                "blank-project", "post-form-import", "post-all-import", "post-save", "post-restart"
            )
        ],
    })
    operator_records = []
    for number in range(operator_count):
        note = (
            b"{opaque operator JSON, deliberately not canonical}\n"
            if operator_suffix == ".json"
            else f"redacted operator note {number}\n".encode("ascii")
        )
        note_sha = hashlib.sha256(note).hexdigest()
        record_id = "record-" + hashlib.sha256(("other\0" + note_sha).encode("ascii")).hexdigest()[:24]
        relative = f"operator-records/{record_id}/note{operator_suffix}"
        target = root / relative
        target.parent.mkdir(parents=True)
        target.write_bytes(note)
        operator_records.append({
            "record_id": record_id, "category": "other", "relative_path": relative,
            "sha256": note_sha, "size": len(note), "media_type": "text",
            "redaction_review_record_ids": [], "redaction_review_record_sha256": [],
            "redaction_review_sidecar_sha256": None,
        })
    operator_records.sort(key=lambda item: item["record_id"])
    _write_json(root, "operator-records/index.json", {**envelope, "records": operator_records})
    _write_json(root, "compile-result.json", {**envelope, "records": [{
        "record_id": f"record-compile-{point}", "point": point, "status": "not-run",
        "started_at": None, "ended_at": None, "catia_operator_record_id": None,
        "vbe_operator_record_id": None, "error_stage": None, "error_module": None,
        "redacted_error_summary": None,
    } for point in ("blank-project", "post-import", "post-save", "post-restart")]})
    _write_json(root, "test-results.json", {**envelope, "records": [{
        "case_id": case_id, "status": "not-run",
        "execution_point": "not-run", "observations": [], "started_at": None,
        "ended_at": None, "operator_record_id": None,
    } for case_id in TARGET_CASE_IDS]})
    _write_json(root, "artifact-manifest.json", {**envelope, "artifact": None, "files": []})
    return root


def test_finalize_raw_is_deterministic_and_never_sealed(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture")

    first = finalize_raw(capture, tmp_path / "one")
    second = finalize_raw(capture, tmp_path / "two")

    assert first.ok and second.ok
    assert first.zip_sha256 == second.zip_sha256
    assert first.zip_path.read_bytes() == second.zip_path.read_bytes()
    with zipfile.ZipFile(first.zip_path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("raw-capture-manifest.json"))
        assert names == sorted(names, key=str.encode)
        assert "SESSION_COMPLETE" not in names
        assert "approval.json" not in names
        assert "gate-receipt.json" not in names
        assert manifest["trust_level"] == "raw-untrusted"
        assert "raw-capture-manifest.json" not in {
            member["path"] for member in manifest["members"]
        }
        assert "SHA256SUMS" in {member["path"] for member in manifest["members"]}
        assert b"SHA256SUMS" not in archive.read("SHA256SUMS")


def test_finalize_requires_all_reference_points_and_rolls_back(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture")
    document = json.loads((capture / "references.json").read_text("ascii"))
    document["observations"].pop()
    (capture / "references.json").write_bytes(canonical_json_bytes(document))

    result = finalize_raw(capture, tmp_path / "output")

    assert not result.ok
    assert result.codes == ("COLLECTOR_CAPTURE_INCOMPLETE",)
    assert not (tmp_path / "output").exists()


def test_finalize_rejects_existing_output_without_overwrite(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture")
    output = tmp_path / "output"
    output.mkdir()

    result = finalize_raw(capture, output)

    assert not result.ok
    assert result.codes == ("COLLECTOR_OUTPUT_EXISTS",)


def test_finalize_rejects_seal_and_returned_artifact_names(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture")
    (capture / "approval.json").write_text("forbidden", encoding="ascii")

    result = finalize_raw(capture, tmp_path / "output")

    assert not result.ok
    assert result.codes == ("COLLECTOR_RAW_MEMBER_FORBIDDEN",)


def test_finalize_rejects_compile_claim_before_publishing(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture")
    session = json.loads((capture / "session.json").read_text("ascii"))
    session["compile_status"] = "passed"
    (capture / "session.json").write_bytes(canonical_json_bytes(session))

    result = finalize_raw(capture, tmp_path / "output")

    assert not result.ok
    assert result.codes == ("DISCOVERY_COMPILE_FORBIDDEN",)
    assert not (tmp_path / "output").exists()


def test_a_environment_ingests_finalizer_zip_only_as_raw(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture")
    finalized = finalize_raw(capture, tmp_path / "output")
    assert finalized.ok and finalized.zip_path is not None

    report = validate_raw_capture(finalized.zip_path)

    assert report.ok
    assert report.phase is EvidencePhase.RAW
    assert report.session_id == "session-20260715120000-raw"
    assert report.evidence_payload_digest is not None


def test_finalize_raw_cli_emits_machine_readable_receipt(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = _complete_capture(tmp_path / "capture")

    exit_code = main([
        "finalize-raw", "--capture", str(capture),
        "--output-root", str(tmp_path / "output"),
    ])

    receipt = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert receipt["ok"] is True
    assert receipt["facts"]["trust_level"] == "raw-untrusted"
    assert receipt["facts"]["gate_evaluated"] is False


@pytest.mark.parametrize(
    ("path", "mutation", "code"),
    [
        ("environment.json", lambda value: {key: value[key] for key in (
            "schema_version", "trust_level", "mode", "compile_status",
            "target_case_status", "artifact_status", "release_eligible",
        )}, "COLLECTOR_CAPTURE_INVALID"),
        ("entitlements.json", lambda value: {**value, "licenses": {}}, "COLLECTOR_LICENSE_SET_INVALID"),
        ("references.json", lambda value: {**value, "observations": []}, "COLLECTOR_CAPTURE_INCOMPLETE"),
        ("operator-records/index.json", lambda value: {**value, "records": [{"record_id": "shallow"}]}, "COLLECTOR_OPERATOR_INDEX_INVALID"),
        ("compile-result.json", lambda value: {**value, "records": [{**value["records"][0], "status": "passed"}, *value["records"][1:]]}, "DISCOVERY_COMPILE_FORBIDDEN"),
        ("test-results.json", lambda value: {**value, "records": [{**value["records"][0], "status": "passed"}, *value["records"][1:]]}, "DISCOVERY_TEST_FORBIDDEN"),
        ("artifact-manifest.json", lambda value: {**value, "release_eligible": True}, "DISCOVERY_RELEASE_FORBIDDEN"),
        ("artifact-manifest.json", lambda value: {**value, "artifact_status": "returned", "artifact": {"path": "returned-catvba/core.catvba"}}, "DISCOVERY_ARTIFACT_FORBIDDEN"),
    ],
)
def test_finalize_rejects_shallow_or_executed_raw_documents(
    tmp_path: Path, path: str, mutation: object, code: str
) -> None:
    capture = _complete_capture(tmp_path / "capture")
    document = json.loads((capture / path).read_text("ascii"))
    changed = mutation(document)  # type: ignore[operator]
    (capture / path).write_bytes(canonical_json_bytes(changed))

    result = finalize_raw(capture, tmp_path / "output")

    assert result.codes == (code,)
    assert not (tmp_path / "output").exists()


def test_finalize_rejects_unknown_legacy_governance_document(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture")
    _write_json(capture, "state-diff.json", {"schema_version": 1})

    result = finalize_raw(capture, tmp_path / "output")

    assert result.codes == ("COLLECTOR_RAW_MEMBER_FORBIDDEN",)


def test_a_environment_rejects_directory_and_authenticated_compile_claim(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture")
    assert {item.code for item in validate_raw_capture(capture).diagnostics} == {
        "RAW_CAPTURE_ZIP_REQUIRED"
    }

    compile_path = capture / "compile-result.json"
    compile_document = json.loads(compile_path.read_text("ascii"))
    compile_document["records"][0]["status"] = "passed"
    compile_path.write_bytes(canonical_json_bytes(compile_document))
    files = {
        path.relative_to(capture).as_posix(): path.read_bytes()
        for path in capture.rglob("*") if path.is_file()
    }
    files["SHA256SUMS"] = _checksum_bytes(files)
    session = json.loads(files["session.json"])
    files["raw-capture-manifest.json"] = _manifest(session, files)
    archive = tmp_path / "compile-claim.zip"
    archive.write_bytes(_zip_bytes(files))

    report = validate_raw_capture(archive)

    assert "DISCOVERY_COMPILE_FORBIDDEN" in {item.code for item in report.diagnostics}


def test_publish_race_never_replaces_competitor_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import catvba_refactor.target_collector.finalize as module

    capture = _complete_capture(tmp_path / "capture")
    output = tmp_path / "output"
    original = module._atomic_publish

    def race(staging: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "competitor.txt").write_text("keep", encoding="ascii")
        original(staging, destination)

    monkeypatch.setattr(module, "_atomic_publish", race)
    result = finalize_raw(capture, output)

    assert result.codes == ("COLLECTOR_OUTPUT_EXISTS",)
    assert (output / "competitor.txt").read_text("ascii") == "keep"


def test_staging_write_failure_never_exposes_final_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import catvba_refactor.target_collector.finalize as module

    capture = _complete_capture(tmp_path / "capture")
    original = module._write_exclusive_file

    def fail_second(path: Path, data: bytes):
        if path.name == "SHA256SUMS":
            raise OSError("injected second write failure")
        return original(path, data)

    monkeypatch.setattr(module, "_write_exclusive_file", fail_second)
    result = finalize_raw(capture, tmp_path / "output")
    assert not result.ok
    assert not (tmp_path / "output").exists()
    assert list(tmp_path.glob(".output.staging-*")) == []


def test_consumer_observes_only_absent_or_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import catvba_refactor.target_collector.finalize as module

    capture = _complete_capture(tmp_path / "capture")
    output = tmp_path / "output"
    original = module._atomic_publish

    def observe(staging: Path, destination: Path) -> None:
        assert not destination.exists()
        assert {item.name for item in staging.iterdir()} == {
            "raw-capture-manifest.json", "SHA256SUMS", "raw-discovery-capture.zip"
        }
        original(staging, destination)
        assert {item.name for item in destination.iterdir()} == {
            "raw-capture-manifest.json", "SHA256SUMS", "raw-discovery-capture.zip"
        }

    monkeypatch.setattr(module, "_atomic_publish", observe)
    assert finalize_raw(capture, output).ok


def test_foreign_replacement_staging_is_never_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import catvba_refactor.target_collector.finalize as module

    capture = _complete_capture(tmp_path / "capture")

    def replace(staging: Path, _destination: Path) -> None:
        for child in staging.iterdir():
            child.unlink()
        staging.rmdir()
        staging.mkdir()
        (staging / "foreign.txt").write_text("keep", encoding="ascii")
        raise module.CollectorError("COLLECTOR_OUTPUT_EXISTS")

    monkeypatch.setattr(module, "_atomic_publish", replace)
    result = finalize_raw(capture, tmp_path / "output")
    assert result.codes == ("COLLECTOR_STAGING_CLEANUP_REFUSED",)
    foreign = list(tmp_path.glob(".output.staging-*/foreign.txt"))
    assert len(foreign) == 1 and foreign[0].read_text("ascii") == "keep"


def test_capture_empty_directory_budget_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import catvba_refactor.target_collector.finalize as module

    capture = _complete_capture(tmp_path / "capture")
    (capture / "empty-one").mkdir()
    (capture / "empty-two").mkdir()
    monkeypatch.setattr(module, "MAX_RAW_DIRECTORIES", 2)

    result = finalize_raw(capture, tmp_path / "output")

    assert result.codes == ("COLLECTOR_DIRECTORY_COUNT_EXCEEDED",)


def test_source_member_boundary_produces_512_member_ingestible_zip(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture", operator_count=502)
    result = finalize_raw(capture, tmp_path / "output")
    assert result.ok and result.zip_path is not None
    with zipfile.ZipFile(result.zip_path) as archive:
        assert len(archive.infolist()) == 512
    assert validate_raw_capture(result.zip_path).ok


def test_source_member_511_fails_before_publication(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture", operator_count=503)
    result = finalize_raw(capture, tmp_path / "output")
    assert not result.ok
    assert not (tmp_path / "output").exists()


def test_operator_json_is_opaque_text_not_governance_json(tmp_path: Path) -> None:
    capture = _complete_capture(tmp_path / "capture", operator_suffix=".json")
    result = finalize_raw(capture, tmp_path / "output")
    assert result.ok and result.zip_path is not None
    assert validate_raw_capture(result.zip_path).ok


def test_atomic_backend_has_no_replacement_fallback() -> None:
    import catvba_refactor.target_collector.finalize as module

    source = inspect.getsource(module._atomic_publish)
    assert "MoveFileExW" in source and "0x8" in source
    assert "renameat2" in source and ", 1" in source
    assert "os.rename" not in source
    assert ".replace(" not in source


def test_windows_directory_fsync_is_noop_without_flush_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import catvba_refactor.target_collector.finalize as module

    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(
        module.ctypes, "WinDLL",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("WinDLL called")),
        raising=False,
    )
    module._fsync_directory(tmp_path)


def test_windows_atomic_publish_uses_write_through_and_stable_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import catvba_refactor.target_collector.finalize as module

    calls: list[tuple[str, str, int]] = []

    class Move:
        argtypes = None
        restype = None

        def __call__(self, source: str, destination: str, flags: int) -> int:
            calls.append((source, destination, flags))
            return 0

    class Kernel:
        MoveFileExW = Move()

    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module.ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel(), raising=False)
    monkeypatch.setattr(module.ctypes, "get_last_error", lambda: 183, raising=False)

    with pytest.raises(module.CollectorError) as caught:
        module._atomic_publish(tmp_path / "staging", tmp_path / "output")

    assert caught.value.code == "COLLECTOR_OUTPUT_EXISTS"
    assert calls == [(str(tmp_path / "staging"), str(tmp_path / "output"), 0x8)]
