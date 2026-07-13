from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from catvba_refactor.macro_build.manifests import ManifestSet
from catvba_refactor.macro_build.model import (
    Component,
    Diagnostic,
    Inventory,
    Origin,
    SourceMember,
    ValidationReport,
)
from catvba_refactor.macro_build.resolver import resolve_sources


def _member(path: str, role: str, data: bytes | None = None) -> SourceMember:
    payload = data if data is not None else f"bytes:{path}:{role}".encode("ascii")
    return SourceMember(
        path=path,
        blob_oid=hashlib.sha1(payload).hexdigest(),
        raw_sha256=hashlib.sha256(payload).hexdigest(),
        role=role,
        data=payload,
    )


def _component(
    source_id: str,
    origin: Origin,
    component_type: str,
    vb_name: str,
    members: tuple[SourceMember, ...],
    *,
    package_id: str | None = "core",
    disposition: str = "candidate",
) -> Component:
    return Component(
        source_id=source_id,
        origin=origin,
        component_type=component_type,
        vb_name=vb_name,
        members=members,
        package_id=package_id,
        disposition=disposition,
        encoding_decision=None,
    )


def _binding(member: SourceMember) -> dict[str, str | None]:
    return {
        "path": member.path,
        "blob_oid": member.blob_oid,
        "raw_sha256": member.raw_sha256,
        "role": member.role,
    }


def _record(
    component: Component,
    *,
    base: Component | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_id": component.source_id,
        "origin": component.origin.value,
        "component_type": component.component_type,
        "vb_name": component.vb_name,
        "package_id": component.package_id,
        "disposition": component.disposition,
        "members": [_binding(member) for member in component.members],
    }
    if base is not None:
        record["base_members"] = [_binding(member) for member in base.members]
    return record


def _roots() -> list[dict[str, Any]]:
    return [
        {
            "root_id": "upstream-src",
            "origin": "upstream",
            "path": "Src",
            "extensions": [".bas", ".cls", ".frm", ".frx"],
            "default_disposition": "quarantine",
        },
        {
            "root_id": "new-src",
            "origin": "new",
            "path": "catvba_refactor/vba/new",
            "extensions": [".bas", ".cls", ".frm", ".frx"],
            "default_disposition": "quarantine",
        },
        {
            "root_id": "override-src",
            "origin": "override",
            "path": "catvba_refactor/vba/overrides",
            "extensions": [".bas", ".cls", ".frm", ".frx"],
            "default_disposition": "quarantine",
        },
        {
            "root_id": "shared-src",
            "origin": "shared",
            "path": "catvba_refactor/vba/shared_contracts",
            "extensions": [".bas", ".cls", ".frm", ".frx"],
            "default_disposition": "quarantine",
        },
        {
            "root_id": "quarantine-src",
            "origin": "quarantine",
            "path": "catvba_refactor/vba/quarantine",
            "extensions": [".bas", ".cls", ".frm", ".frx"],
            "default_disposition": "quarantine",
        },
    ]


def _manifests(
    records: list[dict[str, Any]],
    *,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> ManifestSet:
    return ManifestSet(
        project={},
        components={
            "schema_version": 1,
            "source_roots": _roots(),
            "components": records,
        },
        packages={
            "schema_version": 1,
            "packages": [
                {"package_id": "core", "classification": "CORE_CANDIDATE"},
                {
                    "package_id": "fleet-spa",
                    "classification": "FLEET_EXTENSION_SPA",
                },
            ],
        },
        tools={"schema_version": 1, "tools": []},
        digest="f" * 64,
        report=ValidationReport(diagnostics),
    )


def _inventory(
    components: list[Component],
    *,
    diagnostics: tuple[Diagnostic, ...] = (),
    formal_eligible: bool = True,
) -> Inventory:
    return Inventory(
        components=tuple(components),
        report=ValidationReport(diagnostics),
        formal_eligible=formal_eligible,
    )


def _codes(resolved: Any) -> list[str]:
    return [diagnostic.code for diagnostic in resolved.report.diagnostics]


def _valid_fixture() -> tuple[list[Component], list[dict[str, Any]]]:
    upstream = _component(
        "core.upstream",
        Origin.UPSTREAM,
        "standard_module",
        "UpstreamTool",
        (_member("Src/UpstreamTool.bas", "source"),),
    )
    new = _component(
        "core.new-tool",
        Origin.NEW,
        "class_module",
        "NewTool",
        (_member("catvba_refactor/vba/new/NewTool.cls", "source"),),
    )
    shared = _component(
        "shared.contract",
        Origin.SHARED,
        "standard_module",
        "SharedContract",
        (
            _member(
                "catvba_refactor/vba/shared_contracts/SharedContract.bas",
                "source",
            ),
        ),
        package_id="fleet-spa",
    )
    quarantined = _component(
        "hold.unsafe",
        Origin.QUARANTINE,
        "standard_module",
        "Unsafe",
        (_member("catvba_refactor/vba/quarantine/Unsafe.bas", "source"),),
        package_id=None,
        disposition="quarantine",
    )
    base_module = _component(
        "discovered-base-module",
        Origin.UPSTREAM,
        "standard_module",
        "BaseTool",
        (_member("Src/BaseTool.bas", "source"),),
        package_id=None,
        disposition="quarantine",
    )
    override_module = _component(
        "core.base-tool",
        Origin.OVERRIDE,
        "standard_module",
        "BaseTool",
        (_member("catvba_refactor/vba/overrides/BaseTool.bas", "source"),),
    )
    base_form = _component(
        "discovered-base-form",
        Origin.UPSTREAM,
        "user_form",
        "MenuForm",
        (
            _member("Src/MenuForm.frm", "frm"),
            _member("Src/MenuForm.frx", "frx", b"upstream-form-resource"),
        ),
        package_id=None,
        disposition="quarantine",
    )
    override_form = _component(
        "core.menu-form",
        Origin.OVERRIDE,
        "user_form",
        "MenuForm",
        (
            _member("catvba_refactor/vba/overrides/MenuForm.frm", "frm"),
            _member(
                "catvba_refactor/vba/overrides/MenuForm.frx",
                "frx",
                b"local-form-resource",
            ),
        ),
    )
    inventory = [
        base_form,
        shared,
        upstream,
        override_form,
        quarantined,
        base_module,
        new,
        override_module,
    ]
    records = [
        _record(shared),
        _record(override_form, base=base_form),
        _record(quarantined),
        _record(new),
        _record(override_module, base=base_module),
        _record(upstream),
    ]
    return inventory, records


def test_resolves_explicit_origins_and_atomic_overrides_with_exact_bytes() -> None:
    components, records = _valid_fixture()

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert resolved.report.ok
    assert [component.source_id for component in resolved.components] == [
        "core.base-tool",
        "core.menu-form",
        "core.new-tool",
        "core.upstream",
        "shared.contract",
    ]
    assert [component.source_id for component in resolved.quarantined] == [
        "discovered-base-form",
        "discovered-base-module",
        "hold.unsafe",
    ]
    selected_form = next(
        component
        for component in resolved.components
        if component.source_id == "core.menu-form"
    )
    original_form = next(
        component for component in components if component.source_id == "core.menu-form"
    )
    assert selected_form is original_form
    assert selected_form.members[0] is original_form.members[0]
    assert selected_form.members[1].data == b"local-form-resource"
    assert all(member.path.startswith("catvba_refactor/") for member in selected_form.members)


def test_nonformal_worktree_members_resolve_without_git_object_identity() -> None:
    components, records = _valid_fixture()
    worktree_components = [
        replace(
            component,
            members=tuple(
                replace(member, blob_oid=None) for member in component.members
            ),
        )
        for component in components
    ]

    resolved = resolve_sources(
        _inventory(worktree_components, formal_eligible=False),
        _manifests(records),
    )

    assert resolved.report.ok
    assert [component.source_id for component in resolved.components] == [
        "core.base-tool",
        "core.menu-form",
        "core.new-tool",
        "core.upstream",
        "shared.contract",
    ]


def test_formal_inventory_rejects_missing_git_object_identity() -> None:
    components, records = _valid_fixture()
    component = next(
        component for component in components if component.source_id == "core.new-tool"
    )
    component_index = components.index(component)
    components[component_index] = replace(
        component,
        members=(replace(component.members[0], blob_oid=None),),
    )

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "SOURCE_BINDING_MISMATCH" in _codes(resolved)


def test_nonformal_worktree_members_still_reject_raw_hash_drift() -> None:
    components, records = _valid_fixture()
    component = next(
        component for component in components if component.source_id == "core.new-tool"
    )
    component_index = components.index(component)
    components[component_index] = replace(
        component,
        members=(
            replace(component.members[0], blob_oid=None, raw_sha256="0" * 64),
        ),
    )

    resolved = resolve_sources(
        _inventory(components, formal_eligible=False),
        _manifests(records),
    )

    assert "SOURCE_BINDING_MISMATCH" in _codes(resolved)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("blob_oid", "0" * 40),
        ("raw_sha256", "0" * 64),
        ("role", "frm"),
    ],
)
def test_override_rejects_every_base_member_binding_drift(
    field: str, replacement: str
) -> None:
    components, records = _valid_fixture()
    override = next(record for record in records if record["source_id"] == "core.base-tool")
    override["base_members"][0][field] = replacement

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "OVERRIDE_STALE_BASE" in _codes(resolved)
    assert "core.base-tool" not in {
        component.source_id for component in resolved.components
    }


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("vb_name", "RenamedBase"), ("component_type", "class_module")],
)
def test_override_rejects_upstream_identity_drift(
    field: str, replacement: str
) -> None:
    components, records = _valid_fixture()
    base_index = next(
        index
        for index, component in enumerate(components)
        if component.source_id == "discovered-base-module"
    )
    components[base_index] = replace(components[base_index], **{field: replacement})

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "OVERRIDE_STALE_BASE" in _codes(resolved)
    assert "core.base-tool" not in {
        component.source_id for component in resolved.components
    }


def test_form_override_rejects_one_sided_base_binding() -> None:
    components, records = _valid_fixture()
    override = next(record for record in records if record["source_id"] == "core.menu-form")
    override["base_members"] = override["base_members"][:1]

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "OVERRIDE_STALE_BASE" in _codes(resolved)
    assert "core.menu-form" not in {
        component.source_id for component in resolved.components
    }


def test_form_override_rejects_local_and_upstream_member_mixing() -> None:
    components, records = _valid_fixture()
    local_index = next(
        index
        for index, component in enumerate(components)
        if component.source_id == "core.menu-form"
    )
    local = components[local_index]
    upstream_frx = next(
        component
        for component in components
        if component.source_id == "discovered-base-form"
    ).members[1]
    components[local_index] = replace(
        local,
        members=(local.members[0], upstream_frx),
    )
    override = next(record for record in records if record["source_id"] == "core.menu-form")
    override["members"] = [_binding(member) for member in components[local_index].members]

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "COMPONENT_MEMBER_ORIGIN_MIXED" in _codes(resolved)
    assert "core.menu-form" not in {
        component.source_id for component in resolved.components
    }


def test_form_override_rejects_mixed_upstream_base_components() -> None:
    components, records = _valid_fixture()
    second_form = _component(
        "discovered-other-form",
        Origin.UPSTREAM,
        "user_form",
        "MenuForm",
        (
            _member("Src/OtherForm.frm", "frm"),
            _member("Src/OtherForm.frx", "frx"),
        ),
        package_id=None,
        disposition="quarantine",
    )
    components.append(second_form)
    override = next(record for record in records if record["source_id"] == "core.menu-form")
    override["base_members"][1] = _binding(second_form.members[1])

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "OVERRIDE_STALE_BASE" in _codes(resolved)
    assert "core.menu-form" not in {
        component.source_id for component in resolved.components
    }


def test_fuzzy_case_path_is_not_guessed_for_selected_member() -> None:
    components, records = _valid_fixture()
    record = next(record for record in records if record["source_id"] == "core.upstream")
    record["members"][0]["path"] = "src/upstreamtool.bas"

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "SOURCE_BINDING_MISMATCH" in _codes(resolved)
    assert "core.upstream" not in {
        component.source_id for component in resolved.components
    }


def test_renamed_override_base_never_falls_back_to_upstream() -> None:
    components, records = _valid_fixture()
    override = next(record for record in records if record["source_id"] == "core.base-tool")
    override["base_members"][0]["path"] = "Src/OldBaseTool.bas"

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "OVERRIDE_STALE_BASE" in _codes(resolved)
    assert "core.base-tool" not in {
        component.source_id for component in resolved.components
    }
    assert not any(
        component.vb_name == "BaseTool" for component in resolved.components
    )


def test_override_rejects_base_with_duplicate_inventory_source_id() -> None:
    components, records = _valid_fixture()
    base = next(
        component
        for component in components
        if component.source_id == "discovered-base-module"
    )
    components.append(
        replace(
            base,
            members=(_member("Src/DuplicateBaseTool.bas", "source"),),
        )
    )

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "DUPLICATE_SOURCE_ID" in _codes(resolved)
    assert "OVERRIDE_STALE_BASE" in _codes(resolved)
    assert "core.base-tool" not in {
        component.source_id for component in resolved.components
    }


def test_override_rejects_base_with_portable_member_path_shadow() -> None:
    components, records = _valid_fixture()
    base = next(
        component
        for component in components
        if component.source_id == "discovered-base-module"
    )
    components.append(
        replace(
            base,
            source_id="discovered-shadow-base",
            members=(_member("Src/BASETOOL.BAS", "source"),),
        )
    )

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert "SOURCE_PATH_SHADOW" in _codes(resolved)
    assert "OVERRIDE_STALE_BASE" in _codes(resolved)
    assert "core.base-tool" not in {
        component.source_id for component in resolved.components
    }


def test_candidate_base_and_override_are_mutually_exclusive_across_packages() -> None:
    components, records = _valid_fixture()
    base_index = next(
        index
        for index, component in enumerate(components)
        if component.source_id == "discovered-base-module"
    )
    candidate_base = replace(
        components[base_index],
        package_id="fleet-spa",
        disposition="candidate",
    )
    components[base_index] = candidate_base
    records.append(_record(candidate_base))

    forward = resolve_sources(_inventory(components), _manifests(records))
    reversed_order = resolve_sources(
        _inventory(list(reversed(components))),
        _manifests(list(reversed(records))),
    )

    assert _codes(forward) == ["OVERLAY_SIDE_CONFLICT"]
    assert forward.report.diagnostics == reversed_order.report.diagnostics
    for resolved in (forward, reversed_order):
        assert {
            "core.base-tool",
            "discovered-base-module",
        }.isdisjoint(component.source_id for component in resolved.components)


def test_two_candidate_overrides_cannot_reuse_one_exact_base() -> None:
    components, records = _valid_fixture()
    base = next(
        component
        for component in components
        if component.source_id == "discovered-base-module"
    )
    second_override = _component(
        "fleet.base-tool",
        Origin.OVERRIDE,
        "standard_module",
        "BaseTool",
        (
            _member(
                "catvba_refactor/vba/overrides/FleetBaseTool.bas",
                "source",
            ),
        ),
        package_id="fleet-spa",
    )
    components.append(second_override)
    records.append(_record(second_override, base=base))

    forward = resolve_sources(_inventory(components), _manifests(records))
    reversed_order = resolve_sources(
        _inventory(list(reversed(components))),
        _manifests(list(reversed(records))),
    )

    assert _codes(forward) == ["OVERLAY_SIDE_CONFLICT"]
    assert forward.report.diagnostics == reversed_order.report.diagnostics
    for resolved in (forward, reversed_order):
        assert {"core.base-tool", "fleet.base-tool"}.isdisjoint(
            component.source_id for component in resolved.components
        )


def test_one_override_remains_selected_over_a_retired_base() -> None:
    components, records = _valid_fixture()
    base_index = next(
        index
        for index, component in enumerate(components)
        if component.source_id == "discovered-base-module"
    )
    retired_base = replace(components[base_index], disposition="retired")
    components[base_index] = retired_base

    resolved = resolve_sources(_inventory(components), _manifests(records))

    assert resolved.report.ok
    assert "core.base-tool" in {
        component.source_id for component in resolved.components
    }
    assert retired_base in resolved.quarantined


def test_duplicate_package_output_filename_excludes_both_components() -> None:
    first = _component(
        "core.first",
        Origin.NEW,
        "standard_module",
        "First",
        (_member("catvba_refactor/vba/new/folder/Tool.bas", "source"),),
    )
    second = _component(
        "core.second",
        Origin.SHARED,
        "standard_module",
        "Second",
        (
            _member(
                "catvba_refactor/vba/shared_contracts/TOOL.BAS",
                "source",
            ),
        ),
    )

    resolved = resolve_sources(
        _inventory([first, second]),
        _manifests([_record(first), _record(second)]),
    )

    assert _codes(resolved) == ["PACKAGE_OUTPUT_PATH_COLLISION"]
    assert resolved.components == ()


def test_package_local_vb_name_collision_is_case_insensitive() -> None:
    first = _component(
        "core.first",
        Origin.NEW,
        "standard_module",
        "SameName",
        (_member("catvba_refactor/vba/new/First.bas", "source"),),
    )
    second = _component(
        "core.second",
        Origin.SHARED,
        "class_module",
        "samename",
        (
            _member(
                "catvba_refactor/vba/shared_contracts/Second.cls",
                "source",
            ),
        ),
    )

    resolved = resolve_sources(
        _inventory([first, second]),
        _manifests([_record(first), _record(second)]),
    )

    assert _codes(resolved) == ["PACKAGE_VB_NAME_COLLISION"]
    assert resolved.components == ()


def test_duplicate_inventory_source_ids_and_portable_path_shadows_are_rejected() -> None:
    first = _component(
        "core.duplicate",
        Origin.NEW,
        "standard_module",
        "First",
        (_member("catvba_refactor/vba/new/Shadow.bas", "source"),),
    )
    duplicate = _component(
        "core.duplicate",
        Origin.SHARED,
        "standard_module",
        "Second",
        (
            _member(
                "catvba_refactor/vba/shared_contracts/Unrelated.bas",
                "source",
            ),
        ),
    )
    shadow = _component(
        "core.shadow",
        Origin.NEW,
        "standard_module",
        "Shadow",
        (_member("catvba_refactor/vba/new/shadow.BAS", "source"),),
    )

    resolved = resolve_sources(
        _inventory([shadow, duplicate, first]),
        _manifests([_record(first), _record(shadow)]),
    )

    assert _codes(resolved) == ["DUPLICATE_SOURCE_ID", "SOURCE_PATH_SHADOW"]
    assert resolved.components == ()


def test_duplicate_manifest_source_id_excludes_all_duplicate_entries() -> None:
    component = _component(
        "core.duplicate",
        Origin.NEW,
        "standard_module",
        "Duplicate",
        (_member("catvba_refactor/vba/new/Duplicate.bas", "source"),),
    )

    resolved = resolve_sources(
        _inventory([component]),
        _manifests([_record(component), _record(component)]),
    )

    assert _codes(resolved) == ["DUPLICATE_SOURCE_ID"]
    assert resolved.components == ()


def test_orphan_manifest_entry_is_rejected_without_fuzzy_source_id_match() -> None:
    component = _component(
        "core.actual",
        Origin.NEW,
        "standard_module",
        "Actual",
        (_member("catvba_refactor/vba/new/Actual.bas", "source"),),
    )
    record = _record(component)
    record["source_id"] = "core.actua1"

    resolved = resolve_sources(_inventory([component]), _manifests([record]))

    assert _codes(resolved) == [
        "MANIFEST_SOURCE_ORPHAN",
        "UNMANIFESTED_CANDIDATE",
    ]
    assert resolved.components == ()


def test_unmanifested_candidate_and_non_candidate_manifest_selection_fail_closed() -> None:
    unmanifested = _component(
        "core.unmanifested",
        Origin.NEW,
        "standard_module",
        "Unmanifested",
        (_member("catvba_refactor/vba/new/Unmanifested.bas", "source"),),
    )
    quarantined = _component(
        "core.quarantined",
        Origin.NEW,
        "standard_module",
        "Quarantined",
        (_member("catvba_refactor/vba/new/Quarantined.bas", "source"),),
        package_id=None,
        disposition="quarantine",
    )
    record = _record(quarantined)
    record["disposition"] = "candidate"
    record["package_id"] = "core"

    resolved = resolve_sources(
        _inventory([quarantined, unmanifested]),
        _manifests([record]),
    )

    assert _codes(resolved) == [
        "CANDIDATE_DISPOSITION_INVALID",
        "UNMANIFESTED_CANDIDATE",
    ]
    assert resolved.components == ()
    assert resolved.quarantined == (quarantined,)


def test_explicit_quarantine_package_assignment_must_also_match_exactly() -> None:
    quarantined = _component(
        "hold.package-test",
        Origin.QUARANTINE,
        "standard_module",
        "HeldPackageTest",
        (
            _member(
                "catvba_refactor/vba/quarantine/HeldPackageTest.bas",
                "source",
            ),
        ),
        package_id=None,
        disposition="quarantine",
    )
    record = _record(quarantined)
    record["package_id"] = "core"

    resolved = resolve_sources(
        _inventory([quarantined]),
        _manifests([record]),
    )

    assert _codes(resolved) == ["PACKAGE_ASSIGNMENT_MISMATCH"]
    assert resolved.components == ()
    assert resolved.quarantined == (quarantined,)


@pytest.mark.parametrize("package_id", [None, "", "missing"])
def test_candidate_requires_assigned_known_package(package_id: str | None) -> None:
    component = _component(
        "core.package-test",
        Origin.NEW,
        "standard_module",
        "PackageTest",
        (_member("catvba_refactor/vba/new/PackageTest.bas", "source"),),
        package_id=package_id,
    )

    resolved = resolve_sources(
        _inventory([component]),
        _manifests([_record(component)]),
    )

    expected = "PACKAGE_REQUIRED" if not package_id else "UNKNOWN_PACKAGE"
    assert _codes(resolved) == [expected]
    assert resolved.components == ()


def test_initial_upstream_quarantine_yields_no_candidates_or_runtime_claims() -> None:
    upstream = _component(
        "discovered-upstream",
        Origin.UPSTREAM,
        "standard_module",
        "Legacy",
        (_member("Src/Legacy.bas", "source"),),
        package_id=None,
        disposition="quarantine",
    )

    resolved = resolve_sources(_inventory([upstream]), _manifests([]))

    assert resolved.report.ok
    assert resolved.components == ()
    assert resolved.quarantined == (upstream,)
    assert all(
        "pass" not in diagnostic.message.casefold()
        and "verified" not in diagnostic.message.casefold()
        for diagnostic in resolved.report.diagnostics
    )


def test_existing_diagnostics_and_new_results_are_deduplicated_and_sorted() -> None:
    shared = Diagnostic("Z_EXISTING", "z", "inventory")
    repeated = Diagnostic("A_EXISTING", "a", "shared")
    missing = _component(
        "core.missing",
        Origin.NEW,
        "standard_module",
        "Missing",
        (_member("catvba_refactor/vba/new/Missing.bas", "source"),),
    )

    resolved = resolve_sources(
        _inventory([], diagnostics=(shared, repeated)),
        _manifests([_record(missing)], diagnostics=(repeated,)),
    )

    assert resolved.report.diagnostics == tuple(sorted(resolved.report.diagnostics))
    assert _codes(resolved) == [
        "A_EXISTING",
        "MANIFEST_SOURCE_ORPHAN",
        "Z_EXISTING",
    ]
