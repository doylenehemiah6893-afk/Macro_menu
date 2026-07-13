from __future__ import annotations

import hashlib
from typing import Any

import pytest

from catvba_refactor.macro_build.generator import generate_sources
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
        "group_id": "core.general",
        "package_id": "core",
        "module_name": "MM_HealthCheck",
        "entrypoint": "Run",
        "document_types": ["none"],
        "required_capabilities": [],
        "risk_level": "read-only",
    }


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
            "packages": packages
            if packages is not None
            else [{"package_id": "core", "classification": "CORE_CANDIDATE"}],
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
    body: str = "Public Sub Run()\r\nEnd Sub\r\n",
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


def test_generates_sorted_cp936_catalog_with_parallel_escaped_captions() -> None:
    manifests = _manifests(
        [
            _tool("core.zulu", '英文 "检查"'),
            _tool("core.alpha", "中文菜单"),
        ]
    )

    generated = generate_sources(_resolved(), manifests)

    assert generated.report.ok
    assert len(generated.components) == 1
    component = generated.components[0]
    assert component.source_id == "generated.tool-catalog"
    assert component.origin is Origin.GENERATED
    assert component.component_type == "standard_module"
    assert component.vb_name == "MM_GeneratedCatalog"
    assert component.package_id == "core"
    assert component.disposition == "candidate"
    assert len(component.members) == 1

    member = component.members[0]
    assert member.path == "generated/MM_GeneratedCatalog.bas"
    assert member.blob_oid is None
    assert member.role == "source"
    assert member.raw_sha256 == hashlib.sha256(member.data).hexdigest()
    assert b"\n" not in member.data.replace(b"\r\n", b"")
    assert b"\r" not in member.data.replace(b"\r\n", b"")

    text = member.data.decode("cp936", errors="strict")
    assert text == (
        'Attribute VB_Name = "MM_GeneratedCatalog"\r\n'
        "Option Explicit\r\n"
        "\r\n"
        "Public Function MM_ToolIds() As Variant\r\n"
        '    MM_ToolIds = Array("core.alpha", "core.zulu")\r\n'
        "End Function\r\n"
        "\r\n"
        "Public Function MM_ToolCaptions() As Variant\r\n"
        '    MM_ToolCaptions = Array("中文菜单", "英文 ""检查""")\r\n'
        "End Function\r\n"
    )
    assert text.encode("cp936", errors="strict") == member.data

    catalog = ResolvedCatalog(
        snapshot=_snapshot(),
        components=(*_resolved().components, *generated.components),
        packages=tuple(manifests.packages["packages"]),
        tools=tuple(manifests.tools["tools"]),
        report=generated.report,
    )
    assert validate_catalog(catalog).ok


def test_generation_is_byte_deterministic_across_manifest_order() -> None:
    tools = [
        _tool("core.zulu", "末项"),
        _tool("core.alpha", "首项"),
    ]

    forward = generate_sources(_resolved(), _manifests(tools))
    reverse = generate_sources(_resolved(), _manifests(list(reversed(tools))))

    assert forward == reverse
    assert forward.components[0].members[0].data == reverse.components[0].members[0].data


def test_empty_tool_manifest_generates_no_component_or_fake_status() -> None:
    generated = generate_sources(_resolved(), _manifests([]))

    assert generated.components == ()
    assert generated.report.ok


def test_unencodable_caption_fails_closed_without_replacement_bytes() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests([_tool("core.emoji", "unsafe 😀 caption")]),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "GENERATED_CP936_UNENCODABLE"
    ]
    finding = generated.report.diagnostics[0]
    assert finding.path == "generated/MM_GeneratedCatalog.bas"
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
    )

    assert generated.components == ()
    assert generated.report.diagnostics == (inherited,)


def test_manifest_diagnostic_is_inherited_once_when_resolver_already_has_it() -> None:
    inherited = Diagnostic("SCHEMA_PREEXISTING", "tools.json", "existing config finding")
    generated = generate_sources(
        _resolved((inherited,)),
        _manifests([_tool("core.alpha", "Alpha")], diagnostics=(inherited,)),
    )

    assert generated.components == ()
    assert generated.report.diagnostics == (inherited,)


def test_caption_with_physical_newline_is_rejected_before_vba_emission() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests([_tool("core.multiline", "line one\nline two")]),
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


def test_generator_has_fixed_independent_byte_and_hash_golden_oracle() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests([_tool("core.alpha", '菜单 "一"')]),
    )

    expected = bytes.fromhex(
        "4174747269627574652056425f4e616d65203d20224d4d5f47656e6572617465"
        "64436174616c6f67220d0a4f7074696f6e204578706c696369740d0a0d0a5075"
        "626c69632046756e6374696f6e204d4d5f546f6f6c4964732829204173205661"
        "7269616e740d0a202020204d4d5f546f6f6c496473203d204172726179282263"
        "6f72652e616c70686122290d0a456e642046756e6374696f6e0d0a0d0a507562"
        "6c69632046756e6374696f6e204d4d5f546f6f6c43617074696f6e7328292041"
        "732056617269616e740d0a202020204d4d5f546f6f6c43617074696f6e73203d"
        "2041727261792822b2cbb5a5202222d2bb222222290d0a456e642046756e6374"
        "696f6e0d0a"
    )
    member = generated.components[0].members[0]
    assert member.data == expected
    assert member.raw_sha256 == (
        "98ad313636424f616e05113d7515a8e4f0ba4aa505b4cfb641e7c321d0e9a5da"
    )


@pytest.mark.parametrize(
    ("collision", "expected_code"),
    [
        (
            _module(
                "generated.tool-catalog",
                vb_name="ExistingId",
                path="existing/ExistingId.bas",
            ),
            "GENERATED_SOURCE_ID_COLLISION",
        ),
        (
            _module(
                "core.path-shadow",
                vb_name="ExistingPath",
                path="GENERATED/mm_generatedcatalog.BAS",
            ),
            "GENERATED_PATH_SHADOW",
        ),
        (
            _module(
                "core.basename-shadow",
                vb_name="ExistingBasename",
                path="another/MM_GeneratedCatalog.bas",
            ),
            "GENERATED_OUTPUT_BASENAME_COLLISION",
        ),
        (
            _module(
                "core.name-shadow",
                vb_name="mm_generatedcatalog",
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
    )

    assert generated.components == ()
    assert expected_code in {item.code for item in generated.report.diagnostics}


def test_generator_requires_tool_to_bind_to_resolved_public_entrypoint() -> None:
    generated = generate_sources(
        _resolved(components=(_module(body="Private Sub Run()\r\nEnd Sub\r\n"),)),
        _manifests([_tool("core.private", "Private")]),
    )

    assert generated.components == ()
    assert [item.code for item in generated.report.diagnostics] == [
        "TOOL_ENTRYPOINT_BINDING_INVALID"
    ]
    assert generated.report.diagnostics[0].path == (
        "tools.json#/tools/0/entrypoint"
    )


def test_generated_cp936_caption_one_is_accepted_by_policy_view() -> None:
    generated = generate_sources(
        _resolved(),
        _manifests([_tool("core.one", "一")]),
    )

    assert generated.report.ok
    assert generated.components[0].members[0].data.decode("cp936").count("一") == 1
