from __future__ import annotations

import json
import os
import stat
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.errors import (
    BuildKitError,
    EvidenceError,
    InfrastructureError,
    VerificationError,
)
from catvba_refactor.macro_build.model import Diagnostic
from catvba_refactor.macro_build.target_evidence import container as container_module
from catvba_refactor.macro_build.target_evidence import packer as packer_module
from catvba_refactor.macro_build.target_evidence.approval import (
    record_target_approval,
)
from catvba_refactor.macro_build.target_evidence.container import (
    canonical_payload_manifest,
    read_evidence_container,
)
from catvba_refactor.macro_build.target_evidence.gate import evaluate_target_gate
from catvba_refactor.macro_build.target_evidence.model import (
    ComputedOutcome,
    EvidencePhase,
    GateId,
)
from catvba_refactor.macro_build.target_evidence.packer import pack_target_evidence
from catvba_refactor.macro_build.target_evidence.validator import (
    validate_target_evidence,
)
from catvba_refactor.tests import test_target_evidence_validator as evidence
from catvba_refactor.tests.test_target_gate import _eligible_g2_files


DETACHED_REVIEW_ID = "record-independent-gate-review"


def _write_tree(root: Path, files: dict[str, bytes]) -> None:
    root.mkdir(parents=True)
    for relative, data in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def _file_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _tree_identity(root: Path) -> dict[str, tuple[object, ...]]:
    paths = [root, *sorted(root.rglob("*"))]
    result: dict[str, tuple[object, ...]] = {}
    for path in paths:
        observed = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        result[relative] = (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_nlink,
            observed.st_size,
            observed.st_mtime_ns,
            observed.st_ctime_ns,
            path.read_bytes() if path.is_file() else None,
        )
    return result


def _assert_output_empty(output_root: Path) -> None:
    assert not output_root.exists() or list(output_root.iterdir()) == []


def _capture_files(outcome: str) -> dict[str, bytes]:
    if outcome == "eligible":
        return _eligible_g2_files()
    if outcome == "blocked":
        return evidence._capture_files("g2")
    if outcome == "fail":
        return evidence._replace_json(
            _eligible_g2_files(),
            "session.json",
            lambda document: document.__setitem__(
                "production_macro_library_touched", True
            ),
        )
    raise AssertionError(f"unsupported outcome fixture: {outcome}")


def _approval_bytes(receipt_bytes: bytes, *, status: str) -> bytes:
    receipt = json.loads(receipt_bytes)
    body = {
        "schema_version": 1,
        "session_id": receipt["session_id"],
        "session_mode": receipt["session_mode"],
        "gate_id": receipt["gate_id"],
        "evidence_payload_digest": receipt["evidence_payload_digest"],
        "gate_receipt_sha256": sha256_bytes(receipt_bytes),
        "approval_scope": "gate",
        "approval_status": status,
        "reviewer_role": "independent-reviewer",
        "review_record_id": DETACHED_REVIEW_ID,
        "approved_at": evidence.APPROVED,
    }
    approval_id = "approval-" + sha256_bytes(canonical_json_bytes(body))[:20]
    return canonical_json_bytes({"approval_id": approval_id, **body})


def _make_inputs(
    tmp_path: Path,
    *,
    outcome: str = "blocked",
    approval_status: str = "approved",
) -> tuple[Path, Path, Path, dict[str, bytes]]:
    files = _capture_files(outcome)
    capture = tmp_path / "inputs" / "capture"
    _write_tree(capture, files)
    evaluation = evaluate_target_gate(
        capture,
        evidence._kit(formal=True),
        tmp_path / "inputs" / "receipt",
        gate_id=GateId.G2,
        schema_dir=evidence.SCHEMA_DIR,
    )
    assert evaluation.computed_outcome is ComputedOutcome(outcome)
    receipt = Path(evaluation.receipt_path)
    approval = tmp_path / "inputs" / "approval.json"
    approval.write_bytes(
        _approval_bytes(receipt.read_bytes(), status=approval_status)
    )
    return capture, receipt, approval, files


def _pack(
    capture: Path,
    receipt: Path,
    approval: Path,
    output_root: Path,
):
    return pack_target_evidence(
        capture,
        evidence._kit(formal=True),
        receipt,
        approval,
        output_root,
        schema_dir=evidence.SCHEMA_DIR,
    )


@pytest.mark.parametrize("outcome", ["eligible", "fail", "blocked"])
@pytest.mark.parametrize("approval_status", ["approved", "rejected"])
def test_every_gate_outcome_with_a_final_review_can_be_sealed(
    tmp_path: Path, outcome: str, approval_status: str
) -> None:
    capture, receipt, approval, capture_files = _make_inputs(
        tmp_path,
        outcome=outcome,
        approval_status=approval_status,
    )

    bundle = _pack(capture, receipt, approval, tmp_path / "sealed")

    bundle_dir = Path(bundle.bundle_dir)
    zip_path = Path(bundle.zip_path)
    sealed_files = _file_map(bundle_dir)
    assert {
        "gate-receipt.json",
        "approval.json",
        "SHA256SUMS",
        "SESSION_COMPLETE",
    }.issubset(sealed_files)
    assert all(sealed_files[path] == data for path, data in capture_files.items())
    assert json.loads(sealed_files["gate-receipt.json"])[
        "computed_outcome"
    ] == outcome
    assert json.loads(sealed_files["approval.json"])[
        "approval_status"
    ] == approval_status
    assert bundle.zip_sha256 == sha256_bytes(zip_path.read_bytes())


def test_pending_is_neither_a_recordable_final_review_nor_sealable(
    tmp_path: Path,
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)

    with pytest.raises(EvidenceError):
        record_target_approval(
            capture,
            evidence._kit(formal=True),
            receipt,
            tmp_path / "pending-approval-output",
            scope="gate",
            status="pending",
            reviewer_role="independent-reviewer",
            review_record_id=DETACHED_REVIEW_ID,
            approved_at=evidence.APPROVED,
            schema_dir=evidence.SCHEMA_DIR,
        )

    approval.write_bytes(_approval_bytes(receipt.read_bytes(), status="pending"))
    with pytest.raises(EvidenceError):
        _pack(capture, receipt, approval, tmp_path / "pending-seal-output")
    _assert_output_empty(tmp_path / "pending-approval-output")
    _assert_output_empty(tmp_path / "pending-seal-output")


def test_handcrafted_approval_cannot_reuse_a_capture_record_id(
    tmp_path: Path,
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    document = json.loads(approval.read_bytes())
    document["review_record_id"] = "record-compile-blank-project"
    body = dict(document)
    body.pop("approval_id")
    document["approval_id"] = (
        "approval-" + sha256_bytes(canonical_json_bytes(body))[:20]
    )
    approval.write_bytes(canonical_json_bytes(document))
    output = tmp_path / "reused-record-output"

    with pytest.raises(EvidenceError, match="TARGET_APPROVAL_INVALID"):
        _pack(capture, receipt, approval, output)

    _assert_output_empty(output)


@pytest.mark.parametrize(
    "failure",
    [
        InfrastructureError("temporary-storage-failed"),
        VerificationError("g3-reaudit-failed"),
    ],
    ids=["infrastructure", "verification"],
)
def test_packer_preserves_typed_gate_recompute_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    output = tmp_path / "sealed"

    def fail(_inspection: object) -> None:
        raise failure

    monkeypatch.setattr(packer_module, "recompute_gate_receipt", fail)

    with pytest.raises(type(failure), match=str(failure)):
        _pack(capture, receipt, approval, output)

    _assert_output_empty(output)


def test_packer_normalizes_raw_gate_recompute_io_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    output = tmp_path / "sealed"

    def fail(_inspection: object) -> None:
        raise OSError("temporary-storage-failed")

    monkeypatch.setattr(packer_module, "recompute_gate_receipt", fail)

    with pytest.raises(InfrastructureError, match="TARGET_EVIDENCE_RECOMPUTE_IO"):
        _pack(capture, receipt, approval, output)

    _assert_output_empty(output)


def test_two_output_roots_have_identical_directory_zip_and_exact_hash_closure(
    tmp_path: Path,
) -> None:
    capture, receipt, approval, capture_files = _make_inputs(tmp_path)

    first = _pack(capture, receipt, approval, tmp_path / "first")
    second = _pack(capture, receipt, approval, tmp_path / "second")

    first_files = _file_map(Path(first.bundle_dir))
    second_files = _file_map(Path(second.bundle_dir))
    assert first_files == second_files
    assert Path(first.zip_path).read_bytes() == Path(second.zip_path).read_bytes()
    assert first.zip_sha256 == second.zip_sha256
    assert first.evidence_payload_digest == second.evidence_payload_digest
    assert first.bundle_content_digest == second.bundle_content_digest

    payload_manifest, payload_digest, _payload_members = canonical_payload_manifest(
        capture_files
    )
    assert first.evidence_payload_digest == payload_digest
    assert sha256_bytes(payload_manifest) == payload_digest

    covered = {
        path: data
        for path, data in first_files.items()
        if path not in {"SHA256SUMS", "SESSION_COMPLETE"}
    }
    _bundle_manifest, bundle_digest, _bundle_members = canonical_payload_manifest(
        covered
    )
    expected_sums = "".join(
        f"{sha256_bytes(data)}  {path}\n"
        for path, data in sorted(
            covered.items(), key=lambda item: item[0].encode("ascii")
        )
    ).encode("ascii")
    assert first_files["SHA256SUMS"] == expected_sums
    assert b"SHA256SUMS" not in expected_sums
    assert b"SESSION_COMPLETE" not in expected_sums
    completion = json.loads(first_files["SESSION_COMPLETE"])
    assert completion == {
        "schema_version": 1,
        "session_id": evidence._binding("g2")["session_id"],
        "sealed_at": evidence.APPROVED,
        "bundle_content_digest": bundle_digest,
        "evidence_payload_digest": payload_digest,
        "sha256sums_sha256": sha256_bytes(expected_sums),
        "gate_receipt_sha256": sha256_bytes(first_files["gate-receipt.json"]),
        "approval_sha256": sha256_bytes(first_files["approval.json"]),
    }
    assert first.bundle_content_digest == bundle_digest

    with zipfile.ZipFile(first.zip_path) as archive:
        assert archive.namelist() == sorted(first_files)
        for info in archive.infolist():
            assert info.compress_type == zipfile.ZIP_STORED
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.create_system == 3
            assert stat.S_IFMT(info.external_attr >> 16) == stat.S_IFREG
            assert stat.S_IMODE(info.external_attr >> 16) == 0o644
            assert info.extra == b""
            assert info.comment == b""


def test_sealed_directory_and_zip_have_identical_snapshots_and_full_validation(
    tmp_path: Path,
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    bundle = _pack(capture, receipt, approval, tmp_path / "sealed")

    directory_snapshot = read_evidence_container(
        bundle.bundle_dir, phase=EvidencePhase.SEALED
    )
    zip_snapshot = read_evidence_container(
        bundle.zip_path, phase=EvidencePhase.SEALED
    )
    assert directory_snapshot.diagnostics == zip_snapshot.diagnostics == ()
    assert directory_snapshot.files == zip_snapshot.files

    reports = [
        validate_target_evidence(
            path,
            evidence._kit(formal=True),
            phase=EvidencePhase.SEALED,
            schema_dir=evidence.SCHEMA_DIR,
        )
        for path in (bundle.bundle_dir, bundle.zip_path)
    ]
    assert all(report.ok for report in reports)
    assert reports[0].evidence_payload_digest == reports[1].evidence_payload_digest
    assert reports[0].payload_members == reports[1].payload_members


@pytest.mark.parametrize("drift", ["capture", "receipt", "approval"])
def test_any_detached_input_drift_is_rejected_before_output(
    tmp_path: Path, drift: str
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    if drift == "capture":
        current = json.loads((capture / "session.json").read_bytes())
        current["production_macro_library_touched"] = True
        (capture / "session.json").write_bytes(canonical_json_bytes(current))
    elif drift == "receipt":
        current = json.loads(receipt.read_bytes())
        current["computed_outcome"] = "fail"
        current["reason"] = "explicit-failure"
        body = dict(current)
        body.pop("receipt_id")
        current["receipt_id"] = (
            "gate-receipt-" + sha256_bytes(canonical_json_bytes(body))[:20]
        )
        receipt.write_bytes(canonical_json_bytes(current))
        approval.write_bytes(_approval_bytes(receipt.read_bytes(), status="approved"))
    else:
        current = json.loads(approval.read_bytes())
        current["evidence_payload_digest"] = "f" * 64
        approval.write_bytes(canonical_json_bytes(current))

    output = tmp_path / f"{drift}-output"
    with pytest.raises(BuildKitError):
        _pack(capture, receipt, approval, output)
    _assert_output_empty(output)


def test_capture_is_snapshotted_once_and_never_reopened_for_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, receipt, approval, original_files = _make_inputs(tmp_path)
    original_reader = packer_module.read_evidence_container
    capture_absolute = os.path.abspath(capture)
    capture_reads = 0

    def mutate_after_snapshot(path: object, **kwargs: object):
        nonlocal capture_reads
        snapshot = original_reader(path, **kwargs)
        try:
            absolute = os.path.abspath(os.fspath(path))
        except TypeError:
            return snapshot
        if absolute == capture_absolute:
            capture_reads += 1
            current = json.loads((capture / "session.json").read_bytes())
            current["production_macro_library_touched"] = True
            (capture / "session.json").write_bytes(canonical_json_bytes(current))
        return snapshot

    monkeypatch.setattr(
        packer_module, "read_evidence_container", mutate_after_snapshot
    )

    bundle = _pack(capture, receipt, approval, tmp_path / "sealed")

    assert capture_reads == 1
    assert _file_map(Path(bundle.bundle_dir))["session.json"] == original_files[
        "session.json"
    ]
    assert (capture / "session.json").read_bytes() != original_files["session.json"]


def test_receipt_and_approval_are_each_snapshotted_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    original_receipt = receipt.read_bytes()
    original_approval = approval.read_bytes()
    original_reader = container_module._read_regular_path
    tracked = {
        os.path.abspath(receipt): (receipt, b"receipt changed after snapshot\n"),
        os.path.abspath(approval): (approval, b"approval changed after snapshot\n"),
    }
    reads = {path: 0 for path in tracked}

    def mutate_after_snapshot(path: object, **kwargs: object):
        data, absolute = original_reader(path, **kwargs)
        if absolute in tracked:
            reads[absolute] += 1
            target, replacement = tracked[absolute]
            target.write_bytes(replacement)
        return data, absolute

    monkeypatch.setattr(
        container_module, "_read_regular_path", mutate_after_snapshot
    )

    bundle = _pack(capture, receipt, approval, tmp_path / "sealed")
    sealed_files = _file_map(Path(bundle.bundle_dir))

    assert reads == {path: 1 for path in tracked}
    assert sealed_files["gate-receipt.json"] == original_receipt
    assert sealed_files["approval.json"] == original_approval


def test_packer_never_reads_the_current_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)

    class ForbiddenDateTime:
        @classmethod
        def now(cls, *args: object, **kwargs: object) -> None:
            raise AssertionError("packer read the current clock")

        @classmethod
        def utcnow(cls) -> None:
            raise AssertionError("packer read the current clock")

    def forbidden_current_utc() -> str:
        raise AssertionError("packer read the current clock")

    monkeypatch.setattr(packer_module, "datetime", ForbiddenDateTime, raising=False)
    monkeypatch.setattr(
        packer_module, "_current_utc", forbidden_current_utc, raising=False
    )

    bundle = _pack(capture, receipt, approval, tmp_path / "sealed")

    assert json.loads(_file_map(Path(bundle.bundle_dir))["SESSION_COMPLETE"])[
        "sealed_at"
    ] == evidence.APPROVED


def test_identical_existing_output_is_idempotent_but_different_bytes_conflict(
    tmp_path: Path,
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    output = tmp_path / "sealed"
    first = _pack(capture, receipt, approval, output)
    first_zip = Path(first.zip_path).read_bytes()

    second = _pack(capture, receipt, approval, output)
    assert second == first

    session_path = Path(first.bundle_dir) / "session.json"
    session_path.write_bytes(b"different bytes\n")
    with pytest.raises(BuildKitError):
        _pack(capture, receipt, approval, output)
    assert session_path.read_bytes() == b"different bytes\n"
    assert Path(first.zip_path).read_bytes() == first_zip


def test_output_cannot_be_created_inside_the_capture_tree(
    tmp_path: Path,
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    before = _tree_identity(capture)
    output = capture / "sealed-output"

    with pytest.raises(EvidenceError):
        _pack(capture, receipt, approval, output)

    assert _tree_identity(capture) == before
    assert not output.exists()


@pytest.mark.parametrize(
    ("input_name", "attack"),
    [
        ("capture", "symlink"),
        ("capture", "hardlink"),
        ("receipt", "symlink"),
        ("receipt", "hardlink"),
        ("approval", "symlink"),
        ("approval", "hardlink"),
    ],
)
def test_symlink_and_hardlink_inputs_are_rejected_without_output(
    tmp_path: Path, input_name: str, attack: str
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    arguments: dict[str, Path] = {
        "capture": capture,
        "receipt": receipt,
        "approval": approval,
    }
    original = arguments[input_name]
    if input_name == "capture" and attack == "hardlink":
        os.link(capture / "session.json", tmp_path / "external-session.json")
    else:
        attacked = tmp_path / f"attacked-{input_name}"
        if attack == "symlink":
            attacked.symlink_to(original, target_is_directory=input_name == "capture")
        else:
            os.link(original, attacked)
        arguments[input_name] = attacked

    output = tmp_path / "sealed"
    with pytest.raises(BuildKitError):
        _pack(
            arguments["capture"],
            arguments["receipt"],
            arguments["approval"],
            output,
        )
    _assert_output_empty(output)


def test_symlinked_output_root_is_rejected_without_following_it(
    tmp_path: Path,
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    real = tmp_path / "real-output"
    real.mkdir()
    linked = tmp_path / "linked-output"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(BuildKitError):
        _pack(capture, receipt, approval, linked)
    assert list(real.iterdir()) == []


def test_partial_staging_failure_cleans_every_temporary_and_public_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, receipt, approval, capture_files = _make_inputs(tmp_path)
    original_write = container_module._write_all
    calls = 0
    fail_at = len(capture_files) + 5

    def fail_during_zip_stage(fd: int, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise OSError("injected ZIP staging failure")
        original_write(fd, data)

    monkeypatch.setattr(container_module, "_write_all", fail_during_zip_stage)
    output = tmp_path / "sealed"

    with pytest.raises(BuildKitError):
        _pack(capture, receipt, approval, output)
    _assert_output_empty(output)


def test_publisher_revalidation_failure_leaves_no_completed_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    monkeypatch.setattr(
        container_module,
        "_existing_outputs_match",
        lambda *args, **kwargs: False,
    )
    output = tmp_path / "sealed"

    with pytest.raises(BuildKitError):
        _pack(capture, receipt, approval, output)

    _assert_output_empty(output)


def test_final_full_validator_failure_rolls_back_both_directory_and_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture, receipt, approval, _files = _make_inputs(tmp_path)
    original_validate = packer_module.validate_target_evidence

    def fail_final_zip(evidence_input: object, *args: object, **kwargs: object):
        report = original_validate(evidence_input, *args, **kwargs)
        if isinstance(evidence_input, (str, os.PathLike)) and os.fspath(
            evidence_input
        ).endswith(".zip"):
            return replace(
                report,
                diagnostics=(
                    Diagnostic(
                        code="INJECTED_FINAL_VALIDATION_FAILURE",
                        path="sealed.zip",
                        message="injected final ZIP validation failure",
                    ),
                ),
            )
        return report

    monkeypatch.setattr(
        packer_module, "validate_target_evidence", fail_final_zip
    )
    output = tmp_path / "sealed"

    with pytest.raises(BuildKitError):
        _pack(capture, receipt, approval, output)

    _assert_output_empty(output)
