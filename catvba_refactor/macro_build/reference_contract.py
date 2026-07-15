from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from .canonical import canonical_json_bytes, sha256_bytes
from .model import Diagnostic
from .portable_paths import validate_portable_ascii_paths


_POINTS = (
    "blank-project",
    "post-form-import",
    "post-all-import",
    "post-save",
    "post-restart",
)
_TRANSITIONS = tuple(zip(_POINTS[:-1], _POINTS[1:], strict=True))
_GUID = re.compile(
    r"^\{[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}\}$"
)
_REFERENCE_ID = re.compile(r"^ref\.[0-9a-f]{32}\.[0-9]+\.[0-9]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECORD_ID = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
_UTC = re.compile(
    r"^[0-9]{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])"
    r"T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$"
)
_BASENAME = re.compile(r"^[A-Za-z0-9._ -]{1,100}$")
_ROOT_KINDS = frozenset({"catia-install", "windows-install", "system"})
_SOURCE_CLASSIFICATIONS = frozenset(
    {"builtin", "host-default", "package-added", "import-introduced"}
)
_DISCOVERY_FIELDS = frozenset(
    {
        "contract_id",
        "contract_version",
        "observation_points",
        "reference_definitions",
        "status",
        "transitions",
    }
)
_APPROVED_FIELDS = frozenset(
    {
        *_DISCOVERY_FIELDS,
        "path_policy",
        "contract_body_digest",
        "approval",
    }
)
_DEFINITION_FIELDS = frozenset(
    {
        "stable_reference_id",
        "guid",
        "major",
        "minor",
        "allowed_names",
        "allowed_descriptions",
        "source_classification",
        "architecture",
        "release_provenance",
        "path_policy",
    }
)
_DEFINITION_PATH_FIELDS = frozenset(
    {
        "root_kind",
        "allowed_basenames",
        "allowed_relative_paths",
        "canonical_path_sha256",
    }
)
_GLOBAL_PATH_FIELDS = frozenset({"allowed_root_kinds", "allow_user_paths"})
_TRANSITION_FIELDS = frozenset({"from", "to", "added", "removed"})
_APPROVAL_FIELDS = frozenset(
    {
        "reference_approval_record_id",
        "reviewer_role",
        "approved_at",
        "discovery_session_id",
        "discovery_bundle_sha256",
        "discovery_gate_receipt_sha256",
        "observation_approval_sha256",
        "approved_contract_body_digest",
    }
)


def resolved_reference_id(guid: str, major: int, minor: int) -> str:
    """Return the locale-independent stable identity for one resolved Reference."""
    if type(guid) is not str or _GUID.fullmatch(guid) is None:
        raise ValueError("GUID must use canonical uppercase-braced form")
    if (
        type(major) is not int
        or type(minor) is not int
        or major < 0
        or minor < 0
    ):
        raise ValueError("Reference major/minor must be non-negative integers")
    compact = guid[1:-1].replace("-", "").lower()
    return f"ref.{compact}.{major}.{minor}"


def reference_contract_body_digest(contract: object) -> str | None:
    """Hash only the approved contract body, never approval or self metadata."""
    if not isinstance(contract, Mapping):
        return None
    body_fields = (
        "reference_definitions",
        "observation_points",
        "transitions",
        "path_policy",
    )
    if any(contract.get(field) is None for field in body_fields):
        return None
    body = {field: contract[field] for field in body_fields}
    try:
        return sha256_bytes(canonical_json_bytes(body))
    except (RecursionError, TypeError, ValueError):
        return None


def reference_companion(package: Mapping[str, Any]) -> dict[str, Any]:
    """Create the sole canonical Kit companion representation for a package."""
    contract = copy.deepcopy(package["reference_contract"])
    return {
        "schema_version": 2,
        "package_id": package["package_id"],
        "reference_allowlist": copy.deepcopy(package.get("reference_allowlist", [])),
        "reference_contract": contract,
        "contract_body_digest": reference_contract_body_digest(contract),
        "compile_status": "not-run",
    }


def approved_reference_set(contract: object, point: str) -> frozenset[str]:
    if point not in _POINTS:
        raise ValueError(f"unknown Reference observation point: {point}")
    if not isinstance(contract, Mapping) or contract.get("status") != "approved":
        raise ValueError("Reference contract is not approved")
    points = contract.get("observation_points")
    if not isinstance(points, Mapping) or not isinstance(points.get(point), list):
        raise ValueError("approved Reference point is malformed")
    values = points[point]
    if any(type(value) is not str for value in values):
        raise ValueError("approved Reference point is malformed")
    return frozenset(values)


def _unique_string_array(
    value: object, *, nonempty: bool = False, pattern: re.Pattern[str] | None = None
) -> bool:
    if type(value) is not list or (nonempty and not value):
        return False
    if any(type(item) is not str or not item for item in value):
        return False
    if pattern is not None and any(pattern.fullmatch(item) is None for item in value):
        return False
    return len(value) == len(set(value))


def _aliases_valid(value: object, *, maximum: int) -> tuple[bool, bool]:
    if not _unique_string_array(value, nonempty=True):
        return False, False
    assert isinstance(value, list)
    if any(
        len(item) > maximum
        or unicodedata.normalize("NFC", item) != item
        or any(ord(character) < 32 or ord(character) == 127 for character in item)
        for item in value
    ):
        return False, False
    normalized = [unicodedata.normalize("NFC", item).casefold() for item in value]
    return True, len(normalized) != len(set(normalized))


def _diagnostic(code: str, path: str, message: str) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message)


def reference_contract_diagnostics(
    package: object, *, path: str
) -> tuple[Diagnostic, ...]:
    """Apply strict package Reference semantics independently of JSON Schema."""
    diagnostics: list[Diagnostic] = []

    def add(code: str, suffix: str, message: str) -> None:
        diagnostics.append(_diagnostic(code, f"{path}{suffix}", message))

    if not isinstance(package, Mapping):
        add("REFERENCE_CONTRACT_INVALID", "", "package must be an object")
        return tuple(diagnostics)
    package_id = package.get("package_id")
    contract = package.get("reference_contract")
    if type(package_id) is not str or not isinstance(contract, Mapping):
        add(
            "REFERENCE_CONTRACT_INVALID",
            "/reference_contract",
            "package requires a structured Reference contract",
        )
        return tuple(diagnostics)

    status = contract.get("status")
    expected_contract_id = f"references.{package_id}.b28"
    if status not in {"discovery-required", "approved"}:
        add(
            "REFERENCE_CONTRACT_STATUS_INVALID",
            "/reference_contract/status",
            "Reference contract status must be discovery-required or approved",
        )
        return tuple(sorted(diagnostics))
    if contract.get("contract_id") != expected_contract_id:
        add(
            "REFERENCE_CONTRACT_ID_INVALID",
            "/reference_contract/contract_id",
            f"Reference contract ID must be {expected_contract_id}",
        )
    if contract.get("contract_version") != 1 or type(
        contract.get("contract_version")
    ) is not int:
        add(
            "REFERENCE_CONTRACT_VERSION_INVALID",
            "/reference_contract/contract_version",
            "Reference contract version must be integer 1",
        )

    allowlist = package.get("reference_allowlist", [])
    if not _unique_string_array(allowlist, pattern=_REFERENCE_ID):
        add(
            "REFERENCE_ALLOWLIST_INVALID",
            "/reference_allowlist",
            "Reference allowlist must contain unique stable Reference IDs",
        )

    if status == "discovery-required":
        if (
            frozenset(contract) != _DISCOVERY_FIELDS
            or contract.get("reference_definitions") is not None
            or contract.get("observation_points") is not None
            or contract.get("transitions") is not None
        ):
            add(
                "REFERENCE_DISCOVERY_SHAPE_INVALID",
                "/reference_contract",
                "discovery-required contract must use the exact empty discovery shape",
            )
        return tuple(sorted(diagnostics))

    if frozenset(contract) != _APPROVED_FIELDS:
        add(
            "REFERENCE_APPROVED_SHAPE_INVALID",
            "/reference_contract",
            "approved Reference contract has missing or unknown fields",
        )

    definitions = contract.get("reference_definitions")
    known_ids: set[str] = set()
    definition_root_kinds: set[str] = set()
    if type(definitions) is not list or not definitions:
        add(
            "REFERENCE_DEFINITION_INVALID",
            "/reference_contract/reference_definitions",
            "approved contract requires Reference definitions",
        )
        definitions = []
    for index, definition in enumerate(definitions):
        definition_path = f"/reference_contract/reference_definitions/{index}"
        if not isinstance(definition, Mapping) or frozenset(definition) != _DEFINITION_FIELDS:
            add(
                "REFERENCE_DEFINITION_INVALID",
                definition_path,
                "Reference definition has missing or unknown fields",
            )
            continue
        stable_id = definition.get("stable_reference_id")
        if type(stable_id) is str and stable_id.startswith("unresolved."):
            add(
                "REFERENCE_DEFINITION_UNRESOLVED",
                f"{definition_path}/stable_reference_id",
                "approved definitions cannot contain unresolved identities",
            )
        elif type(stable_id) is not str or _REFERENCE_ID.fullmatch(stable_id) is None:
            add(
                "REFERENCE_DEFINITION_INVALID",
                f"{definition_path}/stable_reference_id",
                "stable Reference ID is invalid",
            )
        elif stable_id in known_ids:
            add(
                "REFERENCE_DEFINITION_DUPLICATE",
                f"{definition_path}/stable_reference_id",
                "stable Reference ID is duplicated",
            )
        else:
            known_ids.add(stable_id)

        guid = definition.get("guid")
        if type(guid) is not str or _GUID.fullmatch(guid) is None:
            add(
                "REFERENCE_GUID_INVALID",
                f"{definition_path}/guid",
                "GUID must use canonical uppercase-braced form",
            )
        major = definition.get("major")
        minor = definition.get("minor")
        if (
            type(major) is not int
            or type(minor) is not int
            or major < 0
            or minor < 0
        ):
            add(
                "REFERENCE_VERSION_INVALID",
                definition_path,
                "major and minor must be non-negative integers",
            )
        elif type(guid) is str and _GUID.fullmatch(guid) is not None:
            if stable_id != resolved_reference_id(guid, major, minor):
                add(
                    "REFERENCE_STABLE_ID_MISMATCH",
                    f"{definition_path}/stable_reference_id",
                    "stable Reference ID does not match GUID and version",
                )

        for field, maximum in (("allowed_names", 160), ("allowed_descriptions", 320)):
            valid, ambiguous = _aliases_valid(definition.get(field), maximum=maximum)
            if not valid:
                add(
                    "REFERENCE_ALIAS_INVALID",
                    f"{definition_path}/{field}",
                    "Reference aliases must be unique controlled NFC strings",
                )
            elif ambiguous:
                add(
                    "REFERENCE_ALIAS_AMBIGUOUS",
                    f"{definition_path}/{field}",
                    "Reference aliases collide after NFC case normalization",
                )
        if definition.get("source_classification") not in _SOURCE_CLASSIFICATIONS:
            add(
                "REFERENCE_SOURCE_INVALID",
                f"{definition_path}/source_classification",
                "Reference source classification is invalid",
            )
        if definition.get("architecture") != "x64" or definition.get(
            "release_provenance"
        ) != "B28":
            add(
                "REFERENCE_PROVENANCE_INVALID",
                definition_path,
                "approved Reference must bind x64 B28 provenance",
            )
        definition_policy = definition.get("path_policy")
        allowed_basenames = (
            definition_policy.get("allowed_basenames", [])
            if isinstance(definition_policy, Mapping)
            else []
        )
        allowed_relative_paths = (
            definition_policy.get("allowed_relative_paths", [])
            if isinstance(definition_policy, Mapping)
            else []
        )
        valid_definition_policy = (
            isinstance(definition_policy, Mapping)
            and frozenset(definition_policy) == _DEFINITION_PATH_FIELDS
            and definition_policy.get("root_kind") in _ROOT_KINDS
            and _unique_string_array(
                allowed_basenames,
                nonempty=True,
                pattern=_BASENAME,
            )
            and validate_portable_ascii_paths(allowed_basenames).ok
            and _unique_string_array(allowed_relative_paths)
            and all(len(value) <= 240 for value in allowed_relative_paths)
            and validate_portable_ascii_paths(allowed_relative_paths).ok
            and (
                definition_policy.get("canonical_path_sha256") is None
                or (
                    type(definition_policy.get("canonical_path_sha256")) is str
                    and _SHA256.fullmatch(
                        definition_policy["canonical_path_sha256"]
                    )
                    is not None
                )
            )
        )
        if not valid_definition_policy:
            add(
                "REFERENCE_PATH_POLICY_INVALID",
                f"{definition_path}/path_policy",
                "Reference definition path policy is invalid",
            )
        else:
            definition_root_kinds.add(definition_policy["root_kind"])

    if isinstance(allowlist, list) and all(
        type(value) is str and _REFERENCE_ID.fullmatch(value) is not None
        for value in allowlist
    ):
        for index, stable_id in enumerate(allowlist):
            if stable_id not in known_ids:
                add(
                    "REFERENCE_ALLOWLIST_UNKNOWN",
                    f"/reference_allowlist/{index}",
                    "allowlisted Reference ID is absent from approved definitions",
                )

    global_policy = contract.get("path_policy")
    valid_global_policy = (
        isinstance(global_policy, Mapping)
        and frozenset(global_policy) == _GLOBAL_PATH_FIELDS
        and _unique_string_array(global_policy.get("allowed_root_kinds"), nonempty=True)
        and set(global_policy.get("allowed_root_kinds", [])) <= _ROOT_KINDS
        and global_policy.get("allow_user_paths") is False
    )
    if not valid_global_policy:
        add(
            "REFERENCE_PATH_POLICY_INVALID",
            "/reference_contract/path_policy",
            "global Reference path policy is invalid",
        )
    elif not definition_root_kinds <= set(global_policy["allowed_root_kinds"]):
        add(
            "REFERENCE_PATH_POLICY_INVALID",
            "/reference_contract/path_policy/allowed_root_kinds",
            "global path policy must allow every Reference definition root",
        )

    point_sets: dict[str, set[str]] = {}
    points = contract.get("observation_points")
    if not isinstance(points, Mapping) or frozenset(points) != frozenset(_POINTS):
        add(
            "REFERENCE_POINTS_INVALID",
            "/reference_contract/observation_points",
            "approved contract requires exactly five observation points",
        )
    else:
        for point in _POINTS:
            values = points.get(point)
            if not _unique_string_array(values, pattern=_REFERENCE_ID):
                add(
                    "REFERENCE_POINTS_INVALID",
                    f"/reference_contract/observation_points/{point}",
                    "Reference point must contain unique stable IDs",
                )
                continue
            assert isinstance(values, list)
            point_sets[point] = set(values)
            if not set(values) <= known_ids:
                add(
                    "REFERENCE_POINT_UNKNOWN",
                    f"/reference_contract/observation_points/{point}",
                    "Reference point contains an unknown stable ID",
                )

    transitions = contract.get("transitions")
    if type(transitions) is not list or len(transitions) != len(_TRANSITIONS):
        add(
            "REFERENCE_TRANSITION_INVALID",
            "/reference_contract/transitions",
            "approved contract requires four adjacent transitions",
        )
    else:
        for index, ((source, target), transition) in enumerate(
            zip(_TRANSITIONS, transitions, strict=True)
        ):
            transition_path = f"/reference_contract/transitions/{index}"
            if (
                not isinstance(transition, Mapping)
                or frozenset(transition) != _TRANSITION_FIELDS
                or transition.get("from") != source
                or transition.get("to") != target
                or not _unique_string_array(transition.get("added"), pattern=_REFERENCE_ID)
                or not _unique_string_array(transition.get("removed"), pattern=_REFERENCE_ID)
            ):
                add(
                    "REFERENCE_TRANSITION_INVALID",
                    transition_path,
                    "Reference transition must bind its adjacent points and exact deltas",
                )
                continue
            added = set(transition["added"])
            removed = set(transition["removed"])
            if (
                not added <= known_ids
                or not removed <= known_ids
                or source not in point_sets
                or target not in point_sets
                or added != point_sets[target] - point_sets[source]
                or removed != point_sets[source] - point_sets[target]
            ):
                add(
                    "REFERENCE_TRANSITION_INVALID",
                    transition_path,
                    "Reference transition delta does not reproduce adjacent point sets",
                )

    body_digest = reference_contract_body_digest(contract)
    if (
        type(contract.get("contract_body_digest")) is not str
        or _SHA256.fullmatch(contract["contract_body_digest"]) is None
        or contract.get("contract_body_digest") != body_digest
    ):
        add(
            "REFERENCE_CONTRACT_DIGEST_MISMATCH",
            "/reference_contract/contract_body_digest",
            "contract body digest must match only the canonical approved body",
        )

    approval = contract.get("approval")
    if not isinstance(approval, Mapping) or frozenset(approval) != _APPROVAL_FIELDS:
        add(
            "REFERENCE_APPROVAL_REQUIRED",
            "/reference_contract/approval",
            "approved Reference contract requires complete observation approval provenance",
        )
    else:
        record_fields = (
            "reference_approval_record_id",
            "reviewer_role",
            "discovery_session_id",
        )
        digest_fields = (
            "discovery_bundle_sha256",
            "discovery_gate_receipt_sha256",
            "observation_approval_sha256",
        )
        if (
            any(
                type(approval.get(field)) is not str
                or _RECORD_ID.fullmatch(approval[field]) is None
                for field in record_fields
            )
            or type(approval.get("approved_at")) is not str
            or _UTC.fullmatch(approval["approved_at"]) is None
            or any(
                type(approval.get(field)) is not str
                or _SHA256.fullmatch(approval[field]) is None
                for field in digest_fields
            )
        ):
            add(
                "REFERENCE_APPROVAL_INVALID",
                "/reference_contract/approval",
                "Reference approval provenance is malformed",
            )
        if approval.get("approved_contract_body_digest") != body_digest:
            add(
                "REFERENCE_APPROVAL_DIGEST_MISMATCH",
                "/reference_contract/approval/approved_contract_body_digest",
                "observation approval does not bind this contract body",
            )

    return tuple(sorted(set(diagnostics)))
