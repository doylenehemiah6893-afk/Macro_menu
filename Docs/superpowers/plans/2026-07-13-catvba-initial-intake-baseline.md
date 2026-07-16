# CATVBA Initial Intake Baseline Implementation Plan

> **历史执行状态：** 首次 no-content intake baseline 已实施并提交 accepted record。未勾选框不代表当前未完成。执行只依赖仓库内命令和测试，不依赖外部命名 skill；当前进度见 `Docs/CURRENT_DEVELOPMENT_PLAN.md`。

**Goal:** Establish the first accepted upstream `dev` cutoff and a local read-only-by-process `dev` ref without changing any remote branch, while leaving the repository fail-closed until real Core candidates exist.

**Architecture:** Treat GitHub repository identity and local Git object evidence as separate layers. Query upstream and fork `dev` independently, validate their exact common commit against committed `Src/` and `resources/`, record the accepted initial baseline as strict JSON, then atomically create `refs/heads/dev` only after every check passes. The baseline is a no-content intake because the accepted cutoff is already an ancestor of the work branch and its governed upstream trees are unchanged.

**Tech Stack:** Git, GitHub CLI/API, Python 3.11, pytest, jsonschema Draft 2020-12, existing `macro-menu-build` CLI.

## Global Constraints

- The only remote write branch is `doylenehemiah6893-afk/Macro_menu:codex/dev-review-report`; never push, create, update, merge, rebase, or force-push remote `main` or `dev`.
- `UPSTREAM_DEV` is `verysolecd/Macro_menu:dev`; `FORK_DEV` is `doylenehemiah6893-afk/Macro_menu:dev`; both must independently resolve to the same full commit SHA.
- The accepted initial cutoff is `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad`; stop if either remote no longer resolves to that SHA.
- `Src/` and `resources/` remain upstream-owned intake mirrors; this plan must not edit their bytes.
- The initial baseline is not a formal content intake: `merge_commit` is `null`, `changed_paths` is empty, and no synthetic merge commit is allowed.
- A local `dev` ref is created only with an atomic create operation and must never overwrite an existing ref.
- This workspace has no CATIA. Evidence is limited to Git, static analysis, pytest, deterministic Build Kit behavior, and read-only audit preparation.
- `G0` and `G1` remain `NOT_RUN` while `components.json` and `tools.json` have no approved candidates; `G2`–`G7` remain `BLOCKED`, `compile_status=not-run`, and `release_eligible=false`.
- Target eligibility remains `(AB3 OR HD2 OR MD2) AND SPA AND FTA`; Core itself targets the `(AB3 OR HD2 OR MD2)` capability intersection and must not early-bind SPA or FTA.

---

### Task 1: Accept indented exported Form resource bindings

**Files:**
- Modify: `catvba_refactor/tests/test_inventory.py`
- Modify: `catvba_refactor/macro_build/inventory.py`

**Interfaces:**
- Consumes: `scan_inputs(snapshot, manifests, repository) -> InventoryResult` and exported VBA Form syntax.
- Produces: `OLE_BLOB` recognition that permits horizontal indentation before `OleObjectBlob` but still anchors the complete line and exact `.frx` filename.

- [ ] **Step 1: Write the failing regression test**

Add a focused test beside the existing complete Form tests:

```python
def test_exported_form_accepts_indented_ole_object_blob(tmp_path: Path) -> None:
    form = (
        b'VERSION 5.00\r\n'
        b'Attribute VB_Name = "IndentedForm"\r\n'
        b'   OleObjectBlob   =   "IndentedForm.frx":0000\r\n'
    )
    resource = b"exact-resource"
    tree = {
        "Src/IndentedForm.frm": form,
        "Src/IndentedForm.frx": resource,
    }

    inventory = scan_inputs(
        _snapshot(),
        _manifests(),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: tree}),
    )

    assert inventory.report.ok
    assert len(inventory.components) == 1
    assert inventory.components[0].vb_name == "IndentedForm"
```

- [ ] **Step 2: Run the regression test and verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_inventory.py::test_exported_form_accepts_indented_ole_object_blob -q
```

Expected: FAIL because `FORM_OLE_BLOB_MISSING` excludes the component.

- [ ] **Step 3: Implement the minimal anchored parser fix**

Change only the leading anchor in `inventory.py`:

```python
OLE_BLOB = re.compile(
    r'^\s*OleObjectBlob\s*=\s*"([^":]+\.frx)":([0-9A-Fa-f]+)\s*$',
    re.MULTILINE,
)
```

Do not make matching case-insensitive and do not allow non-whitespace prefixes.

- [ ] **Step 4: Verify GREEN and the inventory suite**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_inventory.py -q
```

Expected: PASS with no warnings or failures.

- [ ] **Step 5: Commit the isolated parser fix**

```bash
git add catvba_refactor/tests/test_inventory.py catvba_refactor/macro_build/inventory.py
git commit -m "fix: accept indented form resource bindings"
```

---

### Task 2: Define the strict initial-baseline evidence contract

**Files:**
- Create: `catvba_refactor/schemas/intake-initial-baseline.schema.json`
- Create: `catvba_refactor/intake/README.md`
- Create: `catvba_refactor/tests/test_intake_baseline.py`
- Modify: `Docs/superpowers/specs/2026-07-13-catvba-upstream-intake-design.md`
- Modify: `Docs/PROJECT_STRUCTURE.md`

**Interfaces:**
- Consumes: the approved intake record fields and Draft 2020-12 jsonschema validation.
- Produces: a version-1, unknown-field-rejecting contract for a no-content `initial_baseline` record.

- [ ] **Step 1: Write failing schema-contract tests**

Create tests that load `intake-initial-baseline.schema.json` with `Draft202012Validator` and assert:

```python
def test_initial_baseline_schema_accepts_no_content_record() -> None:
    assert list(_validator().iter_errors(_valid_record())) == []


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        (lambda value: value.update({"unknown": True}), ""),
        (lambda value: value.update({"merge_commit": "a" * 40}), "merge_commit"),
        (lambda value: value["changed_paths"].append("Src/A.bas"), "changed_paths"),
        (lambda value: value["upstream"].update({"commit": "b" * 40}), "checks"),
    ],
)
def test_initial_baseline_schema_rejects_non_baseline_shapes(mutation, expected_path) -> None:
    record = _valid_record()
    mutation(record)
    assert list(_validator().iter_errors(record))
```

The test helper's valid record must use the exact cutoff, `merge_commit: null`, empty `changed_paths`, empty `override_decisions`, empty `superseded_kit_ids`, and equal upstream/fork commits and tree OIDs.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_intake_baseline.py -q
```

Expected: FAIL because the schema file does not exist.

- [ ] **Step 3: Add the exact strict schema**

The schema must require only these top-level fields and set `additionalProperties=false`:

```text
schema_version = 1
record_type = initial_baseline
status = accepted
recorded_date = YYYY-MM-DD
approver
upstream = {repository, ref, commit}
fork = {repository, ref, commit}
work_pre_intake_commit
merge_commit = null
merge_reason = initial-baseline/no-content-intake
trees = {Src: {cutoff_oid, work_oid}, resources: {cutoff_oid, work_oid}}
changed_paths = []
override_decisions = []
checks = {
  remote_refs_equal: true,
  cutoff_is_work_ancestor: true,
  src_tree_equal: true,
  resources_tree_equal: true,
  reserved_namespace_absent: true,
  portable_paths: passed,
  form_frx_pairs: passed
}
superseded_kit_ids = []
```

Use `^[0-9a-f]{40}$` for `work_pre_intake_commit`. Use JSON Schema `const` for the two repository/ref identities, both remote commit values, both `Src` tree values, both `resources` tree values, and every other fixed initial-baseline invariant. This record is deliberately bound to the exact accepted cutoff and known tree OIDs; future intake requires a different record type/schema rather than weakening this one. Do not invent a nonstandard cross-field keyword.

- [ ] **Step 4: Document the baseline boundary and resolve the merge ambiguity**

Document that this schema covers only the first no-content baseline. Add this explicit clarification to the approved intake spec:

```text
当 U 已是 O 的祖先且 O 的 Src/resources tree 与 U 完全相同时，首次 initial baseline 不制造空 merge；
record 使用 merge_commit=null、merge_reason=initial-baseline/no-content-intake。未来 U 发生内容变化时，
仍按 §7 使用两父 merge commit。
```

Document `catvba_refactor/intake/records/` under the project structure. Do not add the record to the four Build Kit input manifests.

- [ ] **Step 5: Verify schema tests and policy text**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_intake_baseline.py -q
rg -n "merge_commit=null|initial-baseline/no-content-intake|intake/records" Docs/superpowers/specs/2026-07-13-catvba-upstream-intake-design.md Docs/PROJECT_STRUCTURE.md catvba_refactor/intake/README.md
```

Expected: pytest PASS; all three documentation locations are found.

- [ ] **Step 6: Commit the evidence contract separately**

```bash
git add Docs/PROJECT_STRUCTURE.md Docs/superpowers/specs/2026-07-13-catvba-upstream-intake-design.md catvba_refactor/intake/README.md catvba_refactor/schemas/intake-initial-baseline.schema.json catvba_refactor/tests/test_intake_baseline.py
git commit -m "docs: define initial intake baseline evidence"
```

---

### Task 3: Accept the exact cutoff and establish the local dev ref

**Files:**
- Create: `catvba_refactor/intake/records/2026-07-13-initial-baseline.json`
- Modify: `catvba_refactor/tests/test_intake_baseline.py`
- Modify: `Docs/STATUS.md`
- Modify: `catvba_refactor/config/README.md`
- Modify: `catvba_refactor/macro_build/README.md`

**Interfaces:**
- Consumes: independently queried GitHub refs, the Task 2 schema, and the local Git object database.
- Produces: an accepted baseline record committed on the work branch and a local `refs/heads/dev` pointing exactly to the accepted cutoff.

- [ ] **Step 1: Capture the clean pre-intake work commit**

Run:

```bash
git status --porcelain=v1
git rev-parse HEAD
git show-ref --verify --quiet refs/heads/dev
```

Expected: status prints nothing; the full HEAD becomes `work_pre_intake_commit`; `show-ref` exits 1 because `dev` does not yet exist. Stop if any expectation differs.

- [ ] **Step 2: Query upstream and fork independently**

Run both read-only queries and record the full outputs:

```bash
git ls-remote https://github.com/verysolecd/Macro_menu.git refs/heads/dev
git ls-remote https://github.com/doylenehemiah6893-afk/Macro_menu.git refs/heads/dev
```

Expected: both output exactly `abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad` for `refs/heads/dev`. Stop on absence, multiplicity, or mismatch.

- [ ] **Step 3: Verify local object ancestry, trees, and reserved namespace**

Run:

```bash
git cat-file -e abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad^{commit}
git merge-base --is-ancestor abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad HEAD
git rev-parse abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad:Src HEAD:Src
git rev-parse abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad:resources HEAD:resources
git cat-file -e abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad:catvba_refactor
```

Expected: the commit and ancestor commands exit 0; each pair of tree OIDs is equal; the final reserved-namespace command exits nonzero. The known tree OIDs are `Src=0f7263465cdd5ecd7dbe5ceff090cad859cc1173` and `resources=720c20864bff3c48694acaf780b50518f49b9a60`.

- [ ] **Step 4: Run the real cutoff through inventory/check before acceptance**

Create an isolated temporary copy of the four manifests and replace only its two ref names with the exact accepted commit. This exercises the real committed `Src/resources` bytes without creating `dev` or changing repository files:

```bash
INTAKE_CONFIG=$(mktemp -d)
cp catvba_refactor/config/components.json "$INTAKE_CONFIG/components.json"
cp catvba_refactor/config/packages.json "$INTAKE_CONFIG/packages.json"
cp catvba_refactor/config/tools.json "$INTAKE_CONFIG/tools.json"
jq '.upstream_ref = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad" | .fork_dev_ref = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"' catvba_refactor/config/project.json > "$INTAKE_CONFIG/project.json"
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build --config-dir "$INTAKE_CONFIG" inventory --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build --config-dir "$INTAKE_CONFIG" check --format json
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_inventory.py catvba_refactor/tests/test_policy.py -q
```

Expected: both CLI commands exit 0 with `formal_eligible=true`, 77 discovered upstream components, zero candidate components/tools, and no Form/FRX or portable-path diagnostic; pytest passes. This is A-environment static evidence only. Remove only the temporary directory after capturing the results.

- [ ] **Step 5: Add a failing test for the repository record**

Add the exact record path and a test that reads the committed JSON rather than only a helper value:

```python
RECORD_PATH = (
    Path(__file__).parents[1]
    / "intake"
    / "records"
    / "2026-07-13-initial-baseline.json"
)


def test_repository_initial_baseline_record_matches_schema() -> None:
    record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    assert list(_validator().iter_errors(record)) == []
```

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_intake_baseline.py::test_repository_initial_baseline_record_matches_schema -q
```

Expected: FAIL with `FileNotFoundError` because the record does not exist.

- [ ] **Step 6: Write and validate the exact initial baseline record**

Create the record with the full `work_pre_intake_commit` captured in Step 1, the fixed cutoff, the two known tree OIDs, and all schema constants from Task 2. Validate it with:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest catvba_refactor/tests/test_intake_baseline.py -q
```

Expected: PASS and the repository record itself is included as the test fixture loaded from disk.

- [ ] **Step 7: Commit the record before moving the local ref**

```bash
git add catvba_refactor/intake/records/2026-07-13-initial-baseline.json catvba_refactor/tests/test_intake_baseline.py
git commit -m "docs: accept initial upstream dev baseline"
```

- [ ] **Step 8: Atomically create, never overwrite, the local dev ref**

Run exactly:

```bash
git update-ref refs/heads/dev abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad 0000000000000000000000000000000000000000
git rev-parse refs/heads/dev
```

Expected: creation succeeds and resolves to the exact accepted cutoff. Do not checkout `dev`; do not push it.

- [ ] **Step 9: Verify the repository's new fail-closed state**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build inventory --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build build-kit --format json
git status --short
```

Expected:

- `inventory` and `check` exit 0 with `formal_eligible=true` and zero approved candidate components/tools;
- `build-kit` exits 3 with `NO_BUILDABLE_COMPONENTS` and creates no completed Kit;
- no command writes `Src/`, `resources/`, remote refs, `main`, or remote `dev`.

- [ ] **Step 10: Update current status without promoting gates**

Update the four status/README files to record the accepted cutoff and local `dev` ref, remove the obsolete exit-4 statement, and preserve:

```text
G0 INPUT-FROZEN = NOT_RUN (baseline accepted; no approved Core candidate bindings)
G1 KIT-READY = NOT_RUN (no repository Kit)
G2-G7 = BLOCKED
compile_status=not-run
release_eligible=false
```

Also replace the obsolete `STATUS` phrase that Core Runtime MVP still needs spec approval with: the Core spec is approved and its implementation plan is next.

- [ ] **Step 11: Validate and commit status evidence before candidate verification**

Run:

```bash
git diff --check
git status --short
```

Expected: only the planned status files are modified. Commit them before running candidate-mode commands because both `catvba_refactor` README files are governed inputs and an uncommitted change must correctly block candidate checks.

Commit:

```bash
git add Docs/STATUS.md catvba_refactor/config/README.md catvba_refactor/macro_build/README.md
git commit -m "docs: record accepted upstream cutoff"
```

- [ ] **Step 12: Run full verification on the clean governed tree**

Run:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv sync --frozen
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build build-kit --format json
git diff --check
git status --short --branch
```

Expected: frozen sync and all tests pass; `check` reports a formal zero-candidate state; `build-kit` fails closed with exit 3 and no completed output; the working tree is clean. Do not create another commit only to record command output.

---

## Final Verification Gate

Before reporting the baseline phase complete, freshly run the repository-native verification commands below:

```bash
git rev-parse HEAD refs/heads/dev
git status --short --branch
git diff refs/heads/dev HEAD -- Src resources
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build inventory --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build check --format json
UV_CACHE_DIR=/tmp/uv-cache uv run macro-menu-build build-kit --format json
git diff --check
```

Required conclusions:

- local `dev` is exactly the accepted cutoff and `Src/resources` have zero diff from it;
- the work branch remains the only branch intended for remote push;
- no remote branch was changed;
- baseline evidence is strict, committed, and independently reproduces upstream/fork equality;
- inventory/check are usable, but no empty/fake Kit is produced;
- G0/G1 are still `NOT_RUN`, G2-G7 are still `BLOCKED`, and no CATIA/license/runtime claim was added.

## Explicitly Deferred

- Any future upstream content intake and its two-parent merge commit.
- Core Runtime MVP source, Form override, generated dispatcher/catalog/build info, and manifest bindings.
- Product/Part/Drawing audit tools.
- B28 Compile, References, save/restart, P-AB3/P-HD2/P-MD2, SPA/FTA isolation, packaging, pilot, and rollback.
