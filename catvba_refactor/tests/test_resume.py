import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from catvba_refactor.macro_build.errors import ConfigError, EvidenceError
from catvba_refactor.macro_build.resume import (
    StrictDraft202012Validator,
    load_resume_state,
    validate_raw_capture_manifest,
)


SCHEMA_DIR = Path(__file__).parents[1] / "schemas"
GIT = "a" * 40
TREE = "b" * 40
SHA = "c" * 64
SHA_B = "d" * 64
UTC = "2026-07-15T18:00:00Z"


def _validator(filename: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return StrictDraft202012Validator(
        schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def valid_resume_state() -> dict:
    return {
        "schema_version": 1,
        "repository": "doylenehemiah6893-afk/Macro_menu",
        "branch": "codex/dev-review-report",
        "evidence_commit": GIT,
        "evidence_tree": TREE,
        "delivery_parent_commit": GIT,
        "approved_cutoff": "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad",
        "intake_record_path": "Docs/process/2026-07-14-initial-baseline-intake.md",
        "intake_record_digest": SHA,
        "python_requirement": "CPython 3.12",
        "uv_requirement": "uv 0.9.25",
        "lock_digest": SHA_B,
        "gate_statuses": {
            "G0": "PASS",
            "G1": "PASS",
            "G2": "BLOCKED",
            "G3": "BLOCKED",
            "G4": "BLOCKED",
            "G5": "BLOCKED",
            "G6": "BLOCKED",
            "G7": "BLOCKED",
        },
        "active_bundle_path": None,
        "bundle_digest": None,
        "active_kit_id": None,
        "kit_zip_digest": None,
        "active_handoff_id": None,
        "handoff_digest": None,
        "expiry": None,
        "revocation_status": "preparation",
        "last_full_test_count": 1306,
        "last_reproducibility_receipt": None,
        "release_eligible": False,
        "next_action": "Build and verify the B28 discovery operator bundle.",
    }


def valid_bundle_provenance() -> dict:
    return {
        "schema_version": 1,
        "repository": "doylenehemiah6893-afk/Macro_menu",
        "branch": "codex/dev-review-report",
        "evidence_commit": GIT,
        "evidence_tree": TREE,
        "approved_cutoff": "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad",
        "kit_id": "kit-0123456789abcdef0123",
        "catalog_sha256": SHA,
        "manifest_sha256": SHA_B,
        "manifest_digest": SHA,
        "kit_zip_sha256": SHA_B,
        "kit_sidecar_sha256": SHA,
        "handoff_id": "handoff-0123456789abcdef0123",
        "handoff_sha256": SHA_B,
        "handoff_created_at": UTC,
        "handoff_expires_at": "2026-07-22T18:00:00Z",
        "issuance_revocation_snapshot_sha256": SHA,
        "active_ledger_schema_version": 1,
        "active_ledger_source": "macro-menu-repository",
        "collector_source_commit": GIT,
        "collector_source_sha256": SHA_B,
        "collector_pyz_sha256": SHA,
        "python_requirement": "CPython 3.12",
        "session_skeleton_sha256": SHA_B,
        "tutorials_sha256": SHA,
        "templates_sha256": SHA_B,
        "schemas_sha256": SHA,
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
        "generation_record_id": "record-bundle-generation",
        "test_record_id": "record-target-collector-tests",
        "review_record_id": "record-bundle-independent-review",
    }


def valid_raw_capture_manifest() -> dict:
    return {
        "schema_version": 1,
        "session_id": "session-20260715-001",
        "created_at": UTC,
        "trust_level": "raw-untrusted",
        "mode": "discovery",
        "package_id": "core",
        "profile_id": "DISCOVERY",
        "bundle_id": "bundle-0123456789abcdef01234567",
        "kit_id": "kit-0123456789abcdef0123",
        "handoff_id": "handoff-0123456789abcdef0123",
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
        "members": [
            {"path": "session.json", "sha256": SHA, "size": 123},
            {"path": "references.json", "sha256": SHA_B, "size": 456},
            {"path": "SHA256SUMS", "sha256": "e" * 64, "size": 789},
        ],
    }


def valid_revocation_document() -> dict:
    return {
        "schema_version": 1,
        "captured_at": UTC,
        "source": "macro-menu-repository",
        "active_handoff_ids": ["handoff-current-example"],
        "withdrawn_handoff_ids": ["handoff-historical-example"],
    }


@pytest.mark.parametrize(
    ("filename", "document"),
    [
        ("resume-state.schema.json", valid_resume_state()),
        ("operator-bundle-provenance.schema.json", valid_bundle_provenance()),
        ("raw-capture-manifest.schema.json", valid_raw_capture_manifest()),
    ],
)
def test_delivery_state_schemas_accept_canonical_documents(filename, document):
    assert list(_validator(filename).iter_errors(document)) == []


def test_resume_state_schema_rejects_unknown_and_self_referential_fields():
    state = valid_resume_state()
    state["state_commit"] = "a" * 40
    errors = list(_validator("resume-state.schema.json").iter_errors(state))
    assert [error.validator for error in errors] == ["additionalProperties"]


def test_load_resume_state_reads_a_strict_valid_document(tmp_path: Path):
    state = valid_resume_state()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    assert load_resume_state(state_path, SCHEMA_DIR) == state


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b'{"schema_version":', "RESUME_STATE_JSON_INVALID"),
        (b'{"schema_version":1,"schema_version":1}', "RESUME_STATE_JSON_INVALID"),
        (b"\xff", "RESUME_STATE_READ_ERROR"),
    ],
)
def test_load_resume_state_rejects_malformed_or_non_utf8_json(
    tmp_path: Path, payload: bytes, code: str
):
    state_path = tmp_path / "state.json"
    state_path.write_bytes(payload)
    with pytest.raises(ConfigError, match=code):
        load_resume_state(state_path, SCHEMA_DIR)


def test_load_resume_state_rejects_unknown_fields(tmp_path: Path):
    state = valid_resume_state()
    state["state_commit"] = "a" * 40
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ConfigError, match="RESUME_STATE_INVALID"):
        load_resume_state(state_path, SCHEMA_DIR)


def test_load_resume_state_rejects_missing_state_and_schema_paths(tmp_path: Path):
    with pytest.raises(ConfigError, match="RESUME_STATE_READ_ERROR"):
        load_resume_state(tmp_path / "missing.json", SCHEMA_DIR)

    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(valid_resume_state()), encoding="utf-8")
    with pytest.raises(ConfigError, match="RESUME_STATE_SCHEMA_READ_ERROR"):
        load_resume_state(state_path, tmp_path / "missing-schemas")


def test_load_resume_state_rejects_malformed_schema(tmp_path: Path):
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    (schema_dir / "resume-state.schema.json").write_text(
        '{"$schema":"https://json-schema.org/draft/2020-12/schema","type":"invalid"}',
        encoding="utf-8",
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(valid_resume_state()), encoding="utf-8")
    with pytest.raises(ConfigError, match="RESUME_STATE_SCHEMA_INVALID"):
        load_resume_state(state_path, schema_dir)


@pytest.mark.parametrize("reference", ["#/$defs/missing", "other.schema.json"])
def test_load_resume_state_maps_unresolvable_and_external_refs_to_schema_error(
    tmp_path: Path, reference: str
):
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    schema = json.loads(
        (SCHEMA_DIR / "resume-state.schema.json").read_text(encoding="utf-8")
    )
    schema["properties"]["next_action"] = {"$ref": reference}
    (schema_dir / "resume-state.schema.json").write_text(
        json.dumps(schema), encoding="utf-8"
    )
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(valid_resume_state()), encoding="utf-8")

    with pytest.raises(ConfigError, match="RESUME_STATE_SCHEMA_INVALID"):
        load_resume_state(state_path, schema_dir)


@pytest.mark.parametrize("field", ["evidence_commit", "delivery_parent_commit"])
def test_resume_state_requires_lowercase_40_hex_git_oids(field):
    state = valid_resume_state()
    state[field] = "A" * 40
    errors = list(_validator("resume-state.schema.json").iter_errors(state))
    assert errors


def test_resume_state_requires_all_gate_statuses_and_blocks_release():
    state = valid_resume_state()
    del state["gate_statuses"]["G7"]
    assert [
        error.validator
        for error in _validator("resume-state.schema.json").iter_errors(state)
    ] == ["required"]

    state = valid_resume_state()
    state["release_eligible"] = True
    assert [
        error.validator
        for error in _validator("resume-state.schema.json").iter_errors(state)
    ] == ["const"]


@pytest.mark.parametrize(
    ("filename", "document", "field"),
    [
        ("operator-bundle-provenance.schema.json", valid_bundle_provenance(), "bundle_id"),
        ("raw-capture-manifest.schema.json", valid_raw_capture_manifest(), "manifest_sha256"),
    ],
)
def test_digest_documents_reject_self_referential_fields(filename, document, field):
    mutated = copy.deepcopy(document)
    mutated[field] = SHA
    errors = list(_validator(filename).iter_errors(mutated))
    assert [error.validator for error in errors] == ["additionalProperties"]


def test_raw_capture_manifest_enforces_discovery_boundaries():
    manifest = valid_raw_capture_manifest()
    manifest["compile_status"] = "passed"
    manifest["release_eligible"] = True
    assert {
        error.validator
        for error in _validator("raw-capture-manifest.schema.json").iter_errors(manifest)
    } == {"const"}


@pytest.mark.parametrize(
    ("field", "value"),
    [("target_case_status", "passed"), ("artifact_status", "produced")],
)
def test_bundle_provenance_enforces_discovery_execution_boundaries(field, value):
    provenance = valid_bundle_provenance()
    provenance[field] = value
    assert list(
        _validator("operator-bundle-provenance.schema.json").iter_errors(provenance)
    )


def test_raw_capture_manifest_rejects_unsafe_and_duplicate_member_paths():
    manifest = valid_raw_capture_manifest()
    manifest["members"][0]["path"] = "../session.json"
    assert list(
        _validator("raw-capture-manifest.schema.json").iter_errors(manifest)
    )

    manifest = valid_raw_capture_manifest()
    manifest["members"].append(copy.deepcopy(manifest["members"][0]))
    assert [
        error.validator
        for error in _validator("raw-capture-manifest.schema.json").iter_errors(manifest)
    ] == ["uniqueItems"]


@pytest.mark.parametrize("colliding_path", ["session.json", "SESSION.JSON"])
def test_raw_capture_manifest_semantics_reject_portable_path_collisions(
    colliding_path: str,
):
    manifest = valid_raw_capture_manifest()
    manifest["members"].append(
        {"path": colliding_path, "sha256": "e" * 64, "size": 999}
    )
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_PATH_NAMESPACE_INVALID"):
        validate_raw_capture_manifest(manifest)


def test_raw_capture_manifest_semantics_reject_file_directory_collision():
    manifest = valid_raw_capture_manifest()
    manifest["members"] = [
        {"path": "a", "sha256": SHA, "size": 1},
        {"path": "a/b", "sha256": SHA_B, "size": 2},
        {"path": "SHA256SUMS", "sha256": "e" * 64, "size": 3},
    ]
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_PATH_NAMESPACE_INVALID"):
        validate_raw_capture_manifest(manifest)


def test_raw_capture_manifest_semantics_reserves_manifest_control_path():
    manifest = valid_raw_capture_manifest()
    manifest["members"].append(
        {"path": "RAW-CAPTURE-MANIFEST.JSON", "sha256": "f" * 64, "size": 3}
    )
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_CONTROL_PATH_RESERVED"):
        validate_raw_capture_manifest(manifest)


def test_raw_capture_manifest_semantics_requires_one_canonical_sha256sums_member():
    manifest = valid_raw_capture_manifest()
    assert [item["path"] for item in manifest["members"]].count("SHA256SUMS") == 1
    assert validate_raw_capture_manifest(manifest).ok

    missing = valid_raw_capture_manifest()
    missing["members"] = [
        item for item in missing["members"] if item["path"] != "SHA256SUMS"
    ]
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_SHA256SUMS_MEMBER_INVALID"):
        validate_raw_capture_manifest(missing)

    duplicate = valid_raw_capture_manifest()
    duplicate["members"].append(
        {"path": "SHA256SUMS", "sha256": "f" * 64, "size": 999}
    )
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_SHA256SUMS_MEMBER_INVALID"):
        validate_raw_capture_manifest(duplicate)

    wrong_case = valid_raw_capture_manifest()
    next(
        item for item in wrong_case["members"] if item["path"] == "SHA256SUMS"
    )["path"] = "sha256sums"
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_SHA256SUMS_MEMBER_INVALID"):
        validate_raw_capture_manifest(wrong_case)


@pytest.mark.parametrize("path", ["CON.txt", "lPt1.log"])
def test_raw_capture_manifest_semantics_rejects_windows_reserved_names(path):
    manifest = valid_raw_capture_manifest()
    manifest["members"].append({"path": path, "sha256": "e" * 64, "size": 3})
    with pytest.raises(EvidenceError, match="RAW_CAPTURE_PATH_NAMESPACE_INVALID"):
        validate_raw_capture_manifest(manifest)


def test_raw_capture_manifest_semantics_accept_disjoint_paths():
    assert validate_raw_capture_manifest(valid_raw_capture_manifest()).ok


@pytest.mark.parametrize(
    ("filename", "document"),
    [
        ("resume-state.schema.json", valid_resume_state()),
        ("revocation-snapshot.schema.json", valid_revocation_document()),
        ("active-handoff-ledger.schema.json", valid_revocation_document()),
        ("operator-bundle-provenance.schema.json", valid_bundle_provenance()),
        ("raw-capture-manifest.schema.json", valid_raw_capture_manifest()),
    ],
)
def test_delivery_schemas_reject_float_schema_version(filename, document):
    document["schema_version"] = 1.0
    assert list(_validator(filename).iter_errors(document))
