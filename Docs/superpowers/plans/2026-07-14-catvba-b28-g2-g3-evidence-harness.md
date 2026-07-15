# CATVBA B28 G2/G3 Evidence Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在无 CATIA 的 A 环境实现可复算的 B28 discovery、G2、Core-only G3-C 会话初始化、证据验证、Reference 审计、Gate 计算、审批记录、确定性封包和唯一 handoff 工具链。

**Architecture:** 保持现有 Build Kit 为不可变输入，在新的 `target_evidence` package 中分离 schema/model、容器快照、session、validator、Gate、approval 和 packer。每条证据命令只使用一次已认证 Kit snapshot，capture 只做结构验证，Gate evaluator 单独计算 `eligible|fail|blocked`，detached approval 后才生成 sealed directory/ZIP。真实 CATIA/VBE 操作仍由 B28 人工 runbook 执行，本计划只生成 discovery handoff，不能预先生成 formal Reference 合同、G2/G3 PASS 或 CATVBA。

**Tech Stack:** Python 3.12、标准库 `argparse/dataclasses/enum/hashlib/json/os/pathlib/subprocess/tempfile/zipfile`、`jsonschema` Draft 2020-12、`olefile`、`oletools`、`pcodedmp`、pytest、uv、现有确定性 Build Kit。

## Global Constraints

- 唯一写分支是 `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`；不得写 fork `main/dev`、上游、tag、Release 或其他分支。
- 本工作区无 CATIA；不得声称或伪造 CATIA/VBE Compile、Reference、许可证、checkout、UI、运行、安装或发布证据。
- 目标固定为 `CATIA V5-6R2018 (R28/B28) / VBA7 / 64-bit`。
- 正式目标资格固定为 `(AB3 OR HD2 OR MD2) AND SPA AND FTA`；单一 profile 的 G2/G3-C 不等于 G4 三个隔离最小 profile。
- 本计划只覆盖 `package_id=core` 的 discovery、G2 和 G3-C；Fleet-SPA/Fleet-FTA、G4-G7 和 Production 安装继续延后。
- discovery 只使用 `profile_id=DISCOVERY` 和 `purpose=discovery` handoff；G2/G3-C 只使用 approved Reference contract 与 `purpose=formal` handoff。
- `target-test-plan/target-test-plan.json` 的 30 个 case、顺序、expected 和 `status=not-run` 永远不可回写；结果只写 Kit 外 `test-results.json`。
- capture validator 只判结构、binding、容器和哈希；业务失败/阻断必须仍可生成 receipt、approval 和 sealed 历史包。
- Gate PASS 需要 `computed_outcome=eligible + approval_status=approved + sealed directory/ZIP 再验证通过`；任何单一可编辑状态字段都不能升级 Gate。
- A 环境输出和所有新 Kit 继续固定 `compile_status=not-run`、`target_build_required=true`、`release_eligible=false`。
- 不通过 COM、SendKeys、PowerShell、WSH 或 GUI 自动化控制 CATIA/VBE；不自动勾 Reference、修改 DSLS/Licensing Repository 或调用 `SetLicense`。
- discovery returned CATVBA 只作 observation，不能复用为 formal G3 制品；现场热改不得成为源码真源。
- evidence 路径只允许 portable ASCII；禁止 symlink、hardlink、路径穿越、Windows 保留名、大小写/NFKC 碰撞、非普通 ZIP entry 和额外文件。
- 所有 JSON 使用 canonical ASCII bytes、拒绝 duplicate key/NaN/Infinity/unknown field；所有诊断按 `(code,path,message,details)` 稳定排序。
- Evidence ZIP 固定 `ZIP_STORED`、1980 UTC 元数据、POSIX `0644`、无目录项/extra/comment；相同显式输入必须 byte-identical。
- 不把当前 ignored temp Kit 或历史 `kit-134ecc68d131cdff743b` 直接签发为新 handoff；实现完成后必须在 clean governed tree 上重新双构建。
- 每个功能/修复任务在实现前使用 `superpowers:test-driven-development`；Task 1 还必须先使用 `superpowers:systematic-debugging`，不得用放宽 timeout 掩盖原因。

---

## File Map

| 路径 | 职责 |
|---|---|
| `catvba_refactor/macro_build/canonical.py` | strict canonical JSON 解码与摘要 |
| `catvba_refactor/macro_build/portable_paths.py` | evidence portable ASCII path 规则 |
| `catvba_refactor/macro_build/errors.py` | `EVIDENCE=6`、`GATE=7` 退出边界 |
| `catvba_refactor/macro_build/model.py` | 一次认证的 `BuildKitInspection` |
| `catvba_refactor/macro_build/kit.py` | Reference companion、work branch identity、Kit snapshot inspection |
| `catvba_refactor/macro_build/reference_contract.py` | GUID/version stable ID、五点合同和 transition 比对 |
| `catvba_refactor/macro_build/handoff.py` | 两次 Build Kit 比对、handoff 创建/验证/撤回继承 |
| `catvba_refactor/macro_build/target_evidence/model.py` | session/Gate/receipt immutable types |
| `catvba_refactor/macro_build/target_evidence/schemas.py` | evidence/envelope schema 加载和稳定诊断 |
| `catvba_refactor/macro_build/target_evidence/container.py` | no-follow directory/ZIP snapshot、payload manifest、确定性发布 |
| `catvba_refactor/macro_build/target_evidence/session.py` | capture skeleton、30-case 结果外置、G2 prerequisite 嵌入 |
| `catvba_refactor/macro_build/target_evidence/validator.py` | capture/sealed 结构、binding、时间、mode 文件矩阵验证 |
| `catvba_refactor/macro_build/target_evidence/gate.py` | discovery/G2/G3-C 纯规则 oracle 与 receipt |
| `catvba_refactor/macro_build/target_evidence/approval.py` | detached observation/Gate approval 规范化 |
| `catvba_refactor/macro_build/target_evidence/packer.py` | SHA 闭包、completion marker、sealed directory/ZIP |
| `catvba_refactor/macro_build/audit.py` | structured Reference contract + 外部 observation 交叉审计 |
| `catvba_refactor/macro_build/cli.py` | handoff 与五个 target evidence 子命令 |
| `catvba_refactor/schemas/target_evidence/*.schema.json` | 九类 evidence 和五类 envelope schema |
| `Docs/runbooks/2026-07-14-catvba-b28-g2-g3-core.md` | B28 discovery/G2/G3-C 人工步骤、停止和脱敏边界 |
| `catvba_refactor/tests/test_target_*.py` | schema/session/container/validator/Gate/approval/packer 测试 |

---

### Task 1: Stabilize Bounded Audit Subprocess Cleanup

**Files:**
- Modify: `catvba_refactor/macro_build/audit.py` (`_run_bounded_process`, `_kill_process_group`)
- Modify: `catvba_refactor/tests/test_audit.py` (detached descendant timeout tests)

**Interfaces:**
- Preserves: `_run_bounded_process(command, *, timeout, maximum) -> _ProcessCapture`.
- Proves: timeout never waits on inherited descendant pipes and tests always clean their spawned child.

- [ ] **Step 1: Reproduce the current failure and record the process state**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_audit.py::test_bounded_process_timeout_is_not_held_open_by_descendant_pipes \
  catvba_refactor/tests/test_audit.py::test_bounded_process_timeout_closes_pipes_held_by_detached_descendant
```

Expected before the fix: the detached-descendant case can fail because the PID handshake is empty before the 0.1 s timeout; capture the exact failing assertion before editing implementation.

- [ ] **Step 2: Make the regression fixture deterministic and cleanup unconditional**

Use an explicit ready/PID handshake before starting the timeout assertion, retain the detached PID in the parent test, and put final termination/reap checks in `finally`. The test must assert bounded wall time, closed reader threads and absence of the child PID; it must not merely increase the timeout.

- [ ] **Step 3: Fix process termination only if the deterministic test exposes an implementation defect**

Keep process-group termination for the direct child, close parent pipe descriptors on timeout, join bounded reader threads, and never block waiting for a detached descendant that retained an inherited descriptor. Preserve stdout/stderr caps and `timed_out=True`.

- [ ] **Step 4: Verify and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q catvba_refactor/tests/test_audit.py -k 'bounded_process'
git diff --check
git add catvba_refactor/macro_build/audit.py catvba_refactor/tests/test_audit.py
git commit -m "fix: stabilize bounded audit cleanup"
```

Expected: all bounded-process tests PASS with no leftover descendant process.

---

### Task 2: Add Canonical Evidence Primitives and Exit Boundaries

**Files:**
- Modify: `catvba_refactor/macro_build/canonical.py`
- Modify: `catvba_refactor/macro_build/portable_paths.py`
- Modify: `catvba_refactor/macro_build/errors.py`
- Modify: `catvba_refactor/tests/test_canonical.py`
- Modify: `catvba_refactor/tests/test_portable_paths.py`
- Modify: `catvba_refactor/tests/test_cli.py`

**Interfaces:**
- Produces: `CanonicalJsonError`, `parse_canonical_json_bytes(data) -> Any`.
- Produces: `validate_portable_ascii_paths(paths) -> ValidationReport`.
- Produces: `ExitCode.EVIDENCE=6`, `ExitCode.GATE=7`, `EvidenceError`, `GateError`.

- [ ] **Step 1: Write failing primitive tests**

Add exact assertions for canonical ASCII round-trip and duplicate-key rejection:

```python
value = {"schema_version": 1, "session_id": "session-001"}
assert parse_canonical_json_bytes(canonical_json_bytes(value)) == value

with pytest.raises(CanonicalJsonError, match="DUPLICATE_JSON_KEY"):
    parse_canonical_json_bytes(b'{"a":1,"a":2}\n')

with pytest.raises(CanonicalJsonError, match="NONCANONICAL_JSON"):
    parse_canonical_json_bytes(b'{"schema_version": 1}\n')
```

Parameterize evidence paths for non-ASCII, backslash, control characters, `<>:"|?*`, traversal, reserved names and NFKC/casefold collisions. Assert existing source-path behavior is unchanged. Assert exit enum integer values stay `0,2,3,4,5,6,7`.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_canonical.py \
  catvba_refactor/tests/test_portable_paths.py \
  catvba_refactor/tests/test_cli.py -k 'exit or canonical or portable'
```

Expected: FAIL because the strict decoder, ASCII path API and two exit codes do not exist.

- [ ] **Step 3: Implement minimal strict boundaries**

`parse_canonical_json_bytes` must decode ASCII, use a duplicate-key hook, reject non-finite constants, require a built-in JSON value, and compare the original bytes with `canonical_json_bytes(parsed)`. `validate_portable_ascii_paths` first applies the existing portable validator, then emits stable `PATH_NOT_ASCII`, `PATH_SEPARATOR_INVALID` and `PATH_INVALID_CHARACTER` diagnostics without silently normalizing the stored name.

Add:

```python
class EvidenceError(BuildKitError):
    exit_code = ExitCode.EVIDENCE


class GateError(BuildKitError):
    exit_code = ExitCode.GATE
```

Normal `fail|blocked` Gate calculations do not raise `GateError`; they write a receipt and the CLI returns 7.

- [ ] **Step 4: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_canonical.py \
  catvba_refactor/tests/test_portable_paths.py \
  catvba_refactor/tests/test_cli.py -k 'exit or canonical or portable'
git diff --check
git add catvba_refactor/macro_build/canonical.py catvba_refactor/macro_build/portable_paths.py catvba_refactor/macro_build/errors.py catvba_refactor/tests/test_canonical.py catvba_refactor/tests/test_portable_paths.py catvba_refactor/tests/test_cli.py
git commit -m "feat: add target evidence primitives"
```

---

### Task 3: Define Target Evidence Models and Strict Schemas

**Files:**
- Create: `catvba_refactor/macro_build/target_evidence/__init__.py`
- Create: `catvba_refactor/macro_build/target_evidence/model.py`
- Create: `catvba_refactor/macro_build/target_evidence/schemas.py`
- Create: `catvba_refactor/schemas/target_evidence/common.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/session.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/environment.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/entitlements.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/references.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/compile-result.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/test-results.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/state-diff.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/artifact-manifest.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/operator-index.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/handoff.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/payload-manifest.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/gate-receipt.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/approval.schema.json`
- Create: `catvba_refactor/schemas/target_evidence/session-complete.schema.json`
- Create: `catvba_refactor/tests/test_target_evidence_schemas.py`
- Modify: `catvba_refactor/schemas/README.md`

**Interfaces:**
- Produces: `EvidencePhase`, `SessionMode`, `GateId`, `ComputedOutcome`, `PayloadMember`, `TargetEvidenceReport`, `TargetSessionReceipt`, `GateEvaluation`, `TargetEvidenceBundleReceipt`.
- Produces: `load_target_evidence_schemas(schema_dir) -> TargetEvidenceSchemaSet` and `validate_target_document(filename, document, schemas) -> ValidationReport`.

- [ ] **Step 1: Write failing model and schema golden tests**

Lock these enum values:

```python
assert tuple(EvidencePhase) == (EvidencePhase.CAPTURE, EvidencePhase.SEALED)
assert [item.value for item in SessionMode] == ["discovery", "g2", "g3-c"]
assert [item.value for item in GateId] == ["DISCOVERY", "G2", "G3-C"]
assert [item.value for item in ComputedOutcome] == ["eligible", "fail", "blocked"]
```

Create one valid canonical document for every schema. Add negative parameterization for missing/extra fields, wrong mode/profile, non-UTC time, bad digest/ID, `release_eligible=true`, discovery Gate approval, artifact/file mismatch, incomplete five-point records, 29/31 target cases, non-null observed fields on `not-run`, approval provenance gaps and self-referential completion fields. Explicitly reject username, customer/machine full name, full user/customer paths, PN, object/model/parameter names and unredacted operator-record status fields.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q catvba_refactor/tests/test_target_evidence_schemas.py
```

Expected: FAIL because the package and schema directory do not exist.

- [ ] **Step 3: Implement frozen result types**

Use the interfaces below without mutable document dictionaries in public reports:

```python
@dataclass(frozen=True, order=True)
class PayloadMember:
    path: str
    sha256: str
    size: int


@dataclass(frozen=True)
class TargetEvidenceReport:
    phase: EvidencePhase
    session_id: str | None
    evidence_payload_digest: str | None
    payload_members: tuple[PayloadMember, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return not self.diagnostics


@dataclass(frozen=True)
class TargetSessionReceipt:
    session_id: str
    session_dir: str
    mode: SessionMode
    kit_id: str
    evidence_payload_digest: str


@dataclass(frozen=True)
class GateEvaluation:
    gate_id: GateId
    computed_outcome: ComputedOutcome
    reason: str
    evidence_payload_digest: str
    receipt_path: str
    receipt_sha256: str
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class TargetEvidenceBundleReceipt:
    session_id: str
    bundle_dir: str
    zip_path: str
    zip_sha256: str
    evidence_payload_digest: str
    bundle_content_digest: str
```

Add `TargetEvidenceSchemaSet(validators: Mapping[str, Draft202012Validator])` in `schemas.py`; published receipt paths are strings and every digest field is lowercase SHA-256.

- [ ] **Step 4: Implement the schema family**

Every document has `schema_version=1`, `additionalProperties=false`, exact `binding` where applicable, and `$defs` from `common.schema.json`. Encode mode-dependent `if/then` rules rather than leaving them to prose: discovery→DISCOVERY, formal modes→one approved profile, G2 no returned artifact, G3 conditional artifact, discovery observation approval only, and approved Reference provenance complete. Schema loader validates every schema with `Draft202012Validator.check_schema` and returns stable JSON-pointer diagnostics.

- [ ] **Step 5: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q catvba_refactor/tests/test_target_evidence_schemas.py
git diff --check
git add catvba_refactor/macro_build/target_evidence catvba_refactor/schemas/target_evidence catvba_refactor/schemas/README.md catvba_refactor/tests/test_target_evidence_schemas.py
git commit -m "feat: define target evidence schemas"
```

---

### Task 4: Add Structured Reference Contracts and Authenticated Kit Inspection

**Files:**
- Create: `catvba_refactor/macro_build/reference_contract.py`
- Create: `catvba_refactor/tests/test_reference_contract.py`
- Modify: `catvba_refactor/schemas/packages.schema.json`
- Modify: `catvba_refactor/config/packages.json`
- Modify: `catvba_refactor/macro_build/manifests.py`
- Modify: `catvba_refactor/macro_build/model.py`
- Modify: `catvba_refactor/macro_build/kit.py`
- Modify: `catvba_refactor/tests/{test_manifests,test_kit,test_end_to_end,test_generator,test_policy,test_resolver}.py`

**Interfaces:**
- Produces: `resolved_reference_id(guid, major, minor) -> str`.
- Produces: `reference_contract_diagnostics(package, *, path)`, `reference_contract_body_digest(contract)`, `reference_companion(package)`, `approved_reference_set(contract, point)`.
- Produces: `BuildKitInspection` and `inspect_build_kit(path) -> BuildKitInspection` from one authenticated byte snapshot.
- Changes: authenticated catalog snapshot now includes stable `work_branch` but still excludes local filesystem/repository labels.

- [ ] **Step 1: Write failing Reference contract tests**

Lock the discovery variant used initially by all three packages:

```json
{
  "contract_id": "references.core.b28",
  "contract_version": 1,
  "observation_points": null,
  "reference_definitions": null,
  "status": "discovery-required",
  "transitions": null
}
```

Approved fixtures must have exactly five point arrays, four adjacent transitions, globally unique definitions, canonical uppercase-braced GUIDs, integer major/minor, stable IDs equal to `ref.<32hex>.<major>.<minor>`, schema-defined path policies and full discovery approval provenance. Reject empty-status substitution, aliases with ambiguous normalization, duplicate definitions, point references to unknown IDs, illegal transition deltas, unresolved definitions, self-referential digest and an `approved` text without observation approval.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_reference_contract.py \
  catvba_refactor/tests/test_manifests.py
```

Expected: FAIL because `reference_contract` is an unknown package field and the semantic module is absent.

- [ ] **Step 3: Implement the pure Reference contract module**

Use arrays with explicit `stable_reference_id`; do not depend on JSON object insertion order. `reference_contract_body_digest` hashes only definitions, observation points, transitions and path policy, excluding approval metadata. `reference_companion` is the only creator for Kit `references/<package>.json` and returns:

```python
{
    "schema_version": 2,
    "package_id": package["package_id"],
    "reference_allowlist": package.get("reference_allowlist", []),
    "reference_contract": package["reference_contract"],
    "contract_body_digest": body_digest_or_none,
    "compile_status": "not-run",
}
```

Call `reference_contract_diagnostics` from `manifests._cross_file_diagnostics`; schema success alone is not sufficient. Tighten `reference_allowlist` semantics to stable Reference IDs that exist in definitions when the contract is approved; an empty list means “no explicit manual additions,” never “the final project has no host-default Reference.”

- [ ] **Step 4: Bind contract and work branch into the Kit identity**

Add `reference_contract` to `kit._PACKAGE_FIELDS`, use `reference_companion()` in both `_layout()` and `_expected_catalog_graph()`, and extend `_catalog_document_errors()` so creator and verifier apply the same strict boundary. Add `work_branch` to `_snapshot_record()` and `_SNAPSHOT_FIELDS`; update the old test that intentionally ignored branch labels so a branch change now changes catalog/Kit identity while repository paths still do not.

- [ ] **Step 5: Add one-shot Kit inspection**

Define:

```python
@dataclass(frozen=True)
class BuildKitInspection:
    files: tuple[tuple[str, bytes], ...]
    kit_id: str | None
    catalog_sha256: str | None
    manifest_sha256: str | None
    manifest_digest: str | None
    upstream_commit: str | None
    fork_dev_commit: str | None
    work_commit: str | None
    work_tree: str | None
    work_branch: str | None
    canonical_zip_sha256: str | None
    report: VerificationReport
```

`inspect_build_kit` captures directory or ZIP bytes once, runs `_verify_file_map` against that snapshot, and derives all fields only from verified bytes. Refactor `verify_build_kit(path)` to return `inspect_build_kit(path).report`; evidence code must never verify then reopen the Kit.

- [ ] **Step 6: Update all manifest fixtures and verify GREEN**

Make every test package explicit: Core and both empty Fleet records start with their own `discovery-required` contract and `reference_allowlist=[]`. Update literal catalog/reference companion expectations and assert directory/ZIP inspection returns the same identity.

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_reference_contract.py \
  catvba_refactor/tests/test_manifests.py \
  catvba_refactor/tests/test_kit.py \
  catvba_refactor/tests/test_end_to_end.py \
  catvba_refactor/tests/test_generator.py \
  catvba_refactor/tests/test_policy.py \
  catvba_refactor/tests/test_resolver.py
git diff --check
git add catvba_refactor/config/packages.json catvba_refactor/schemas/packages.schema.json catvba_refactor/macro_build/reference_contract.py catvba_refactor/macro_build/manifests.py catvba_refactor/macro_build/model.py catvba_refactor/macro_build/kit.py catvba_refactor/tests/test_reference_contract.py catvba_refactor/tests/test_manifests.py catvba_refactor/tests/test_kit.py catvba_refactor/tests/test_end_to_end.py catvba_refactor/tests/test_generator.py catvba_refactor/tests/test_policy.py catvba_refactor/tests/test_resolver.py
git commit -m "feat: bind reference contracts into kits"
```

---

### Task 5: Issue and Verify Unique Target Handoffs

**Files:**
- Create: `catvba_refactor/macro_build/handoff.py`
- Create: `catvba_refactor/tests/test_handoff.py`
- Modify: `catvba_refactor/macro_build/cli.py`
- Modify: `catvba_refactor/tests/test_cli.py`

**Interfaces:**
- Produces: `issue_target_handoff(primary_build_root, comparison_build_root, request, output_root) -> HandoffReceipt`.
- Produces: `validate_handoff(inspection, document, *, effective_at) -> ValidationReport`.
- Produces CLI: `create-target-handoff <primary-build-root> --compare-build-root <root> --purpose discovery|formal [--supersedes-handoff <file>] --revocation-snapshot <file> --prepared-record-id <id> --review-record-id <id> [--created-at <utc>] --expires-at <utc> --output-root <dir>`.

- [ ] **Step 1: Write failing handoff tests**

Build identical Kits into two independent roots. Assert issuance verifies both directories, both ZIPs and both sidecars; compares Kit ID/catalog/manifest/ZIP bytes; emits one canonical handoff outside the Kit; and derives `handoff_id = "handoff-" + sha256(body)[:20]`. Assert required target/status fields remain `CATIA R2018/VBA7 64`, `compile_status=not-run` and `release_eligible=false`.

Negative tests cover zero/two Kit pairs in a root, different Kit bytes, bad sidecar, expiry before the requested session time, withdrawn snapshot, another active handoff of the same purpose, upstream/fork cutoff or branch mismatch, non-Core package, formal purpose with discovery-required contract, discovery purpose with approved contract, formal without `--supersedes-handoff`, and discovery with a supersedes input. Historical sealed evidence validates against its recorded session time rather than becoming invalid when the wall clock later passes handoff expiry.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_handoff.py \
  catvba_refactor/tests/test_cli.py -k 'handoff or help'
```

Expected: FAIL because no handoff producer or command exists.

- [ ] **Step 3: Implement detached issuance**

Use these frozen public request/receipt types:

```python
@dataclass(frozen=True)
class HandoffRequest:
    purpose: str
    created_at: str
    expires_at: str
    revocation_snapshot: bytes
    prepared_record_id: str
    review_record_id: str
    supersedes_handoff: bytes | None = None


@dataclass(frozen=True)
class HandoffReceipt:
    handoff_id: str
    handoff_path: str
    handoff_sha256: str
    kit_id: str
    kit_zip_sha256: str
```

Require exactly one complete Kit directory/ZIP/sidecar triplet per build root and compare both authenticated snapshots before writing. The revocation snapshot schema contains `captured_at`, `source`, `active_handoff_ids` and `withdrawn_handoff_ids`; issuance rejects ambiguity rather than choosing among active IDs. The handoff binds schema version, Kit/catalog/manifest/ZIP/sidecar hashes, upstream/fork cutoff, work commit/tree/branch, manifest digest, target, package, purpose, timestamps, revocation snapshot digest and the four verifier report digests.

The writer stages one file in the destination filesystem and publishes with no-replace atomic semantics; identical existing bytes are a no-op, different bytes under the same ID are an infrastructure failure.

- [ ] **Step 4: Wire only the handoff command**

Add `_create_target_handoff_command(args) -> int` and exact non-abbreviated options. `--output-root` is required after parsing; scalar handoff options already reject duplicates in this task. Do not add the five evidence commands yet.

- [ ] **Step 5: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q catvba_refactor/tests/test_handoff.py catvba_refactor/tests/test_cli.py
git diff --check
git add catvba_refactor/macro_build/handoff.py catvba_refactor/macro_build/cli.py catvba_refactor/tests/test_handoff.py catvba_refactor/tests/test_cli.py
git commit -m "feat: issue deterministic target handoffs"
```

---

### Task 6: Build the Secure Evidence Container Layer

**Files:**
- Create: `catvba_refactor/macro_build/target_evidence/container.py`
- Create: `catvba_refactor/tests/test_target_evidence_container.py`

**Interfaces:**
- Produces: `EvidenceContainerSnapshot`.
- Produces: `read_evidence_container(path, *, phase, nesting_depth=0)`.
- Produces: `canonical_payload_manifest(files) -> tuple[bytes, str, tuple[PayloadMember, ...]]`.
- Produces: `canonical_evidence_zip_bytes(files) -> bytes`, `publish_evidence_artifacts(files, *, bundle_name, output_root) -> tuple[Path, Path, str]`.

- [ ] **Step 1: Write failing directory/ZIP attack tests**

Use the same logical file map in a directory and ZIP and assert equal payload members/digest. Cover symlink, hardlink (`st_nlink != 1`), FIFO/device, ancestor replacement, file identity TOCTOU, absolute/traversal/backslash/non-ASCII/reserved names, case/NFKC/file-directory collisions, duplicate ZIP names, encrypted/data-descriptor/unsupported-compression entries, entry/individual/total size limits, compression ratio, extra/comment, nested ZIP depth greater than one and extra undeclared files.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q catvba_refactor/tests/test_target_evidence_container.py
```

Expected: FAIL during import.

- [ ] **Step 3: Implement immutable container snapshots**

Define:

```python
@dataclass(frozen=True)
class EvidenceContainerSnapshot:
    files: tuple[tuple[str, bytes], ...]
    directories: tuple[str, ...]
    container_sha256: str | None
    diagnostics: tuple[Diagnostic, ...]
```

Use descriptor-relative no-follow traversal for directories, require link count one, bound file count/size before reading and verify identity after. For ZIPs, validate central-directory metadata and total limits before reading entry bytes; do not extract. Keep constants versioned in this module and set nested `depth=1` only for `prerequisites/g2-evidence.zip`.

Payload manifest is canonical JSON over bytewise path-sorted records:

```python
{"schema_version": 1, "members": [{"path": p, "sha256": sha256_bytes(b), "size": len(b)}]}
```

Its SHA-256 is `evidence_payload_digest`. Evidence ZIP metadata exactly matches the Global Constraints.

- [ ] **Step 4: Implement atomic no-replace publication**

Validate the complete output file map in memory, write a same-filesystem temporary directory/ZIP, fsync files and parent, then publish without replacement. Identical existing output is a no-op; same name/different bytes fails and cleans all temporary files.

- [ ] **Step 5: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q catvba_refactor/tests/test_target_evidence_container.py
git diff --check
git add catvba_refactor/macro_build/target_evidence/container.py catvba_refactor/tests/test_target_evidence_container.py
git commit -m "feat: add secure evidence containers"
```

---

### Task 7: Enhance Returned CATVBA Reference Audit

**Files:**
- Modify: `catvba_refactor/macro_build/audit.py`
- Modify: `catvba_refactor/macro_build/cli.py`
- Modify: `catvba_refactor/tests/test_audit.py`
- Modify: `catvba_refactor/tests/test_cli.py`

**Interfaces:**
- Preserves: `audit_catvba(path, expected_manifest=None, *, package_id=None)` for existing callers.
- Adds keyword-only: `expected_kit: BuildKitInspection | None` and `reference_observation: Mapping[str, Any] | None`.
- Adds: `AuditReport.reference_verification: ReferenceVerification` with status, contract/observation digests and matched IDs.

- [ ] **Step 1: Write failing structured Reference tests**

Create approved contract fixtures containing host defaults and MSForms at the five points. Assert post-restart audit compares exact GUID, integer major/minor and approved aliases, detects duplicate same-name/different-GUID and same-GUID/different-version records, and never treats `reference_allowlist=[]` as the expected final set.

Add external observation tests for MISSING, B28/B30, x64/x86, path category/hash and unresolved identities. Assert container-only output is `partial|unavailable`, not fabricated `verified`; external evidence is accepted only when its contract body digest and post-restart observation hash match the same Kit/session.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_audit.py -k 'reference or expected_kit or deterministic'
```

Expected: FAIL because `_Expected.references` is token-only and `AuditReport` lacks structured verification.

- [ ] **Step 3: Implement structured expected references**

Replace the allowlist-derived expectation with the approved `post-restart` set from the authenticated Kit companion. Parse each container LIBID into canonical GUID and integer major/minor; names/descriptions only match explicit aliases. Retain exact-count and one-to-one matching so duplicates cannot collapse.

Define:

```python
@dataclass(frozen=True)
class ReferenceVerification:
    status: str  # verified | partial | unavailable
    contract_body_digest: str | None
    observation_sha256: str | None
    matched_stable_ids: tuple[str, ...]
```

The canonical audit report includes this object. MISSING/path/architecture/release are cross-bound to `references.json`; they are never inferred from CFB bytes.

- [ ] **Step 4: Preserve no-follow and semantic audit behavior**

Consume `BuildKitInspection.files` directly rather than reopening a Kit. Keep existing module/source/FRX semantic hashes, package selection, read-only CATVBA copy, p-code diagnostic-only signal and original-input TOCTOU checks. Reject simultaneous `expected_manifest` and `expected_kit`.

- [ ] **Step 5: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_audit.py \
  catvba_refactor/tests/test_cli.py -k 'audit'
git diff --check
git add catvba_refactor/macro_build/audit.py catvba_refactor/macro_build/cli.py catvba_refactor/tests/test_audit.py catvba_refactor/tests/test_cli.py
git commit -m "feat: audit structured reference contracts"
```

---

### Task 8: Validate Capture and Sealed Evidence Structure

**Files:**
- Create: `catvba_refactor/macro_build/target_evidence/kit_binding.py`
- Create: `catvba_refactor/macro_build/target_evidence/validator.py`
- Create: `catvba_refactor/tests/test_target_evidence_validator.py`

**Interfaces:**
- Produces internal immutable `TargetEvidenceInspection` from one evidence snapshot and one `BuildKitInspection`.
- Produces: `validate_target_evidence(evidence, kit, *, phase, schema_dir, nesting_depth=0) -> TargetEvidenceReport`.
- Produces: `environment_fingerprint(document, contract_body_digest) -> str`.

- [ ] **Step 1: Write failing capture validation tests**

Build canonical discovery, G2 and G3-C file maps by hand. Assert the validator requires the eight root evidence JSON documents plus operator index and handoff, exact shared binding, exact five Reference/Compile points, exact 30 target-result records/case hashes/order, mode/profile/handoff purpose, environment fingerprint, time ordering, record cross-links and conditional artifact/prerequisite files. For observed References, recompute `ref.<32hex>.<major>.<minor>` from GUID/version; discovery may retain a `null` stable ID with hashed unresolved observation ID, while formal sessions become blocked. Preserve duplicate stable IDs as distinct observation records and map them to formal failure rather than silently deduplicating.

The committed schemas define five ordered Reference points and four ordered Compile points. Each Compile point has its own explicit, unique event `record_id`; CATIA/VBE operator record IDs are witnesses and must never be used as aliases for that Compile event ID.

Distinguish structure from outcome: `failed|blocked|not-run` business states remain structurally valid, while missing/extra/unknown/reordered/cross-Kit records, forged expected values, non-null fields on `not-run`, unsafe operator members and invalid hashes are evidence errors.

- [ ] **Step 2: Write failing sealed envelope tests**

Handcraft valid `SHA256SUMS`/`SESSION_COMPLETE` and assert sealed phase additionally requires gate receipt and approval, rejects either in capture, checks the exact hash closure excluding only sums/completion, and validates nested G2 ZIP at depth one. At this stage the validator checks receipt/envelope structure and identity; Task 9 adds semantic Gate recomputation.

- [ ] **Step 3: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q catvba_refactor/tests/test_target_evidence_validator.py
```

Expected: FAIL during import.

- [ ] **Step 4: Implement Kit/handoff binding from authenticated bytes**

Parse catalog, manifest, package Reference companion and target plan only from `BuildKitInspection.files`. Validate the detached handoff against Kit ID, catalog/manifest/ZIP hashes, manifest digest, work commit/tree/branch, package, purpose, expiry/revocation snapshot and contract status. Never reopen Kit paths.

Environment fingerprint is SHA-256 over canonical host ID, VM/snapshot lineage ID, Windows build/patch, CATIA GA/SP/HF, VBA/VBE/VBA7/Win64, install-root category/hash, DSLS connection category, profile ID and contract body digest; timestamps, operator IDs, notes and checkout state are excluded.

- [ ] **Step 5: Implement structural validation and payload digest**

Use this internal handoff type between validator and Gate/session code:

```python
@dataclass(frozen=True)
class TargetEvidenceInspection:
    report: TargetEvidenceReport
    files: tuple[tuple[str, bytes], ...]
    documents: tuple[tuple[str, Any], ...]
    kit: BuildKitInspection
```

Read the container once, parse canonical JSON, apply per-file schemas, compare bindings, validate cross-record references, then compute payload members/digest over capture content excluding current receipt/approval/seal files. `TargetEvidenceReport.ok` says only that this phase is structurally valid. Keep `TargetEvidenceInspection` internal to the package so mutable parsed values never appear in CLI reports.

- [ ] **Step 6: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_target_evidence_validator.py \
  catvba_refactor/tests/test_target_evidence_container.py
git diff --check
git add catvba_refactor/macro_build/target_evidence/kit_binding.py catvba_refactor/macro_build/target_evidence/validator.py catvba_refactor/tests/test_target_evidence_validator.py
git commit -m "feat: validate target evidence structure"
```

---

### Task 9: Evaluate Discovery, G2, and G3-C Gates

**Files:**
- Create: `catvba_refactor/macro_build/target_evidence/gate.py`
- Create: `catvba_refactor/tests/test_target_gate.py`
- Modify: `catvba_refactor/macro_build/target_evidence/validator.py`
- Modify: `catvba_refactor/tests/test_target_evidence_validator.py`

**Interfaces:**
- Produces: `RULE_VERSION = "b28-g2-g3-c-v1"`.
- Produces: `evaluate_gate_rules(inspection, *, gate_id, audit_report) -> GateRuleResult`.
- Produces: `evaluate_target_gate(capture, kit, output_root, *, gate_id, schema_dir) -> GateEvaluation`.
- Extends: sealed validation recomputes the embedded Gate receipt with the supplied Kit.

- [ ] **Step 1: Write the pure rule oracle tests**

Define the pure result once in this task:

```python
@dataclass(frozen=True)
class GateRuleResult:
    computed_outcome: ComputedOutcome
    reason: str
    diagnostics: tuple[Diagnostic, ...]
```

Use table-driven documents with no filesystem I/O. Assert fixed precedence:

```text
invalid structure -> no receipt / evidence exit 6
any explicit failed condition -> fail
otherwise any missing/not-run/unknown/blocked condition -> blocked
otherwise -> eligible
discovery -> blocked/discovery-only regardless of observed facts
```

G2 eligible requires formal handoff, approved contract, complete environment/entitlement, blank Reference match, no pollution, Production untouched and witness records. G3-C eligible additionally requires a fully validated eligible+approved sealed G2 prerequisite with identical Kit/handoff/environment/profile, five matching points, three passed Compile records, post-restart smoke code 0 after Compile, returned artifact and non-blocking audit.

- [ ] **Step 2: Write evaluator/receipt tests**

Assert `DISCOVERY|G2|G3-C` must exactly match session mode. Receipt binds payload digest, Gate/rule version, Kit ZIP/verifier report digests, audit rule/report digests, outcome/reason and stable diagnostics. `eligible` returns CLI-level success; `fail|blocked` still writes an immutable receipt but maps to exit 7. Receipt generation never reads the current clock; if an evaluation UTC field is retained it equals the capture-complete UTC. Repeated explicit inputs therefore produce byte-identical receipt bytes.

- [ ] **Step 3: Add nested G2 prerequisite tests**

For G3-C, recursively validate `prerequisites/g2-evidence.zip` at depth one, recompute its G2 receipt with the same Kit, verify Gate approval and compare formal handoff, profile and environment fingerprint. Reject nested discovery, fail/blocked/pending/rejected G2, another Kit, deeper ZIP, altered receipt or stale completion hash.

- [ ] **Step 4: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q catvba_refactor/tests/test_target_gate.py
```

Expected: FAIL because Gate evaluator and rule result types do not exist.

- [ ] **Step 5: Implement the pure rules then the I/O wrapper**

Keep business rules in `evaluate_gate_rules`; the wrapper only obtains authenticated capture/Kit/audit snapshots, writes one canonical detached receipt atomically and returns `GateEvaluation`. For G3-C take `returned-catvba/core.catvba` bytes from `TargetEvidenceInspection.files`, write that authenticated snapshot to a private read-only temporary file, call `audit_catvba(temporary_returned, expected_kit=kit_inspection, package_id="core", reference_observation=references_document)`, compare the audit file digest with the artifact manifest, and hash the complete canonical audit report. Never reopen the mutable capture path after validation.

- [ ] **Step 6: Extend sealed validator to recompute Gate semantics**

During sealed validation, recompute the receipt in memory without writing and require byte equality with `gate-receipt.json`. This closes the gap where a structurally valid receipt could lie about outcome or audit.

- [ ] **Step 7: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_target_gate.py \
  catvba_refactor/tests/test_target_evidence_validator.py \
  catvba_refactor/tests/test_audit.py -k 'reference or expected_kit or bounded_process'
git diff --check
git add catvba_refactor/macro_build/target_evidence/gate.py catvba_refactor/macro_build/target_evidence/validator.py catvba_refactor/tests/test_target_gate.py catvba_refactor/tests/test_target_evidence_validator.py
git commit -m "feat: evaluate target evidence gates"
```

---

### Task 10: Initialize Deterministic Target Sessions

**Files:**
- Create: `catvba_refactor/macro_build/target_evidence/session.py`
- Create: `catvba_refactor/tests/test_target_session.py`
- Modify: `catvba_refactor/schemas/target_evidence/session.schema.json`
- Modify: `catvba_refactor/schemas/target_evidence/environment.schema.json`
- Modify: `catvba_refactor/schemas/target_evidence/entitlements.schema.json`
- Modify: `catvba_refactor/macro_build/target_evidence/validator.py`
- Modify: `catvba_refactor/macro_build/target_evidence/gate.py`
- Modify: `catvba_refactor/macro_build/target_evidence/container.py`
- Modify: `catvba_refactor/tests/test_target_evidence_schemas.py`
- Modify: `catvba_refactor/tests/test_target_evidence_validator.py`
- Modify: `catvba_refactor/tests/test_target_gate.py`

**Interfaces:**
- Produces: `init_target_session(kit, handoff, output_root, *, mode, package_id, profile_id, schema_dir, prerequisite_evidence=None, session_id=None, created_at=None) -> TargetSessionReceipt`.

- [x] **Step 1: Write failing skeleton tests**

For fixed `session_id` and UTC, assert two output roots receive byte-identical discovery/G2 skeletons. Every skeleton has canonical `session/environment/entitlements/references/compile-result/test-results/state-diff/artifact-manifest/operator-records/index`, an exact handoff copy, no current receipt/approval/seal files, `capture_status=in-progress`, `ended_at=null`, an empty current operator index and all mutable observation fields set to safe `not-run/unknown/null` values. Detached handoff witness IDs are never synthesized as current records.

Derive `test-results.json` from the authenticated target plan: exactly 30 records in canonical order, each with `case_definition_sha256 = sha256(canonical_json_bytes(case))`, copied expected values and external result fields `not-run/null`. Never copy a mutable PASS into the Kit.

- [x] **Step 2: Test mode/profile/file matrices**

Discovery accepts only discovery handoff + `DISCOVERY`; G2 accepts only formal handoff + one formal profile and has `artifact_status=not-produced`; G3-C requires the same formal profile and a fully validated sealed G2 ZIP, copies it canonically to `prerequisites/g2-evidence.zip`, and permits conditional returned artifact. Reject unknown package, Fleet/empty package, mismatched purpose/contract, invalid prerequisite and default/random fields when explicit determinism was requested.

- [x] **Step 3: Verify RED**

```bash
UV_NO_SYNC=1 \
UV_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
UV_CACHE_DIR=/tmp/uv-cache \
.venv/bin/python -m pytest -q catvba_refactor/tests/test_target_session.py
```

Expected: FAIL during import.

- [x] **Step 4: Implement fail-before-write initialization**

Inspect Kit, validate handoff and optional G2 prerequisite completely before creating output. Default ID is a cryptographically random `session-<lowerhex>` and default UTC is current UTC; explicit values are required for deterministic tests. Build all bytes in memory, validate the in-progress capture skeleton through Task 8, then publish the new directory atomically without modifying Kit/handoff/prerequisite. CAPTURE accepts truthful drafts, while Gate receipt generation and SEALED validation require `complete`. G3 inheritance eligibility binds only the sealed G2 fingerprint projection and host/VM/snapshot identity; anonymous container IDs may remain prerequisite context, while current security, pollution, account and operator facts restart unobserved. Reject any G3 `started_at` earlier than the prerequisite `sealed_at`.

Enforce the 4 MiB handoff limit before reading payload bytes. For a directory prerequisite, reject canonical no-follow path or directory-identity overlap where `output_root` is inside the prerequisite or the final session directory would contain it; the prerequisite tree must remain byte- and identity-unchanged on failure.

- [x] **Step 5: Verify GREEN and commit**

```bash
UV_NO_SYNC=1 \
UV_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
UV_CACHE_DIR=/tmp/uv-cache \
.venv/bin/python -m pytest -q \
  catvba_refactor/tests/test_target_session.py \
  catvba_refactor/tests/test_target_evidence_schemas.py \
  catvba_refactor/tests/test_target_evidence_validator.py \
  catvba_refactor/tests/test_target_gate.py
git diff --check
git add Docs/superpowers/specs/2026-07-14-catvba-b28-g2-g3-evidence-harness-design.md \
  Docs/superpowers/plans/2026-07-14-catvba-b28-g2-g3-evidence-harness.md \
  catvba_refactor/macro_build/target_evidence/session.py \
  catvba_refactor/macro_build/target_evidence/validator.py \
  catvba_refactor/macro_build/target_evidence/gate.py \
  catvba_refactor/macro_build/target_evidence/container.py \
  catvba_refactor/schemas/target_evidence/session.schema.json \
  catvba_refactor/schemas/target_evidence/environment.schema.json \
  catvba_refactor/schemas/target_evidence/entitlements.schema.json \
  catvba_refactor/tests/test_target_session.py \
  catvba_refactor/tests/test_target_evidence_schemas.py \
  catvba_refactor/tests/test_target_evidence_validator.py \
  catvba_refactor/tests/test_target_gate.py
git commit -m "feat: initialize target evidence sessions"
```

---

### Task 11: Record Approval and Seal Deterministic Evidence Bundles

**Files:**
- Create: `catvba_refactor/macro_build/target_evidence/approval.py`
- Create: `catvba_refactor/macro_build/target_evidence/packer.py`
- Create: `catvba_refactor/tests/test_target_approval.py`
- Create: `catvba_refactor/tests/test_target_evidence_packer.py`
- Modify: `catvba_refactor/macro_build/target_evidence/container.py`
- Modify: `catvba_refactor/macro_build/target_evidence/session.py`
- Modify: `catvba_refactor/macro_build/target_evidence/validator.py`
- Modify: `catvba_refactor/tests/test_target_evidence_container.py`
- Modify: `catvba_refactor/tests/test_target_evidence_validator.py`
- Modify: `catvba_refactor/tests/test_target_gate.py`

**Interfaces:**
- Produces: `record_target_approval(capture, kit, gate_receipt, output_root, *, scope, status, reviewer_role, review_record_id, approved_at, schema_dir) -> Path`.
- Produces: `pack_target_evidence(capture, kit, gate_receipt, approval, output_root, *, schema_dir) -> TargetEvidenceBundleReceipt`.
- Completes: final sealed directory/ZIP validation and deterministic SHA/completion closure.

- [x] **Step 1: Write failing detached approval tests**

Assert approval binds exact payload digest, gate receipt SHA-256, scope, status, reviewer role/record ID and UTC. Discovery permits only `scope=observation`; G2/G3-C use `scope=gate`. Recording an approved `fail|blocked` decision is allowed and means “approved record of this outcome,” not PASS. The normalization API accepts only final `approved|rejected`; schema-only `pending` remains historical compatibility and cannot be packed. The detached review ID must be fresh relative to capture, handoff and Reference approval provenance. Reject payload/receipt drift, unknown scope/status, self-review record reuse and current capture mutation.

- [x] **Step 2: Write failing pack/seal tests**

Assert packer accepts structurally valid eligible/fail/blocked captures, but only after receipt and approval validate. It copies the capture, adds receipt/approval, builds ASCII LF `SHA256SUMS` over every regular file except sums/completion, and writes canonical `SESSION_COMPLETE` binding session ID, payload digest, bundle content digest, sums hash, receipt hash, approval hash and `sealed_at=approval UTC`.

Two independent output roots with identical explicit inputs must have equal directory files, ZIP bytes and ZIP SHA-256. Negative tests cover seal input mutation, output collision, sums self-reference, extra file, bad completion, current-clock injection, symlink/hardlink, partial write cleanup and sealed ZIP/directory parity.

- [x] **Step 3: Verify RED**

```bash
UV_NO_SYNC=1 \
UV_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
UV_CACHE_DIR=/tmp/uv-cache \
.venv/bin/python -m pytest -q \
  catvba_refactor/tests/test_target_approval.py \
  catvba_refactor/tests/test_target_evidence_packer.py
```

Expected: FAIL during import.

- [x] **Step 4: Implement approval normalization**

Revalidate capture and Gate receipt from authenticated bytes immediately before writing. `record_target_approval` never chooses scope/status or fabricates a reviewer; it only canonicalizes the explicit independent review record.

- [x] **Step 5: Implement packer and final validator**

Validate all inputs before output, build the sealed file map in memory, generate deterministic sums/completion/ZIP, publish staged directory/ZIP siblings with no-replace semantics, then call the full sealed validator on both with the same Kit. If either final validation fails, roll back only this invocation's inode identities and do not return a completed bundle.

- [x] **Step 6: Verify GREEN and commit**

```bash
UV_NO_SYNC=1 \
UV_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
UV_CACHE_DIR=/tmp/uv-cache \
.venv/bin/python -m pytest -q \
  catvba_refactor/tests/test_target_approval.py \
  catvba_refactor/tests/test_target_evidence_packer.py \
  catvba_refactor/tests/test_target_evidence_validator.py \
  catvba_refactor/tests/test_target_gate.py
git diff --check
git add Docs/superpowers/specs/2026-07-14-catvba-b28-g2-g3-evidence-harness-design.md \
  Docs/superpowers/plans/2026-07-14-catvba-b28-g2-g3-evidence-harness.md \
  catvba_refactor/macro_build/target_evidence/approval.py \
  catvba_refactor/macro_build/target_evidence/packer.py \
  catvba_refactor/macro_build/target_evidence/container.py \
  catvba_refactor/macro_build/target_evidence/session.py \
  catvba_refactor/macro_build/target_evidence/validator.py \
  catvba_refactor/tests/test_target_approval.py \
  catvba_refactor/tests/test_target_evidence_packer.py \
  catvba_refactor/tests/test_target_evidence_container.py \
  catvba_refactor/tests/test_target_evidence_validator.py \
  catvba_refactor/tests/test_target_gate.py
git commit -m "feat: approve and seal target evidence"
```

---

### Task 12: Expose the Complete Evidence CLI and End-to-End Workflow

**Files:**
- Modify: `catvba_refactor/macro_build/cli.py`
- Modify: `catvba_refactor/macro_build/target_evidence/kit_binding.py`
- Modify: `catvba_refactor/tests/test_cli.py`
- Modify: `catvba_refactor/tests/test_end_to_end.py`

**Interfaces:**
- Produces exactly: `init-target-session`, `validate-target-evidence`, `evaluate-target-gate`, `record-target-approval`, `pack-target-evidence` in addition to `create-target-handoff`.
- Preserves existing inventory/check/build/verify/audit CLI behavior.

- [x] **Step 1: Write failing parser and dispatch tests**

Assert `--help` lists all eleven commands. Test every new command with global options both before and after the subcommand; reject abbreviations, duplicate `--kit/--gate/--status/--phase/--output-root`, missing required output root, unknown profile/package and phase/mode/Gate mismatches. Extend `_reject_duplicate_global_options` into `_reject_duplicate_options` for every scalar option.

- [x] **Step 2: Write failing exit/output tests**

Lock exit behavior:

| Condition | Exit/output |
|---|---|
| argparse/schema configuration | 2, usage/stderr |
| I/O/lock/atomic publish | 4, canonical error/stderr |
| Kit/CATVBA verification | 5, canonical error/stderr |
| evidence structure/hash/binding | 6, report/stdout |
| legal `fail|blocked` Gate | 7, receipt written/report stdout |
| eligible, rejected approval recorded, or fail/blocked bundle sealed | 0 |

Discovery evaluator must return 7 with a `blocked/discovery-only` receipt; packer can subsequently seal it with an approved observation record and return 0.

- [x] **Step 3: Verify RED**

```bash
UV_NO_SYNC=1 \
UV_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
UV_CACHE_DIR=/tmp/uv-cache \
.venv/bin/python -m pytest -q catvba_refactor/tests/test_cli.py
```

Expected: FAIL because only handoff and legacy commands are wired.

- [x] **Step 4: Implement command handlers**

Add and dispatch the exact handlers `_init_target_session_command`, `_validate_target_evidence_command`,
`_evaluate_target_gate_command`, `_record_target_approval_command`, and `_pack_target_evidence_command`; each takes
one `argparse.Namespace` and returns an integer exit code.

Each handler delegates to one domain API and renders the same canonical record in text/JSON. It must not implement a second validator, reopen Kit bytes or update `Docs/STATUS.md`.

- [x] **Step 5: Add one complete synthetic end-to-end test**

First build a discovery-required fixture twice and prove `handoff → init → blocked receipt → observation approval → seal → directory/ZIP validate` is byte-identical across two explicit output roots. Then create an approved-contract fixture whose provenance binds that synthetic discovery bundle, build it twice, issue a formal handoff that explicitly supersedes the discovery handoff, initialize G2, fill a structurally valid eligible G2 capture with synthetic non-CATIA evidence, evaluate, record approval and seal. Finally initialize G3-C with the sealed G2 prerequisite and prove a deliberately blocked G3 capture still seals. Label every fixture fact synthetic and never promote repository target status.

- [x] **Step 6: Verify GREEN and commit**

```bash
UV_NO_SYNC=1 \
UV_PYTHON=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
UV_CACHE_DIR=/tmp/uv-cache \
.venv/bin/python -m pytest -q \
  catvba_refactor/tests/test_cli.py \
  catvba_refactor/tests/test_end_to_end.py
git diff --check
git add Docs/superpowers/specs/2026-07-14-catvba-b28-g2-g3-evidence-harness-design.md \
  Docs/superpowers/plans/2026-07-14-catvba-b28-g2-g3-evidence-harness.md \
  catvba_refactor/macro_build/cli.py \
  catvba_refactor/macro_build/target_evidence/kit_binding.py \
  catvba_refactor/tests/test_cli.py \
  catvba_refactor/tests/test_end_to_end.py
git commit -m "feat: expose target evidence workflow"
```

---

### Task 13: Add the B28 Operator Runbook and Correct Status Drift

**Files:**
- Create: `Docs/runbooks/2026-07-14-catvba-b28-g2-g3-core.md`
- Modify: `Docs/README.md`
- Modify: `Docs/STATUS.md`
- Modify: `Docs/PROJECT_STRUCTURE.md`
- Modify: `Docs/发版.md`
- Modify: `catvba_refactor/README.md`
- Modify: `catvba_refactor/macro_build/README.md`
- Modify: `catvba_refactor/schemas/README.md`
- Modify: `catvba_refactor/tests/README.md`

**Interfaces:**
- Produces: one sequential human runbook for discovery, formal G2 and G3-C.
- Preserves: G2-G7 `BLOCKED`, all target cases `not-run`, `release_eligible=false` until authentic B28 sealed evidence exists.

- [ ] **Step 1: Write the runbook from the approved command contracts**

The runbook must contain these executable phases in order:

1. Verify one active handoff, Kit ZIP/sidecar/hash, expiry/revocation and VM snapshot.
2. Initialize discovery capture; record environment/entitlements without license mutation.
3. Create disposable blank CATVBA; record blank Reference.
4. Import strictly by `import-order/core.txt`; at the `.frm` point pair the adjacent `.frx`, then capture post-form/post-all/save/restart Reference sets.
5. Do not run target cases or claim PASS in discovery; return/seal observation, restore snapshot and never reuse the CATVBA.
6. In A environment approve only clean five-point facts; edit/commit the structured contract and rebuild a different formal Kit/handoff.
7. Formal G2 records blank environment only; formal G3-C imports from blank, Compile/save/full-close/restart/Compile, then runs only `context.core.healthcheck.none` post-restart.
8. On pollution, compile/import/hash/customer-data failure: stop, isolate output, record failed/blocked state, seal history and restore snapshot.

Include exact CLI syntax, optional `certutil` SHA commands plus a manual UI recording alternative, operator record naming/redaction, no PowerShell/WSH dependency, no customer names/paths/PN/model data and no Production macro library registration.

- [ ] **Step 2: Correct documentation drift without inventing new evidence**

Update `macro_build/README.md` to remove the obsolete “zero candidates/no Kit” statement and list all commands/exits. Update `Docs/发版.md` so existing historical G0/G1 are A-environment PASS while G2+ stay blocked. Update `Docs/STATUS.md` next action to “implement harness → new discovery Kit/handoff → B28 discovery”; add approved spec/plan/runbook links but do not prefill the future Kit/handoff hashes.

- [ ] **Step 3: Run policy/document scans**

```bash
rg -n "release_eligible=true|compile_status[=: ]+(pass|passed)|G[2-7].*PASS|CATIA.*已编译通过" README.md Docs catvba_refactor
rg -n "零 candidate|NO_BUILDABLE_COMPONENTS|G0 INPUT-FROZEN.*NOT_RUN|G1 KIT-READY.*NOT_RUN" Docs catvba_refactor/macro_build/README.md
find catvba_refactor -name pyproject.toml -o -name uv.lock -o -name .python-version
git diff --check
```

Expected: only negated/checklist/schema enum text is found in the first scan; no stale current-authority status in the second; no nested Python project files.

- [ ] **Step 4: Verify docs-linked tests and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q \
  catvba_refactor/tests/test_project_layout.py \
  catvba_refactor/tests/test_target_evidence_schemas.py \
  catvba_refactor/tests/test_cli.py
git add Docs/runbooks/2026-07-14-catvba-b28-g2-g3-core.md Docs/README.md Docs/STATUS.md Docs/PROJECT_STRUCTURE.md Docs/发版.md catvba_refactor/README.md catvba_refactor/macro_build/README.md catvba_refactor/schemas/README.md catvba_refactor/tests/README.md
git commit -m "docs: add b28 evidence operator runbook"
```

---

### Task 14: Verify the Clean Implementation and Issue the Discovery Handoff

**Files:**
- Modify after evidence: `Docs/STATUS.md`
- Modify after evidence: `catvba_refactor/tests/README.md`
- No tracked Kit, evidence ZIP, CATVBA, revocation snapshot or customer/operator artifact.

**Interfaces:**
- Proves: complete offline suite, deterministic new G0/G1 Kit, two-directory/two-ZIP verification, unique discovery handoff and deterministic session skeleton.
- Does not prove: B28 discovery, formal Reference approval, G2/G3-C, Compile or runtime.

- [ ] **Step 1: Invoke completion verification and establish a clean evidence commit**

Use `superpowers:verification-before-completion`. Confirm `git status --short` is empty before building; record exact `HEAD^{commit}` and `HEAD^{tree}` as the evidence identity.

- [ ] **Step 2: Run the complete offline gate**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build inventory --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json
```

Expected: frozen sync succeeds; every pytest passes; candidate inventory/check are `ok=true`, `formal_eligible=true`, zero diagnostics. No command launches CATIA or contacts the network.

- [ ] **Step 3: Build and verify two independent Kits**

Use two new `mktemp -d` roots outside the repository, run `build-kit` once in each, then run `verify-kit` on both directories and both ZIPs. Compare exact Kit ID, `catalog.json` bytes/SHA, `kit-manifest.json` bytes/SHA, manifest digest, ZIP SHA and ZIP bytes with `cmp --silent`; any difference blocks handoff issuance.

- [ ] **Step 4: Create the canonical A-environment handoff inputs**

Create a canonical `revocation-snapshot.json` outside the repo with schema version 1, captured UTC, source `a-env-active-handoff-ledger`, `active_handoff_ids=[]` for the first discovery issuance, and the currently withdrawn handoff IDs. Record preparation and independent review IDs as `record.a-env-preparation.<work-commit-prefix>` and `record.a-env-review.<work-commit-prefix>`; the review must actually inspect both verifier reports and comparison results before its ID is used.

- [ ] **Step 5: Issue and verify the discovery handoff**

Run `create-target-handoff` over the two build roots with `purpose=discovery`, explicit created/expiry UTC, the revocation snapshot and the two real record IDs. Validate that exactly one handoff is produced, it binds the new discovery-required Kit and it contains no `supersedes` field. Do not create a formal handoff in this task.

- [ ] **Step 6: Prove deterministic discovery session initialization**

Run `init-target-session` twice with the same Kit, handoff, `mode=discovery`, `package=core`, `profile=DISCOVERY`, explicit session ID and created UTC into two output roots. Compare all skeleton bytes and run capture validation on both; do not fill target observations or evaluate a Gate.

- [ ] **Step 7: Record exact achieved evidence in a docs-only commit**

Update `Docs/STATUS.md` and `catvba_refactor/tests/README.md` with the exact clean evidence commit/tree, pytest count, inventory/check counts, Kit/catalog/manifest/ZIP identities, four verifier results, handoff ID/hash/purpose/expiry and deterministic skeleton result. State explicitly:

```text
G0/G1 = PASS for the bound discovery Kit
G2-G7 = BLOCKED
target cases = not-run
compile_status = not-run
release_eligible = false
```

The status commit occurs after the evidence commit and must say it binds the earlier clean evidence commit rather than pretending the docs-only commit was built.

- [ ] **Step 8: Final fresh verification and commit**

```bash
git diff --check
git status --short
git add Docs/STATUS.md catvba_refactor/tests/README.md
git commit -m "docs: record b28 evidence harness verification"
git show --check --stat --oneline HEAD
git status --short --branch
```

Expected: only the two evidence/status documents are in the final commit; the branch is clean and ahead of its remote. Do not push until the user explicitly requests it.

---

## Final Verification Gate

Before reporting implementation complete, invoke `superpowers:verification-before-completion` and freshly run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build --help
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build inventory --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json
git diff --check
git status --short --branch
```

Required conclusions:

- All offline tests pass, including bounded subprocess cleanup, structured Reference, attack containers, Gate oracle, failed/blocked sealing and synthetic end-to-end flows.
- New discovery Kit is built twice byte-identically and passes two-directory/two-ZIP verification.
- One discovery handoff exists and no formal handoff, target PASS, returned CATVBA or release asset is fabricated.
- No tracked `dist/`, target evidence, CATVBA, customer data, credential, absolute machine path or second Python project is introduced.
- Current target truth remains G2-G7 `BLOCKED`, all 30 target cases `not-run`, `compile_status=not-run`, `release_eligible=false`.
- Only `codex/dev-review-report` contains commits; no remote is pushed by this plan without a new explicit user request.

## Explicitly Deferred

- Real B28 discovery execution and its five-point Reference observations.
- User approval/commit of an `approved` Core Reference contract and the resulting formal G0/G1 Kit/handoff.
- Formal G2 and Core-only G3-C target sessions and returned CATVBA.
- G4-C P-AB3/P-HD2/P-MD2 full matrix, P-ALL/P-PROD supplements.
- Fleet-SPA/Fleet-FTA sources, contracts, G5 round-trip and failure isolation.
- MISSING Reference fault injection, signing, ACL, installation, pilot, rollback, tag and Release.

## Self-Review Result

- Spec §1-3 scope/Gate separation: Tasks 3, 8-12; discovery, G2 and package-scoped G3-C are separate and target plan remains immutable.
- Spec §4 handoff: Tasks 4-5 and 14; work branch enters authenticated identity, two independent builds are compared, discovery/formal purposes and withdrawal inheritance are enforced.
- Spec §5-7 evidence layout/schema: Tasks 2-3, 6, 8, 10-11; mode file matrix, nine evidence documents, envelopes, cross-links and SHA closure are covered.
- Spec §8 Reference contract/audit: Tasks 4 and 7; allowlist is not final set, five points/transitions and container/external evidence boundary are explicit.
- Spec §9 CLI: Tasks 5 and 12; handoff producer plus all five approved evidence commands, duplicate options and exits `0/2/3/4/5/6/7` are fixed.
- Spec §10 Gate rules: Task 9; invalid/fail/blocked/eligible precedence, G2 prerequisite and audit report digest are independently tested.
- Spec §11 runbook: Task 13; exact import order, Form/FRX, save/restart, smoke, stop/recovery and redaction are present.
- Spec §12 tests: Tasks 1-12 and Final Gate; current detached-child regression, attacks, deterministic outputs and full suite are included.
- Spec §13-16 governance/acceptance: Tasks 13-14; stale docs are corrected before new Kit, evidence binds the clean pre-status commit, and no target status is advanced.
- Scope check: the plan is one sequential subsystem; Reference/Kit/handoff are prerequisites for session/validator/Gate rather than independent deliverables. Fleet/G4+/release remain separate future specs/plans.
- 占位扫描：没有遗留禁用占位语、泛化测试步骤或未定义的公开接口；执行期身份均由 clean evidence commit 的明确命令推导。
- Type consistency: `BuildKitInspection`, evidence enums/receipts, `ReferenceVerification`, `TargetEvidenceReport`, Gate/approval/packer signatures are introduced once and consumed with the same names in later tasks.
