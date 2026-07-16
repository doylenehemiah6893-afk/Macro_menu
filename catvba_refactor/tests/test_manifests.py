import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build.errors import ConfigError
from catvba_refactor.macro_build.manifests import load_and_validate_config


PROJECT_ROOT = Path(__file__).parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SCHEMA_DIR = PROJECT_ROOT / "schemas"


@pytest.fixture
def manifest_dirs(tmp_path: Path) -> tuple[Path, Path]:
    config_dir = tmp_path / "config"
    schema_dir = tmp_path / "schemas"
    shutil.copytree(CONFIG_DIR, config_dir)
    shutil.copytree(SCHEMA_DIR, schema_dir)
    return config_dir, schema_dir


def _read(config_dir: Path, filename: str) -> dict[str, Any]:
    return json.loads((config_dir / filename).read_text(encoding="utf-8"))


def _write(config_dir: Path, filename: str, value: dict[str, Any]) -> None:
    (config_dir / filename).write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _member(path: str, role: str, marker: str = "a") -> dict[str, str]:
    return {
        "path": path,
        "blob_oid": marker * 40,
        "raw_sha256": marker * 64,
        "role": role,
    }


def _standard_component(source_id: str = "core.healthcheck") -> dict[str, Any]:
    return {
        "source_id": source_id,
        "origin": "new",
        "component_type": "standard_module",
        "vb_name": "Healthcheck",
        "package_id": "core",
        "disposition": "candidate",
        "members": [_member("catvba_refactor/vba/new/Healthcheck.bas", "source")],
    }


def _form_override() -> dict[str, Any]:
    return {
        "source_id": "core.menu-form",
        "origin": "override",
        "component_type": "user_form",
        "vb_name": "MenuForm",
        "package_id": "core",
        "disposition": "candidate",
        "members": [
            _member("catvba_refactor/vba/overrides/MenuForm.frm", "frm", "a"),
            _member("catvba_refactor/vba/overrides/MenuForm.frx", "frx", "b"),
        ],
        "base_members": [
            _member("Src/MenuForm.frm", "frm", "c"),
            _member("Src/MenuForm.frx", "frx", "d"),
        ],
    }


def _tool(
    tool_id: str = "core.healthcheck", package_id: str = "core"
) -> dict[str, Any]:
    return {
        "tool_id": tool_id,
        "caption": "Healthcheck",
        "tooltip": "Check the Core runtime",
        "group_id": "core.general",
        "group_caption": "General",
        "package_id": package_id,
        "module_name": "Healthcheck",
        "entrypoint": "Main",
        "document_types": ["Part", "Product", "Drawing"],
        "required_capabilities": [],
        "risk_level": "read-only",
    }


def _codes(config_dir: Path, schema_dir: Path) -> list[str]:
    manifest_set = load_and_validate_config(config_dir, schema_dir)
    return [diagnostic.code for diagnostic in manifest_set.report.diagnostics]


def test_committed_core_manifests_are_first_cycle_only_and_valid() -> None:
    manifest_set = load_and_validate_config(CONFIG_DIR, SCHEMA_DIR)

    assert manifest_set.report.ok
    assert manifest_set.project == {
        "schema_version": 1,
        "upstream_repository": "verysolecd/Macro_menu",
        "upstream_ref": "refs/heads/dev",
        "fork_repository": "doylenehemiah6893-afk/Macro_menu",
        "fork_dev_ref": "refs/heads/dev",
        "work_repository": "doylenehemiah6893-afk/Macro_menu",
        "work_branch": "codex/dev-review-report",
        "governed_paths": [
            ".python-version",
            "pyproject.toml",
            "uv.lock",
            "Src",
            "resources",
            "catvba_refactor",
        ],
    }
    assert [root["origin"] for root in manifest_set.components["source_roots"]] == [
        "upstream",
        "new",
        "override",
    ]
    components = manifest_set.components["components"]
    assert len(components) == 13
    assert {component["package_id"] for component in components} == {"core"}
    assert {component["disposition"] for component in components} == {"candidate"}
    assert sum(component["component_type"] == "user_form" for component in components) == 1
    form = next(
        component for component in components if component["component_type"] == "user_form"
    )
    assert form["source_id"] == "core.menu-form"
    assert [member["role"] for member in form["members"]] == ["frm", "frx"]
    assert [member["role"] for member in form["base_members"]] == ["frm", "frx"]
    assert [package["package_id"] for package in manifest_set.packages["packages"]] == [
        "core",
        "fleet-spa",
        "fleet-fta",
    ]
    assert [
        package["reference_contract"]
        for package in manifest_set.packages["packages"]
    ] == [
        {
            "contract_id": f"references.{package_id}.b28",
            "contract_version": 1,
            "observation_points": None,
            "reference_definitions": None,
            "status": "discovery-required",
            "transitions": None,
        }
        for package_id in ("core", "fleet-spa", "fleet-fta")
    ]
    assert all(
        package["reference_allowlist"] == []
        for package in manifest_set.packages["packages"]
    )
    assert all(
        "verified" not in json.dumps(package).lower()
        and "pass" not in json.dumps(package).lower()
        for package in manifest_set.packages["packages"]
    )
    assert [tool["tool_id"] for tool in manifest_set.tools["tools"]] == [
        "core.healthcheck",
        "core.document-summary",
    ]
    assert all(
        tool["package_id"] == "core"
        and tool["required_capabilities"] == []
        and tool["risk_level"] == "read-only"
        for tool in manifest_set.tools["tools"]
    )
    assert len(manifest_set.digest) == 64


def test_unknown_field_is_rejected_with_stable_code(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    project = _read(config_dir, "project.json")
    project["unexpected"] = True
    _write(config_dir, "project.json", project)

    assert _codes(config_dir, schema_dir) == ["SCHEMA_UNKNOWN_FIELD"]


@pytest.mark.parametrize("kind", ["source", "package", "tool"])
def test_duplicate_exact_ids_are_rejected_before_reference_resolution(
    manifest_dirs: tuple[Path, Path], kind: str
) -> None:
    config_dir, schema_dir = manifest_dirs
    if kind == "source":
        components = _read(config_dir, "components.json")
        component = _standard_component()
        components["components"] = [component, component.copy()]
        _write(config_dir, "components.json", components)
    elif kind == "package":
        packages = _read(config_dir, "packages.json")
        packages["packages"].append(packages["packages"][0].copy())
        _write(config_dir, "packages.json", packages)
    else:
        tools = _read(config_dir, "tools.json")
        tool = _tool()
        tools["tools"] = [tool, tool.copy()]
        _write(config_dir, "tools.json", tools)

    assert "DUPLICATE_ID" in _codes(config_dir, schema_dir)


def test_tool_referencing_missing_package_is_rejected(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    tools = _read(config_dir, "tools.json")
    tools["tools"] = [_tool(package_id="missing-package")]
    _write(config_dir, "tools.json", tools)

    assert _codes(config_dir, schema_dir) == ["UNKNOWN_PACKAGE"]


def test_tool_display_metadata_accepts_chinese_with_ascii_stable_ids(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    tools = _read(config_dir, "tools.json")
    tool = _tool()
    tool.update(
        {
            "caption": "运行状况检查",
            "tooltip": "检查核心运行时状态",
            "group_caption": "常规工具",
        }
    )
    tools["tools"] = [tool]
    _write(config_dir, "tools.json", tools)

    assert _codes(config_dir, schema_dir) == []


@pytest.mark.parametrize("missing_field", ["tooltip", "group_caption"])
def test_tool_requires_non_empty_display_metadata(
    manifest_dirs: tuple[Path, Path], missing_field: str
) -> None:
    config_dir, schema_dir = manifest_dirs
    tools = _read(config_dir, "tools.json")
    tool = _tool()
    tool.pop(missing_field)
    tools["tools"] = [tool]
    _write(config_dir, "tools.json", tools)

    assert _codes(config_dir, schema_dir) == ["SCHEMA_REQUIRED_FIELD"]


@pytest.mark.parametrize("field", ["caption", "tooltip", "group_caption"])
def test_tool_rejects_empty_display_metadata(
    manifest_dirs: tuple[Path, Path], field: str
) -> None:
    config_dir, schema_dir = manifest_dirs
    tools = _read(config_dir, "tools.json")
    tool = _tool()
    tool[field] = ""
    tools["tools"] = [tool]
    _write(config_dir, "tools.json", tools)

    assert _codes(config_dir, schema_dir) == ["SCHEMA_VALIDATION"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_id", "Core.healthcheck"),
        ("tool_id", "核心.健康检查"),
        ("group_id", "Core.General"),
        ("group_id", "核心.常规"),
    ],
)
def test_tool_and_group_ids_remain_ascii_lowercase_stable_ids(
    manifest_dirs: tuple[Path, Path], field: str, value: str
) -> None:
    config_dir, schema_dir = manifest_dirs
    tools = _read(config_dir, "tools.json")
    tool = _tool()
    tool[field] = value
    tools["tools"] = [tool]
    _write(config_dir, "tools.json", tools)

    assert "SCHEMA_VALIDATION" in _codes(config_dir, schema_dir)


def test_nfkc_casefold_duplicate_tool_ids_are_rejected(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    tools = _read(config_dir, "tools.json")
    first = _tool("core.healthcheck")
    second = _tool("ＣＯＲＥ.HealthCheck")
    tools["tools"] = [first, second]
    _write(config_dir, "tools.json", tools)

    assert "CANONICAL_ID_COLLISION" in _codes(config_dir, schema_dir)


def test_one_group_id_cannot_have_conflicting_group_captions(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    tools = _read(config_dir, "tools.json")
    first = _tool("core.healthcheck")
    first["group_caption"] = "常规工具"
    second = _tool("core.document-summary")
    second["group_caption"] = "General"
    tools["tools"] = [first, second]
    _write(config_dir, "tools.json", tools)

    first_report = load_and_validate_config(config_dir, schema_dir).report
    tools["tools"] = [second, first]
    _write(config_dir, "tools.json", tools)
    reversed_report = load_and_validate_config(config_dir, schema_dir).report

    expected = (
        "GROUP_CAPTION_CONFLICT",
        "tools.json#/tools",
        "group core.general has conflicting captions: 'General', '常规工具'",
    )
    assert [
        (item.code, item.path, item.message) for item in first_report.diagnostics
    ] == [expected]
    assert [
        (item.code, item.path, item.message) for item in reversed_report.diagnostics
    ] == [expected]


def test_candidate_component_requires_a_known_package(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    components = _read(config_dir, "components.json")
    component = _standard_component()
    component.pop("package_id")
    components["components"] = [component]
    _write(config_dir, "components.json", components)

    assert "PACKAGE_REQUIRED" in _codes(config_dir, schema_dir)


def test_override_form_requires_complete_selected_and_base_bindings(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    components = _read(config_dir, "components.json")
    override = _form_override()
    override["base_members"] = override["base_members"][:1]
    components["components"] = [override]
    _write(config_dir, "components.json", components)

    assert "FORM_BINDING_INCOMPLETE" in _codes(config_dir, schema_dir)


def test_non_form_member_roles_and_override_base_roles_are_fail_closed(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    components = _read(config_dir, "components.json")
    component = _standard_component()
    component["origin"] = "override"
    component["base_members"] = [_member("Src/Healthcheck.bas", "frm", "c")]
    components["components"] = [component]
    _write(config_dir, "components.json", components)

    codes = _codes(config_dir, schema_dir)
    assert "MEMBER_BINDING_MISMATCH" in codes
    assert "MEMBER_BINDING_INVALID" in codes


def test_base_members_are_forbidden_for_non_overrides(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    components = _read(config_dir, "components.json")
    component = _standard_component()
    component["base_members"] = [_member("Src/Healthcheck.bas", "source", "b")]
    components["components"] = [component]
    _write(config_dir, "components.json", components)

    assert "BASE_MEMBERS_FORBIDDEN" in _codes(config_dir, schema_dir)


@pytest.mark.parametrize("claim", ["pass", "verified"])
def test_manifest_cannot_claim_a_verified_or_passed_license_result(
    manifest_dirs: tuple[Path, Path], claim: str
) -> None:
    config_dir, schema_dir = manifest_dirs
    packages = _read(config_dir, "packages.json")
    packages["packages"][0]["license_result"] = claim
    _write(config_dir, "packages.json", packages)

    assert _codes(config_dir, schema_dir) == ["LICENSE_STATUS_FORBIDDEN"]


def test_duplicate_json_keys_fail_before_validation(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    (config_dir / "tools.json").write_text(
        '{"schema_version":1,"tools":[],"tools":[]}\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError, match=r"^DUPLICATE_JSON_KEY: tools$"):
        load_and_validate_config(config_dir, schema_dir)


def test_content_diagnostics_are_aggregated_and_deterministically_sorted(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    project = _read(config_dir, "project.json")
    project["unknown"] = "field"
    _write(config_dir, "project.json", project)

    packages = _read(config_dir, "packages.json")
    packages["packages"].append(packages["packages"][0].copy())
    _write(config_dir, "packages.json", packages)

    tools = _read(config_dir, "tools.json")
    tools["tools"] = [_tool(package_id="missing-package")]
    _write(config_dir, "tools.json", tools)

    manifest_set = load_and_validate_config(config_dir, schema_dir)

    assert manifest_set.report == manifest_set.report.sorted()
    assert {diagnostic.code for diagnostic in manifest_set.report.diagnostics} == {
        "DUPLICATE_ID",
        "SCHEMA_UNKNOWN_FIELD",
        "UNKNOWN_PACKAGE",
    }


def test_digest_uses_canonical_documents_in_filename_order(
    manifest_dirs: tuple[Path, Path],
) -> None:
    config_dir, schema_dir = manifest_dirs
    original = load_and_validate_config(config_dir, schema_dir)
    project = _read(config_dir, "project.json")
    reversed_project = dict(reversed(tuple(project.items())))
    (config_dir / "project.json").write_text(
        json.dumps(reversed_project, separators=(",", ":")), encoding="utf-8"
    )

    reformatted = load_and_validate_config(config_dir, schema_dir)
    assert reformatted.digest == original.digest

    reversed_project["work_branch"] = "codex/another-work-branch"
    _write(config_dir, "project.json", reversed_project)
    changed = load_and_validate_config(config_dir, schema_dir)
    assert changed.digest != original.digest
