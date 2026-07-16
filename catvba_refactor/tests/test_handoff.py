from __future__ import annotations

import copy
import json
import os
import shutil
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build import handoff as handoff_module
from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.errors import (
    EvidenceError,
    InfrastructureError,
    VerificationError,
)
from catvba_refactor.macro_build.handoff import (
    HandoffReceipt,
    HandoffRequest,
    issue_target_handoff as _production_issue_target_handoff,
    validate_handoff,
)
from catvba_refactor.macro_build.kit import inspect_build_kit, stage_build_kit
from catvba_refactor.macro_build.target_evidence.schemas import (
    load_target_evidence_schemas,
    validate_target_document,
)
from catvba_refactor.tests.test_kit import (
    _approved_reference_contract,
    _catalog,
)


CREATED = "2026-07-14T12:00:00Z"
EXPIRES = "2026-07-21T12:00:00Z"


def issue_target_handoff(
    primary_build_root: str | os.PathLike[str],
    comparison_build_root: str | os.PathLike[str],
    request: HandoffRequest,
    output_root: str | os.PathLike[str],
) -> HandoffReceipt:
    """Inject deterministic issuance time for the handoff unit tests."""

    return _production_issue_target_handoff(
        primary_build_root,
        comparison_build_root,
        request,
        output_root,
        _clock=lambda: request.created_at,
    )


def _revocations(
    *,
    captured_at: str = "2026-07-14T11:59:00Z",
    active: list[str] | None = None,
    withdrawn: list[str] | None = None,
) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "captured_at": captured_at,
            "source": "repository-active-handoff-ledger",
            "active_handoff_ids": active or [],
            "withdrawn_handoff_ids": withdrawn or [],
        }
    )


def _request(**changes: Any) -> HandoffRequest:
    values: dict[str, Any] = {
        "purpose": "discovery",
        "created_at": CREATED,
        "expires_at": EXPIRES,
        "revocation_snapshot": _revocations(),
        "prepared_record_id": "record-handoff-prepared",
        "review_record_id": "record-handoff-reviewed",
    }
    values.update(changes)
    return HandoffRequest(**values)


def _approved_catalog():
    catalog, _unused = _catalog()
    core = dict(catalog.packages[0])
    assert core["package_id"] == "core"
    core["reference_contract"] = _approved_reference_contract(
        "System/VBE7.DLL"
    )
    return replace(catalog, packages=(core, *catalog.packages[1:]))


def _stage_pair(
    tmp_path: Path, *, approved: bool = False, prefix: str = "build"
) -> tuple[Path, Path, Any, Any]:
    catalog = _approved_catalog() if approved else _catalog()[0]
    primary_root = tmp_path / f"{prefix}-primary"
    comparison_root = tmp_path / f"{prefix}-comparison"
    primary = stage_build_kit(catalog, primary_root)
    comparison = stage_build_kit(catalog, comparison_root)
    return primary_root, comparison_root, primary, comparison


def _document(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="ascii"))


def _reidentify(document: dict[str, Any], **changes: Any) -> bytes:
    body = copy.deepcopy(document)
    body.pop("handoff_id")
    body.update(changes)
    handoff_id = "handoff-" + sha256_bytes(canonical_json_bytes(body))[:20]
    return canonical_json_bytes({**body, "handoff_id": handoff_id})


def test_handoff_public_request_and_receipt_interfaces_are_frozen() -> None:
    request = HandoffRequest(
        purpose="discovery",
        created_at="2026-07-14T12:00:00Z",
        expires_at="2026-07-21T12:00:00Z",
        revocation_snapshot=b"{}\n",
        prepared_record_id="record-handoff-prepared",
        review_record_id="record-handoff-reviewed",
    )
    receipt = HandoffReceipt(
        handoff_id="handoff-0123456789abcdef0123",
        handoff_path="/detached/handoff-0123456789abcdef0123.json",
        handoff_sha256="a" * 64,
        kit_id="kit-0123456789abcdef0123",
        kit_zip_sha256="b" * 64,
    )

    assert request.supersedes_handoff is None
    with pytest.raises(FrozenInstanceError):
        request.purpose = "formal"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        receipt.kit_id = "kit-fedcba98765432100123"  # type: ignore[misc]


def test_discovery_issuance_authenticates_one_complete_triplet_per_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_root, comparison_root, primary, comparison = _stage_pair(tmp_path)
    calls: list[Path] = []

    def inspect(path: str | os.PathLike[str]):
        calls.append(Path(path))
        return inspect_build_kit(path)

    monkeypatch.setattr(handoff_module, "inspect_build_kit", inspect)
    output_root = tmp_path / "detached handoffs"
    receipt = issue_target_handoff(
        primary_root, comparison_root, _request(), output_root
    )

    assert calls == [
        Path(primary.kit_dir),
        Path(primary.zip_path),
        Path(comparison.kit_dir),
        Path(comparison.zip_path),
    ]
    assert Path(primary.zip_path).read_bytes() == Path(comparison.zip_path).read_bytes()
    assert receipt.kit_id == primary.kit_id == comparison.kit_id
    assert receipt.kit_zip_sha256 == primary.zip_sha256 == comparison.zip_sha256
    assert Path(receipt.handoff_path).parent == output_root.absolute()
    assert list(output_root.iterdir()) == [Path(receipt.handoff_path)]

    raw = Path(receipt.handoff_path).read_bytes()
    document = json.loads(raw)
    assert raw == canonical_json_bytes(document)
    body = dict(document)
    handoff_id = body.pop("handoff_id")
    assert handoff_id == "handoff-" + sha256_bytes(canonical_json_bytes(body))[:20]
    assert Path(receipt.handoff_path).name == f"{handoff_id}.json"
    assert receipt.handoff_sha256 == sha256_bytes(raw)

    assert document["target"] == "CATIA R2018/VBA7 64"
    assert document["compile_status"] == "not-run"
    assert document["release_eligible"] is False
    assert document["package_id"] == "core"
    assert document["purpose"] == "discovery"
    assert "supersedes_handoff_id" not in document
    report_digest = sha256_bytes(
        canonical_json_bytes({"ok": True, "diagnostics": []})
    )
    for field in (
        "primary_directory_verifier_report_digest",
        "comparison_directory_verifier_report_digest",
        "primary_zip_verifier_report_digest",
        "comparison_zip_verifier_report_digest",
    ):
        assert document[field] == report_digest

    schemas = load_target_evidence_schemas(
        Path(__file__).resolve().parents[1] / "schemas" / "target_evidence"
    )
    assert validate_target_document("handoff.json", document, schemas).ok


def test_handoff_validation_uses_explicit_effective_time_not_wall_clock(
    tmp_path: Path,
) -> None:
    primary_root, comparison_root, primary, _comparison = _stage_pair(tmp_path)
    receipt = issue_target_handoff(
        primary_root, comparison_root, _request(), tmp_path / "handoffs"
    )
    inspection = inspect_build_kit(primary.kit_dir)
    document = _document(receipt.handoff_path)

    assert validate_handoff(
        inspection, document, effective_at="2026-07-20T23:59:59Z"
    ).ok
    expired = validate_handoff(
        inspection, document, effective_at="2026-07-21T12:00:00Z"
    )
    assert not expired.ok
    assert {item.code for item in expired.diagnostics} == {"HANDOFF_EXPIRED"}
    assert validate_handoff(inspection, document, effective_at=CREATED).ok


def test_production_issuance_uses_injected_trusted_clock_not_request_history(
    tmp_path: Path,
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    trusted_now = "2026-07-14T13:00:00Z"

    receipt = _production_issue_target_handoff(
        primary_root,
        comparison_root,
        _request(
            created_at="2020-01-01T00:00:00Z",
            expires_at="2026-07-21T13:00:00Z",
        ),
        tmp_path / "trusted-clock-handoffs",
        _clock=lambda: trusted_now,
    )

    assert _document(receipt.handoff_path)["created_at"] == trusted_now


@pytest.mark.parametrize(
    "field",
    [
        "primary_directory_verifier_report_digest",
        "comparison_directory_verifier_report_digest",
        "primary_zip_verifier_report_digest",
        "comparison_zip_verifier_report_digest",
    ],
)
def test_validation_rejects_reidentified_forged_verifier_report_digest(
    tmp_path: Path, field: str
) -> None:
    primary_root, comparison_root, primary, _comparison = _stage_pair(tmp_path)
    receipt = issue_target_handoff(
        primary_root, comparison_root, _request(), tmp_path / "handoffs"
    )
    forged = json.loads(
        _reidentify(_document(receipt.handoff_path), **{field: "f" * 64})
    )

    report = validate_handoff(
        inspect_build_kit(primary.kit_dir), forged, effective_at=CREATED
    )
    assert not report.ok
    assert "HANDOFF_VERIFIER_REPORT_MISMATCH" in {
        item.code for item in report.diagnostics
    }


def test_issuance_rejects_expiry_at_or_before_creation(tmp_path: Path) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)

    with pytest.raises(EvidenceError, match="HANDOFF_REQUEST_INVALID"):
        issue_target_handoff(
            primary_root,
            comparison_root,
            _request(expires_at=CREATED),
            tmp_path / "handoffs",
        )


@pytest.mark.parametrize("root_name", ["primary", "comparison"])
def test_issuance_rejects_zero_complete_kit_triplets(
    tmp_path: Path, root_name: str
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    empty = tmp_path / f"empty-{root_name}"
    empty.mkdir()
    roots = {
        "primary": (empty, comparison_root),
        "comparison": (primary_root, empty),
    }

    with pytest.raises(EvidenceError, match="HANDOFF_KIT_TRIPLET_COUNT"):
        issue_target_handoff(*roots[root_name], _request(), tmp_path / "handoffs")


def test_issuance_rejects_two_complete_kit_triplets(tmp_path: Path) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    stage_build_kit(_approved_catalog(), primary_root)

    with pytest.raises(EvidenceError, match="HANDOFF_KIT_TRIPLET_COUNT"):
        issue_target_handoff(
            primary_root, comparison_root, _request(), tmp_path / "handoffs"
        )


def test_issuance_rejects_different_authenticated_kit_bytes(tmp_path: Path) -> None:
    primary_root, _unused, _primary, _comparison = _stage_pair(
        tmp_path, prefix="discovery"
    )
    _unused, comparison_root, _primary, _comparison = _stage_pair(
        tmp_path, approved=True, prefix="approved"
    )

    with pytest.raises(EvidenceError, match="HANDOFF_KIT_MISMATCH"):
        issue_target_handoff(
            primary_root, comparison_root, _request(), tmp_path / "handoffs"
        )


def test_issuance_rejects_bad_zip_sidecar_before_writing(tmp_path: Path) -> None:
    primary_root, comparison_root, primary, _comparison = _stage_pair(tmp_path)
    Path(primary.zip_path + ".sha256").write_text(
        f"{'0' * 64}  {Path(primary.zip_path).name}\n", encoding="ascii"
    )
    output = tmp_path / "handoffs"

    with pytest.raises(VerificationError, match="HANDOFF_KIT_VERIFICATION_FAILED"):
        issue_target_handoff(primary_root, comparison_root, _request(), output)
    assert not output.exists()


def test_issuance_rejects_output_inside_an_authenticated_kit(tmp_path: Path) -> None:
    primary_root, comparison_root, primary, _comparison = _stage_pair(tmp_path)
    embedded_output = Path(primary.kit_dir) / "detached"

    with pytest.raises(EvidenceError, match="HANDOFF_OUTPUT_INSIDE_KIT"):
        issue_target_handoff(
            primary_root, comparison_root, _request(), embedded_output
        )
    assert not embedded_output.exists()


@pytest.mark.parametrize(
    "snapshot",
    [
        _revocations(active=["handoff-existing-discovery"]),
        canonical_json_bytes(
            {
                "schema_version": 1,
                "captured_at": "2026-07-14T11:59:00Z",
                "source": "repository-active-handoff-ledger",
                "active_handoff_ids": ["handoff-existing-discovery"],
                "withdrawn_handoff_ids": ["handoff-existing-discovery"],
            }
        ),
        b'{"schema_version":1, "captured_at":"2026-07-14T11:59:00Z"}\n',
    ],
)
def test_issuance_rejects_ambiguous_or_malformed_revocation_snapshots(
    tmp_path: Path, snapshot: bytes
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)

    with pytest.raises(EvidenceError, match="REVOCATION_SNAPSHOT_INVALID"):
        issue_target_handoff(
            primary_root,
            comparison_root,
            _request(revocation_snapshot=snapshot),
            tmp_path / "handoffs",
        )


def test_withdrawn_handoff_document_is_invalid(tmp_path: Path) -> None:
    primary_root, comparison_root, primary, _comparison = _stage_pair(tmp_path)
    receipt = issue_target_handoff(
        primary_root, comparison_root, _request(), tmp_path / "handoffs"
    )
    document = _document(receipt.handoff_path)
    document["revocation_status"] = "revoked"

    report = validate_handoff(
        inspect_build_kit(primary.kit_dir), document, effective_at=CREATED
    )
    assert not report.ok
    assert "HANDOFF_REVOKED" in {item.code for item in report.diagnostics}


def test_discovery_and_formal_purpose_contract_and_supersedes_rules(
    tmp_path: Path,
) -> None:
    discovery_primary, discovery_comparison, _primary, _comparison = _stage_pair(
        tmp_path, prefix="discovery"
    )
    discovery_receipt = issue_target_handoff(
        discovery_primary,
        discovery_comparison,
        _request(),
        tmp_path / "discovery-handoff",
    )
    discovery_bytes = Path(discovery_receipt.handoff_path).read_bytes()

    with pytest.raises(EvidenceError, match="HANDOFF_SUPERSEDES_FORBIDDEN"):
        issue_target_handoff(
            discovery_primary,
            discovery_comparison,
            _request(supersedes_handoff=discovery_bytes),
            tmp_path / "bad-discovery",
        )

    approved_primary, approved_comparison, _primary, _comparison = _stage_pair(
        tmp_path, approved=True, prefix="approved"
    )
    with pytest.raises(EvidenceError, match="HANDOFF_CONTRACT_PURPOSE_MISMATCH"):
        issue_target_handoff(
            approved_primary,
            approved_comparison,
            _request(),
            tmp_path / "bad-approved-discovery",
        )
    with pytest.raises(EvidenceError, match="HANDOFF_SUPERSEDES_REQUIRED"):
        issue_target_handoff(
            approved_primary,
            approved_comparison,
            _request(purpose="formal"),
            tmp_path / "missing-supersedes",
        )
    with pytest.raises(EvidenceError, match="HANDOFF_CONTRACT_PURPOSE_MISMATCH"):
        issue_target_handoff(
            discovery_primary,
            discovery_comparison,
            _request(
                purpose="formal",
                supersedes_handoff=discovery_bytes,
                revocation_snapshot=_revocations(
                    withdrawn=[discovery_receipt.handoff_id]
                ),
            ),
            tmp_path / "bad-formal-discovery-kit",
        )


def test_formal_handoff_supersedes_withdrawn_discovery_across_new_approved_kit(
    tmp_path: Path,
) -> None:
    discovery_primary, discovery_comparison, _primary, _comparison = _stage_pair(
        tmp_path, prefix="discovery"
    )
    discovery_receipt = issue_target_handoff(
        discovery_primary,
        discovery_comparison,
        _request(),
        tmp_path / "discovery-handoff",
    )
    discovery_bytes = Path(discovery_receipt.handoff_path).read_bytes()
    approved_primary, approved_comparison, approved, _comparison = _stage_pair(
        tmp_path, approved=True, prefix="approved"
    )
    formal_request = _request(
        purpose="formal",
        created_at="2026-07-14T13:00:00Z",
        expires_at="2026-07-21T13:00:00Z",
        revocation_snapshot=_revocations(
            captured_at="2026-07-14T12:59:00Z",
            withdrawn=[discovery_receipt.handoff_id],
        ),
        supersedes_handoff=discovery_bytes,
    )

    formal = issue_target_handoff(
        approved_primary,
        approved_comparison,
        formal_request,
        tmp_path / "formal-handoff",
    )
    document = _document(formal.handoff_path)

    assert formal.kit_id == approved.kit_id
    assert formal.kit_id != discovery_receipt.kit_id
    assert formal.handoff_id != discovery_receipt.handoff_id
    assert document["supersedes_handoff_id"] == discovery_receipt.handoff_id
    assert document["purpose"] == "formal"
    assert document["reference_contract"]["status"] == "approved"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("work_branch", "codex/another-branch"),
        ("upstream_cutoff", "f" * 40),
        ("fork_dev_cutoff", "e" * 40),
    ],
)
def test_formal_rejects_superseded_branch_or_cutoff_mismatch(
    tmp_path: Path, field: str, value: str
) -> None:
    discovery_primary, discovery_comparison, _primary, _comparison = _stage_pair(
        tmp_path, prefix=f"discovery-{field}"
    )
    discovery_receipt = issue_target_handoff(
        discovery_primary,
        discovery_comparison,
        _request(),
        tmp_path / f"old-{field}",
    )
    changed = _reidentify(_document(discovery_receipt.handoff_path), **{field: value})
    changed_id = json.loads(changed)["handoff_id"]
    approved_primary, approved_comparison, _primary, _comparison = _stage_pair(
        tmp_path, approved=True, prefix=f"approved-{field}"
    )

    with pytest.raises(EvidenceError, match="HANDOFF_SUPERSEDED_IDENTITY_MISMATCH"):
        issue_target_handoff(
            approved_primary,
            approved_comparison,
            _request(
                purpose="formal",
                created_at="2026-07-14T13:00:00Z",
                expires_at="2026-07-21T13:00:00Z",
                revocation_snapshot=_revocations(
                    captured_at="2026-07-14T12:59:00Z",
                    withdrawn=[changed_id],
                ),
                supersedes_handoff=changed,
            ),
            tmp_path / f"formal-{field}",
        )


def test_formal_rejects_noncanonical_or_not_withdrawn_superseded_handoff(
    tmp_path: Path,
) -> None:
    discovery_primary, discovery_comparison, _primary, _comparison = _stage_pair(
        tmp_path, prefix="discovery"
    )
    discovery_receipt = issue_target_handoff(
        discovery_primary,
        discovery_comparison,
        _request(),
        tmp_path / "old",
    )
    discovery_bytes = Path(discovery_receipt.handoff_path).read_bytes()
    approved_primary, approved_comparison, _primary, _comparison = _stage_pair(
        tmp_path, approved=True, prefix="approved"
    )

    for supersedes, withdrawn in (
        (discovery_bytes.replace(b'"purpose"', b' "purpose"', 1), []),
        (discovery_bytes, []),
    ):
        with pytest.raises(EvidenceError, match="HANDOFF_SUPERSEDED_INVALID"):
            issue_target_handoff(
                approved_primary,
                approved_comparison,
                _request(
                    purpose="formal",
                    created_at="2026-07-14T13:00:00Z",
                    expires_at="2026-07-21T13:00:00Z",
                    revocation_snapshot=_revocations(
                        captured_at="2026-07-14T12:59:00Z",
                        withdrawn=withdrawn,
                    ),
                    supersedes_handoff=supersedes,
                ),
                tmp_path / "formal",
            )


def test_formal_rejects_reidentified_but_structurally_invalid_discovery(
    tmp_path: Path,
) -> None:
    discovery_primary, discovery_comparison, _primary, _comparison = _stage_pair(
        tmp_path, prefix="discovery-invalid-contract"
    )
    discovery_receipt = issue_target_handoff(
        discovery_primary,
        discovery_comparison,
        _request(),
        tmp_path / "old-invalid-contract",
    )
    document = _document(discovery_receipt.handoff_path)
    invalid_contract = copy.deepcopy(document["reference_contract"])
    invalid_contract["unexpected"] = True
    changed = _reidentify(document, reference_contract=invalid_contract)
    changed_id = json.loads(changed)["handoff_id"]
    approved_primary, approved_comparison, _primary, _comparison = _stage_pair(
        tmp_path, approved=True, prefix="approved-invalid-contract"
    )

    with pytest.raises(EvidenceError, match="HANDOFF_SUPERSEDED_INVALID"):
        issue_target_handoff(
            approved_primary,
            approved_comparison,
            _request(
                purpose="formal",
                created_at="2026-07-14T13:00:00Z",
                expires_at="2026-07-21T13:00:00Z",
                revocation_snapshot=_revocations(
                    captured_at="2026-07-14T12:59:00Z",
                    withdrawn=[changed_id],
                ),
                supersedes_handoff=changed,
            ),
            tmp_path / "formal-invalid-contract",
        )


def test_validation_rejects_non_core_or_changed_kit_identity(tmp_path: Path) -> None:
    primary_root, comparison_root, primary, _comparison = _stage_pair(tmp_path)
    receipt = issue_target_handoff(
        primary_root, comparison_root, _request(), tmp_path / "handoffs"
    )
    inspection = inspect_build_kit(primary.kit_dir)
    document = _document(receipt.handoff_path)

    non_core = copy.deepcopy(document)
    non_core["package_id"] = "fleet-spa"
    assert not validate_handoff(inspection, non_core, effective_at=CREATED).ok

    changed = copy.deepcopy(document)
    changed["work_branch"] = "codex/another-branch"
    assert not validate_handoff(inspection, changed, effective_at=CREATED).ok


def test_identical_existing_handoff_is_idempotent_and_conflict_fails_closed(
    tmp_path: Path,
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    output = tmp_path / "handoffs"
    first = issue_target_handoff(primary_root, comparison_root, _request(), output)
    path = Path(first.handoff_path)
    before = path.stat()
    second = issue_target_handoff(primary_root, comparison_root, _request(), output)

    assert second == first
    after = path.stat()
    assert (after.st_dev, after.st_ino) == (before.st_dev, before.st_ino)
    conflict = b"conflicting existing bytes\n"
    path.write_bytes(conflict)
    with pytest.raises(InfrastructureError, match="HANDOFF_ID_CONTENT_MISMATCH"):
        issue_target_handoff(primary_root, comparison_root, _request(), output)
    assert path.read_bytes() == conflict
    assert not list(output.glob(".*.tmp-*"))


def test_idempotence_rejects_identical_multiply_linked_destination(
    tmp_path: Path,
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    reference = issue_target_handoff(
        primary_root, comparison_root, _request(), tmp_path / "reference"
    )
    unsafe = tmp_path / "unsafe hardlink output"
    unsafe.mkdir()
    external = tmp_path / "externally mutable handoff.json"
    external.write_bytes(Path(reference.handoff_path).read_bytes())
    destination = unsafe / Path(reference.handoff_path).name
    os.link(external, destination)
    assert destination.stat().st_nlink == 2

    with pytest.raises(InfrastructureError, match="HANDOFF_ID_CONTENT_MISMATCH"):
        issue_target_handoff(primary_root, comparison_root, _request(), unsafe)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_idempotence_rejects_unsafe_nonregular_destination(
    tmp_path: Path, kind: str
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    reference = issue_target_handoff(
        primary_root, comparison_root, _request(), tmp_path / "reference"
    )
    unsafe = tmp_path / f"unsafe {kind} output"
    unsafe.mkdir()
    external = tmp_path / f"external-{kind}.json"
    external.write_bytes(Path(reference.handoff_path).read_bytes())
    destination = unsafe / Path(reference.handoff_path).name
    if kind == "symlink":
        destination.symlink_to(external)
    else:
        os.mkfifo(destination)

    with pytest.raises(InfrastructureError, match="HANDOFF_ID_CONTENT_MISMATCH"):
        issue_target_handoff(primary_root, comparison_root, _request(), unsafe)


def test_idempotence_rejects_content_race_even_when_read_bytes_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    reference = issue_target_handoff(
        primary_root, comparison_root, _request(), tmp_path / "reference"
    )
    output = tmp_path / "raced content output"
    output.mkdir()
    destination = output / Path(reference.handoff_path).name
    expected = Path(reference.handoff_path).read_bytes()
    destination.write_bytes(expected)
    target = destination.stat()
    real_read = os.read
    raced = False

    def racing_read(descriptor: int, size: int) -> bytes:
        nonlocal raced
        data = real_read(descriptor, size)
        opened = os.fstat(descriptor)
        if not raced and data and (opened.st_dev, opened.st_ino) == (
            target.st_dev,
            target.st_ino,
        ):
            raced = True
            destination.write_bytes(b"X" * len(expected))
        return data

    monkeypatch.setattr(handoff_module.os, "read", racing_read)
    with pytest.raises(InfrastructureError, match="HANDOFF_ID_CONTENT_MISMATCH"):
        issue_target_handoff(primary_root, comparison_root, _request(), output)
    assert raced


def test_publication_pins_root_against_rename_and_symlink_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    output = tmp_path / "pinned output"
    moved = tmp_path / "moved pinned output"
    attacker = tmp_path / "attacker output"
    real_open = os.open
    raced = False

    def racing_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        nonlocal raced
        if (
            not raced
            and isinstance(path, str)
            and path.startswith(".handoff-")
            and flags & os.O_CREAT
        ):
            raced = True
            output.rename(moved)
            attacker.mkdir()
            output.symlink_to(attacker, target_is_directory=True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(handoff_module.os, "open", racing_open)
    with pytest.raises(
        InfrastructureError, match="HANDOFF_OUTPUT_IDENTITY_CHANGED"
    ):
        issue_target_handoff(primary_root, comparison_root, _request(), output)
    assert raced
    assert list(attacker.iterdir()) == []
    assert not list(moved.glob(".*.tmp-*"))


def test_publication_fails_closed_without_required_dirfd_capabilities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    output = tmp_path / "unsupported publication output"
    monkeypatch.setattr(handoff_module, "_DIRFD_PUBLICATION_SUPPORTED", False)

    with pytest.raises(
        InfrastructureError, match="HANDOFF_ATOMIC_NOREPLACE_UNAVAILABLE"
    ):
        issue_target_handoff(primary_root, comparison_root, _request(), output)
    assert not output.exists()


def test_temp_cleanup_failure_surfaces_after_successful_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    output = tmp_path / "cleanup failure output"
    real_unlink = os.unlink

    def failing_unlink(path: Any, *args: Any, **kwargs: Any) -> None:
        if isinstance(path, str) and path.startswith(".handoff-"):
            raise PermissionError("injected temp cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(handoff_module.os, "unlink", failing_unlink)
    with pytest.raises(InfrastructureError, match="HANDOFF_TEMP_CLEANUP_FAILED"):
        issue_target_handoff(primary_root, comparison_root, _request(), output)

    entries = list(output.iterdir())
    assert len(entries) == 2
    assert len({(entry.stat().st_dev, entry.stat().st_ino) for entry in entries}) == 1
    assert entries[0].stat().st_nlink == 2


def test_temp_cleanup_failure_chains_primary_publication_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)
    reference = issue_target_handoff(
        primary_root, comparison_root, _request(), tmp_path / "reference"
    )
    output = tmp_path / "primary and cleanup failure output"
    output.mkdir()
    destination = output / Path(reference.handoff_path).name
    destination.write_bytes(b"conflicting bytes\n")
    real_unlink = os.unlink

    def failing_unlink(path: Any, *args: Any, **kwargs: Any) -> None:
        if isinstance(path, str) and path.startswith(".handoff-"):
            raise PermissionError("injected temp cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(handoff_module.os, "unlink", failing_unlink)
    with pytest.raises(
        InfrastructureError, match="HANDOFF_TEMP_CLEANUP_FAILED"
    ) as raised:
        issue_target_handoff(primary_root, comparison_root, _request(), output)

    assert isinstance(raised.value.__cause__, InfrastructureError)
    assert "HANDOFF_ID_CONTENT_MISMATCH" in str(raised.value.__cause__)


def test_handoff_rejects_expiry_beyond_seven_day_ttl(tmp_path: Path) -> None:
    primary_root, comparison_root, _primary, _comparison = _stage_pair(tmp_path)

    with pytest.raises(EvidenceError, match="HANDOFF_TTL_INVALID"):
        issue_target_handoff(
            primary_root,
            comparison_root,
            _request(expires_at="2026-07-21T12:00:01Z"),
            tmp_path / "handoffs",
        )
