from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from catvba_refactor.macro_build.reference_contract import (
    approved_reference_set,
    reference_companion,
    reference_contract_body_digest,
    reference_contract_diagnostics,
    resolved_reference_id,
)


POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
VBA_ID = "ref.000204ef00000000c000000000000046.4.2"
FORMS_ID = "ref.0d452ee1e08f101a852e02608c4d0bb4.2.0"
SHA = "a" * 64


def discovery_contract(package_id: str = "core") -> dict:
    return {
        "contract_id": f"references.{package_id}.b28",
        "contract_version": 1,
        "observation_points": None,
        "reference_definitions": None,
        "status": "discovery-required",
        "transitions": None,
    }


def _definition(
    stable_reference_id: str,
    guid: str,
    *,
    name: str,
    source_classification: str,
) -> dict:
    major, minor = (int(value) for value in stable_reference_id.rsplit(".", 2)[1:])
    return {
        "stable_reference_id": stable_reference_id,
        "guid": guid,
        "major": major,
        "minor": minor,
        "allowed_names": [name],
        "allowed_descriptions": [f"{name} Object Library"],
        "source_classification": source_classification,
        "architecture": "x64",
        "release_provenance": "B28",
        "path_policy": {
            "root_kind": "system" if name == "VBA" else "windows-install",
            "allowed_basenames": ["VBE7.DLL" if name == "VBA" else "FM20.DLL"],
            "allowed_relative_paths": [],
            "canonical_path_sha256": None,
        },
    }


def approved_contract() -> dict:
    contract = {
        "contract_id": "references.core.b28",
        "contract_version": 1,
        "status": "approved",
        "reference_definitions": [
            _definition(
                VBA_ID,
                "{000204EF-0000-0000-C000-000000000046}",
                name="VBA",
                source_classification="host-default",
            ),
            _definition(
                FORMS_ID,
                "{0D452EE1-E08F-101A-852E-02608C4D0BB4}",
                name="MSForms",
                source_classification="import-introduced",
            ),
        ],
        "observation_points": {
            "blank-project": [VBA_ID],
            "post-form-import": [VBA_ID, FORMS_ID],
            "post-all-import": [VBA_ID, FORMS_ID],
            "post-save": [VBA_ID, FORMS_ID],
            "post-restart": [VBA_ID, FORMS_ID],
        },
        "transitions": [
            {
                "from": source,
                "to": target,
                "added": [FORMS_ID] if source == "blank-project" else [],
                "removed": [],
            }
            for source, target in zip(POINTS[:-1], POINTS[1:], strict=True)
        ],
        "path_policy": {
            "allowed_root_kinds": ["catia-install", "windows-install", "system"],
            "allow_user_paths": False,
        },
    }
    digest = reference_contract_body_digest(contract)
    contract["contract_body_digest"] = digest
    contract["approval"] = {
        "reference_approval_record_id": "record-reference-approval",
        "reviewer_role": "independent-reviewer",
        "approved_at": "2026-07-14T12:00:00Z",
        "discovery_session_id": "session-20260714-000",
        "discovery_bundle_sha256": SHA,
        "discovery_gate_receipt_sha256": "b" * 64,
        "observation_approval_sha256": "c" * 64,
        "approved_contract_body_digest": digest,
    }
    return contract


def _codes(contract: object, *, allowlist: list[str] | None = None) -> set[str]:
    package = {
        "package_id": "core",
        "classification": "CORE_CANDIDATE",
        "reference_allowlist": allowlist or [],
        "reference_contract": contract,
    }
    return {
        diagnostic.code
        for diagnostic in reference_contract_diagnostics(
            package, path="packages.json#/packages/0"
        )
    }


def test_discovery_contract_is_exact_for_each_package_and_companion_is_v2() -> None:
    for package_id in ("core", "fleet-spa", "fleet-fta"):
        contract = discovery_contract(package_id)
        package = {
            "package_id": package_id,
            "classification": "CORE_CANDIDATE",
            "reference_allowlist": [],
            "reference_contract": contract,
        }
        assert not reference_contract_diagnostics(
            package, path=f"packages.json#/{package_id}"
        )
        assert reference_contract_body_digest(contract) is None
        assert reference_companion(package) == {
            "schema_version": 2,
            "package_id": package_id,
            "reference_allowlist": [],
            "reference_contract": contract,
            "contract_body_digest": None,
            "compile_status": "not-run",
        }


def test_resolved_reference_id_uses_canonical_guid_and_decimal_version() -> None:
    assert resolved_reference_id(
        "{000204EF-0000-0000-C000-000000000046}", 4, 2
    ) == VBA_ID
    with pytest.raises(ValueError):
        resolved_reference_id("000204ef-0000-0000-c000-000000000046", 4, 2)
    with pytest.raises(ValueError):
        resolved_reference_id("{000204EF-0000-0000-C000-000000000046}", True, 2)


def test_approved_contract_is_complete_and_exposes_exact_point_set() -> None:
    contract = approved_contract()
    assert not _codes(contract, allowlist=[FORMS_ID])
    assert approved_reference_set(contract, "blank-project") == frozenset({VBA_ID})
    assert approved_reference_set(contract, "post-restart") == frozenset(
        {VBA_ID, FORMS_ID}
    )
    with pytest.raises(ValueError):
        approved_reference_set(contract, "unknown")


def test_approved_contract_satisfies_the_package_schema() -> None:
    schema_path = Path(__file__).parents[1] / "schemas/packages.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    document = {
        "schema_version": 1,
        "packages": [
            {
                "package_id": "core",
                "classification": "CORE_CANDIDATE",
                "reference_allowlist": [FORMS_ID],
                "reference_contract": approved_contract(),
            }
        ],
    }
    assert list(Draft202012Validator(schema).iter_errors(document)) == []


def _schema_errors(contract: dict) -> list:
    schema_path = Path(__file__).parents[1] / "schemas/packages.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    document = {
        "schema_version": 1,
        "packages": [
            {
                "package_id": "core",
                "classification": "CORE_CANDIDATE",
                "reference_allowlist": [],
                "reference_contract": contract,
            }
        ],
    }
    return list(Draft202012Validator(schema).iter_errors(document))


def _resign(contract: dict) -> None:
    digest = reference_contract_body_digest(contract)
    contract["contract_body_digest"] = digest
    contract["approval"]["approved_contract_body_digest"] = digest


@pytest.mark.parametrize(
    "basename",
    [
        ".",
        "..",
        "CON",
        "AUX.dll",
        "nul.TLB",
        "COM1.ocx",
        "LPT9.dll",
        "library.",
        "library ",
    ],
)
def test_definition_path_policy_rejects_nonportable_basenames_in_schema_and_semantics(
    basename: str,
) -> None:
    contract = approved_contract()
    contract["reference_definitions"][0]["path_policy"]["allowed_basenames"] = [
        basename
    ]

    assert _schema_errors(contract)
    assert "REFERENCE_PATH_POLICY_INVALID" in _codes(contract)


@pytest.mark.parametrize(
    "relative_path",
    [
        "./VBE7.DLL",
        "../VBE7.DLL",
        "Libraries/CON.dll",
        "AUX/VBE7.DLL",
        "Libraries/nul.TLB",
        "Libraries/COM1.ocx",
        "Libraries/LPT9.dll",
        "Libraries./VBE7.DLL",
        "Libraries /VBE7.DLL",
        "Libraries/VBE7.DLL.",
        "Libraries/VBE7.DLL ",
        "A" * 241,
    ],
)
def test_definition_path_policy_rejects_nonportable_relative_segments_in_schema_and_semantics(
    relative_path: str,
) -> None:
    contract = approved_contract()
    contract["reference_definitions"][0]["path_policy"][
        "allowed_relative_paths"
    ] = [relative_path]

    assert _schema_errors(contract)
    assert "REFERENCE_PATH_POLICY_INVALID" in _codes(contract)


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("allowed_basenames", ["VBE7.DLL", "vbe7.dll"]),
        ("allowed_basenames", ["K.TLB", "\u212a.tlb"]),
        (
            "allowed_relative_paths",
            ["System/VBE7.DLL", "system/vbe7.dll"],
        ),
        (
            "allowed_relative_paths",
            ["System/K.TLB", "system/\u212a.tlb"],
        ),
    ],
)
def test_definition_path_policy_rejects_portable_key_collisions(
    field: str, values: list[str]
) -> None:
    contract = approved_contract()
    contract["reference_definitions"][0]["path_policy"][field] = values

    assert "REFERENCE_PATH_POLICY_INVALID" in _codes(contract)


def test_definition_path_policy_preserves_valid_windows_library_names() -> None:
    contract = approved_contract()
    policy = contract["reference_definitions"][0]["path_policy"]
    policy["allowed_basenames"] = ["VBE7.DLL", "CATIA.Application.TLB"]
    policy["allowed_relative_paths"] = [
        "System32/VBE7.DLL",
        "Dassault Systemes/B28/CATIA.Application.TLB",
    ]
    _resign(contract)

    assert not _schema_errors(contract)
    assert not _codes(contract)


def test_contract_body_digest_is_order_independent_for_objects_and_excludes_metadata() -> None:
    contract = approved_contract()
    expected = reference_contract_body_digest(contract)
    reordered = {
        key: copy.deepcopy(contract[key])
        for key in reversed(tuple(contract))
    }
    reordered["approval"]["reviewer_role"] = "second-reviewer"
    reordered["contract_body_digest"] = "f" * 64
    reordered["contract_id"] = "references.changed.b28"
    reordered["contract_version"] = 99
    reordered["status"] = "metadata-only"
    assert reference_contract_body_digest(reordered) == expected


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (lambda value: value.update(status=""), "REFERENCE_CONTRACT_STATUS_INVALID"),
        (
            lambda value: value["reference_definitions"][0]["allowed_names"].append("vba"),
            "REFERENCE_ALIAS_AMBIGUOUS",
        ),
        (
            lambda value: value["reference_definitions"].append(
                copy.deepcopy(value["reference_definitions"][0])
            ),
            "REFERENCE_DEFINITION_DUPLICATE",
        ),
        (
            lambda value: value["observation_points"]["post-save"].append(
                "ref.ffffffffffffffffffffffffffffffff.1.0"
            ),
            "REFERENCE_POINT_UNKNOWN",
        ),
        (
            lambda value: value["transitions"][0].update(added=[]),
            "REFERENCE_TRANSITION_INVALID",
        ),
        (
            lambda value: value["reference_definitions"][0].update(
                stable_reference_id="unresolved.deadbeef"
            ),
            "REFERENCE_DEFINITION_UNRESOLVED",
        ),
        (
            lambda value: value["reference_definitions"][0].update(
                guid="{000204ef-0000-0000-c000-000000000046}"
            ),
            "REFERENCE_GUID_INVALID",
        ),
        (
            lambda value: value["reference_definitions"][0].update(major="4.2"),
            "REFERENCE_VERSION_INVALID",
        ),
        (
            lambda value: value["reference_definitions"][0]["path_policy"].update(
                root_kind="user-profile"
            ),
            "REFERENCE_PATH_POLICY_INVALID",
        ),
        (
            lambda value: value["path_policy"].update(
                allowed_root_kinds=["catia-install"]
            ),
            "REFERENCE_PATH_POLICY_INVALID",
        ),
        (
            lambda value: value["reference_definitions"][0].update(
                release_provenance="B30"
            ),
            "REFERENCE_PROVENANCE_INVALID",
        ),
        (
            lambda value: value.update(contract_body_digest="f" * 64),
            "REFERENCE_CONTRACT_DIGEST_MISMATCH",
        ),
        (
            lambda value: value["approval"].update(
                approved_contract_body_digest="f" * 64
            ),
            "REFERENCE_APPROVAL_DIGEST_MISMATCH",
        ),
    ],
)
def test_approved_contract_rejects_invalid_semantics(mutator, expected_code: str) -> None:
    contract = approved_contract()
    mutator(contract)
    assert expected_code in _codes(contract)


def test_approved_text_without_observation_approval_is_rejected() -> None:
    contract = approved_contract()
    contract.pop("approval")
    assert "REFERENCE_APPROVAL_REQUIRED" in _codes(contract)


def test_discovery_contract_rejects_substitution_and_extra_fields() -> None:
    contract = discovery_contract()
    contract["status"] = ""
    assert "REFERENCE_CONTRACT_STATUS_INVALID" in _codes(contract)
    contract = discovery_contract()
    contract["approval"] = None
    assert "REFERENCE_DISCOVERY_SHAPE_INVALID" in _codes(contract)


def test_allowlist_is_stable_ids_within_approved_definitions_only() -> None:
    contract = approved_contract()
    assert "REFERENCE_ALLOWLIST_INVALID" in _codes(contract, allowlist=["VBA"])
    assert "REFERENCE_ALLOWLIST_UNKNOWN" in _codes(
        contract, allowlist=["ref.ffffffffffffffffffffffffffffffff.1.0"]
    )
    assert not _codes(contract, allowlist=[])
