# CATVBA Offline Build Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在无 CATIA 的 A 环境实现可复算、fail-closed 的 CATVBA 源码清点、解析、政策检查、确定性 Build Kit 和回传 CATVBA 只读审计工具链。

**Architecture:** 根 Python 项目提供唯一的 `macro-menu-build` CLI；实现位于 `catvba_refactor/macro_build/`，依次把固定 Git 输入转换为 inventory、resolved sources、generated catalog 和不可变 Kit。正式 `build-kit` 只读取干净 committed Git blobs；worktree 入口只产生诊断，不能生成 candidate receipt。当前仓库配置把未逐项批准的上游 VBA 默认归入 Quarantine，因此本计划完成后工具可在 fixture 上端到端构建，但仓库自身 G1 仍保持 `NOT_RUN`，直到 Core Runtime 计划提供获批组件和工具目录。

**Tech Stack:** Python 3.12、标准库 `argparse/dataclasses/enum/hashlib/json/pathlib/subprocess/zipfile`、`jsonschema`、`olefile`、`oletools`、`pcodedmp`、pytest、uv。

## Global Constraints

- 唯一写分支是 `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`；不得写 fork `main/dev` 或 `verysolecd/Macro_menu`。
- 根 `pyproject.toml`、`uv.lock`、`.python-version` 是唯一 Python project、lock 和版本真源；不得创建 `catvba_refactor/pyproject.toml`。
- A 环境没有 CATIA；所有输出固定写入 `target_build_required=true`、`compile_status="not-run"`、`release_eligible=false`。
- 正式目标资格保持 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`；Core 静态政策不得因三种 profile 都含 SPA/FTA 而放宽。
- `Src/`、`resources/` 只读；实现、配置、schema 和测试只进入 `catvba_refactor/`，治理修改只进入根元数据或 `Docs/`。
- FRM/FRX 是原子 bundle；override 必须同时绑定 path、blob OID、raw SHA-256、role、组件类型和 `VB_Name`。
- 正式 Kit 只接受 clean committed blobs；`inventory/check --worktree` 永远返回 `formal_eligible=false`。
- 所有可预期诊断按 `(code, path, message)` 稳定排序；同输入必须产生相同 canonical JSON、kit ID、目录摘要和 ZIP SHA-256。
- ZIP 使用 `ZIP_STORED`、NFC/POSIX 排序、`1980-01-01 00:00:00`、`create_system=3`、`0644`，不写目录项、extra 或 comment。
- 旧 CATVBA 只能作为只读审计输入，不能作为 seed、staging 成员、回滚包或发布资产。

---

## File Map

| 路径 | 职责 |
|---|---|
| `pyproject.toml`, `uv.lock` | 唯一依赖、CLI entry point、pytest 配置 |
| `.gitignore`, `.gitattributes` | 派生输出隔离与 VBA/FRX 原始字节策略 |
| `main.py` | 兼容入口，只委托正式 CLI |
| `catvba_refactor/macro_build/errors.py` | 稳定退出码和异常边界 |
| `catvba_refactor/macro_build/model.py` | snapshot、组件、catalog、receipt 数据模型 |
| `catvba_refactor/macro_build/canonical.py` | canonical JSON 和 SHA-256 |
| `catvba_refactor/macro_build/git_objects.py` | Git OID、tree/blob 和 worktree 状态的只读访问 |
| `catvba_refactor/macro_build/manifests.py` | JSON Schema 加载和跨 manifest 校验 |
| `catvba_refactor/macro_build/portable_paths.py` | Windows portable path 与碰撞检查 |
| `catvba_refactor/macro_build/encoding.py` | UTF-8/CP936/ASCII/歧义分类 |
| `catvba_refactor/macro_build/inventory.py` | `.bas/.cls/.frm/.frx` 清点、`VB_Name`、Form bundle |
| `catvba_refactor/macro_build/resolver.py` | upstream/new/override/shared/quarantine 解析 |
| `catvba_refactor/macro_build/policy.py` | Core 禁令、Declare、Option Explicit、入口/UI 检查 |
| `catvba_refactor/macro_build/generator.py` | 静态工具目录与 CP936/CRLF 生成模块 |
| `catvba_refactor/macro_build/kit.py` | staging、锁、原子 rename、hash、确定性 ZIP |
| `catvba_refactor/macro_build/audit.py` | CATVBA CFB、源码、Reference、p-code 诊断信号只读审计 |
| `catvba_refactor/macro_build/cli.py` | 五个获批子命令、text/JSON 输出、退出码映射 |
| `catvba_refactor/config/*.json` | 项目、组件、包、工具的受审配置 |
| `catvba_refactor/schemas/*.schema.json` | 拒绝未知字段的 JSON Schema |
| `catvba_refactor/tests/` | 单元、Git fixture、CLI、确定性与审计测试 |

---

### Task 1: Root Python Project and Byte-Preservation Guardrails

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `.gitignore`
- Modify: `.gitattributes`
- Modify: `main.py`
- Create: `catvba_refactor/__init__.py`
- Create: `catvba_refactor/macro_build/__init__.py`
- Create: `catvba_refactor/macro_build/cli.py`
- Test: `catvba_refactor/tests/test_project_layout.py`

**Interfaces:**
- Produces: console script `macro-menu-build`; import root `catvba_refactor.macro_build`.
- Produces: generated paths ignored and VBA-family files not text-normalized by Git.

- [ ] **Step 1: Write the failing project-layout test**

```python
from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).parents[2]


def test_root_project_is_the_only_python_project() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert project["project"]["scripts"]["macro-menu-build"] == (
        "catvba_refactor.macro_build.cli:main"
    )
    assert not (ROOT / "catvba_refactor/pyproject.toml").exists()
    assert not (ROOT / "catvba_refactor/uv.lock").exists()


def test_generated_paths_are_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "catvba_refactor/build/probe"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_vba_attributes_preserve_bytes() -> None:
    result = subprocess.run(
        ["git", "check-attr", "text", "--", "probe.bas", "probe.frx"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "probe.bas: text: unset" in result.stdout
    assert "probe.frx: text: unset" in result.stdout
```

- [ ] **Step 2: Run the test and confirm the current metadata fails**

Run: `uv run pytest catvba_refactor/tests/test_project_layout.py -q`

Expected: FAIL because the script entry point is absent, generated paths are not ignored, and current `.gitattributes` marks VBA text for normalization.

- [ ] **Step 3: Replace root project metadata and add the minimal CLI package**

Use this `pyproject.toml` shape, retaining the existing project name/version:

```toml
[project]
name = "macro-menu"
version = "0.1.0"
description = "Offline CATVBA recovery, audit, and Build Kit tooling"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "jsonschema>=4.23,<5",
    "olefile>=0.47",
    "oletools>=0.60.2",
    "pcodedmp>=1.2.6",
]

[project.scripts]
macro-menu-build = "catvba_refactor.macro_build.cli:main"

[dependency-groups]
dev = ["pytest>=9.1.1"]

[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["catvba_refactor*"]
exclude = ["catvba_refactor.tests*"]

[tool.pytest.ini_options]
testpaths = ["catvba_refactor/tests"]
addopts = "--strict-markers --strict-config"
```

Create both `__init__.py` files with only a module docstring. Create the first `cli.py`:

```python
import argparse


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="macro-menu-build")


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    return 0
```

Replace `main.py` with:

```python
from catvba_refactor.macro_build.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Fix ignore and attribute rules**

Use repository-root slash paths in `.gitignore`:

```gitignore
.context/
.antigravity/
.venv/
__pycache__/
.pytest_cache/
*.py[cod]
/catvba_refactor/build/
/catvba_refactor/dist/
```

Replace unsafe merge/text rules in `.gitattributes`:

```gitattributes
*.bas     -text diff=vb
*.cls     -text diff=vb
*.frm     -text diff=vb
*.frx     binary
*.catvba  binary
```

- [ ] **Step 5: Lock, sync, and prove the root environment is reproducible**

Run: `uv lock && uv sync --frozen && uv run pytest catvba_refactor/tests/test_project_layout.py -q`

Expected: lock updates once; sync succeeds; all three tests PASS.

- [ ] **Step 6: Commit the project boundary**

```bash
git add pyproject.toml uv.lock .gitignore .gitattributes main.py catvba_refactor/__init__.py catvba_refactor/macro_build/__init__.py catvba_refactor/macro_build/cli.py catvba_refactor/tests/test_project_layout.py
git commit -m "build: establish offline build tool package"
```

---

### Task 2: Stable Models, Diagnostics, and Canonical JSON

**Files:**
- Create: `catvba_refactor/macro_build/errors.py`
- Create: `catvba_refactor/macro_build/canonical.py`
- Create: `catvba_refactor/macro_build/model.py`
- Test: `catvba_refactor/tests/test_canonical.py`
- Test: `catvba_refactor/tests/test_model.py`

**Interfaces:**
- Produces: `ExitCode`, typed `BuildKitError` subclasses.
- Produces: `canonical_json_bytes(value) -> bytes`, `sha256_bytes(data) -> str`.
- Produces: immutable `Diagnostic`, `ValidationReport`, `InputSnapshot`, component and catalog records used by every later task.

- [ ] **Step 1: Write failing canonicalization and sorting tests**

```python
from catvba_refactor.macro_build.canonical import canonical_json_bytes, sha256_bytes
from catvba_refactor.macro_build.model import Diagnostic, ValidationReport


def test_canonical_json_is_key_order_independent() -> None:
    left = canonical_json_bytes({"b": 2, "a": "中"})
    right = canonical_json_bytes({"a": "中", "b": 2})
    assert left == right == b'{"a":"\\u4e2d","b":2}\n'
    assert sha256_bytes(left) == sha256_bytes(right)


def test_diagnostics_have_stable_order() -> None:
    report = ValidationReport(
        diagnostics=(
            Diagnostic("Z_CODE", "b.bas", "second"),
            Diagnostic("A_CODE", "a.bas", "first"),
        )
    )
    assert [d.code for d in report.sorted().diagnostics] == ["A_CODE", "Z_CODE"]
    assert not report.ok
```

- [ ] **Step 2: Run tests and confirm imports fail**

Run: `uv run pytest catvba_refactor/tests/test_canonical.py catvba_refactor/tests/test_model.py -q`

Expected: collection FAIL with missing modules.

- [ ] **Step 3: Implement stable error and canonical helpers**

```python
# errors.py
from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    CONFIG = 2
    SOURCE = 3
    INFRASTRUCTURE = 4
    VERIFICATION = 5


class BuildKitError(Exception):
    exit_code = ExitCode.INFRASTRUCTURE


class ConfigError(BuildKitError):
    exit_code = ExitCode.CONFIG


class SourceError(BuildKitError):
    exit_code = ExitCode.SOURCE


class InfrastructureError(BuildKitError):
    exit_code = ExitCode.INFRASTRUCTURE


class VerificationError(BuildKitError):
    exit_code = ExitCode.VERIFICATION
```

```python
# canonical.py
import hashlib
import json
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    text = json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (text + "\n").encode("ascii")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
```

- [ ] **Step 4: Implement immutable cross-task models**

`model.py` must define string enums `SnapshotMode(CANDIDATE, WORKTREE)`, `Origin(UPSTREAM, NEW, OVERRIDE, SHARED, GENERATED, QUARANTINE)`, and frozen dataclasses with these exact public fields:

```python
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any


class SnapshotMode(StrEnum):
    CANDIDATE = "candidate"
    WORKTREE = "worktree"


class Origin(StrEnum):
    UPSTREAM = "upstream"
    NEW = "new"
    OVERRIDE = "override"
    SHARED = "shared"
    GENERATED = "generated"
    QUARANTINE = "quarantine"


@dataclass(frozen=True, order=True)
class Diagnostic:
    code: str
    path: str
    message: str
    details: dict[str, Any] = field(default_factory=dict, compare=False)


@dataclass(frozen=True)
class ValidationReport:
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.diagnostics

    def sorted(self) -> "ValidationReport":
        return replace(self, diagnostics=tuple(sorted(self.diagnostics)))


@dataclass(frozen=True)
class InputSnapshot:
    mode: SnapshotMode
    upstream_repository: str
    upstream_ref: str
    upstream_commit: str
    fork_repository: str
    fork_dev_commit: str
    work_repository: str
    work_branch: str
    work_commit: str
    work_tree: str
    manifest_digest: str
    tool_version: str
    formal_eligible: bool


@dataclass(frozen=True)
class SourceMember:
    path: str
    blob_oid: str | None
    raw_sha256: str
    role: str
    data: bytes = field(repr=False, compare=False)


@dataclass(frozen=True)
class Component:
    source_id: str
    origin: Origin
    component_type: str
    vb_name: str
    members: tuple[SourceMember, ...]
    package_id: str | None
    disposition: str


@dataclass(frozen=True)
class Inventory:
    components: tuple[Component, ...]
    report: ValidationReport
    formal_eligible: bool


@dataclass(frozen=True)
class ResolvedSourceSet:
    components: tuple[Component, ...]
    quarantined: tuple[Component, ...]
    report: ValidationReport


@dataclass(frozen=True)
class GeneratedSourceSet:
    components: tuple[Component, ...]
    report: ValidationReport


@dataclass(frozen=True)
class ResolvedCatalog:
    snapshot: InputSnapshot
    components: tuple[Component, ...]
    packages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]
    report: ValidationReport


@dataclass(frozen=True)
class BuildKitReceipt:
    kit_id: str
    kit_dir: str
    zip_path: str
    zip_sha256: str
    manifest_sha256: str


@dataclass(frozen=True)
class VerificationReport:
    ok: bool
    diagnostics: tuple[Diagnostic, ...]
```

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest catvba_refactor/tests/test_canonical.py catvba_refactor/tests/test_model.py -q`

Expected: PASS.

- [ ] **Step 6: Commit stable interfaces**

```bash
git add catvba_refactor/macro_build/errors.py catvba_refactor/macro_build/canonical.py catvba_refactor/macro_build/model.py catvba_refactor/tests/test_canonical.py catvba_refactor/tests/test_model.py
git commit -m "feat: add deterministic build domain models"
```

---

### Task 3: Read-Only Git Object Access and Snapshot Freeze

**Files:**
- Create: `catvba_refactor/macro_build/git_objects.py`
- Test: `catvba_refactor/tests/conftest.py`
- Test: `catvba_refactor/tests/test_git_objects.py`

**Interfaces:**
- Produces: `GitRepository(root)`, `resolve_commit`, `tree_oid`, `list_tree`, `read_blob`, `status_for`.
- Produces: `freeze_snapshot(repo, project, manifest_digest, tool_version, worktree=False) -> InputSnapshot`.
- Consumes: Task 2 models/errors/canonical helpers.

- [ ] **Step 1: Create a deterministic temporary Git fixture**

`conftest.py` defines `git_repo(tmp_path)`: create `Src/A.bas`, run the following exact argument-array commands,
and return `(repo_path, dev_oid)` without configuring a network remote:

```python
commands = (
    ("git", "init", "--initial-branch=codex/dev-review-report"),
    ("git", "config", "user.name", "Macro Menu Tests"),
    ("git", "config", "user.email", "macro-menu-tests@example.invalid"),
    ("git", "add", "Src/A.bas"),
    ("git", "commit", "-m", "fixture: add A"),
    ("git", "branch", "dev"),
)
for command in commands:
    subprocess.run(command, cwd=repo_path, check=True, capture_output=True)
```

- [ ] **Step 2: Write failing candidate/worktree tests**

```python
PROJECT = {
    "upstream_repository": "verysolecd/Macro_menu",
    "upstream_ref": "dev",
    "fork_repository": "doylenehemiah6893-afk/Macro_menu",
    "fork_dev_ref": "dev",
    "work_repository": "doylenehemiah6893-afk/Macro_menu",
    "work_branch": "codex/dev-review-report",
    "governed_paths": ["Src", "catvba_refactor"],
}


def test_candidate_reads_committed_blob_and_rejects_dirty_governed_path(git_repo):
    repo_path, dev_oid = git_repo
    repo = GitRepository(repo_path)
    assert repo.read_blob(dev_oid, "Src/A.bas").startswith(b'Attribute VB_Name = "A"')
    (repo_path / "Src/A.bas").write_bytes(b"dirty")
    assert repo.status_for(("Src", "catvba_refactor")) == (" M Src/A.bas",)


def test_worktree_snapshot_is_never_formal(git_repo):
    repo_path, _ = git_repo
    snapshot = freeze_snapshot(
        GitRepository(repo_path), PROJECT, "a" * 64, "0.1.0", worktree=True
    )
    assert snapshot.mode.value == "worktree"
    assert snapshot.formal_eligible is False
```

- [ ] **Step 3: Run tests and confirm missing implementation**

Run: `uv run pytest catvba_refactor/tests/test_git_objects.py -q`

Expected: FAIL with missing `GitRepository`.

- [ ] **Step 4: Implement the Git wrapper without shell interpolation**

`GitRepository._run(*args, text=False)` must invoke `git` using a list, set `cwd=self.root`, capture stderr, and raise `InfrastructureError` with the Git subcommand and return code but no environment variables. `list_tree(commit, prefix)` must parse `git ls-tree -rz` NUL records; `read_blob` must call `git show <commit>:<path>`; `status_for` must call `git status --porcelain=v1 -z --untracked-files=all -- <paths>` and return decoded surrogate-escaped records sorted by path.

`freeze_snapshot` resolves HEAD once, `dev` once, records exact OIDs/tree, and applies:

```python
if not worktree and repo.status_for(tuple(project["governed_paths"])):
    raise SourceError("candidate snapshot requires a clean governed tree")
if fork_dev_commit != upstream_commit:
    raise SourceError("fork dev does not match the declared upstream cutoff")
```

The returned worktree snapshot must set `formal_eligible=False`; candidate sets it `True` only after both checks.

- [ ] **Step 5: Run Git tests**

Run: `uv run pytest catvba_refactor/tests/test_git_objects.py -q`

Expected: PASS, including paths containing spaces and non-ASCII characters.

- [ ] **Step 6: Commit snapshot support**

```bash
git add catvba_refactor/macro_build/git_objects.py catvba_refactor/tests/conftest.py catvba_refactor/tests/test_git_objects.py
git commit -m "feat: freeze build inputs from git objects"
```

---

### Task 4: JSON Schemas, Initial Quarantine Configuration, and Manifest Validation

**Files:**
- Create: `catvba_refactor/config/project.json`
- Create: `catvba_refactor/config/components.json`
- Create: `catvba_refactor/config/packages.json`
- Create: `catvba_refactor/config/tools.json`
- Create: `catvba_refactor/schemas/project.schema.json`
- Create: `catvba_refactor/schemas/components.schema.json`
- Create: `catvba_refactor/schemas/packages.schema.json`
- Create: `catvba_refactor/schemas/tools.schema.json`
- Create: `catvba_refactor/macro_build/manifests.py`
- Test: `catvba_refactor/tests/test_manifests.py`

**Interfaces:**
- Produces: frozen `ManifestSet(project, components, packages, tools, digest)`.
- Produces: `load_and_validate_config(config_dir, schema_dir) -> ManifestSet`.
- Consumes: canonical JSON and `ConfigError`.

- [ ] **Step 1: Write schema rejection tests**

Cover unknown keys, duplicate source/package/tool IDs, a tool referencing a missing package, an override without both FRM/FRX bindings, and a manifest attempting to mark a license result `pass`. Each case must assert a stable diagnostic code such as `SCHEMA_UNKNOWN_FIELD`, `DUPLICATE_ID`, `UNKNOWN_PACKAGE`, `FORM_BINDING_INCOMPLETE`, or `LICENSE_STATUS_FORBIDDEN`.

- [ ] **Step 2: Run tests and confirm loader is absent**

Run: `uv run pytest catvba_refactor/tests/test_manifests.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Add strict schemas and real initial configuration**

All four schemas use draft 2020-12, `additionalProperties: false`, explicit `required`, and stable ID patterns `^[a-z][a-z0-9._-]{2,63}$`.

The schema field sets are exact:

| Schema | Required top-level keys | Allowed nested keys |
|---|---|---|
| project | `schema_version`, three repository identities, `upstream_ref`, `fork_dev_ref`, `work_branch`, `governed_paths` | strings plus a unique non-empty path array |
| components | `schema_version`, `source_roots`, `components` | root: `root_id/origin/path/extensions/default_disposition`; component: `source_id/origin/component_type/vb_name/package_id/disposition/members/base_members/encoding_decision` |
| packages | `schema_version`, `packages` | `package_id/classification/additional_deny_tokens/reference_allowlist` |
| tools | `schema_version`, `tools` | `tool_id/caption/group_id/package_id/module_name/entrypoint/document_types/required_capabilities/risk_level` |

`origin` is restricted to `upstream/new/override/shared/quarantine`; `component_type` to
`standard_module/class_module/user_form`; `disposition` to `candidate/quarantine/retired`; package
classification to the eight values in the approved master spec. Member bindings require
`path/blob_oid/raw_sha256/role`, Git OIDs match `^[0-9a-f]{40,64}$`, SHA-256 matches
`^[0-9a-f]{64}$`, and Form entries require exactly one `frm` and one `frx` member on both selected and
base sides.

Initial `project.json`:

```json
{
  "schema_version": 1,
  "upstream_repository": "verysolecd/Macro_menu",
  "upstream_ref": "dev",
  "fork_repository": "doylenehemiah6893-afk/Macro_menu",
  "fork_dev_ref": "dev",
  "work_repository": "doylenehemiah6893-afk/Macro_menu",
  "work_branch": "codex/dev-review-report",
  "governed_paths": [
    ".python-version",
    "pyproject.toml",
    "uv.lock",
    "Src",
    "resources",
    "catvba_refactor"
  ]
}
```

Initial `components.json` deliberately does not claim a candidate component:

```json
{
  "schema_version": 1,
  "source_roots": [
    {
      "root_id": "upstream-src",
      "origin": "upstream",
      "path": "Src",
      "extensions": [".bas", ".cls", ".frm", ".frx"],
      "default_disposition": "quarantine"
    }
  ],
  "components": []
}
```

Initial `packages.json` declares package policies but no verified capability:

```json
{
  "schema_version": 1,
  "packages": [
    {"package_id": "core", "classification": "CORE_CANDIDATE"},
    {"package_id": "fleet-spa", "classification": "FLEET_EXTENSION_SPA"},
    {"package_id": "fleet-fta", "classification": "FLEET_EXTENSION_FTA"}
  ]
}
```

Initial `tools.json`:

```json
{"schema_version":1,"tools":[]}
```

The empty component/tool lists are intentional evidence: upstream sources are discoverable but quarantined, so repository `build-kit` must fail with `NO_BUILDABLE_COMPONENTS` rather than manufacture an empty G1 candidate.

- [ ] **Step 4: Implement load, schema validation, and cross-file checks**

`manifests.py` must read UTF-8 with duplicate-key detection via
`json.loads(text, object_pairs_hook=_unique_object)`, validate each file using
`jsonschema.Draft202012Validator`, canonicalize the four parsed objects in filename order, and compute one digest.
Cross checks use dictionaries keyed by exact IDs; they reject duplicates before resolving references. Return all
expected content errors as one sorted `ValidationReport`, then raise `ConfigError` only at the CLI boundary.

Define the returned type and duplicate-key hook exactly:

```python
@dataclass(frozen=True)
class ManifestSet:
    project: dict[str, Any]
    components: dict[str, Any]
    packages: dict[str, Any]
    tools: dict[str, Any]
    digest: str
    report: ValidationReport


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f"DUPLICATE_JSON_KEY: {key}")
        result[key] = value
    return result
```

- [ ] **Step 5: Run manifest tests**

Run: `uv run pytest catvba_refactor/tests/test_manifests.py -q`

Expected: PASS; the committed initial manifests validate and contain no `verified/pass` license claim.

- [ ] **Step 6: Commit schemas and manifests**

```bash
git add catvba_refactor/config catvba_refactor/schemas catvba_refactor/macro_build/manifests.py catvba_refactor/tests/test_manifests.py
git commit -m "feat: define strict build manifests"
```

---

### Task 5: Portable Paths and Encoding Classification

**Files:**
- Create: `catvba_refactor/macro_build/portable_paths.py`
- Create: `catvba_refactor/macro_build/encoding.py`
- Test: `catvba_refactor/tests/test_portable_paths.py`
- Test: `catvba_refactor/tests/test_encoding.py`

**Interfaces:**
- Produces: `portable_key(path) -> str`, `validate_portable_paths(paths) -> ValidationReport`.
- Produces: `decode_vba(data, declared_encoding=None) -> DecodedVba` with `kind`, `text`, `encoding`.

`encoding.py` defines:

```python
@dataclass(frozen=True)
class DecodedVba:
    kind: str
    text: str
    encoding: str
```

- [ ] **Step 1: Write failing path-policy tests**

Cover `A.bas/a.bas`, NFC versus decomposed Chinese, trailing dot/space, `CON.bas`, `x/../y.bas`, absolute paths, file/directory collisions, and two distinct names that collide after NFKC+casefold. Assert stable codes and sorted paths.

- [ ] **Step 2: Write failing encoding tests**

Use literal byte fixtures for ASCII, UTF-8 BOM, UTF-8-only Chinese, CP936-only Chinese, bytes valid under both decoders with different text, and invalid bytes. Ambiguous input without an explicit decision must return `ENC_AMBIGUOUS`; explicit `utf-8` or `cp936` must choose exactly that strict decoder.

- [ ] **Step 3: Implement path normalization**

`portable_key` converts `\` to `/`, rejects absolute/drive/UNC and `.`/`..`, applies NFC for the stored path and NFKC+casefold for the collision key, strips no characters, and checks Windows reserved base names including `COM1..9` and `LPT1..9`. `validate_portable_paths` also creates prefix keys so `a` and `a/b.bas` report `PATH_FILE_DIR_COLLISION`.

- [ ] **Step 4: Implement strict decoding**

Use this precedence exactly:

```python
if data.startswith(b"\xef\xbb\xbf"):
    return DecodedVba("utf8-bom", data[3:].decode("utf-8"), "utf-8")
if data.isascii():
    return DecodedVba("ascii", data.decode("ascii"), "ascii")
utf8 = _try_decode(data, "utf-8")
cp936 = _try_decode(data, "cp936")
if utf8 is not None and cp936 is None:
    return DecodedVba("utf8", utf8, "utf-8")
if cp936 is not None and utf8 is None:
    return DecodedVba("cp936", cp936, "cp936")
if utf8 is not None and cp936 is not None and utf8 != cp936:
    raise SourceError("ENC_AMBIGUOUS")
raise SourceError("ENC_INVALID")
```

Explicit decisions still decode with `errors="strict"`; no replacement characters are allowed.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest catvba_refactor/tests/test_portable_paths.py catvba_refactor/tests/test_encoding.py -q`

Expected: PASS.

```bash
git add catvba_refactor/macro_build/portable_paths.py catvba_refactor/macro_build/encoding.py catvba_refactor/tests/test_portable_paths.py catvba_refactor/tests/test_encoding.py
git commit -m "feat: enforce portable paths and source encodings"
```

---

### Task 6: VBA Inventory and Atomic Form Bundles

**Files:**
- Create: `catvba_refactor/macro_build/inventory.py`
- Test: `catvba_refactor/tests/test_inventory.py`

**Interfaces:**
- Produces: `scan_inputs(snapshot, manifests, repo) -> Inventory`.
- Consumes: Git blobs for candidate mode; filesystem bytes only for worktree diagnostics.
- Produces: `.frm/.frx` as one `Component.members` tuple ordered `frm`, then `frx`.

- [ ] **Step 1: Write failing inventory tests**

Cover `.bas`, `.cls`, complete Form, missing FRX, orphan FRX, duplicate `VB_Name`, missing or duplicate `Attribute VB_Name`, extension/type mismatch, `OleObjectBlob` name mismatch, candidate bytes differing from dirty worktree, and worktree `formal_eligible=False`.

- [ ] **Step 2: Run tests and confirm failure**

Run: `uv run pytest catvba_refactor/tests/test_inventory.py -q`

Expected: FAIL with missing `scan_inputs`.

- [ ] **Step 3: Implement type and identity parsing**

Use anchored case-insensitive expressions:

```python
VB_NAME = re.compile(r'^Attribute\s+VB_Name\s*=\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*$', re.I | re.M)
OLE_BLOB = re.compile(r'^OleObjectBlob\s*=\s*"([^":]+\.frx)":([0-9A-Fa-f]+)\s*$', re.I | re.M)
```

Standard/class modules require exactly one `VB_Name`. A Form requires exactly one same-stem FRX and an `OleObjectBlob` filename equal under exact NFC spelling, not casefold guessing. Raw SHA-256 is computed before decoding; unchanged members preserve exact data bytes.

- [ ] **Step 4: Implement candidate/worktree readers and stable inventory**

Candidate mode calls `GitRepository.list_tree/read_blob`; worktree mode calls `Path.read_bytes`. Both pass through the same portable path, encoding, identity, and Form checks. Sort components by `(source_id, vb_name)` and members by role. Discovered files absent from explicit component entries inherit their root's `default_disposition`; the committed initial config therefore reports them as Quarantine, not candidate.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest catvba_refactor/tests/test_inventory.py -q`

Expected: PASS.

```bash
git add catvba_refactor/macro_build/inventory.py catvba_refactor/tests/test_inventory.py
git commit -m "feat: inventory vba components and form bundles"
```

---

### Task 7: Fail-Closed Source Resolver

**Files:**
- Create: `catvba_refactor/macro_build/resolver.py`
- Test: `catvba_refactor/tests/test_resolver.py`

**Interfaces:**
- Produces: `resolve_sources(inventory, manifests) -> ResolvedSourceSet`.
- Enforces: exact override binding, one selected side, no shadows, unique output path/`VB_Name` per package.

- [ ] **Step 1: Write failing resolver tests**

Create fixture manifests for upstream, new, shared, quarantine, a valid `.bas` override, and a valid Form override. Add failure cases for base blob drift, raw hash drift, `VB_Name` drift, one-sided Form binding, local/upstream mixed Form members, fuzzy path match, renamed base, duplicate output path, and package-local `VB_Name` collision.

- [ ] **Step 2: Run tests and confirm missing resolver**

Run: `uv run pytest catvba_refactor/tests/test_resolver.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement exact binding checks**

Build dictionaries by exact `source_id` and portable path. For every override compare all declared upstream member fields to inventory before selecting any local member:

```python
def _binding_matches(actual: SourceMember, binding: dict[str, str]) -> bool:
    return (
        actual.path == binding["path"]
        and actual.blob_oid == binding["blob_oid"]
        and actual.raw_sha256 == binding["raw_sha256"]
        and actual.role == binding["role"]
    )
```

Any mismatch emits `OVERRIDE_STALE_BASE` and excludes the whole component. Form selection is atomic: all selected members have the same origin. Renames are represented only as one quarantined/retired old entry plus a distinct new `source_id`.

- [ ] **Step 4: Implement collision and disposition checks**

Reject implicit same-path shadows, duplicate source IDs, package-local output filename/`VB_Name` collisions, orphan manifest entries, and any candidate member with `disposition` other than `candidate`. Preserve Quarantine separately in the resolved receipt; never copy its bytes into package staging.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest catvba_refactor/tests/test_resolver.py -q`

Expected: PASS.

```bash
git add catvba_refactor/macro_build/resolver.py catvba_refactor/tests/test_resolver.py
git commit -m "feat: resolve exact source overlays"
```

---

### Task 8: Static Policy and Generated Catalog

**Files:**
- Create: `catvba_refactor/macro_build/policy.py`
- Create: `catvba_refactor/macro_build/generator.py`
- Test: `catvba_refactor/tests/test_policy.py`
- Test: `catvba_refactor/tests/test_generator.py`

**Interfaces:**
- Produces: `validate_catalog(catalog) -> ValidationReport`.
- Produces: `generate_sources(resolved, manifests) -> GeneratedSourceSet`.
- Produces: generated `MM_GeneratedCatalog.bas` encoded strict CP936 with CRLF when at least one tool exists.

- [ ] **Step 1: Write failing Core policy tests**

Cover missing `Option Explicit`, non-PtrSafe Declare, `VBProject/VBComponents/CodeModule`, `Shell/PowerShell/WSH`, URL/network tokens, license mutation, Office/Excel, `SPAWorkbench/SPATypeLib`, FTA `AnnotationSet`, `Cls_PDM`, `Cls_XLM`, and public standard-module UDT exposed through a class signature. Assert comments and string literals alone do not trigger API-token rules.

- [ ] **Step 2: Write failing generator tests**

Use two tools in reverse manifest order and captions containing quotes and Chinese. Assert stable `tool_id` ordering, doubled VBA quotes, CRLF only, strict CP936 round trip, deterministic bytes, legal generated `VB_Name`, and failure for an emoji not encodable in CP936.

- [ ] **Step 3: Implement conservative lexical policy**

Strip VBA strings and apostrophe comments for token checks while retaining declarations for syntax rules. Core hard-deny tokens are versioned Python constants and cannot be removed by manifest. Package config may add deny tokens. Every finding contains code, component path, line number, and token; reports never claim VBA compilation.

- [ ] **Step 4: Implement the catalog generator**

Generate a standard module with this fixed shape:

```vb
Attribute VB_Name = "MM_GeneratedCatalog"
Option Explicit

Public Function MM_ToolIds() As Variant
    MM_ToolIds = Array("core.document-summary", "core.healthcheck")
End Function
```

The actual array is sorted from `tools.json`; empty tools produce no generated component and later candidate build fails `NO_BUILDABLE_COMPONENTS`. Encode with `text.replace("\n", "\r\n").encode("cp936", errors="strict")`. Run generated output through portable-path, identity, package and Core policy checks before returning it.

- [ ] **Step 5: Run tests and commit**

Run: `uv run pytest catvba_refactor/tests/test_policy.py catvba_refactor/tests/test_generator.py -q`

Expected: PASS.

```bash
git add catvba_refactor/macro_build/policy.py catvba_refactor/macro_build/generator.py catvba_refactor/tests/test_policy.py catvba_refactor/tests/test_generator.py
git commit -m "feat: enforce static package policy"
```

---

### Task 9: Immutable Staging, Hash Receipts, and Deterministic ZIP

**Files:**
- Create: `catvba_refactor/macro_build/kit.py`
- Test: `catvba_refactor/tests/test_kit.py`

**Interfaces:**
- Produces: `assemble_catalog(snapshot, resolved, generated, manifests) -> ResolvedCatalog`.
- Produces: `stage_build_kit(catalog, output_root) -> BuildKitReceipt`.
- Produces: `verify_build_kit(path) -> VerificationReport`.

- [ ] **Step 1: Write failing staging and reproducibility tests**

Test fixture catalog with one `.bas` source and one tool. Cover full required directory layout, quarantine exclusion, sorted import order, hashes, `KIT_COMPLETE` last, no-op on identical existing kit, failure on same ID/different content, stale lock, concurrent lock refusal, staging exception cleanup, path traversal refusal, and two output roots producing byte-identical ZIPs.

- [ ] **Step 2: Run tests and confirm failure**

Run: `uv run pytest catvba_refactor/tests/test_kit.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement catalog and kit identity**

Create canonical `catalog.json` without absolute paths, usernames, timestamps, data bytes, or output roots. Derive:

```python
kit_id = "kit-" + sha256_bytes(canonical_json_bytes(identity_payload))[:20]
```

`identity_payload` includes exact snapshot OIDs/tree, manifest digest, tool version, resolved member paths/blob/raw hashes, generated hashes, package/tool entries and policy result. Reject non-formal snapshot, any diagnostic, or zero buildable components before creating a directory.

- [ ] **Step 4: Implement atomic staging and receipts**

Acquire `<output_root>/.locks/<kit_id>.lock` with `os.open(O_CREAT|O_EXCL|O_WRONLY, 0o600)`. Stage under a same-filesystem temporary sibling. Write package sources, import order, reference JSON, target-test/evidence templates, source-resolution receipt and hashes using canonical JSON. Compute `SHA256SUMS` over every file except itself and `KIT_COMPLETE`, verify it, then write `KIT_COMPLETE` and `os.replace(temp, final)`.

- [ ] **Step 5: Implement deterministic ZIP and verifier**

For every regular file in sorted NFC POSIX order create a `ZipInfo` with:

```python
info.date_time = (1980, 1, 1, 0, 0, 0)
info.compress_type = zipfile.ZIP_STORED
info.create_system = 3
info.external_attr = 0o100644 << 16
info.extra = b""
info.comment = b""
```

Do not add directory entries. Write `<kit_id>.zip.sha256` outside the archive. `verify_build_kit` rejects missing/extra files, traversal/symlink entries, hash mismatch, missing completion marker, wrong immutable status fields, or any CATVBA member.

- [ ] **Step 6: Run reproducibility tests and commit**

Run: `uv run pytest catvba_refactor/tests/test_kit.py -q`

Expected: PASS; the two ZIP SHA-256 values are equal.

```bash
git add catvba_refactor/macro_build/kit.py catvba_refactor/tests/test_kit.py
git commit -m "feat: build deterministic offline kits"
```

---

### Task 10: Read-Only CATVBA Audit

**Files:**
- Create: `catvba_refactor/macro_build/audit.py`
- Test: `catvba_refactor/tests/test_audit.py`
- Modify: `catvba_refactor/macro_build/{model,inventory,resolver,generator,policy,kit}.py`
- Test: corresponding inventory/resolver/generator/policy/kit tests

**Interfaces:**
- Produces: `audit_catvba(path, expected_manifest=None, *, package_id=None) -> AuditReport`.
- Consumes: `olefile`, `oletools.olevba.VBA_Parser`, and isolated `pcodedmp` diagnostic subprocess.
- Never mutates the supplied CATVBA or treats p-code output as compile evidence.

`audit.py` owns these immutable result types:

```python
@dataclass(frozen=True)
class PCodeSignal:
    status: str
    returncode: int | None
    stdout_sha256: str | None
    stderr_sha256: str | None
    diagnostic_only: bool = True


@dataclass(frozen=True)
class AuditReport:
    file_sha256: str
    streams: tuple[dict[str, str | int], ...]
    modules: tuple[dict[str, str], ...]
    references: tuple[dict[str, str], ...]
    pcode: PCodeSignal
    diagnostics: tuple[Diagnostic, ...]
    package_id: str | None = None
```

- [ ] **Step 1: Write failing audit tests**

Use a copied, chmod-read-only `CATIA_V5_SimpleMacroMenu.catvba` for positive CFB/source enumeration. Assert its known SHA-256 `B09195D5BF2787715CF4E8A50C840B0CE256A2408C83038149E1853E27906BA5`. Add truncated CFB, non-CFB, expected-module mismatch, expected-FRX mismatch, orphan Form storage, exact FRX wrapper boundary, staged/extracted directional source normalization, behavioral-attribute mutation, bounded/FIFO/TOCTOU inputs, multi/empty-package selection, cross-package duplicate names, catalog-bound encoding decisions, non-selected-package tamper, and mocked `pcodedmp` timeout/nonzero cases.

- [ ] **Step 2: Run tests and confirm missing audit module**

Run: `uv run pytest catvba_refactor/tests/test_audit.py -q`

Expected: FAIL during import.

- [ ] **Step 3: Implement bounded read-only audit**

Open the input by descriptor-relative no-follow traversal, require a regular file, enforce a 256 MiB cap before and during the read, and identity-check it before and after. Copy it into `TemporaryDirectory`, chmod the copy `0444`, enumerate OLE streams with `olefile.OleFileIO`, and extract VBA source through `VBA_Parser` without calling write APIs. Run p-code diagnostics through a bounded `Popen` reader that continuously drains stdout/stderr, caps each at 1 MiB, and terminates the process group on timeout.

Record timeout/nonzero as diagnostic signals and label all p-code data `diagnostic_only=true`. When an expected Kit manifest is supplied, capture its bounded complete tree through one no-follow root descriptor, run the full in-memory Kit verifier, and only then compare modules/FRX/references/hashes for the selected non-empty package. Auto-select only when exactly one package is non-empty. Preserve the manifest `encoding_decision` in Component/catalog/receipts and use its single strict decoder throughout policy, Kit verify and audit. Normalize staged exports and actual oletools extraction in separate directions: require canonical staged class/Form headers, reject extraction-only attributes in staged source, and strip only structurally valid extraction metadata from actual source while retaining behavioral attributes. If the original CATVBA identity or bytes change, raise `VerificationError`.

- [ ] **Step 4: Run audit tests and commit**

Run: `uv run pytest catvba_refactor/tests/test_audit.py -q`

Expected: PASS; the repository CATVBA remains byte-identical.

```bash
git add catvba_refactor/macro_build/audit.py catvba_refactor/tests/test_audit.py
git commit -m "feat: audit returned catvba read only"
```

---

### Task 11: CLI Orchestration and Stable Exit Codes

**Files:**
- Modify: `catvba_refactor/macro_build/cli.py`
- Test: `catvba_refactor/tests/test_cli.py`

**Interfaces:**
- Produces exactly:
  - `macro-menu-build inventory [--worktree]`
  - `macro-menu-build check [--worktree]`
  - `macro-menu-build build-kit`
  - `macro-menu-build verify-kit <kit>`
  - `macro-menu-build audit-catvba <returned.catvba> --expect <kit-manifest.json> [--package <package-id>]`
- Produces exit codes `0/2/3/4/5` from `ExitCode`.

- [ ] **Step 1: Write failing CLI tests**

Invoke `main(["--format", "json", "inventory", "--worktree"])` directly and invoke
`["uv", "run", "macro-menu-build", "--help"]` through `subprocess`. Cover help, unknown arguments,
text/JSON parity, stable diagnostic sorting, audit package selection/report binding, `--package` without `--expect` usage rejection, worktree reports containing `formal_eligible=false`, worktree rejection
by `build-kit`, initial repository config returning `NO_BUILDABLE_COMPONENTS`/exit 3 without creating `build/`
or `dist/`, Kit verify mismatch/exit 5, and infrastructure exception/exit 4.

- [ ] **Step 2: Run tests and confirm subcommands are absent**

Run: `uv run pytest catvba_refactor/tests/test_cli.py -q`

Expected: FAIL because Task 1 only created the root parser.

- [ ] **Step 3: Implement parser and orchestration**

Add global options `--repo-root`, `--config-dir`, `--schema-dir`, `--output-root`, and
`--format {text,json}`. Defaults are repository-relative; CLI overrides affect locations/reporting only and cannot
override commit OIDs, bindings, package classification or hard security policy. `build-kit` always calls
`freeze_snapshot(repo, manifests.project, manifests.digest, __version__, worktree=False)` and then the complete
scan/resolve/generate/catalog/validate/stage chain.

Map exceptions only at `main`:

```python
try:
    return dispatch(args)
except BuildKitError as exc:
    emit_error(exc, args.format)
    return int(exc.exit_code)
```

Do not catch `KeyboardInterrupt` or `SystemExit`. JSON output uses `canonical_json_bytes`; text renders the same diagnostic fields.

- [ ] **Step 4: Run CLI tests and the complete suite**

Run: `uv run pytest catvba_refactor/tests/test_cli.py -q && uv run pytest -q`

Expected: all tests PASS; current repository `build-kit` fails closed without creating a Kit because all upstream VBA remains Quarantine.

- [ ] **Step 5: Commit CLI orchestration**

```bash
git add catvba_refactor/macro_build/cli.py catvba_refactor/tests/test_cli.py
git commit -m "feat: expose offline build kit cli"
```

---

### Task 12: End-to-End Fixture, Documentation, and A-Environment Receipt

**Files:**
- Create: `catvba_refactor/tests/test_end_to_end.py`
- Modify: `catvba_refactor/README.md`
- Modify: `catvba_refactor/config/README.md`
- Modify: `catvba_refactor/schemas/README.md`
- Modify: `catvba_refactor/macro_build/README.md`
- Modify: `catvba_refactor/tests/README.md`
- Modify: `Docs/STATUS.md`
- Modify: `Docs/PROJECT_STRUCTURE.md`
- Modify: `README.md`

**Interfaces:**
- Proves: fixture candidate builds twice to identical Kit/ZIP; dirty/worktree/current-repo paths fail closed.
- Preserves: `G1 KIT-READY=NOT_RUN`, `compile_status=not-run`, `release_eligible=false` for the repository itself.

- [ ] **Step 1: Write the end-to-end fixture before updating status**

The test creates a temporary Git repo with one safe `Option Explicit` module, one complete Form/FRX bundle, strict manifests, one Core package and one tool. It commits inputs, calls CLI `build-kit` in two distinct output roots, verifies both Kits, and asserts equal kit IDs, catalog bytes, directory hashes and ZIP SHA-256. It then dirties the module and asserts candidate build exit 3 while `check --worktree --format json` succeeds with `formal_eligible=false` and no Kit path.

- [ ] **Step 2: Run end-to-end and full tests**

Run: `uv run pytest catvba_refactor/tests/test_end_to_end.py -q && uv run pytest -q`

Expected: PASS. No test invokes CATIA, changes `Src/`, writes a CATVBA, or contacts a network service.

- [ ] **Step 3: Run immutable-environment and repository fail-closed checks**

Run:

```bash
uv sync --frozen
uv run macro-menu-build check --worktree --format json
uv run macro-menu-build build-kit --format json
git status --short
```

Expected:

- frozen sync succeeds;
- worktree check reports `formal_eligible=false`;
- repository build returns exit 3 with `NO_BUILDABLE_COMPONENTS` and creates no completed Kit;
- only the planned source/config/schema/test/docs files are modified before commit.

- [ ] **Step 4: Update documentation with exact achieved status**

Document all CLI commands, exit codes, manifest locations and JSON output. `Docs/STATUS.md` must say the offline engine and fixture proof exist, while repository G1 remains `NOT_RUN` because no Core components/tools have been approved into manifests. Keep G2-G7 `BLOCKED`, `release_eligible=false`, and explicitly state that pytest/ZIP determinism is not CATIA Compile or license evidence.

- [ ] **Step 5: Run documentation and policy scans**

Run:

```bash
rg -n "release_eligible=true|compile_status[=: ]+pass|CATIA.*已编译通过" README.md Docs catvba_refactor
rg -n "origin/(dev|main)|AB3-only|HD2-only|MD2-only|Optional-(SPA|FTA)" README.md Docs/STATUS.md Docs/PROJECT_STRUCTURE.md Docs/superpowers catvba_refactor
find catvba_refactor -name pyproject.toml -o -name uv.lock -o -name .python-version
```

Expected: the first command only finds negated/checklist text; the second finds no current-authority stale terms; the third prints nothing.

- [ ] **Step 6: Commit the verified A-environment slice**

```bash
git add README.md Docs/STATUS.md Docs/PROJECT_STRUCTURE.md catvba_refactor/README.md catvba_refactor/config/README.md catvba_refactor/schemas/README.md catvba_refactor/macro_build/README.md catvba_refactor/tests/README.md catvba_refactor/tests/test_end_to_end.py
git commit -m "docs: record offline build kit verification"
```

---

## Final Verification Gate

Before reporting implementation complete, invoke `superpowers:verification-before-completion` and run fresh commands:

```bash
uv sync --frozen
uv run pytest -q
uv run macro-menu-build --help
uv run macro-menu-build check --worktree --format json
uv run macro-menu-build build-kit --format json
git diff --check
git status --short
```

Required conclusions:

- dependency lock is reproducible and all offline tests pass;
- current repository still fails closed rather than producing an empty/fake candidate Kit;
- fixture proves deterministic candidate behavior;
- no root/namespace duplicate Python project exists;
- no tracked `build/`, `dist/`, CATVBA, customer data, credential or absolute machine path is introduced;
- no claim exceeds A-environment evidence;
- only `codex/dev-review-report` is committed/pushed.

## Explicitly Deferred to Later Approved Plans

- Core Form override, `MM_MenuCatalog/MM_MenuPresenter/MM_Protocol/C_MMButtonHandler` and the two Runtime MVP tools;
- Product/Part/Drawing audits;
- B28 blank-project import, Compile, save/restart and References capture;
- P-AB3/P-HD2/P-MD2, Fleet-SPA and Fleet-FTA runtime evidence;
- Production installation, cross-CATVBA execution spike, signing, pilot and rollback;
- automated fork `main/dev` synchronization or upstream intake merge execution.

## Self-Review Result

- Spec §2 Python/目录：Task 1；唯一 root project/lock 和 generated ignore 均有测试。
- Spec §3 snapshot：Task 3、Task 11；candidate/worktree、clean tree、fork cutoff 都有失败用例。
- Spec §4 manifest/schema：Task 4；四文件、unknown-field、duplicate/cross-reference、禁止自报 PASS 均覆盖。
- Spec §5 encoding/identity/path/Form：Task 5、Task 6；严格双解码、portable path、`VB_Name`、FRM/FRX 原子性均覆盖。
- Spec §6 resolver/generator/catalog：Task 7、Task 8、Task 9；所有公开函数名与 Task 2 数据类型一致。
- Spec §7 static policy：Task 8；Core hard deny 由代码固定，manifest 只能增加规则。
- Spec §8 CLI：Task 11；五个子命令和 `0/2/3/4/5` 退出码完整。
- Spec §9 immutable Kit/ZIP：Task 9、Task 12；锁、原子 rename、no-op、hash、固定 ZIP 元数据和双构建一致性完整。
- Spec §10 audit：Task 10；原文件前后 hash、只读副本、CFB/VBA/p-code diagnostic-only 和 expected manifest 比较完整。
- Spec §11/§12 tests/acceptance：Task 12 与 Final Verification Gate；当前仓库无获批 Core 输入，所以明确保持 G1 `NOT_RUN`。
- Placeholder scan：未发现禁用占位语或未定义的跨任务公开类型；代码中的 variadic tuple 标注是有效 Python 类型语法。
- Scope check：Core Runtime、B28/Fleet、安装发布和 upstream intake 执行均被列入后续独立计划，没有混入本计划。
