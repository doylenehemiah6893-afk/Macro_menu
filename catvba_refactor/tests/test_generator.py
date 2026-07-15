from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from catvba_refactor.macro_build.generator import (
    GENERATED_SOURCE_DESCRIPTORS,
    generate_sources,
)
from catvba_refactor.macro_build.manifests import ManifestSet
from catvba_refactor.macro_build.model import (
    Component,
    Diagnostic,
    InputSnapshot,
    Origin,
    ResolvedCatalog,
    ResolvedSourceSet,
    SnapshotMode,
    SourceMember,
    ValidationReport,
)
from catvba_refactor.macro_build.policy import validate_catalog


def _tool(tool_id: str, caption: str) -> dict[str, Any]:
    return {
        "tool_id": tool_id,
        "caption": caption,
        "tooltip": f"Run {caption}",
        "group_id": "core.general",
        "group_caption": "Core Tools",
        "package_id": "core",
        "module_name": "MM_HealthCheck",
        "entrypoint": "Run",
        "document_types": ["none"],
        "required_capabilities": [],
        "risk_level": "read-only",
    }


def _complete_package(record: dict[str, Any]) -> dict[str, Any]:
    value = dict(record)
    package_id = value.get("package_id")
    if isinstance(package_id, str):
        value.setdefault("reference_allowlist", [])
        value.setdefault(
            "reference_contract",
            {
                "contract_id": f"references.{package_id}.b28",
                "contract_version": 1,
                "observation_points": None,
                "reference_definitions": None,
                "status": "discovery-required",
                "transitions": None,
            },
        )
    return value


def _manifests(
    tools: list[dict[str, Any]],
    *,
    packages: list[dict[str, Any]] | None = None,
    diagnostics: tuple[Diagnostic, ...] = (),
) -> ManifestSet:
    return ManifestSet(
        project={"schema_version": 1},
        components={"schema_version": 1, "source_roots": [], "components": []},
        packages={
            "schema_version": 1,
            "packages": [
                _complete_package(record)
                for record in (
                    packages
                    if packages is not None
                    else [{"package_id": "core", "classification": "CORE_CANDIDATE"}]
                )
            ],
        },
        tools={"schema_version": 1, "tools": tools},
        digest="f" * 64,
        report=ValidationReport(diagnostics),
    )


def _module(
    source_id: str = "core.healthcheck-module",
    *,
    vb_name: str = "MM_HealthCheck",
    path: str = "catvba_refactor/vba/new/MM_HealthCheck.bas",
    package_id: str = "core",
    body: str = (
        "Public Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
        "End Function\r\n"
    ),
) -> Component:
    text = (
        f'Attribute VB_Name = "{vb_name}"\r\n'
        "Option Explicit\r\n"
        f"{body}"
    )
    data = text.encode("utf-8")
    return Component(
        source_id=source_id,
        origin=Origin.NEW,
        component_type="standard_module",
        vb_name=vb_name,
        members=(
            SourceMember(
                path=path,
                blob_oid="a" * 40,
                raw_sha256=hashlib.sha256(data).hexdigest(),
                role="source",
                data=data,
            ),
        ),
        package_id=package_id,
        disposition="candidate",
        encoding_decision=None,
    )


def _resolved(
    diagnostics: tuple[Diagnostic, ...] = (),
    *,
    components: tuple[Component, ...] | None = None,
) -> ResolvedSourceSet:
    return ResolvedSourceSet(
        components=components if components is not None else (_module(),),
        quarantined=(),
        report=ValidationReport(diagnostics),
    )


def _snapshot() -> InputSnapshot:
    return InputSnapshot(
        mode=SnapshotMode.CANDIDATE,
        upstream_repository="verysolecd/Macro_menu",
        upstream_ref="dev",
        upstream_commit="1" * 40,
        fork_repository="doylenehemiah6893-afk/Macro_menu",
        fork_dev_commit="2" * 40,
        work_repository="doylenehemiah6893-afk/Macro_menu",
        work_branch="codex/dev-review-report",
        work_commit="3" * 40,
        work_tree="4" * 40,
        manifest_digest="f" * 64,
        tool_version="0.1.0",
        formal_eligible=True,
    )


def test_generates_exact_sorted_cp936_runtime_modules() -> None:
    manifests = _manifests(
        [
            _tool("core.zulu", '英文 "检查"'),
            _tool("core.alpha", "中文菜单"),
        ]
    )

    generated = generate_sources(_resolved(), manifests, _snapshot())

    assert generated.report.ok
    assert [component.source_id for component in generated.components] == [
        "generated.build-info",
        "generated.dispatch",
        "generated.menu-catalog",
    ]
    assert [component.vb_name for component in generated.components] == [
        "MM_BuildInfo",
        "MM_Dispatch",
        "MM_MenuCatalog",
    ]
    assert [component.members[0].path for component in generated.components] == [
        "generated/MM_BuildInfo.bas",
        "generated/MM_Dispatch.bas",
        "generated/MM_MenuCatalog.bas",
    ]
    assert all(component.origin is Origin.GENERATED for component in generated.components)
    assert all(component.component_type == "standard_module" for component in generated.components)
    assert all(component.package_id == "core" for component in generated.components)
    assert all(component.disposition == "candidate" for component in generated.components)
    assert all(len(component.members) == 1 for component in generated.components)
    assert len({component.members[0].raw_sha256 for component in generated.components}) == 3
    for component in generated.components:
        member = component.members[0]
        assert member.blob_oid is None
        assert member.role == "source"
        assert member.raw_sha256 == hashlib.sha256(member.data).hexdigest()
        assert b"\n" not in member.data.replace(b"\r\n", b"")
        assert b"\r" not in member.data.replace(b"\r\n", b"")
        assert member.data.decode("cp936", errors="strict").encode(
            "cp936", errors="strict"
        ) == member.data

    by_name = {
        component.vb_name: component.members[0].data.decode("cp936")
        for component in generated.components
    }
    catalog_text = by_name["MM_MenuCatalog"]
    assert 'MM_ToolIds = Array("core.alpha", "core.zulu")' in catalog_text
    assert 'MM_ToolCaptions = Array("中文菜单", "英文 ""检查""")' in catalog_text
    assert 'MM_ToolTooltips = Array("Run 中文菜单", "Run 英文 ""检查""")' in catalog_text
    assert 'MM_ToolGroupIds = Array("core.general", "core.general")' in catalog_text
    assert 'MM_ToolGroupCaptions = Array("Core Tools", "Core Tools")' in catalog_text
    assert (
        'MM_ToolControlNames = Array("btn_core_alpha_821bc2da", '
        '"btn_core_zulu_b2d66980")'
    ) in catalog_text
    assert (
        'MM_ToolPageNames = Array("pg_core_general_635cb7db", '
        '"pg_core_general_635cb7db")'
    ) in catalog_text

    dispatch_text = by_name["MM_Dispatch"]
    assert dispatch_text.count("Select Case commandId") == 1
    assert dispatch_text.count("Set result = MM_HealthCheck.Run(context)") == 2
    assert "MM_HealthCheck.Run(request)" not in dispatch_text
    assert "MM_Protocol.TryParseRequest" in dispatch_text
    assert dispatch_text.count("MM_Protocol.BuildResponse") == 1
    assert dispatch_text.count("CleanExit:") == 1
    assert "Dim buildingResponse As Boolean" in dispatch_text
    clean_exit = dispatch_text.index("CleanExit:")
    build_call = dispatch_text.index("MM_Protocol.BuildResponse")
    fail = dispatch_text.index("Fail:")
    assert clean_exit < dispatch_text.index("buildingResponse = True", clean_exit) < build_call < fail
    fail_body = dispatch_text[fail:]
    assert "If buildingResponse Then Exit Function" in fail_body
    assert fail_body.index("If buildingResponse Then Exit Function") < fail_body.index(
        "MM_Error.InternalError(Err.Number)"
    )
    assert "Resume CleanExit" in fail_body
    assert "Case Else" in dispatch_text
    assert "MM_Error.UnknownCommand(commandId)" in dispatch_text
    assert "MM_Error.InternalError(Err.Number)" in dispatch_text
    assert "Err.Description" not in dispatch_text
    for forbidden in ("ExecuteScript", "CallByName", ".catvba", "user_code"):
        assert forbidden not in dispatch_text

    build_text = by_name["MM_BuildInfo"]
    for value in ("MM/1", "f" * 64, "3" * 40, "4" * 40, "0.1.0"):
        assert value in build_text
    assert "kit_id" not in build_text.casefold()

    catalog = ResolvedCatalog(
        snapshot=_snapshot(),
        components=(*_resolved().components, *generated.components),
        packages=tuple(manifests.packages["packages"]),
        tools=tuple(manifests.tools["tools"]),
        report=generated.report,
    )
    assert validate_catalog(catalog).ok


def test_core_generated_modules_exclude_valid_non_core_tools_after_full_policy() -> None:
    core_tool = _tool("core.healthcheck", "Health Check")
    fleet_tool = {
        **_tool("fleet.spa-audit", "SPA Audit"),
        "group_id": "fleet.spa",
        "group_caption": "SPA Tools",
        "package_id": "fleet-spa",
        "module_name": "MM_SpaAudit",
        "entrypoint": "RunSpaAudit",
    }
    fta_tool = {
        **_tool("fleet.fta-audit", "FTA Audit"),
        "group_id": "fleet.fta",
        "group_caption": "FTA Tools",
        "package_id": "fleet-fta",
        "module_name": "MM_FtaAudit",
        "entrypoint": "RunFtaAudit",
    }
    components = (
        _module(
            body=(
                "Public Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
                "End Function\r\n"
            )
        ),
        _module(
            "fleet.spa-audit-module",
            vb_name="MM_SpaAudit",
            path="catvba_refactor/vba/new/MM_SpaAudit.bas",
            package_id="fleet-spa",
            body=(
                "Public Function RunSpaAudit(ByVal context As C_MMContext) As C_MMResult\r\n"
                "End Function\r\n"
            ),
        ),
        _module(
            "fleet.fta-audit-module",
            vb_name="MM_FtaAudit",
            path="catvba_refactor/vba/new/MM_FtaAudit.bas",
            package_id="fleet-fta",
            body=(
                "Public Function RunFtaAudit(ByVal context As C_MMContext) As C_MMResult\r\n"
                "End Function\r\n"
            ),
        ),
    )
    manifests = _manifests(
        [fta_tool, fleet_tool, core_tool],
        packages=[
            {"package_id": "core", "classification": "CORE_CANDIDATE"},
            {
                "package_id": "fleet-spa",
                "classification": "FLEET_EXTENSION_SPA",
            },
            {
                "package_id": "fleet-fta",
                "classification": "FLEET_EXTENSION_FTA",
            },
        ],
    )

    generated = generate_sources(
        _resolved(components=components), manifests, _snapshot()
    )

    assert generated.report.ok
    texts = "\n".join(
        component.members[0].data.decode("cp936")
        for component in generated.components
    )
    assert "core.healthcheck" in texts
    assert "MM_HealthCheck.Run(context)" in texts
    assert "fleet.spa-audit" not in texts
    assert "MM_SpaAudit" not in texts
    assert "fleet.fta-audit" not in texts
    assert "MM_FtaAudit" not in texts


@pytest.mark.parametrize(
    "body",
    [
        "Public Sub Run(ByVal context As C_MMContext)\r\nEnd Sub\r\n",
        "Public Function Run() As C_MMResult\r\nEnd Function\r\n",
        (
            "Public Function Run(ByRef context As C_MMContext) As C_MMResult\r\n"
            "End Function\r\n"
        ),
        (
            "Public Function Run(ByVal context As Object) As C_MMResult\r\n"
            "End Function\r\n"
        ),
        (
            "Public Function Run(ByVal context As C_MMContext, ByVal extra As Long) As C_MMResult\r\n"
            "End Function\r\n"
        ),
        (
            "Public Function Run(ByVal context As C_MMContext) As Variant\r\n"
            "End Function\r\n"
        ),
    ],
)
def test_generator_rejects_every_non_exact_tool_abi(body: str) -> None:
    generated = generate_sources(
        _resolved(components=(_module(body=body),)),
        _manifests([_tool("core.invalid", "Invalid")]),
        _snapshot(),
    )

    assert generated.components == ()
    assert [finding.code for finding in generated.report.diagnostics] == [
        "TOOL_ENTRYPOINT_BINDING_INVALID"
    ]


def test_generation_is_byte_deterministic_across_manifest_order() -> None:
    tools = [
        _tool("core.zulu", "末项"),
        _tool("core.alpha", "首项"),
    ]

    forward = generate_sources(_resolved(), _manifests(tools), _snapshot())
    reverse = generate_sources(
        _resolved(), _manifests(list(reversed(tools))), _snapshot()
    )

    assert forward == reverse
    forward_bytes = {
        component.source_id: component.members[0].data
        for component in forward.components
    }
    reverse_bytes = {
        component.source_id: component.members[0].data
        for component in reverse.components
    }
    assert forward_bytes == reverse_bytes
    assert set(forward_bytes) == {
        "generated.build-info",
        "generated.dispatch",
        "generated.menu-catalog",
    }


def test_empty_tool_manifest_still_generates_the_exact_runtime_identity_set() -> None:
    generated = generate_sources(_resolved(), _manifests([]), _snapshot())

    assert generated.report.ok
    assert [component.source_id for component in generated.components] == [
        "generated.build-info",
        "generated.dispatch",
        "generated.menu-catalog",
    ]


def test_unencodable_caption_fails_closed_without_replacement_bytes() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests([_tool("core.emoji", "unsafe 😀 caption")]),
        _snapshot(),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "GENERATED_CP936_UNENCODABLE"
    ]
    finding = generated.report.diagnostics[0]
    assert finding.path == "generated/MM_MenuCatalog.bas"
    assert finding.details == {"line": 9, "token": "cp936"}
    assert "PASS" not in finding.message.upper()


def test_missing_core_package_binding_excludes_generated_component() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests(
            [_tool("core.alpha", "Alpha")],
            packages=[
                {
                    "package_id": "fleet-spa",
                    "classification": "FLEET_EXTENSION_SPA",
                }
            ],
        ),
        _snapshot(),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "PACKAGE_BINDING_INVALID",
        "TOOL_PACKAGE_BINDING_INVALID",
    ]
    assert generated.report.diagnostics[1].details == {
        "line": 1,
        "token": "core",
    }


def test_non_core_classified_core_package_is_rejected_by_generator() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests(
            [_tool("core.alpha", "Alpha")],
            packages=[
                {
                    "package_id": "core",
                    "classification": "FLEET_EXTENSION_SPA",
                }
            ],
        ),
        _snapshot(),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "GENERATED_PACKAGE_INVALID"
    ]
    assert generated.report.diagnostics[0].details == {
        "line": 1,
        "token": "core",
    }


def test_duplicate_core_packages_are_rejected_before_generation() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests(
            [_tool("core.alpha", "Alpha")],
            packages=[
                {"package_id": "core", "classification": "CORE_CANDIDATE"},
                {
                    "package_id": "core",
                    "classification": "FLEET_EXTENSION_SPA",
                },
            ],
        ),
        _snapshot(),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "DUPLICATE_PACKAGE_ID",
        "PACKAGE_BINDING_INVALID",
        "TOOL_PACKAGE_BINDING_INVALID",
    ]


def test_prior_diagnostic_is_inherited_and_prevents_generated_output() -> None:
    inherited = Diagnostic("SOURCE_PREEXISTING", "A.bas", "existing source finding")
    generated = generate_sources(
        _resolved((inherited,)),
        _manifests([_tool("core.alpha", "Alpha")]),
        _snapshot(),
    )

    assert generated.components == ()
    assert generated.report.diagnostics == (inherited,)


def test_manifest_diagnostic_is_inherited_once_when_resolver_already_has_it() -> None:
    inherited = Diagnostic("SCHEMA_PREEXISTING", "tools.json", "existing config finding")
    generated = generate_sources(
        _resolved((inherited,)),
        _manifests([_tool("core.alpha", "Alpha")], diagnostics=(inherited,)),
        _snapshot(),
    )

    assert generated.components == ()
    assert generated.report.diagnostics == (inherited,)


def test_caption_with_physical_newline_is_rejected_before_vba_emission() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests([_tool("core.multiline", "line one\nline two")]),
        _snapshot(),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "GENERATED_STRING_INVALID"
    ]
    assert generated.report.diagnostics[0].details == {
        "line": 1,
        "token": "caption",
    }


@pytest.mark.parametrize(
    "control",
    ["\x00", "\t", "\x1f", "\x7f", "\x80", "\x9f", "\u2028", "\u2029"],
)
def test_generated_strings_reject_raw_controls_and_unicode_line_separators(
    control: str,
) -> None:
    generated = generate_sources(
        _resolved(),
        _manifests([_tool("core.control", f"before{control}after")]),
        _snapshot(),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "GENERATED_STRING_INVALID"
    ]
    assert generated.report.diagnostics[0].path == "tools.json#/tools/0/caption"
    assert generated.report.diagnostics[0].details == {
        "line": 1,
        "token": "caption",
    }


def test_each_generated_member_has_an_independent_hash_oracle() -> None:
    generated = generate_sources(
        _resolved(), _manifests([_tool("core.alpha", '菜单 "一"')]), _snapshot()
    )

    assert {
        component.source_id: component.members[0].raw_sha256
        for component in generated.components
    } == {
        "generated.build-info": "be83a33a2c892544de3385eaae68bed94ca6844173945476325d7278ca454dc7",
        "generated.dispatch": "4c64e922d143fc6f49a7894ebff8d4a7fec6fcdaacc8e0446d2106739d21c29d",
        "generated.menu-catalog": "0ffc78b36bbf989bc907566841e3a89d52ee716f206c2d273ba0fa78d67f1c5b",
    }
    menu = next(
        component.members[0].data
        for component in generated.components
        if component.source_id == "generated.menu-catalog"
    )
    assert 'MM_ToolCaptions = Array("菜单 ""一""")'.encode("cp936") in menu
    assert len({component.members[0].data for component in generated.components}) == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("work_commit", "3" * 39 + "\r"),
        ("work_tree", "4" * 39 + "\n"),
        ("manifest_digest", "f" * 63 + "\n"),
        ("tool_version", "0.1.0\r\nPublic Sub Injected()"),
    ],
)
def test_generator_rejects_snapshot_identity_injection(
    field: str, value: str
) -> None:
    snapshot = _snapshot()
    invalid = replace(snapshot, **{field: value})

    generated = generate_sources(
        _resolved(), _manifests([_tool("core.alpha", "Alpha")]), invalid
    )

    assert generated.components == ()
    assert [finding.code for finding in generated.report.diagnostics] == [
        "GENERATED_SNAPSHOT_INVALID"
    ]
    assert generated.report.diagnostics[0].path == f"snapshot/{field}"


@pytest.mark.parametrize(
    ("collision", "expected_code"),
    [
        (
            _module(
                "generated.menu-catalog",
                vb_name="ExistingId",
                path="existing/ExistingId.bas",
            ),
            "GENERATED_SOURCE_ID_COLLISION",
        ),
        (
            _module(
                "core.path-shadow",
                vb_name="ExistingPath",
                path="GENERATED/mm_menucatalog.BAS",
            ),
            "GENERATED_PATH_SHADOW",
        ),
        (
            _module(
                "core.basename-shadow",
                vb_name="ExistingBasename",
                path="another/MM_MenuCatalog.bas",
            ),
            "GENERATED_OUTPUT_BASENAME_COLLISION",
        ),
        (
            _module(
                "core.name-shadow",
                vb_name="mm_menucatalog",
                path="another/NameShadow.bas",
            ),
            "GENERATED_VB_NAME_COLLISION",
        ),
    ],
)
def test_generated_identity_collisions_with_resolved_sources_fail_closed(
    collision: Component,
    expected_code: str,
) -> None:
    generated = generate_sources(
        _resolved(components=(_module(), collision)),
        _manifests([_tool("core.alpha", "Alpha")]),
        _snapshot(),
    )

    assert generated.components == ()
    assert expected_code in {item.code for item in generated.report.diagnostics}


@pytest.mark.parametrize("descriptor", GENERATED_SOURCE_DESCRIPTORS)
@pytest.mark.parametrize(
    ("collision_kind", "expected_code"),
    [
        ("source-id", "GENERATED_SOURCE_ID_COLLISION"),
        ("path", "GENERATED_PATH_SHADOW"),
        ("basename", "GENERATED_OUTPUT_BASENAME_COLLISION"),
        ("vb-name", "GENERATED_VB_NAME_COLLISION"),
    ],
)
def test_every_generated_identity_is_reserved_against_fixed_sources(
    descriptor: object,
    collision_kind: str,
    expected_code: str,
) -> None:
    source_id = getattr(descriptor, "source_id")
    vb_name = getattr(descriptor, "vb_name")
    path = getattr(descriptor, "path")
    basename = path.rsplit("/", 1)[-1]
    collision = {
        "source-id": _module(
            source_id, vb_name="FixedSourceId", path="fixed/SourceId.bas"
        ),
        "path": _module(
            "core.fixed-path",
            vb_name="FixedPath",
            path=path.swapcase(),
        ),
        "basename": _module(
            "core.fixed-basename",
            vb_name="FixedBasename",
            path=f"fixed/{basename}",
        ),
        "vb-name": _module(
            "core.fixed-vb-name",
            vb_name=vb_name.swapcase(),
            path="fixed/VbName.bas",
        ),
    }[collision_kind]

    generated = generate_sources(
        _resolved(components=(_module(), collision)),
        _manifests([_tool("core.alpha", "Alpha")]),
        _snapshot(),
    )

    assert generated.components == ()
    assert expected_code in {item.code for item in generated.report.diagnostics}


def test_generator_requires_tool_to_bind_to_resolved_public_entrypoint() -> None:
    generated = generate_sources(
        _resolved(
            components=(
                _module(
                    body=(
                        "Private Function Run(ByVal context As C_MMContext) As C_MMResult\r\n"
                        "End Function\r\n"
                    )
                ),
            )
        ),
        _manifests([_tool("core.private", "Private")]),
        _snapshot(),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "TOOL_ENTRYPOINT_BINDING_INVALID"
    ]
    assert generated.report.diagnostics[0].path == (
        "tools.json#/tools/0/entrypoint"
    )


@pytest.mark.parametrize("field", ["module_name", "entrypoint"])
def test_dispatcher_rejects_non_identifier_binding_fragments(field: str) -> None:
    tool = _tool("core.unsafe", "Unsafe")
    tool[field] = "Run: injected"

    generated = generate_sources(
        _resolved(),
        _manifests([tool]),
        _snapshot(),
    )

    assert generated.components == ()
    assert "TOOL_RECORD_INVALID" in {
        finding.code for finding in generated.report.diagnostics
    }


def test_generated_cp936_caption_one_is_accepted_by_policy_view() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests([_tool("core.one", "一")]),
        _snapshot(),
    )

    assert generated.report.ok
    menu = next(
        component
        for component in generated.components
        if component.source_id == "generated.menu-catalog"
    )
    assert menu.members[0].data.decode("cp936").count("一") == 2
