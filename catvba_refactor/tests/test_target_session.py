from __future__ import annotations

import copy
import json
import re
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.errors import BuildKitError
from catvba_refactor.macro_build.model import Diagnostic, VerificationReport
from catvba_refactor.macro_build.target_evidence import session as session_module
from catvba_refactor.macro_build.target_evidence.container import (
    canonical_evidence_zip_bytes,
)
from catvba_refactor.macro_build.target_evidence.gate import evaluate_target_gate
from catvba_refactor.macro_build.target_evidence.model import (
    EvidencePhase,
    GateId,
    SessionMode,
)
from catvba_refactor.macro_build.target_evidence.session import init_target_session
from catvba_refactor.macro_build.target_evidence.validator import (
    validate_target_evidence,
)
from catvba_refactor.tests import test_target_evidence_validator as evidence
from catvba_refactor.tests.test_target_gate import (
    _eligible_sealed_g2,
    _seal_with_receipt,
)


SCHEMA_DIR = Path(__file__).parents[1] / "schemas" / "target_evidence"
FIXED_SESSION_ID = "session-20260714-initialized"
FIXED_UTC = "2026-07-14T12:00:00Z"
FIXED_G3_UTC = "2026-07-14T14:00:00Z"
ROOT_DOCUMENTS = (
    "session.json",
    "environment.json",
    "entitlements.json",
    "references.json",
    "compile-result.json",
    "test-results.json",
    "state-diff.json",
    "artifact-manifest.json",
    "operator-records/index.json",
)
SEAL_MEMBERS = {
    "gate-receipt.json",
    "approval.json",
    "SHA256SUMS",
    "SESSION_COMPLETE",
    "payload-manifest.json",
}
FORMAL_PROFILES = ("P-AB3", "P-HD2", "P-MD2", "P-ALL", "P-PROD")
REFERENCE_POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
COMPILE_POINTS = ("blank-project", "post-import", "post-save", "post-restart")


def _handoff_bytes(mode: str) -> bytes:
    return canonical_json_bytes(
        {
            "handoff_id": evidence._handoff_id(mode),
            **evidence._handoff_body(mode),
        }
    )


def _write_handoff(tmp_path: Path, mode: str) -> Path:
    path = tmp_path / f"{mode}-handoff.json"
    path.write_bytes(_handoff_bytes(mode))
    return path


def _write_mutated_formal_handoff(tmp_path: Path, mismatch: str) -> Path:
    document = json.loads(_handoff_bytes("g2"))
    if mismatch == "purpose":
        document["purpose"] = "discovery"
    else:
        document["reference_contract"] = evidence._handoff_body("discovery")[
            "reference_contract"
        ]
    body = dict(document)
    body.pop("handoff_id")
    document["handoff_id"] = (
        "handoff-" + sha256_bytes(canonical_json_bytes(body))[:20]
    )
    path = tmp_path / f"formal-{mismatch}-mismatch.json"
    path.write_bytes(canonical_json_bytes(document))
    return path


def _file_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _tree_identity(root: Path) -> dict[str, tuple[object, ...]]:
    paths = [root, *sorted(root.rglob("*"))]
    identity: dict[str, tuple[object, ...]] = {}
    for path in paths:
        observed = path.lstat()
        relative = "." if path == root else path.relative_to(root).as_posix()
        identity[relative] = (
            observed.st_dev,
            observed.st_ino,
            observed.st_mode,
            observed.st_size,
            observed.st_mtime_ns,
            observed.st_ctime_ns,
            path.read_bytes() if path.is_file() else None,
        )
    return identity


def _documents(files: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    return {
        path: json.loads(files[path])
        for path in (*ROOT_DOCUMENTS, "handoff.json")
    }


def _expected_payload_digest(files: dict[str, bytes]) -> str:
    members = [
        {"path": path, "sha256": sha256_bytes(data), "size": len(data)}
        for path, data in sorted(files.items(), key=lambda item: item[0].encode("ascii"))
    ]
    return sha256_bytes(
        canonical_json_bytes({"schema_version": 1, "members": members})
    )


def _assert_canonical_skeleton(
    receipt: object,
    handoff: Path,
    kit: object,
    *,
    mode: str,
    profile: str,
    prerequisite: bytes | None = None,
) -> dict[str, bytes]:
    session_dir = Path(receipt.session_dir)  # type: ignore[attr-defined]
    assert session_dir.name == f"target-session-{receipt.session_id}"  # type: ignore[attr-defined]
    files = _file_map(session_dir)
    documents = _documents(files)
    index = documents["operator-records/index.json"]
    declared_records = {
        item["relative_path"]: item for item in index["records"]
    }
    expected_paths = {*ROOT_DOCUMENTS, "handoff.json", *declared_records}
    if prerequisite is not None:
        expected_paths.add("prerequisites/g2-evidence.zip")

    assert set(files) == expected_paths
    assert not (set(files) & SEAL_MEMBERS)
    assert files["handoff.json"] == handoff.read_bytes()
    for path in (*ROOT_DOCUMENTS, "handoff.json"):
        assert files[path] == canonical_json_bytes(documents[path])
    for path, record in declared_records.items():
        assert sha256_bytes(files[path]) == record["sha256"]
        assert record["relative_path"].startswith("operator-records/")
    if prerequisite is not None:
        assert files["prerequisites/g2-evidence.zip"] == prerequisite

    binding = documents["session.json"]["binding"]
    assert binding == documents["environment.json"]["binding"]
    assert all(documents[path]["binding"] == binding for path in ROOT_DOCUMENTS)
    assert binding["session_id"] == receipt.session_id  # type: ignore[attr-defined]
    assert binding["session_mode"] == mode
    assert binding["package_id"] == "core"
    assert binding["profile_id"] == profile
    assert binding["kit_id"] == kit.kit_id  # type: ignore[attr-defined]
    assert receipt.mode is SessionMode(mode)  # type: ignore[attr-defined]
    assert receipt.kit_id == kit.kit_id  # type: ignore[attr-defined]
    assert receipt.evidence_payload_digest == _expected_payload_digest(files)  # type: ignore[attr-defined]

    report = validate_target_evidence(
        session_dir,
        kit,
        phase=EvidencePhase.CAPTURE,
        schema_dir=SCHEMA_DIR,
    )
    assert report.ok, report.diagnostics
    assert report.evidence_payload_digest == receipt.evidence_payload_digest  # type: ignore[attr-defined]
    return files


def _assert_safe_not_run_documents(
    files: dict[str, bytes],
    profile: str,
    *,
    inherited_environment: bool = False,
) -> None:
    documents = _documents(files)
    session = documents["session.json"]
    assert session["capture_status"] == "in-progress"
    assert session["ended_at"] is None
    assert session["production_macro_library_touched"] is False
    assert session["supersedes_session_id"] is None
    assert session["notes_record_id"] is None

    environment = documents["environment.json"]
    if not inherited_environment:
        assert session["anonymous_host_id"] is None
        assert session["vm_lineage_id"] is None
        assert session["snapshot_id"] is None
        for field in ("windows", "catia", "catia_environment", "vba", "dsls"):
            assert environment[field] is None
        assert environment["accounts_isolated"] is None
        assert set(environment["pollution_scan"].values()) == {"not-run"}
        assert set(environment["security"].values()) == {"unknown"}
        assert environment["environment_fingerprint"] is None
    assert environment["operator_record_id"] is None

    assert documents["operator-records/index.json"]["records"] == []

    entitlements = documents["entitlements.json"]
    for name in (
        "configuration_product",
        "reference_visibility",
        "api_workbench",
        "session_checkout",
        "tool_result",
    ):
        assert entitlements[name] == {"status": "not-run", "operator_record_id": None}
    expected_baseline = {
        "P-AB3": ["AB3"],
        "P-HD2": ["HD2"],
        "P-MD2": ["MD2"],
        "P-ALL": ["AB3", "HD2", "MD2"],
    }.get(profile)
    if expected_baseline is not None:
        assert entitlements["baseline_any_of"] == expected_baseline
    else:
        assert entitlements["baseline_any_of"] == []
    assert entitlements["additional_required"] == ["SPA", "FTA"]
    assert entitlements["set_license_used"] is False
    assert entitlements["scripted_reference_selection_used"] is False
    assert entitlements["licensing_repository_modified"] is False

    references = documents["references.json"]
    assert [point["point"] for point in references["points"]] == list(REFERENCE_POINTS)
    assert all(
        point == {
            "point": name,
            "status": "not-run",
            "observations": [],
            "operator_record_id": None,
        }
        for point, name in zip(references["points"], REFERENCE_POINTS, strict=True)
    )

    compile_records = documents["compile-result.json"]["records"]
    assert [record["point"] for record in compile_records] == list(COMPILE_POINTS)
    for record in compile_records:
        assert record["status"] == "not-run"
        assert all(
            record[field] is None
            for field in (
                "started_at",
                "ended_at",
                "catia_operator_record_id",
                "vbe_operator_record_id",
                "error_stage",
                "error_module",
                "redacted_error_summary",
            )
        )

    for record in documents["test-results.json"]["records"]:
        assert record["status"] == "not-run"
        assert record["execution_point"] == "not-run"
        assert all(
            record[field] is None
            for field in (
                "compile_record_id",
                "observed_result_code",
                "observed_state",
                "started_at",
                "ended_at",
                "operator_record_id",
                "state_diff_record_id",
                "failure_classification",
            )
        )
    assert documents["state-diff.json"]["overall_status"] == "not-run"
    assert documents["state-diff.json"]["records"] == []
    assert documents["artifact-manifest.json"] == {
        "binding": documents["session.json"]["binding"],
        "artifact_status": "not-produced",
        "artifact": None,
        "release_eligible": False,
    }


@pytest.mark.parametrize(
    ("mode", "profile", "formal"),
    [
        ("discovery", "DISCOVERY", False),
        ("g2", "P-AB3", True),
    ],
)
def test_explicit_session_inputs_create_byte_identical_valid_skeletons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    profile: str,
    formal: bool,
) -> None:
    class NoEntropy:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"explicit session must not read entropy: {name}")

    class NoClock:
        @classmethod
        def now(cls, tz: object) -> datetime:
            raise AssertionError("explicit session must not read the clock")

    monkeypatch.setattr(session_module, "secrets", NoEntropy())
    monkeypatch.setattr(session_module, "datetime", NoClock)
    monkeypatch.setattr(session_module._container, "secrets", NoEntropy())
    kit = evidence._kit(formal=formal)
    handoff = _write_handoff(tmp_path, mode)
    handoff_before = handoff.read_bytes()
    kit_before = copy.deepcopy(kit.files)

    receipts = [
        init_target_session(
            kit,
            handoff,
            tmp_path / f"output-{index}",
            mode=SessionMode(mode),
            package_id="core",
            profile_id=profile,
            schema_dir=SCHEMA_DIR,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )
        for index in range(2)
    ]
    file_maps = [
        _assert_canonical_skeleton(
            receipt, handoff, kit, mode=mode, profile=profile
        )
        for receipt in receipts
    ]

    assert file_maps[0] == file_maps[1]
    assert handoff.read_bytes() == handoff_before
    assert kit.files == kit_before
    _assert_safe_not_run_documents(file_maps[0], profile)


def test_results_are_derived_from_the_authenticated_ordered_thirty_case_plan(
    tmp_path: Path,
) -> None:
    kit = evidence._kit(formal=False)
    handoff = _write_handoff(tmp_path, "discovery")
    receipt = init_target_session(
        kit,
        handoff,
        tmp_path / "output",
        mode=SessionMode.DISCOVERY,
        package_id="core",
        profile_id="DISCOVERY",
        schema_dir=SCHEMA_DIR,
        session_id=FIXED_SESSION_ID,
        created_at=FIXED_UTC,
    )
    files = _file_map(Path(receipt.session_dir))
    results = json.loads(files["test-results.json"])
    plan_bytes = dict(kit.files)["target-test-plan/target-test-plan.json"]
    plan = json.loads(plan_bytes)
    cases = plan["cases"]

    assert len(cases) == len(results["records"]) == 30
    assert results["target_plan_sha256"] == sha256_bytes(plan_bytes)
    assert [item["case_id"] for item in results["records"]] == [
        item["case_id"] for item in cases
    ]
    for case, record in zip(cases, results["records"], strict=True):
        expected = case["expected"]
        assert record["case_definition_sha256"] == sha256_bytes(
            canonical_json_bytes(case)
        )
        assert record["package_id"] == case["package_id"] == "core"
        assert record["tool_id"] == case["tool_id"]
        assert record["expected_result_code"] == expected["result_code"]
        assert record["expected_state"] == expected.get(
            "state", expected.get("core_state")
        )
        assert record["profile_id"] == "DISCOVERY"
        assert record["status"] == "not-run"


@pytest.mark.parametrize("profile", FORMAL_PROFILES)
def test_g2_accepts_each_explicit_formal_profile_and_forbids_artifacts(
    tmp_path: Path, profile: str
) -> None:
    kit = evidence._kit(formal=True)
    handoff = _write_handoff(tmp_path, "g2")
    receipt = init_target_session(
        kit,
        handoff,
        tmp_path / "output",
        mode=SessionMode.G2,
        package_id="core",
        profile_id=profile,
        schema_dir=SCHEMA_DIR,
        session_id=FIXED_SESSION_ID,
        created_at=FIXED_UTC,
    )
    files = _assert_canonical_skeleton(
        receipt, handoff, kit, mode="g2", profile=profile
    )

    assert not any(path.startswith("returned-catvba/") for path in files)
    assert not any(path.startswith("prerequisites/") for path in files)
    _assert_safe_not_run_documents(files, profile)


def test_initialized_g2_draft_cannot_emit_a_gate_receipt(tmp_path: Path) -> None:
    kit = evidence._kit(formal=True)
    receipt = init_target_session(
        kit,
        _write_handoff(tmp_path, "g2"),
        tmp_path / "sessions",
        mode=SessionMode.G2,
        package_id="core",
        profile_id="P-AB3",
        schema_dir=SCHEMA_DIR,
        session_id=FIXED_SESSION_ID,
        created_at=FIXED_UTC,
    )
    gate_output = tmp_path / "gate-output"

    with pytest.raises(BuildKitError, match="TARGET_EVIDENCE_CAPTURE_INCOMPLETE"):
        evaluate_target_gate(
            Path(receipt.session_dir),
            kit,
            gate_output,
            gate_id=GateId.G2,
            schema_dir=SCHEMA_DIR,
        )

    assert not gate_output.exists()


def _write_eligible_g2_zip(tmp_path: Path, *, approval_status: str = "approved") -> Path:
    files = _eligible_sealed_g2(
        tmp_path / f"fixture-{approval_status}",
        approval_status=approval_status,
    )
    path = tmp_path / f"g2-{approval_status}.zip"
    path.write_bytes(canonical_evidence_zip_bytes(files))
    return path


def _write_blocked_g2_zip(tmp_path: Path) -> Path:
    capture = evidence._capture_files("g2")
    evaluation = evaluate_target_gate(
        evidence._snapshot(capture),
        evidence._kit(formal=True),
        tmp_path / "blocked-receipt",
        gate_id=GateId.G2,
        schema_dir=SCHEMA_DIR,
    )
    sealed = _seal_with_receipt(
        capture, Path(evaluation.receipt_path).read_bytes()
    )
    path = tmp_path / "g2-blocked.zip"
    path.write_bytes(canonical_evidence_zip_bytes(sealed))
    return path


def test_g3_requires_and_copies_exact_valid_eligible_approved_g2_zip(
    tmp_path: Path,
) -> None:
    kit = evidence._kit(formal=True)
    handoff = _write_handoff(tmp_path, "g3-c")
    prerequisite = _write_eligible_g2_zip(tmp_path)
    prerequisite_before = prerequisite.read_bytes()
    nested_report = validate_target_evidence(
        prerequisite,
        kit,
        phase=EvidencePhase.SEALED,
        schema_dir=SCHEMA_DIR,
    )
    assert nested_report.ok, nested_report.diagnostics

    receipt = init_target_session(
        kit,
        handoff,
        tmp_path / "output",
        mode=SessionMode.G3_C,
        package_id="core",
        profile_id="P-AB3",
        schema_dir=SCHEMA_DIR,
        prerequisite_evidence=prerequisite,
        session_id=FIXED_SESSION_ID,
        created_at=FIXED_G3_UTC,
    )
    files = _assert_canonical_skeleton(
        receipt,
        handoff,
        kit,
        mode="g3-c",
        profile="P-AB3",
        prerequisite=prerequisite_before,
    )

    assert prerequisite.read_bytes() == prerequisite_before
    _assert_safe_not_run_documents(files, "P-AB3", inherited_environment=True)

    with zipfile.ZipFile(prerequisite) as archive:
        inherited = json.loads(archive.read("environment.json"))
    current = json.loads(files["environment.json"])
    for field in (
        "windows",
        "catia",
        "vba",
        "reference_contract_body_digest",
        "environment_fingerprint",
    ):
        assert current[field] == inherited[field]
    for field in ("root_kind", "normalized_path_sha256"):
        assert current["catia_environment"]["install_root"][field] == inherited[
            "catia_environment"
        ]["install_root"][field]
    assert current["dsls"]["connection_mode"] == inherited["dsls"][
        "connection_mode"
    ]
    assert set(current["security"].values()) == {"unknown"}
    assert current["accounts_isolated"] is None
    assert set(current["pollution_scan"].values()) == {"not-run"}
    with zipfile.ZipFile(prerequisite) as archive:
        inherited_session = json.loads(archive.read("session.json"))
    current_session = json.loads(files["session.json"])
    for field in ("anonymous_host_id", "vm_lineage_id", "snapshot_id"):
        assert current_session[field] == inherited_session[field]


def test_g3_accepts_a_sealed_directory_and_embeds_its_canonical_zip(
    tmp_path: Path,
) -> None:
    prerequisite_files = _eligible_sealed_g2(tmp_path / "fixture-directory")
    prerequisite = tmp_path / "sealed-g2"
    for relative_path, data in prerequisite_files.items():
        member = prerequisite / relative_path
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(data)
    expected_zip = canonical_evidence_zip_bytes(prerequisite_files)

    receipt = init_target_session(
        evidence._kit(formal=True),
        _write_handoff(tmp_path, "g3-c"),
        tmp_path / "output",
        mode=SessionMode.G3_C,
        package_id="core",
        profile_id="P-AB3",
        schema_dir=SCHEMA_DIR,
        prerequisite_evidence=prerequisite,
        session_id=FIXED_SESSION_ID,
        created_at=FIXED_G3_UTC,
    )

    assert (
        Path(receipt.session_dir) / "prerequisites" / "g2-evidence.zip"
    ).read_bytes() == expected_zip


@pytest.mark.parametrize("relationship", ["same", "descendant", "enclosing-session"])
def test_g3_rejects_output_overlap_with_directory_prerequisite_before_writing(
    tmp_path: Path, relationship: str
) -> None:
    session_name = f"target-session-{FIXED_SESSION_ID}"
    if relationship == "enclosing-session":
        output = tmp_path / "output"
        prerequisite = output / session_name / "sealed-g2"
    else:
        prerequisite = tmp_path / "sealed-g2"
        output = prerequisite if relationship == "same" else prerequisite / "output"

    prerequisite_files = _eligible_sealed_g2(tmp_path / "fixture-overlap")
    for relative_path, data in prerequisite_files.items():
        member = prerequisite / relative_path
        member.parent.mkdir(parents=True, exist_ok=True)
        member.write_bytes(data)
    watched_root = output if relationship == "enclosing-session" else prerequisite
    before = _tree_identity(watched_root)

    with pytest.raises(
        BuildKitError, match="TARGET_SESSION_PREREQUISITE_OUTPUT_OVERLAP"
    ):
        init_target_session(
            evidence._kit(formal=True),
            _write_handoff(tmp_path, "g3-c"),
            output,
            mode=SessionMode.G3_C,
            package_id="core",
            profile_id="P-AB3",
            schema_dir=SCHEMA_DIR,
            prerequisite_evidence=prerequisite,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_G3_UTC,
        )

    assert _tree_identity(watched_root) == before
    if relationship != "enclosing-session":
        assert not (output / session_name).exists()


def test_g3_uses_one_prerequisite_snapshot_without_reopening_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prerequisite = _write_eligible_g2_zip(tmp_path)
    captured_bytes = prerequisite.read_bytes()
    original_reader = session_module.read_evidence_container
    calls = 0

    def snapshot_then_mutate(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        snapshot = original_reader(*args, **kwargs)
        prerequisite.write_bytes(b"mutated after authenticated snapshot\n")
        return snapshot

    monkeypatch.setattr(
        session_module, "read_evidence_container", snapshot_then_mutate
    )
    receipt = init_target_session(
        evidence._kit(formal=True),
        _write_handoff(tmp_path, "g3-c"),
        tmp_path / "output",
        mode=SessionMode.G3_C,
        package_id="core",
        profile_id="P-AB3",
        schema_dir=SCHEMA_DIR,
        prerequisite_evidence=prerequisite,
        session_id=FIXED_SESSION_ID,
        created_at=FIXED_G3_UTC,
    )

    assert calls == 1
    assert prerequisite.read_bytes() != captured_bytes
    assert (
        Path(receipt.session_dir) / "prerequisites" / "g2-evidence.zip"
    ).read_bytes() == captured_bytes


def test_g3_start_time_cannot_precede_prerequisite_seal(tmp_path: Path) -> None:
    output = tmp_path / "output"

    with pytest.raises(BuildKitError, match="TARGET_SESSION_PREREQUISITE_INVALID"):
        init_target_session(
            evidence._kit(formal=True),
            _write_handoff(tmp_path, "g3-c"),
            output,
            mode=SessionMode.G3_C,
            package_id="core",
            profile_id="P-AB3",
            schema_dir=SCHEMA_DIR,
            prerequisite_evidence=_write_eligible_g2_zip(tmp_path),
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )

    assert not output.exists()


@pytest.mark.parametrize(
    ("mode", "profile", "formal"),
    [
        ("discovery", "P-AB3", False),
        ("g2", "DISCOVERY", True),
        ("g3-c", "DISCOVERY", True),
        ("unknown", "P-AB3", True),
    ],
)
def test_mode_profile_matrix_rejects_invalid_pairs_before_writing(
    tmp_path: Path, mode: str, profile: str, formal: bool
) -> None:
    kit = evidence._kit(formal=formal)
    handoff_mode = "g2" if formal else "discovery"
    handoff = _write_handoff(tmp_path, handoff_mode)
    output = tmp_path / "output"

    with pytest.raises(BuildKitError):
        init_target_session(
            kit,
            handoff,
            output,
            mode=mode,
            package_id="core",
            profile_id=profile,
            schema_dir=SCHEMA_DIR,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )

    assert not output.exists()


@pytest.mark.parametrize("package_id", ["", "Core", "fleet-spa", "fleet-fta", None])
def test_only_exact_core_package_is_accepted(
    tmp_path: Path, package_id: object
) -> None:
    output = tmp_path / "output"

    with pytest.raises(BuildKitError):
        init_target_session(
            evidence._kit(formal=False),
            _write_handoff(tmp_path, "discovery"),
            output,
            mode=SessionMode.DISCOVERY,
            package_id=package_id,
            profile_id="DISCOVERY",
            schema_dir=SCHEMA_DIR,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )

    assert not output.exists()


@pytest.mark.parametrize("mode", [SessionMode.DISCOVERY, SessionMode.G2])
def test_prerequisite_is_forbidden_outside_g3(
    tmp_path: Path, mode: SessionMode
) -> None:
    formal = mode is SessionMode.G2
    prerequisite = _write_eligible_g2_zip(tmp_path)
    output = tmp_path / "output"

    with pytest.raises(BuildKitError):
        init_target_session(
            evidence._kit(formal=formal),
            _write_handoff(tmp_path, mode.value),
            output,
            mode=mode,
            package_id="core",
            profile_id="P-AB3" if formal else "DISCOVERY",
            schema_dir=SCHEMA_DIR,
            prerequisite_evidence=prerequisite,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )

    assert not output.exists()


@pytest.mark.parametrize("kind", ["missing", "pending", "blocked", "tampered", "profile-mismatch"])
def test_g3_rejects_any_unqualified_prerequisite_before_writing(
    tmp_path: Path, kind: str
) -> None:
    prerequisite: Path | None
    profile = "P-AB3"
    if kind == "missing":
        prerequisite = None
    elif kind == "pending":
        prerequisite = _write_eligible_g2_zip(tmp_path, approval_status="pending")
    elif kind == "blocked":
        prerequisite = _write_blocked_g2_zip(tmp_path)
    else:
        prerequisite = _write_eligible_g2_zip(tmp_path)
        if kind == "tampered":
            data = prerequisite.read_bytes()
            prerequisite.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        elif kind == "profile-mismatch":
            profile = "P-HD2"
    before = prerequisite.read_bytes() if prerequisite is not None else None
    output = tmp_path / "output"

    with pytest.raises(BuildKitError):
        init_target_session(
            evidence._kit(formal=True),
            _write_handoff(tmp_path, "g3-c"),
            output,
            mode=SessionMode.G3_C,
            package_id="core",
            profile_id=profile,
            schema_dir=SCHEMA_DIR,
            prerequisite_evidence=prerequisite,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_G3_UTC,
        )

    assert not output.exists()
    if prerequisite is not None:
        assert prerequisite.read_bytes() == before


@pytest.mark.parametrize("mismatch", ["purpose", "contract"])
def test_handoff_purpose_and_contract_must_match_requested_mode(
    tmp_path: Path, mismatch: str
) -> None:
    kit = evidence._kit(formal=True)
    handoff = _write_mutated_formal_handoff(tmp_path, mismatch)
    output = tmp_path / "output"

    with pytest.raises(BuildKitError):
        init_target_session(
            kit,
            handoff,
            output,
            mode=SessionMode.G2,
            package_id="core",
            profile_id="P-AB3",
            schema_dir=SCHEMA_DIR,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )

    assert not output.exists()


def test_existing_session_directory_is_never_replaced_or_mutated(
    tmp_path: Path,
) -> None:
    kit = evidence._kit(formal=False)
    handoff = _write_handoff(tmp_path, "discovery")
    output = tmp_path / "output"
    receipt = init_target_session(
        kit,
        handoff,
        output,
        mode=SessionMode.DISCOVERY,
        package_id="core",
        profile_id="DISCOVERY",
        schema_dir=SCHEMA_DIR,
        session_id=FIXED_SESSION_ID,
        created_at=FIXED_UTC,
    )
    before = _file_map(Path(receipt.session_dir))

    with pytest.raises(BuildKitError):
        init_target_session(
            kit,
            handoff,
            output,
            mode=SessionMode.DISCOVERY,
            package_id="core",
            profile_id="DISCOVERY",
            schema_dir=SCHEMA_DIR,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )

    assert _file_map(Path(receipt.session_dir)) == before


def test_invalid_kit_or_handoff_fails_before_write_and_mutates_nothing(
    tmp_path: Path,
) -> None:
    clean_kit = evidence._kit(formal=False)
    invalid_kit = replace(
        clean_kit,
        report=VerificationReport(
            ok=False,
            diagnostics=(Diagnostic("KIT_INVALID", "kit", "synthetic invalid Kit"),),
        ),
    )
    handoff = _write_handoff(tmp_path, "discovery")
    handoff_before = handoff.read_bytes()
    sentinel_root = tmp_path / "sentinel-root"
    sentinel_root.mkdir()
    sentinel = sentinel_root / "keep.txt"
    sentinel.write_bytes(b"do not mutate\n")

    with pytest.raises(BuildKitError):
        init_target_session(
            invalid_kit,
            handoff,
            sentinel_root,
            mode=SessionMode.DISCOVERY,
            package_id="core",
            profile_id="DISCOVERY",
            schema_dir=SCHEMA_DIR,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )

    assert _file_map(sentinel_root) == {"keep.txt": b"do not mutate\n"}
    assert handoff.read_bytes() == handoff_before
    assert invalid_kit.files == clean_kit.files

    handoff.write_bytes(b"not canonical json\n")
    invalid_handoff_before = handoff.read_bytes()
    second_output = tmp_path / "second-output"
    with pytest.raises(BuildKitError):
        init_target_session(
            clean_kit,
            handoff,
            second_output,
            mode=SessionMode.DISCOVERY,
            package_id="core",
            profile_id="DISCOVERY",
            schema_dir=SCHEMA_DIR,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )
    assert not second_output.exists()
    assert handoff.read_bytes() == invalid_handoff_before


def test_oversized_handoff_is_rejected_with_the_read_bound_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handoff = tmp_path / "oversized-handoff.json"
    handoff.write_bytes(b"x" * (session_module._MAX_HANDOFF_BYTES + 1))
    output = tmp_path / "output"
    observed_bounds: list[int] = []
    original_reader = session_module._container._read_regular_path

    def bounded_reader(path: object, *, max_bytes: int) -> tuple[bytes, str]:
        observed_bounds.append(max_bytes)
        return original_reader(path, max_bytes=max_bytes)

    monkeypatch.setattr(
        session_module._container, "_read_regular_path", bounded_reader
    )
    with pytest.raises(BuildKitError, match="TARGET_SESSION_HANDOFF_INVALID"):
        init_target_session(
            evidence._kit(formal=False),
            handoff,
            output,
            mode=SessionMode.DISCOVERY,
            package_id="core",
            profile_id="DISCOVERY",
            schema_dir=SCHEMA_DIR,
            session_id=FIXED_SESSION_ID,
            created_at=FIXED_UTC,
        )

    assert observed_bounds == [session_module._MAX_HANDOFF_BYTES]
    assert not output.exists()


@pytest.mark.parametrize(
    ("session_id", "created_at"),
    [
        ("", FIXED_UTC),
        ("session-UPPER", FIXED_UTC),
        (FIXED_SESSION_ID, "2026-07-14 12:00:00"),
        (FIXED_SESSION_ID, "2026-07-14T12:00:00+00:00"),
        (FIXED_SESSION_ID, "2026-07-21T10:00:00Z"),
    ],
)
def test_invalid_explicit_identity_or_utc_fails_before_write(
    tmp_path: Path, session_id: str, created_at: str
) -> None:
    output = tmp_path / "output"

    with pytest.raises(BuildKitError):
        init_target_session(
            evidence._kit(formal=False),
            _write_handoff(tmp_path, "discovery"),
            output,
            mode=SessionMode.DISCOVERY,
            package_id="core",
            profile_id="DISCOVERY",
            schema_dir=SCHEMA_DIR,
            session_id=session_id,
            created_at=created_at,
        )

    assert not output.exists()


def test_default_id_and_time_use_entropy_and_clock_only_when_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"entropy": 0, "clock": 0}

    class FixedEntropy:
        @staticmethod
        def token_hex(nbytes: int) -> str:
            calls["entropy"] += 1
            return "a" * (2 * nbytes)

    class FixedClock:
        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            calls["clock"] += 1
            return datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(session_module, "secrets", FixedEntropy())
    monkeypatch.setattr(session_module, "datetime", FixedClock)
    kit = evidence._kit(formal=False)
    handoff = _write_handoff(tmp_path, "discovery")

    default_receipt = init_target_session(
        kit,
        handoff,
        tmp_path / "defaults",
        mode=SessionMode.DISCOVERY,
        package_id="core",
        profile_id="DISCOVERY",
        schema_dir=SCHEMA_DIR,
    )
    assert calls == {"entropy": 1, "clock": 1}
    assert re.fullmatch(r"session-[0-9a-f]+", default_receipt.session_id)
    default_session = json.loads(
        (Path(default_receipt.session_dir) / "session.json").read_bytes()
    )
    assert default_session["started_at"] == FIXED_UTC

    explicit_receipt = init_target_session(
        kit,
        handoff,
        tmp_path / "explicit",
        mode=SessionMode.DISCOVERY,
        package_id="core",
        profile_id="DISCOVERY",
        schema_dir=SCHEMA_DIR,
        session_id=FIXED_SESSION_ID,
        created_at=FIXED_UTC,
    )
    assert calls == {"entropy": 1, "clock": 1}
    assert explicit_receipt.session_id == FIXED_SESSION_ID


@pytest.mark.parametrize(
    ("session_id", "created_at", "entropy_calls", "clock_calls"),
    [
        (None, FIXED_UTC, 1, 0),
        (FIXED_SESSION_ID, None, 0, 1),
    ],
)
def test_each_omitted_default_reads_only_its_own_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session_id: str | None,
    created_at: str | None,
    entropy_calls: int,
    clock_calls: int,
) -> None:
    calls = {"entropy": 0, "clock": 0}

    class FixedEntropy:
        @staticmethod
        def token_hex(nbytes: int) -> str:
            calls["entropy"] += 1
            return "b" * (2 * nbytes)

    class FixedClock:
        @classmethod
        def now(cls, timezone: object) -> datetime:
            assert timezone is UTC
            calls["clock"] += 1
            return datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(session_module, "secrets", FixedEntropy())
    monkeypatch.setattr(session_module, "datetime", FixedClock)
    receipt = init_target_session(
        evidence._kit(formal=False),
        _write_handoff(tmp_path, "discovery"),
        tmp_path / "output",
        mode=SessionMode.DISCOVERY,
        package_id="core",
        profile_id="DISCOVERY",
        schema_dir=SCHEMA_DIR,
        session_id=session_id,
        created_at=created_at,
    )

    assert calls == {"entropy": entropy_calls, "clock": clock_calls}
    assert Path(receipt.session_dir).is_dir()
