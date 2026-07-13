from __future__ import annotations

import hashlib
from typing import Any

from catvba_refactor.macro_build.generator import generate_sources
from catvba_refactor.macro_build.manifests import ManifestSet
from catvba_refactor.macro_build.model import (
    Diagnostic,
    InputSnapshot,
    Origin,
    ResolvedCatalog,
    ResolvedSourceSet,
    SnapshotMode,
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


def _resolved(
    diagnostics: tuple[Diagnostic, ...] = (),
) -> ResolvedSourceSet:
    return ResolvedSourceSet(
        components=(),
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
        components=generated.components,
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
        "GENERATED_PACKAGE_INVALID"
    ]
    assert generated.report.diagnostics[0].details == {
        "line": 1,
        "token": "core",
    }


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
