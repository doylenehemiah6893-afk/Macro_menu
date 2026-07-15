from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.errors import (
    EvidenceError,
    InfrastructureError,
    VerificationError,
)
from catvba_refactor.macro_build.target_evidence import approval as approval_module
from catvba_refactor.macro_build.target_evidence import session as session_module
from catvba_refactor.macro_build.target_evidence.approval import (
    record_target_approval,
)
from catvba_refactor.macro_build.target_evidence.container import (
    canonical_payload_manifest,
)
from catvba_refactor.macro_build.target_evidence.gate import evaluate_target_gate
from catvba_refactor.macro_build.target_evidence.model import EvidencePhase, GateId
from catvba_refactor.macro_build.target_evidence.validator import (
    validate_target_evidence,
)
from catvba_refactor.tests import test_target_evidence_validator as evidence
from catvba_refactor.tests import test_target_gate as gate_fixtures


REVIEWER_ROLE = "independent-reviewer"
REVIEW_RECORD_ID = "record-independent-gate-review"


def _write_capture(root: Path, files: dict[str, bytes]) -> Path:
    for relative_path, data in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def _receipt(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    mode: str = "g2",
    name: str = "receipt",
) -> Path:
    gate_id = {
        "discovery": GateId.DISCOVERY,
        "g2": GateId.G2,
        "g3-c": GateId.G3_C,
    }[mode]
    evaluation = evaluate_target_gate(
        evidence._snapshot(files),
        evidence._kit(formal=mode != "discovery"),
        tmp_path / name,
        gate_id=gate_id,
        schema_dir=evidence.SCHEMA_DIR,
    )
    return Path(evaluation.receipt_path)


def _approval(
    capture: Path,
    receipt: Path,
    output_root: Path,
    *,
    mode: str = "g2",
    scope: str = "gate",
    status: str = "approved",
    reviewer_role: str = REVIEWER_ROLE,
    review_record_id: str = REVIEW_RECORD_ID,
    approved_at: str = evidence.APPROVED,
) -> Path:
    return record_target_approval(
        capture,
        evidence._kit(formal=mode != "discovery"),
        receipt,
        output_root,
        scope=scope,
        status=status,
        reviewer_role=reviewer_role,
        review_record_id=review_record_id,
        approved_at=approved_at,
        schema_dir=evidence.SCHEMA_DIR,
    )


def _approval_id(body: dict[str, Any]) -> str:
    return "approval-" + sha256_bytes(canonical_json_bytes(body))[:20]


def _reidentify_receipt(document: dict[str, Any]) -> bytes:
    body = dict(document)
    body.pop("receipt_id", None)
    return canonical_json_bytes(
        {
            "receipt_id": (
                "gate-receipt-"
                + sha256_bytes(canonical_json_bytes(body))[:20]
            ),
            **body,
        }
    )


def _sealed_files(
    capture_files: dict[str, bytes], receipt: bytes, approval: bytes
) -> dict[str, bytes]:
    files = {
        **capture_files,
        "gate-receipt.json": receipt,
        "approval.json": approval,
    }
    _, bundle_digest, _ = canonical_payload_manifest(files)
    sums = "".join(
        f"{sha256_bytes(data)}  {path}\n"
        for path, data in sorted(
            files.items(), key=lambda item: item[0].encode("ascii")
        )
    ).encode("ascii")
    approval_document = json.loads(approval)
    completion = {
        "schema_version": 1,
        "session_id": approval_document["session_id"],
        "sealed_at": approval_document["approved_at"],
        "bundle_content_digest": bundle_digest,
        "evidence_payload_digest": approval_document[
            "evidence_payload_digest"
        ],
        "sha256sums_sha256": sha256_bytes(sums),
        "gate_receipt_sha256": sha256_bytes(receipt),
        "approval_sha256": sha256_bytes(approval),
    }
    files["SHA256SUMS"] = sums
    files["SESSION_COMPLETE"] = canonical_json_bytes(completion)
    return dict(sorted(files.items()))


def test_approval_is_canonical_deterministic_and_binds_explicit_review(
    tmp_path: Path,
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    input_capture = _tree_bytes(capture)
    input_receipt = receipt.read_bytes()

    paths = [
        _approval(capture, receipt, tmp_path / f"approval-{index}")
        for index in range(2)
    ]
    approval_bytes = [path.read_bytes() for path in paths]
    receipt_document = json.loads(input_receipt)
    body = {
        "schema_version": 1,
        "session_id": evidence._binding("g2")["session_id"],
        "session_mode": "g2",
        "gate_id": "G2",
        "evidence_payload_digest": receipt_document["evidence_payload_digest"],
        "gate_receipt_sha256": sha256_bytes(input_receipt),
        "approval_scope": "gate",
        "approval_status": "approved",
        "reviewer_role": REVIEWER_ROLE,
        "review_record_id": REVIEW_RECORD_ID,
        "approved_at": evidence.APPROVED,
    }
    expected = {"approval_id": _approval_id(body), **body}

    assert approval_bytes[0] == approval_bytes[1] == canonical_json_bytes(expected)
    assert paths[0].name == paths[1].name == f"{expected['approval_id']}.json"
    assert _tree_bytes(capture) == input_capture
    assert receipt.read_bytes() == input_receipt


def test_discovery_records_only_detached_observation_approval(tmp_path: Path) -> None:
    files = evidence._capture_files("discovery")
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files, mode="discovery")

    path = _approval(
        capture,
        receipt,
        tmp_path / "approval",
        mode="discovery",
        scope="observation",
    )
    document = json.loads(path.read_bytes())

    assert document["session_mode"] == "discovery"
    assert document["gate_id"] == "DISCOVERY"
    assert document["approval_scope"] == "observation"
    assert document["approval_status"] == "approved"


def test_detached_approval_record_is_not_a_current_operator_index_link(
    tmp_path: Path,
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt_path = _receipt(tmp_path, files)
    approval_path = _approval(capture, receipt_path, tmp_path / "approval")

    sealed = _sealed_files(
        files, receipt_path.read_bytes(), approval_path.read_bytes()
    )
    report = validate_target_evidence(
        evidence._snapshot(sealed),
        evidence._kit(formal=True),
        phase=EvidencePhase.SEALED,
        schema_dir=evidence.SCHEMA_DIR,
    )

    assert report.ok, report.diagnostics


@pytest.mark.parametrize("computed_outcome", ["fail", "blocked"])
def test_approved_fail_or_blocked_is_an_approved_record_not_gate_pass(
    tmp_path: Path, computed_outcome: str
) -> None:
    if computed_outcome == "blocked":
        files = evidence._capture_files("g2")
    else:
        files = evidence._replace_json(
            gate_fixtures._eligible_g2_files(),
            "session.json",
            lambda document: document.__setitem__(
                "production_macro_library_touched", True
            ),
        )
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    receipt_document = json.loads(receipt.read_bytes())
    assert receipt_document["computed_outcome"] == computed_outcome

    path = _approval(capture, receipt, tmp_path / "approval")
    document = json.loads(path.read_bytes())

    assert document["approval_status"] == "approved"
    assert document["approval_scope"] == "gate"
    assert "computed_outcome" not in document
    assert "release_eligible" not in document


def test_rejected_is_a_valid_explicit_independent_review_result(tmp_path: Path) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)

    path = _approval(
        capture,
        receipt,
        tmp_path / "approval",
        status="rejected",
    )

    assert json.loads(path.read_bytes())["approval_status"] == "rejected"


@pytest.mark.parametrize(
    ("mode", "scope", "status"),
    [
        ("g2", "observation", "approved"),
        ("g2", "GATE", "approved"),
        ("g2", "gate", "pending"),
        ("g2", "gate", "unknown"),
        ("discovery", "gate", "approved"),
    ],
)
def test_scope_status_and_mode_are_exact_explicit_inputs(
    tmp_path: Path, mode: str, scope: str, status: str
) -> None:
    files = (
        evidence._capture_files("discovery")
        if mode == "discovery"
        else gate_fixtures._eligible_g2_files()
    )
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files, mode=mode)
    output = tmp_path / "approval"

    with pytest.raises(EvidenceError):
        _approval(
            capture,
            receipt,
            output,
            mode=mode,
            scope=scope,
            status=status,
        )

    assert not output.exists()


def test_receipt_from_another_mode_is_rejected_before_output(tmp_path: Path) -> None:
    g2_files = gate_fixtures._eligible_g2_files()
    discovery_files = evidence._capture_files("discovery")
    capture = _write_capture(tmp_path / "capture", g2_files)
    discovery_receipt = _receipt(
        tmp_path, discovery_files, mode="discovery", name="discovery-receipt"
    )
    output = tmp_path / "approval"

    with pytest.raises(EvidenceError):
        _approval(capture, discovery_receipt, output)

    assert not output.exists()


def test_capture_payload_drift_from_the_receipt_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    original_files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", original_files)
    receipt = _receipt(tmp_path, original_files)
    mutated = evidence._replace_json(
        original_files,
        "session.json",
        lambda document: document.__setitem__(
            "production_macro_library_touched", True
        ),
    )
    (capture / "session.json").write_bytes(mutated["session.json"])
    before = _tree_bytes(capture)
    receipt_before = receipt.read_bytes()
    output = tmp_path / "approval"

    with pytest.raises(EvidenceError):
        _approval(capture, receipt, output)

    assert not output.exists()
    assert _tree_bytes(capture) == before
    assert receipt.read_bytes() == receipt_before


def test_canonical_but_reidentified_receipt_drift_is_rejected(tmp_path: Path) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    document = json.loads(receipt.read_bytes())
    document["evidence_payload_digest"] = "0" * 64
    drifted = tmp_path / "drifted-receipt.json"
    drifted.write_bytes(_reidentify_receipt(document))
    output = tmp_path / "approval"

    with pytest.raises(EvidenceError):
        _approval(capture, drifted, output)

    assert not output.exists()


@pytest.mark.parametrize("kind", ["noncanonical", "symlink", "hardlink"])
def test_receipt_must_be_one_canonical_unlinked_regular_file(
    tmp_path: Path, kind: str
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    candidate = tmp_path / f"{kind}-receipt.json"
    if kind == "noncanonical":
        candidate.write_text(
            json.dumps(json.loads(receipt.read_bytes()), indent=2) + "\n",
            encoding="utf-8",
        )
    elif kind == "symlink":
        candidate.symlink_to(receipt)
    else:
        os.link(receipt, candidate)
    output = tmp_path / "approval"

    with pytest.raises(EvidenceError):
        _approval(capture, candidate, output)

    assert not output.exists()


@pytest.mark.parametrize(
    "review_record_id",
    [
        "record-environment",
        "record-compile-blank-project",
        "record-handoff-prepared",
        "record-handoff-reviewed",
        "record-reference-approval",
    ],
    ids=[
        "operator-index",
        "capture-record",
        "handoff-preparer",
        "handoff-reviewer",
        "reference-approval",
    ],
)
def test_detached_review_record_id_cannot_reuse_prior_or_capture_provenance(
    tmp_path: Path, review_record_id: str
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    output = tmp_path / "approval"

    with pytest.raises(EvidenceError):
        _approval(
            capture,
            receipt,
            output,
            review_record_id=review_record_id,
        )

    assert not output.exists()


@pytest.mark.parametrize("reviewer_role", ["isolated-builder", "isolated-standard-user"])
def test_capture_builder_or_standard_user_role_cannot_self_review(
    tmp_path: Path, reviewer_role: str
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    output = tmp_path / "approval"

    with pytest.raises(EvidenceError):
        _approval(
            capture,
            receipt,
            output,
            reviewer_role=reviewer_role,
        )

    assert not output.exists()


@pytest.mark.parametrize(
    "approved_at",
    ["2026-07-14T12:59:59Z", "2026-07-14T06:30:00-07:00", "not-a-time"],
    ids=["before-capture-ended", "offset-not-zulu", "malformed"],
)
def test_review_time_is_explicit_utc_not_before_capture_end(
    tmp_path: Path, approved_at: str
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    output = tmp_path / "approval"

    with pytest.raises(EvidenceError):
        _approval(capture, receipt, output, approved_at=approved_at)

    assert not output.exists()


def test_review_may_follow_handoff_expiry_without_reading_the_current_clock(
    tmp_path: Path,
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    after_handoff_expiry = "2026-07-22T00:00:00Z"

    path = _approval(
        capture,
        receipt,
        tmp_path / "approval",
        approved_at=after_handoff_expiry,
    )

    assert json.loads(path.read_bytes())["approved_at"] == after_handoff_expiry


@pytest.mark.parametrize("nested", [False, True], ids=["capture-root", "capture-child"])
def test_approval_output_cannot_mutate_or_be_nested_in_capture(
    tmp_path: Path, nested: bool
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    before = _tree_bytes(capture)
    output = capture / "detached-approval" if nested else capture

    with pytest.raises(EvidenceError):
        _approval(capture, receipt, output)

    assert _tree_bytes(capture) == before


def test_approval_rejects_identity_alias_overlap_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    output = tmp_path / "identity-alias"
    capture_identity = (capture.stat().st_dev, capture.stat().st_ino)
    original = session_module._existing_directory_identities

    def identities(path: str) -> tuple[tuple[int, int], ...]:
        if path == os.path.abspath(output):
            return (capture_identity,)
        return original(path)

    monkeypatch.setattr(session_module, "_existing_directory_identities", identities)

    with pytest.raises(
        EvidenceError, match="TARGET_APPROVAL_CAPTURE_OUTPUT_OVERLAP"
    ):
        _approval(capture, receipt, output)

    assert not output.exists()


@pytest.mark.parametrize(
    "failure",
    [
        InfrastructureError("temporary-storage-failed"),
        VerificationError("g3-reaudit-failed"),
    ],
    ids=["infrastructure", "verification"],
)
def test_approval_preserves_typed_gate_recompute_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    output = tmp_path / "approval"

    def fail(_inspection: object) -> None:
        raise failure

    monkeypatch.setattr(approval_module, "recompute_gate_receipt", fail)

    with pytest.raises(type(failure), match=str(failure)):
        _approval(capture, receipt, output)

    assert not output.exists()


def test_approval_normalizes_raw_gate_recompute_io_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = gate_fixtures._eligible_g2_files()
    capture = _write_capture(tmp_path / "capture", files)
    receipt = _receipt(tmp_path, files)
    output = tmp_path / "approval"

    def fail(_inspection: object) -> None:
        raise OSError("temporary-storage-failed")

    monkeypatch.setattr(approval_module, "recompute_gate_receipt", fail)

    with pytest.raises(InfrastructureError, match="TARGET_APPROVAL_RECOMPUTE_IO"):
        _approval(capture, receipt, output)

    assert not output.exists()
    assert not (capture / "detached-approval").exists()
