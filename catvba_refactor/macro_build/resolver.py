from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from .errors import SourceError
from .manifests import ManifestSet
from .model import (
    Component,
    Diagnostic,
    Inventory,
    Origin,
    ResolvedSourceSet,
    SourceMember,
    ValidationReport,
)
from .portable_paths import portable_key


_CANDIDATE_ORIGINS = {
    Origin.UPSTREAM,
    Origin.NEW,
    Origin.OVERRIDE,
    Origin.SHARED,
}
_EXPECTED_ROLES = {
    "standard_module": Counter({"source": 1}),
    "class_module": Counter({"source": 1}),
    "user_form": Counter({"frm": 1, "frx": 1}),
}


def _diagnostic(
    code: str,
    path: str,
    message: str,
    **details: Any,
) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message, details=details)


def _frozen_detail(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(
            (str(key), _frozen_detail(nested))
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_frozen_detail(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted((_frozen_detail(item) for item in value), key=repr))
    return value


def _diagnostic_key(diagnostic: Diagnostic) -> tuple[Any, ...]:
    return (
        diagnostic.code,
        diagnostic.path,
        diagnostic.message,
        _frozen_detail(diagnostic.details),
    )


def _deduplicated(diagnostics: list[Diagnostic]) -> tuple[Diagnostic, ...]:
    seen: set[tuple[Any, ...]] = set()
    result: list[Diagnostic] = []
    for diagnostic in diagnostics:
        key = _diagnostic_key(diagnostic)
        if key not in seen:
            seen.add(key)
            result.append(diagnostic)
    return tuple(sorted(result))


def _manifest_records(manifests: ManifestSet) -> list[tuple[int, dict[str, Any]]]:
    records = manifests.components.get("components", [])
    if not isinstance(records, list):
        return []
    return [
        (index, record)
        for index, record in enumerate(records)
        if isinstance(record, dict)
    ]


def _package_ids(manifests: ManifestSet) -> set[str]:
    records = manifests.packages.get("packages", [])
    if not isinstance(records, list):
        return set()
    return {
        record["package_id"]
        for record in records
        if isinstance(record, dict) and isinstance(record.get("package_id"), str)
    }


def _root_origins(manifests: ManifestSet) -> tuple[tuple[str, Origin], ...]:
    records = manifests.components.get("source_roots", [])
    if not isinstance(records, list):
        return ()
    roots: list[tuple[str, Origin]] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            continue
        try:
            origin = Origin(record.get("origin"))
        except (TypeError, ValueError):
            continue
        path = record["path"].replace("\\", "/").rstrip("/")
        roots.append((path, origin))
    return tuple(sorted(roots, key=lambda item: (-len(item[0]), item[0], item[1])))


def _path_origins(path: str, roots: tuple[tuple[str, Origin], ...]) -> set[Origin]:
    normalized = path.replace("\\", "/")
    matches = [
        (root, origin)
        for root, origin in roots
        if normalized == root or normalized.startswith(f"{root}/")
    ]
    if not matches:
        return set()
    longest = len(matches[0][0])
    return {origin for root, origin in matches if len(root) == longest}


def _component_members_have_origin(
    component: Component,
    expected: Origin,
    roots: tuple[tuple[str, Origin], ...],
) -> bool:
    return bool(component.members) and all(
        _path_origins(member.path, roots) == {expected}
        for member in component.members
    )


def _binding_matches(actual: SourceMember, binding: dict[str, Any]) -> bool:
    return (
        actual.path == binding.get("path")
        and actual.blob_oid == binding.get("blob_oid")
        and actual.raw_sha256 == binding.get("raw_sha256")
        and actual.role == binding.get("role")
    )


def _bindings_match_component(component: Component, value: Any) -> bool:
    if not isinstance(value, list) or len(value) != len(component.members):
        return False
    bindings = [binding for binding in value if isinstance(binding, dict)]
    if len(bindings) != len(component.members):
        return False

    unused = list(component.members)
    for binding in bindings:
        match_index = next(
            (
                index
                for index, member in enumerate(unused)
                if _binding_matches(member, binding)
            ),
            None,
        )
        if match_index is None:
            return False
        unused.pop(match_index)
    return not unused


def _roles_match_type(component: Component) -> bool:
    expected = _EXPECTED_ROLES.get(component.component_type)
    return expected is not None and Counter(
        member.role for member in component.members
    ) == expected


def _record_path(index: int) -> str:
    return f"components.json#/components/{index}"


def _first_binding_path(record: dict[str, Any], field: str = "members") -> str:
    value = record.get(field)
    if isinstance(value, list):
        for binding in value:
            if isinstance(binding, dict) and isinstance(binding.get("path"), str):
                return binding["path"]
    return "components.json"


def _identity_matches(component: Component, record: dict[str, Any]) -> bool:
    return (
        component.source_id == record.get("source_id")
        and component.origin.value == record.get("origin")
        and component.component_type == record.get("component_type")
        and component.vb_name == record.get("vb_name")
    )


def _source_shadow_indexes(
    components: tuple[Component, ...], diagnostics: list[Diagnostic]
) -> set[int]:
    by_key: dict[str, list[tuple[int, SourceMember]]] = defaultdict(list)
    for component_index, component in enumerate(components):
        for member in component.members:
            try:
                key = portable_key(member.path)
            except SourceError:
                continue
            by_key[key].append((component_index, member))

    excluded: set[int] = set()
    for key in sorted(by_key):
        matches = by_key[key]
        if len(matches) < 2:
            continue
        component_indexes = {component_index for component_index, _member in matches}
        # Repeating a path within one component is also an ambiguous source bundle.
        excluded.update(component_indexes)
        paths = tuple(sorted(member.path for _index, member in matches))
        source_ids = tuple(
            sorted({components[index].source_id for index in component_indexes})
        )
        diagnostics.append(
            _diagnostic(
                "SOURCE_PATH_SHADOW",
                paths[0],
                "source members share one Windows-portable path key",
                paths=paths,
                source_ids=source_ids,
            )
        )
    return excluded


def _duplicate_source_ids(
    components: tuple[Component, ...], diagnostics: list[Diagnostic]
) -> set[str]:
    by_source_id: dict[str, list[Component]] = defaultdict(list)
    for component in components:
        by_source_id[component.source_id].append(component)
    duplicates: set[str] = set()
    for source_id in sorted(by_source_id):
        matches = by_source_id[source_id]
        if len(matches) < 2:
            continue
        duplicates.add(source_id)
        paths = tuple(
            sorted(
                member.path
                for component in matches
                for member in component.members
            )
        )
        diagnostics.append(
            _diagnostic(
                "DUPLICATE_SOURCE_ID",
                paths[0] if paths else source_id,
                f"inventory source_id is not unique: {source_id}",
                paths=paths,
            )
        )
    return duplicates


def _duplicate_manifest_ids(
    records: list[tuple[int, dict[str, Any]]], diagnostics: list[Diagnostic]
) -> set[str]:
    locations: dict[str, list[int]] = defaultdict(list)
    for index, record in records:
        source_id = record.get("source_id")
        if isinstance(source_id, str):
            locations[source_id].append(index)
    duplicates: set[str] = set()
    for source_id in sorted(locations):
        indices = locations[source_id]
        if len(indices) < 2:
            continue
        duplicates.add(source_id)
        diagnostics.append(
            _diagnostic(
                "DUPLICATE_SOURCE_ID",
                _record_path(indices[0]),
                f"manifest source_id is not unique: {source_id}",
                indices=tuple(indices),
            )
        )
    return duplicates


def _matching_base_index(
    record: dict[str, Any],
    components: tuple[Component, ...],
    by_path: dict[str, list[tuple[int, Component, SourceMember]]],
    roots: tuple[tuple[str, Origin], ...],
    duplicate_source_ids: set[str],
    shadow_indexes: set[int],
) -> int | None:
    bindings = record.get("base_members")
    component_type = record.get("component_type")
    expected = (
        _EXPECTED_ROLES.get(component_type)
        if isinstance(component_type, str)
        else None
    )
    if not isinstance(bindings, list) or expected is None:
        return None
    binding_records = [binding for binding in bindings if isinstance(binding, dict)]
    if len(binding_records) != len(bindings):
        return None
    binding_roles = [binding.get("role") for binding in binding_records]
    if not all(isinstance(role, str) for role in binding_roles):
        return None
    if Counter(binding_roles) != expected:
        return None

    selected: list[tuple[int, Component, SourceMember]] = []
    for binding in binding_records:
        path = binding.get("path")
        if not isinstance(path, str):
            return None
        matches = by_path.get(path, [])
        if len(matches) != 1:
            return None
        component_index, component, member = matches[0]
        if component.origin is not Origin.UPSTREAM:
            return None
        if not _binding_matches(member, binding):
            return None
        selected.append((component_index, component, member))

    component_indexes = {
        component_index
        for component_index, _component, _member in selected
    }
    if len(component_indexes) != 1:
        return None
    base_index = next(iter(component_indexes))
    base = components[base_index]
    if (
        base.origin is not Origin.UPSTREAM
        or base.component_type != record.get("component_type")
        or base.vb_name != record.get("vb_name")
        or not _roles_match_type(base)
        or not _bindings_match_component(base, bindings)
        or not _component_members_have_origin(base, Origin.UPSTREAM, roots)
    ):
        return None
    if base.source_id in duplicate_source_ids or base_index in shadow_indexes:
        return None
    return base_index


def _overlay_side_conflicts(
    candidates_by_index: dict[int, Component],
    override_base_indexes: dict[int, int],
    components: tuple[Component, ...],
    diagnostics: list[Diagnostic],
) -> set[str]:
    overrides_by_base: dict[int, list[int]] = defaultdict(list)
    for override_index, base_index in override_base_indexes.items():
        if override_index in candidates_by_index:
            overrides_by_base[base_index].append(override_index)

    excluded: set[str] = set()
    ordered_base_indexes = sorted(
        overrides_by_base,
        key=lambda index: _component_sort_key(components[index]),
    )
    for base_index in ordered_base_indexes:
        override_indexes = overrides_by_base[base_index]
        base_is_candidate = base_index in candidates_by_index
        if len(override_indexes) == 1 and not base_is_candidate:
            continue

        conflicting_indexes = [*override_indexes]
        if base_is_candidate:
            conflicting_indexes.append(base_index)
        source_ids = tuple(
            sorted(candidates_by_index[index].source_id for index in conflicting_indexes)
        )
        excluded.update(source_ids)
        base = components[base_index]
        diagnostics.append(
            _diagnostic(
                "OVERLAY_SIDE_CONFLICT",
                min(
                    (member.path for member in base.members),
                    default=base.source_id,
                ),
                "candidate selections do not choose one exclusive overlay side",
                base_source_id=base.source_id,
                source_ids=source_ids,
            )
        )
    return excluded


def _candidate_collisions(
    candidates: list[Component], diagnostics: list[Diagnostic]
) -> set[str]:
    excluded: set[str] = set()
    by_output: dict[tuple[str, str], list[tuple[Component, SourceMember]]] = (
        defaultdict(list)
    )
    invalid_output: list[tuple[Component, SourceMember]] = []
    by_vb_name: dict[tuple[str, str], list[Component]] = defaultdict(list)

    for component in candidates:
        assert component.package_id is not None
        for member in component.members:
            filename = PurePosixPath(member.path).name
            try:
                key = portable_key(filename)
            except SourceError:
                invalid_output.append((component, member))
                continue
            by_output[(component.package_id, key)].append((component, member))
        folded_name = unicodedata.normalize("NFKC", component.vb_name).casefold()
        by_vb_name[(component.package_id, folded_name)].append(component)

    for component, member in sorted(
        invalid_output,
        key=lambda item: (item[0].package_id or "", item[1].path),
    ):
        excluded.add(component.source_id)
        diagnostics.append(
            _diagnostic(
                "PACKAGE_OUTPUT_PATH_INVALID",
                member.path,
                "candidate output filename is not Windows-portable",
                package_id=component.package_id,
                source_id=component.source_id,
            )
        )

    for (package_id, _key), matches in sorted(by_output.items()):
        if len(matches) < 2:
            continue
        source_ids = tuple(sorted({component.source_id for component, _ in matches}))
        excluded.update(source_ids)
        paths = tuple(sorted(member.path for _component, member in matches))
        diagnostics.append(
            _diagnostic(
                "PACKAGE_OUTPUT_PATH_COLLISION",
                paths[0],
                "candidate members collide at the package source output filename",
                package_id=package_id,
                paths=paths,
                source_ids=source_ids,
            )
        )

    for (package_id, folded_name), matches in sorted(by_vb_name.items()):
        if len(matches) < 2:
            continue
        source_ids = tuple(sorted(component.source_id for component in matches))
        excluded.update(source_ids)
        paths = tuple(
            sorted(
                member.path
                for component in matches
                for member in component.members[:1]
            )
        )
        diagnostics.append(
            _diagnostic(
                "PACKAGE_VB_NAME_COLLISION",
                paths[0] if paths else folded_name,
                "candidate components share a package-local VB_Name",
                package_id=package_id,
                source_ids=source_ids,
                vb_name=folded_name,
            )
        )
    return excluded


def _component_sort_key(component: Component) -> tuple[Any, ...]:
    return (
        component.source_id,
        component.vb_name,
        component.package_id or "",
        tuple((member.role, member.path) for member in component.members),
    )


def resolve_sources(
    inventory: Inventory,
    manifests: ManifestSet,
) -> ResolvedSourceSet:
    """Resolve exact manifest overlays without fuzzy matching or fallback."""
    diagnostics = [
        *manifests.report.diagnostics,
        *inventory.report.diagnostics,
    ]
    components = inventory.components
    records = _manifest_records(manifests)
    roots = _root_origins(manifests)
    known_packages = _package_ids(manifests)

    duplicate_inventory_ids = _duplicate_source_ids(components, diagnostics)
    duplicate_manifest_ids = _duplicate_manifest_ids(records, diagnostics)
    shadow_indexes = _source_shadow_indexes(components, diagnostics)

    by_source_id: dict[str, list[tuple[int, Component]]] = defaultdict(list)
    by_path: dict[str, list[tuple[int, Component, SourceMember]]] = defaultdict(list)
    for component_index, component in enumerate(components):
        by_source_id[component.source_id].append((component_index, component))
        for member in component.members:
            by_path[member.path].append((component_index, component, member))

    manifest_source_ids = {
        record["source_id"]
        for _index, record in records
        if isinstance(record.get("source_id"), str)
    }
    for component in components:
        if (
            component.disposition == "candidate"
            and component.source_id not in manifest_source_ids
        ):
            diagnostics.append(
                _diagnostic(
                    "UNMANIFESTED_CANDIDATE",
                    (
                        component.members[0].path
                        if component.members
                        else component.source_id
                    ),
                    "candidate inventory component has no exact manifest entry",
                    source_id=component.source_id,
                )
            )

    candidates: list[Component] = []
    candidates_by_index: dict[int, Component] = {}
    override_base_indexes: dict[int, int] = {}
    for record_index, record in records:
        source_id = record.get("source_id")
        if not isinstance(source_id, str) or source_id in duplicate_manifest_ids:
            continue
        matches = by_source_id.get(source_id, [])
        if not matches:
            diagnostics.append(
                _diagnostic(
                    "MANIFEST_SOURCE_ORPHAN",
                    _record_path(record_index),
                    "manifest source_id has no exact inventory component",
                    source_id=source_id,
                )
            )
            continue
        if len(matches) != 1 or source_id in duplicate_inventory_ids:
            continue
        component_index, component = matches[0]

        record_disposition = record.get("disposition")
        if record_disposition == "candidate" and component.disposition != "candidate":
            diagnostics.append(
                _diagnostic(
                    "CANDIDATE_DISPOSITION_INVALID",
                    _record_path(record_index),
                    "candidate manifest entry resolved to a non-candidate component",
                    actual=component.disposition,
                    source_id=source_id,
                )
            )
            continue
        if component.disposition != record_disposition:
            diagnostics.append(
                _diagnostic(
                    "SOURCE_DISPOSITION_MISMATCH",
                    _record_path(record_index),
                    "inventory and manifest dispositions differ",
                    actual=component.disposition,
                    declared=record_disposition,
                    source_id=source_id,
                )
            )
            continue
        if not _identity_matches(component, record) or not _roles_match_type(component):
            diagnostics.append(
                _diagnostic(
                    "SOURCE_IDENTITY_MISMATCH",
                    _record_path(record_index),
                    "component type, origin, VB_Name, or member roles changed",
                    source_id=source_id,
                )
            )
            continue
        if not _bindings_match_component(component, record.get("members")):
            diagnostics.append(
                _diagnostic(
                    "SOURCE_BINDING_MISMATCH",
                    _first_binding_path(record),
                    "selected component does not exactly match every member binding",
                    source_id=source_id,
                )
            )
            continue
        if not _component_members_have_origin(component, component.origin, roots):
            diagnostics.append(
                _diagnostic(
                    "COMPONENT_MEMBER_ORIGIN_MIXED",
                    (
                        component.members[0].path
                        if component.members
                        else _record_path(record_index)
                    ),
                    "component members do not all belong to its one declared source side",
                    source_id=source_id,
                )
            )
            continue
        if component_index in shadow_indexes:
            continue

        declared_package = record.get("package_id")
        if component.package_id != declared_package:
            diagnostics.append(
                _diagnostic(
                    "PACKAGE_ASSIGNMENT_MISMATCH",
                    _record_path(record_index),
                    "inventory and manifest package assignments differ",
                    actual=component.package_id,
                    declared=declared_package,
                    source_id=source_id,
                )
            )
            continue

        if component.origin is Origin.OVERRIDE:
            base_index = _matching_base_index(
                record,
                components,
                by_path,
                roots,
                duplicate_inventory_ids,
                shadow_indexes,
            )
            if base_index is None:
                diagnostics.append(
                    _diagnostic(
                        "OVERRIDE_STALE_BASE",
                        _first_binding_path(record, "base_members"),
                        "override base is missing, drifted, duplicated, or shadowed",
                        source_id=source_id,
                    )
                )
                continue
            override_base_indexes[component_index] = base_index

        if component.disposition != "candidate":
            continue
        if component.origin not in _CANDIDATE_ORIGINS:
            diagnostics.append(
                _diagnostic(
                    "CANDIDATE_ORIGIN_INVALID",
                    _record_path(record_index),
                    "quarantine origin cannot be selected into package staging",
                    source_id=source_id,
                )
            )
            continue
        if (
            not isinstance(component.package_id, str)
            or not component.package_id
            or not isinstance(declared_package, str)
            or not declared_package
        ):
            diagnostics.append(
                _diagnostic(
                    "PACKAGE_REQUIRED",
                    _record_path(record_index),
                    "candidate component requires an explicit package assignment",
                    source_id=source_id,
                )
            )
            continue
        if component.package_id not in known_packages:
            diagnostics.append(
                _diagnostic(
                    "UNKNOWN_PACKAGE",
                    _record_path(record_index),
                    "candidate component references an unknown package",
                    package_id=component.package_id,
                    source_id=source_id,
                )
            )
            continue
        candidates.append(component)
        candidates_by_index[component_index] = component

    overlay_conflict_ids = _overlay_side_conflicts(
        candidates_by_index,
        override_base_indexes,
        components,
        diagnostics,
    )
    collision_ids = _candidate_collisions(candidates, diagnostics)
    excluded_ids = overlay_conflict_ids | collision_ids
    selected = tuple(
        sorted(
            (
                component
                for component in candidates
                if component.source_id not in excluded_ids
            ),
            key=_component_sort_key,
        )
    )
    quarantined = tuple(
        sorted(
            (
                component
                for component in components
                if component.disposition in {"quarantine", "retired"}
            ),
            key=_component_sort_key,
        )
    )
    return ResolvedSourceSet(
        components=selected,
        quarantined=quarantined,
        report=ValidationReport(_deduplicated(diagnostics)),
    )
