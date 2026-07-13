# CATVBA Core Runtime MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the A-environment source, deterministic generation, manifest bindings, and offline G0/G1 evidence for the first Core Runtime containing only `core.healthcheck` and `core.document-summary`.

**Architecture:** Extend the existing offline pipeline from one generated catalog module to three authenticated generated modules, then add a fixed source-first Core framework and one complete Form override. Commit fixed source bytes before writing manifest blob/hash bindings, then build and verify a deterministic Core Kit. CATIA Compile, References, runtime behavior, licenses, and delivery remain B28 work.

**Tech Stack:** Python 3.11, pytest, jsonschema Draft 2020-12, Git object IDs, CP936/CRLF VBA7 source, CATIA V5-6R2018 target contracts, existing `macro-menu-build` CLI.

## Global Constraints

- Work only on `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`; never write or push remote `main/dev`, upstream, tags, Releases, or another branch.
- This workspace has no CATIA. Do not claim VBA Compile, CATIA API/UI behavior, References, DSLS checkout, license validation, installation, rollback, or release success.
- Target host remains CATIA V5-6R2018 (R28/B28), VBA7, 64-bit.
- Target eligibility is `(AB3 OR HD2 OR MD2) AND SPA AND FTA`; Core targets the `(AB3 OR HD2 OR MD2)` capability intersection and must not load, reference, probe, or require SPA/FTA at startup.
- SPA and FTA remain physically isolated Fleet extensions even though the target fleet has both entitlements.
- First-cycle tools are exactly `core.healthcheck` and `core.document-summary`; Product/Part/Drawing audits are deferred.
- Core source must not depend on `KCL`, `Cls_DynaWD`, `Cls_PDM`, `Cls_XLM`, `Cls_VbaMdlMgr`, `Cls_allBTNEVT`, `cls_MnUI`, `A00_Menu`, VBIDE/APC, Office, network, Shell, WSH, PowerShell, SPA, FTA, or license mutation.
- Core must not read its own source and must not use `SystemService.ExecuteScript` for self-calls.
- Protocol version is exactly `MM/1`; request/response values are limited to Empty, Boolean, Long, Double, String, and nested Variant arrays.
- Protocol limits are exact: maximum nesting depth 8, maximum string length 4096, maximum array items 256, maximum total nodes 2048, maximum UI display lines 500.
- Error codes are exactly `0 OK`, `10 CANCELLED`, `20 NOT_APPLICABLE`, `30 CAPABILITY_UNAVAILABLE`, `40 VALIDATION_FAILED`, `50 STATE_CHANGED`, `60 TOOL_FAILED`, `70 INTERNAL_ERROR`, `80 LIMIT_REACHED`, `90 UNKNOWN_COMMAND`.
- Runtime states are exactly `core.status=READY|BLOCKED`, `spa.status/fta.status=NOT_PROBED|READY|UNAVAILABLE|BROKEN`, and `fleet.status=READY|DEGRADED|BLOCKED`.
- Generated and fixed VBA uses strict CP936 bytes and CRLF. Every source has exactly one matching `Attribute VB_Name` and `Option Explicit`.
- Form override is atomic: `Cat_Macro_Menu_View.frm` and `.frx` must be selected, bound, staged, and verified together.
- Control names use `canonical_id=lower(stable tool_id)`, non-`[a-z0-9_]` replaced by `_`, `btn_ + Left(slug,26) + _ + SHA256_UTF8(canonical_id)[0:8]`; page names use the same `pg_` rule. Names start with a letter, contain only `[A-Za-z0-9_]`, are at most 40 characters, and are unique.
- Caption, tooltip, group caption, and stable IDs are independent; handlers store canonical tool IDs and never infer commands from control names.
- Production logs contain only UTC, build/work/manifest identifiers, request/tool IDs, result code, elapsed time, counts, and generic document type. No username, full path, document/object name, PN, parameter value, or model content.
- `On Error Resume Next` is allowed only in tiny `MM_TryGet` wrappers; each wrapper must read and clear `Err` immediately. Logging uses a normal error handler and remains disabled until B28 chooses a sink. All entry points use one cleanup path.
- Fixed VBA source must be committed before manifest blob OID/SHA-256 bindings are written. Any later byte change requires rebinding in a new commit.
- A-environment target cases remain `status=not-run`, `compile_status=not-run`, and `release_eligible=false`.

---

### Task 1: Freeze runtime contracts and UI metadata

**Files:**
- Create: `catvba_refactor/macro_build/runtime_contract.py`
- Create: `catvba_refactor/tests/test_runtime_contract.py`
- Modify: `catvba_refactor/schemas/tools.schema.json`
- Modify: `catvba_refactor/macro_build/manifests.py`
- Modify: `catvba_refactor/tests/test_manifests.py`

**Interfaces:**
- Produces: `PROTOCOL_VERSION`, protocol/UI limit constants, `ERROR_CODES`, state tuples, `canonical_runtime_id(value)`, `control_name(tool_id)`, and `page_name(group_id)`.
- Produces: required `tooltip` and `group_caption` fields on each tool; every identical `group_id` must have one identical `group_caption`.

- [ ] **Step 1: Write failing contract and manifest tests**

Tests must assert these exact values and golden names:

```python
assert PROTOCOL_VERSION == "MM/1"
assert MAX_DEPTH == 8
assert MAX_STRING_LENGTH == 4096
assert MAX_ARRAY_ITEMS == 256
assert MAX_TOTAL_NODES == 2048
assert MAX_DISPLAY_LINES == 500
assert ERROR_CODES == {0: "OK", 10: "CANCELLED", 20: "NOT_APPLICABLE", 30: "CAPABILITY_UNAVAILABLE", 40: "VALIDATION_FAILED", 50: "STATE_CHANGED", 60: "TOOL_FAILED", 70: "INTERNAL_ERROR", 80: "LIMIT_REACHED", 90: "UNKNOWN_COMMAND"}
assert control_name("core.healthcheck").startswith("btn_core_healthcheck_")
assert page_name("core.general").startswith("pg_core_general_")
```

Add parameterized golden coverage for Chinese captions/tooltips/group captions paired with ASCII stable IDs, long IDs, punctuation, case, manifest ordering, and two IDs whose 26-character slugs collide but hashes differ. Reject empty IDs, Chinese or other schema-invalid stable IDs, NFKC/casefold duplicate canonical IDs, illegal output names, and conflicting captions for one group.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_runtime_contract.py catvba_refactor/tests/test_manifests.py -q
```

Expected: FAIL because the module and new required fields/semantic checks do not exist.

- [ ] **Step 3: Implement the minimal Python contract**

Use SHA-256 of UTF-8 canonical IDs and lowercase hex. `canonical_runtime_id` must apply Unicode NFKC then `.casefold()` for collision comparison while the naming formula uses the approved lowercase stable ID; reject values not representable by the stable-ID schema rather than transliterating Chinese into executable IDs.

Add `tooltip` and `group_caption` as required non-empty strings in `tools.schema.json`. In `manifests.py`, emit a deterministic diagnostic when one `group_id` has multiple captions; do not add a fifth manifest.

- [ ] **Step 4: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_runtime_contract.py catvba_refactor/tests/test_manifests.py -q
git diff --check
git add catvba_refactor/macro_build/runtime_contract.py catvba_refactor/schemas/tools.schema.json catvba_refactor/macro_build/manifests.py catvba_refactor/tests/test_runtime_contract.py catvba_refactor/tests/test_manifests.py
git commit -m "feat: define core runtime contracts"
```

---

### Task 2: Generate catalog, dispatcher, and build identity modules

**Files:**
- Modify: `catvba_refactor/macro_build/generator.py`
- Modify: `catvba_refactor/macro_build/model.py`
- Modify: `catvba_refactor/macro_build/kit.py`
- Modify: `catvba_refactor/tests/test_generator.py`
- Modify: `catvba_refactor/tests/test_kit.py`
- Modify: `catvba_refactor/tests/test_end_to_end.py`

**Interfaces:**
- Changes: `generate_sources(resolved, manifests, snapshot) -> GeneratedSourceSet`.
- Produces exactly:
  - `generated.menu-catalog` / `MM_MenuCatalog` / `generated/MM_MenuCatalog.bas`
  - `generated.dispatch` / `MM_Dispatch` / `generated/MM_Dispatch.bas`
  - `generated.build-info` / `MM_BuildInfo` / `generated/MM_BuildInfo.bas`

- [ ] **Step 1: Write failing three-output tests**

Assert exact component identities, sorted CP936/CRLF bytes, independent SHA-256 values, stable output under manifest reorder, and rejection of any fixed component/path/VB_Name collision. `MM_MenuCatalog` must expose parallel arrays for tool IDs, captions, tooltips, group IDs, group captions, control names, and page names. `MM_Dispatch` must contain one `Select Case commandId`, one direct call per approved tool, and code 90 for unknown IDs. `MM_BuildInfo` must contain `MM/1`, manifest digest, work commit, work tree, and tool version, but no final `kit_id`.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_generator.py catvba_refactor/tests/test_kit.py catvba_refactor/tests/test_end_to_end.py -q
```

Expected: FAIL because only `MM_GeneratedCatalog` exists and `generate_sources` lacks `snapshot`.

- [ ] **Step 3: Implement minimal deterministic generation**

Replace the single generated constants with an immutable descriptor tuple. Generate each module separately, encode strict CP936/CRLF, authenticate each `Component/SourceMember`, run portable path and policy validation over all three, and return them sorted by source ID. Generated dispatcher calls only the manifest-bound module/entrypoint pairs; it must not emit `ExecuteScript`, `CallByName`, paths, or user-provided code fragments.

Update Kit preflight and verifier to require the exact three generated identities and regenerate all three from the embedded catalog/snapshot. Reject missing, additional, renamed, reordered, demoted, or byte-modified generated components.

- [ ] **Step 4: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_generator.py catvba_refactor/tests/test_kit.py catvba_refactor/tests/test_end_to_end.py -q
git diff --check
git add catvba_refactor/macro_build/generator.py catvba_refactor/macro_build/model.py catvba_refactor/macro_build/kit.py catvba_refactor/tests/test_generator.py catvba_refactor/tests/test_kit.py catvba_refactor/tests/test_end_to_end.py
git commit -m "feat: generate core runtime modules"
```

---

### Task 3: Add the fixed Core protocol and lifecycle framework

**Files:**
- Create: `catvba_refactor/vba/new/MM_Entry.bas`
- Create: `catvba_refactor/vba/new/MM_MenuPresenter.bas`
- Create: `catvba_refactor/vba/new/MM_Protocol.bas`
- Create: `catvba_refactor/vba/new/MM_Error.bas`
- Create: `catvba_refactor/vba/new/MM_Log.bas`
- Create: `catvba_refactor/vba/new/MM_TryGet.bas`
- Create: `catvba_refactor/vba/new/C_MMButtonHandler.cls`
- Create: `catvba_refactor/vba/new/C_MMContext.cls`
- Create: `catvba_refactor/vba/new/C_MMResult.cls`
- Create: `catvba_refactor/vba/new/C_MMStateGuard.cls`
- Create: `catvba_refactor/tests/test_core_runtime_sources.py`
- Modify: `catvba_refactor/tests/test_policy.py`

**Interfaces:**
- `MM_Entry.CATMain()` starts only the presenter.
- Generated `MM_Dispatch.Core_Invoke(ByVal request As Variant) As Variant` is the sole protocol entry.
- `MM_Protocol` validates `["MM/1", requestId, commandId, clientVersion, options]` and builds `["MM/1", requestId, status, code, displayMessage, data, meta]`.
- `C_MMResult` stores status/code/message/data/meta internally; only `MM_Protocol` converts it to a Variant response.

- [ ] **Step 1: Write failing static contract tests**

Tests read exact source bytes and require one matching `VB_Name`, `Option Explicit`, approved public signatures, one cleanup label per entry, and the fixed protocol/limit/error values. Reject forbidden tokens case-insensitively, public COM-returning functions, Dictionary/custom object values in response construction, arbitrary module/procedure/path dispatch, and `On Error Resume Next` outside `MM_TryGet`.

The tests must assert the complete fixed file set and that none are yet in `components.json`.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_core_runtime_sources.py catvba_refactor/tests/test_policy.py -q
```

Expected: FAIL because fixed Core sources do not exist.

- [ ] **Step 3: Implement the minimal source framework**

Use late-bound CATIA `Object` references in `C_MMContext`; no cross-call COM cache or global `As New`. `C_MMStateGuard` records only active document/window identity, Selection count, and properties actually changed by this invocation. Preserve the original error; append restore diagnostics without replacing it. `MM_Log` accepts only the approved scalar fields and swallows only its own write failure; leave its production sink disabled until B28 chooses a path/ACL policy.

`MM_Protocol` recursively validates exact Variant types and all five limits. Key/value arrays must be sorted, unique, and shaped as two-element arrays. Never return class instances, COM objects, Collection, Dictionary, Error Variant, module names, procedure names, or paths. `MM_Log` uses `On Error GoTo` rather than `On Error Resume Next`; its production sink stays disabled in this slice.

- [ ] **Step 4: Verify GREEN and commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_core_runtime_sources.py catvba_refactor/tests/test_policy.py -q
git diff --check
git add catvba_refactor/vba/new catvba_refactor/tests/test_core_runtime_sources.py catvba_refactor/tests/test_policy.py
git commit -m "feat: add core runtime framework sources"
```

---

### Task 4: Add healthcheck and document-summary tools

**Files:**
- Create: `catvba_refactor/vba/new/MM_HealthCheck.bas`
- Create: `catvba_refactor/vba/new/MM_DocumentSummary.bas`
- Modify: `catvba_refactor/tests/test_core_runtime_sources.py`
- Modify: `catvba_refactor/tests/test_policy.py`

**Interfaces:**
- `MM_HealthCheck.RunHealthCheck(ByVal context As C_MMContext) As C_MMResult`.
- `MM_DocumentSummary.RunDocumentSummary(ByVal context As C_MMContext) As C_MMResult`.

- [ ] **Step 1: Write failing tool behavior-contract tests**

Require HealthCheck to report protocol/build identifiers, VBA7/Win64 compile-conditional labels, CATIA release availability, generic document type, and `core.status=READY`; reject Reference enumeration, license/profile claims, SPA/FTA probes, path/user/model data, and state mutation.

Require DocumentSummary to return code 20 with no active document and code 0 otherwise; allow only generic document type, saved/read-only availability, and bounded counts. Reject `Update`, `Save`, `Open`, `Selection.Clear`, document/path/object names, and measurement/KWA/EKL APIs.

- [ ] **Step 2: Verify RED, implement minimal tools, verify GREEN**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_core_runtime_sources.py catvba_refactor/tests/test_policy.py -q
```

Expected before implementation: FAIL for missing tools. Implement only the two functions through `MM_TryGet` and `C_MMResult`; CATIA property compatibility remains target-test `not-run`.

Run the same command again; expected PASS.

- [ ] **Step 3: Commit**

```bash
git add catvba_refactor/vba/new/MM_HealthCheck.bas catvba_refactor/vba/new/MM_DocumentSummary.bas catvba_refactor/tests/test_core_runtime_sources.py catvba_refactor/tests/test_policy.py
git commit -m "feat: add first core runtime tools"
```

---

### Task 5: Replace the legacy Form code with an atomic Core override

**Files:**
- Create: `catvba_refactor/vba/overrides/Cat_Macro_Menu_View.frm`
- Create: `catvba_refactor/vba/overrides/Cat_Macro_Menu_View.frx`
- Create: `catvba_refactor/tests/test_core_form_override.py`
- Modify: `catvba_refactor/tests/test_inventory.py`
- Modify: `catvba_refactor/tests/test_resolver.py`
- Modify: `catvba_refactor/tests/test_policy.py`

**Interfaces:**
- Preserves the upstream Form storage metadata and exact FRX bytes.
- Presenter passes generated descriptors; handlers retain canonical tool IDs in an intrinsic `Collection`.

- [ ] **Step 1: Write failing atomic override tests**

Require exact FRX SHA-256 `12529f95a32b090015bb4d7f623aa53545cfb3226048c86c47b8e92224e5942e`, matching `OleObjectBlob`, `VB_PredeclaredId = True`, generated control/page names, separate captions/tooltips/groups, and `Collection` handler lifetime. Reject missing/mismatched FRX, upstream/local cross-pairing, `Cls_PDM`, `pdm`, `toMP`, `KCL`, `Cls_allBTNEVT`, dynamic source scanning, and broad `Try_SetProperty` error suppression.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_core_form_override.py catvba_refactor/tests/test_inventory.py catvba_refactor/tests/test_resolver.py catvba_refactor/tests/test_policy.py -q
```

Expected: FAIL because override files do not exist.

- [ ] **Step 3: Create the minimal complete override**

Copy the FRX bytes without transformation. Rebuild the FRM code section so it consumes only generated catalog arrays, creates MultiPage/Button controls, stores each `C_MMButtonHandler` in a Form-level `Collection`, and dispatches only its saved canonical ID. Preserve required designer/storage declarations but remove all legacy dependencies and dynamic project inspection.

- [ ] **Step 4: Verify GREEN and commit source bytes**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_core_form_override.py catvba_refactor/tests/test_inventory.py catvba_refactor/tests/test_resolver.py catvba_refactor/tests/test_policy.py -q
git diff --check
git add catvba_refactor/vba/overrides/Cat_Macro_Menu_View.frm catvba_refactor/vba/overrides/Cat_Macro_Menu_View.frx catvba_refactor/tests/test_core_form_override.py catvba_refactor/tests/test_inventory.py catvba_refactor/tests/test_resolver.py catvba_refactor/tests/test_policy.py
git commit -m "feat: add core menu form override"
```

Do not edit fixed VBA/FRX bytes after this commit without rebinding them in Task 7.

---

### Task 6: Generate explicit B28 target-test cases as NOT_RUN

**Files:**
- Modify: `catvba_refactor/macro_build/kit.py`
- Modify: `catvba_refactor/tests/test_kit.py`
- Modify: `catvba_refactor/tests/test_end_to_end.py`

**Interfaces:**
- Produces deterministic `target-test-plan/target-test-plan.json` entries for every first-cycle tool/profile/context/isolation case, all with `status=not-run`.

- [ ] **Step 1: Write failing target-plan tests**

Require cases for:

```text
core.healthcheck: none, CATPart, CATProduct, CATDrawing -> expected code 0
core.document-summary: none -> expected code 20
core.document-summary: CATPart, CATProduct, CATDrawing -> expected code 0
profiles: P-AB3, P-HD2, P-MD2
restart, repeat, cross-document, state-diff
SPA package missing/broken/reference-failed/checkout-failed with Core expected READY
FTA package missing/broken/reference-failed/checkout-failed with Core expected READY
```

Every case must bind package/tool/build identity and use `status=not-run`; the verifier rejects missing, duplicate, extra, reordered-by-tampering, or PASS-like status.

- [ ] **Step 2: Verify RED, implement, verify GREEN, commit**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_kit.py catvba_refactor/tests/test_end_to_end.py -q
```

Expected before implementation: FAIL for absent exact cases. Implement deterministic generation and verifier parity; run again for PASS.

```bash
git add catvba_refactor/macro_build/kit.py catvba_refactor/tests/test_kit.py catvba_refactor/tests/test_end_to_end.py
git commit -m "feat: bind core target test cases"
```

---

### Task 7: Bind the committed Core source set into manifests

**Files:**
- Modify: `catvba_refactor/config/components.json`
- Modify: `catvba_refactor/config/tools.json`
- Modify: `catvba_refactor/tests/test_manifests.py`
- Modify: `catvba_refactor/tests/test_core_runtime_sources.py`
- Modify: `catvba_refactor/tests/test_end_to_end.py`
- Modify: `Docs/PROJECT_STRUCTURE.md`

**Interfaces:**
- Adds source roots `catvba_refactor/vba/new` (`origin=new`) and `catvba_refactor/vba/overrides` (`origin=override`).
- Binds exactly 12 fixed new modules/classes plus one atomic Form override.
- Adds exactly two tools with direct module/entrypoint bindings.

- [ ] **Step 1: Write failing repository-manifest tests**

Assert exact component/tool sets, exact package `core`, exact member roles, and Git blob/raw SHA-256 equality against committed files. Assert the Form override has both local `members` and upstream-cutoff `base_members`. Reject worktree bytes, placeholder hashes, missing components, unbound tools, extra candidate tools, and any second-cycle/Fleet/Optional component.

- [ ] **Step 2: Verify RED**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_end_to_end.py -q
```

Expected: FAIL because production manifests remain empty.

- [ ] **Step 3: Compute exact committed bindings**

For every fixed local member, obtain its committed blob OID and raw SHA-256 with this exact loop:

```bash
for path in \
  catvba_refactor/vba/new/MM_Entry.bas \
  catvba_refactor/vba/new/MM_MenuPresenter.bas \
  catvba_refactor/vba/new/MM_Protocol.bas \
  catvba_refactor/vba/new/MM_Error.bas \
  catvba_refactor/vba/new/MM_Log.bas \
  catvba_refactor/vba/new/MM_TryGet.bas \
  catvba_refactor/vba/new/C_MMButtonHandler.cls \
  catvba_refactor/vba/new/C_MMContext.cls \
  catvba_refactor/vba/new/C_MMResult.cls \
  catvba_refactor/vba/new/C_MMStateGuard.cls \
  catvba_refactor/vba/new/MM_HealthCheck.bas \
  catvba_refactor/vba/new/MM_DocumentSummary.bas
do
  git rev-parse "HEAD:$path"
  git show "HEAD:$path" | sha256sum
done
for path in \
  catvba_refactor/vba/overrides/Cat_Macro_Menu_View.frm \
  catvba_refactor/vba/overrides/Cat_Macro_Menu_View.frx
do
  git rev-parse "HEAD:$path"
  git show "HEAD:$path" | sha256sum
done
for path in \
  Src/Cat_Macro_Menu_View.frm \
  Src/Cat_Macro_Menu_View.frx
do
  git rev-parse "dev:$path"
  git show "dev:$path" | sha256sum
done
```

Record the resulting literal 40-hex blob OIDs and 64-hex raw hashes in `components.json`. Never hash a worktree file for formal binding.

Add exactly:

```text
core.healthcheck | Health Check | core.general | Core | MM_HealthCheck | RunHealthCheck
core.document-summary | Document Summary | core.general | Core | MM_DocumentSummary | RunDocumentSummary
```

Both use required capabilities `[]`, risk `read-only`, explicit tooltip/group caption, and document types matching Task 6.

- [ ] **Step 4: Verify and commit manifest bindings**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_manifests.py catvba_refactor/tests/test_inventory.py catvba_refactor/tests/test_resolver.py catvba_refactor/tests/test_policy.py catvba_refactor/tests/test_generator.py catvba_refactor/tests/test_core_runtime_sources.py catvba_refactor/tests/test_end_to_end.py -q
git diff --check
git add catvba_refactor/config/components.json catvba_refactor/config/tools.json catvba_refactor/tests/test_end_to_end.py Docs/PROJECT_STRUCTURE.md
git commit -m "feat: bind core runtime candidates"
```

After this commit, any source-byte change requires a new binding update commit.

---

### Task 8: Produce and verify the first real Core Build Kit

**Files:**
- Modify: `Docs/STATUS.md`
- Modify: `README.md`
- Modify: `catvba_refactor/README.md`
- Modify: `catvba_refactor/tests/README.md`

**Interfaces:**
- Produces two independently rebuilt, byte-identical candidate Kits/ZIPs and a current G0/G1 status record.

- [ ] **Step 1: Run the complete clean-tree validation**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build inventory --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json
```

Expected: frozen sync/test PASS; candidate inventory/check PASS with the exact fixed/generated Core component set and two tools. No CATIA claim.

- [ ] **Step 2: Build twice in separate output roots and verify both**

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build --output-root /tmp/macro-menu-core-build-1 build-kit --format json | tee /tmp/macro-menu-core-receipt-1.json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build --output-root /tmp/macro-menu-core-build-2 build-kit --format json | tee /tmp/macro-menu-core-receipt-2.json
kit_dir_1="$(jq -er '.kit_dir' /tmp/macro-menu-core-receipt-1.json)"
kit_zip_1="$(jq -er '.zip_path' /tmp/macro-menu-core-receipt-1.json)"
kit_dir_2="$(jq -er '.kit_dir' /tmp/macro-menu-core-receipt-2.json)"
kit_zip_2="$(jq -er '.zip_path' /tmp/macro-menu-core-receipt-2.json)"
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build verify-kit "$kit_dir_1" --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build verify-kit "$kit_zip_1" --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build verify-kit "$kit_dir_2" --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build verify-kit "$kit_zip_2" --format json
cmp --silent "$kit_zip_1" "$kit_zip_2"
cmp --silent "$kit_dir_1/catalog.json" "$kit_dir_2/catalog.json"
test "$(jq -er '.kit_id' /tmp/macro-menu-core-receipt-1.json)" = "$(jq -er '.kit_id' /tmp/macro-menu-core-receipt-2.json)"
test "$(jq -er '.manifest_sha256' /tmp/macro-menu-core-receipt-1.json)" = "$(jq -er '.manifest_sha256' /tmp/macro-menu-core-receipt-2.json)"
test "$(jq -er '.zip_sha256' /tmp/macro-menu-core-receipt-1.json)" = "$(jq -er '.zip_sha256' /tmp/macro-menu-core-receipt-2.json)"
```

Use the exact paths returned by each build receipt. Compare kit ID, catalog bytes, manifest SHA-256, ZIP SHA-256, and ZIP bytes; all must match. Inspect staged Core contents and reject any legacy, second-cycle, Fleet, Optional, Office, VBIDE, network, Shell, SPA, or FTA component.

- [ ] **Step 3: Update status at the A-environment ceiling**

Record exact commands, test count, kit ID/hashes, component/tool list, and verifier results. Set G0/G1 only to the status justified by the generated receipts; retain G2-G7 `BLOCKED`, target cases `not-run`, `compile_status=not-run`, and `release_eligible=false`. Explicitly state that static VBA source and a verified Kit are not CATIA Compile or runtime evidence.

- [ ] **Step 4: Commit status, then verify from a clean governed tree**

```bash
git add Docs/STATUS.md README.md catvba_refactor/README.md catvba_refactor/tests/README.md
git commit -m "docs: record core runtime offline evidence"
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json
git diff --check
git status --short --branch
```

Expected: full PASS, clean tree, only local/remote work branch divergence, and no remote write yet.

---

## Final Verification Gate

Before claiming the Core MVP A-environment slice complete, invoke `superpowers:verification-before-completion` and freshly run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build inventory --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build build-kit --format json
git diff --check
git status --short --branch
git diff refs/heads/dev HEAD -- Src resources
```

Required conclusions:

- local `dev` remains the accepted cutoff and `Src/resources` remain byte-identical to it;
- all fixed local components are committed before and exactly matched by manifest blob/hash bindings;
- the Kit contains exactly the approved fixed and three generated Core components plus two first-cycle tools;
- repeated Kit/ZIP builds and both verifier paths are deterministic;
- no forbidden legacy/Fleet/Optional/API dependency enters Core;
- all target cases remain `not-run`; no CATIA/Compile/References/license/runtime/release claim exceeds A evidence;
- only `codex/dev-review-report` may be pushed.

## Explicitly Deferred

- CATIA B28 blank-project import, Compile, save, close/restart, and References GUID/version/path evidence.
- Actual MSForms control creation, event lifetime, CATIA property compatibility, and cross-document behavior.
- P-AB3, P-HD2, and P-MD2 runtime matrix; SPA/FTA missing/broken/checkout/reference isolation evidence.
- Product/Part/Drawing structure audits.
- Fleet-SPA, Fleet-FTA, Optional packages, and cross-CATVBA `ExecuteScript` spike.
- Production log path/ACL/retention, signing, CATVBA packaging, installation, pilot, rollback, tag, and Release.
