from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

import pytest

from catvba_refactor.macro_build.git_objects import GitRepository
from catvba_refactor.macro_build.inventory import scan_inputs
from catvba_refactor.macro_build.manifests import ManifestSet
from catvba_refactor.macro_build.model import (
    InputSnapshot,
    Origin,
    SnapshotMode,
    ValidationReport,
)


UPSTREAM_COMMIT = "1" * 40
WORK_COMMIT = "2" * 40


def _oid(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


class MemoryRepository:
    def __init__(
        self,
        root: Path,
        trees: dict[str, dict[str, bytes]],
    ) -> None:
        self.root = root
        self.trees = trees
        self.list_calls: list[tuple[str, str]] = []
        self.read_calls: list[tuple[str, str]] = []

    def list_tree(self, commit: str, prefix: str) -> tuple[tuple[str, str], ...]:
        self.list_calls.append((commit, prefix))
        prefix_with_slash = prefix.rstrip("/") + "/"
        return tuple(
            sorted(
                (path, _oid(data))
                for path, data in self.trees.get(commit, {}).items()
                if path == prefix or path.startswith(prefix_with_slash)
            )
        )

    def read_blob(self, commit: str, path: str) -> bytes:
        self.read_calls.append((commit, path))
        return self.trees[commit][path]


def _snapshot(
    mode: SnapshotMode = SnapshotMode.CANDIDATE,
    *,
    upstream_commit: str = UPSTREAM_COMMIT,
    work_commit: str = WORK_COMMIT,
    formal_eligible: bool | None = None,
) -> InputSnapshot:
    return InputSnapshot(
        mode=mode,
        upstream_repository="upstream/repository",
        upstream_ref="dev",
        upstream_commit=upstream_commit,
        fork_repository="fork/repository",
        fork_dev_commit=upstream_commit,
        work_repository="work/repository",
        work_branch="codex/dev-review-report",
        work_commit=work_commit,
        work_tree="3" * 40,
        manifest_digest="4" * 64,
        tool_version="0.1.0",
        formal_eligible=(mode is SnapshotMode.CANDIDATE)
        if formal_eligible is None
        else formal_eligible,
    )


def _root(
    path: str = "Src",
    *,
    root_id: str = "upstream-src",
    origin: str = "upstream",
    default_disposition: str = "quarantine",
) -> dict[str, Any]:
    return {
        "root_id": root_id,
        "origin": origin,
        "path": path,
        "extensions": [".bas", ".cls", ".frm", ".frx"],
        "default_disposition": default_disposition,
    }


def _binding(path: str, role: str, data: bytes) -> dict[str, str]:
    return {
        "path": path,
        "blob_oid": _oid(data),
        "raw_sha256": hashlib.sha256(data).hexdigest(),
        "role": role,
    }


def _component(
    source_id: str,
    component_type: str,
    vb_name: str,
    members: list[dict[str, str]],
    *,
    origin: str = "upstream",
    disposition: str = "candidate",
    encoding_decision: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "source_id": source_id,
        "origin": origin,
        "component_type": component_type,
        "vb_name": vb_name,
        "package_id": "core" if disposition == "candidate" else None,
        "disposition": disposition,
        "members": members,
    }
    if encoding_decision is not None:
        result["encoding_decision"] = encoding_decision
    return result


def _manifests(
    roots: list[dict[str, Any]] | None = None,
    components: list[dict[str, Any]] | None = None,
) -> ManifestSet:
    return ManifestSet(
        project={},
        components={
            "schema_version": 1,
            "source_roots": roots or [_root()],
            "components": components or [],
        },
        packages={"schema_version": 1, "packages": []},
        tools={"schema_version": 1, "tools": []},
        digest="5" * 64,
        report=ValidationReport(),
    )


def _codes(inventory: Any) -> list[str]:
    return [diagnostic.code for diagnostic in inventory.report.diagnostics]


def _symlink_or_skip(
    link: Path,
    target: Path,
    *,
    target_is_directory: bool = False,
) -> None:
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlinks are unavailable on this platform: {error}")


def test_memory_repository_oid_uses_git_blob_object_framing() -> None:
    data = b'Attribute VB_Name = "OidEvidence"\r\n'
    expected = subprocess.run(
        ("git", "hash-object", "--stdin"),
        input=data,
        check=True,
        capture_output=True,
    ).stdout.decode("ascii").strip()

    assert _oid(data) == expected


def test_explicit_modules_and_complete_form_preserve_exact_members(
    tmp_path: Path,
) -> None:
    module = b'Attribute VB_Name = "Alpha"\r\nPublic Sub Main()\r\nEnd Sub\r\n'
    class_module = b'Version 1.0 Class\r\nAttribute VB_Name = "Zulu"\r\n'
    form = (
        b'VERSION 5.00\r\nAttribute VB_Name = "MenuForm"\r\n'
        b'OleObjectBlob = "MenuForm.frx":0000\r\n'
    )
    resource = b"\x00\x01exact-form-bytes"
    tree = {
        "Src/Alpha.bas": module,
        "Src/Zulu.cls": class_module,
        "Src/MenuForm.frm": form,
        "Src/MenuForm.frx": resource,
    }
    components = [
        _component(
            "source.zulu",
            "class_module",
            "Zulu",
            [_binding("Src/Zulu.cls", "source", class_module)],
        ),
        _component(
            "source.menu",
            "user_form",
            "MenuForm",
            [
                _binding("Src/MenuForm.frm", "frm", form),
                _binding("Src/MenuForm.frx", "frx", resource),
            ],
        ),
        _component(
            "source.alpha",
            "standard_module",
            "Alpha",
            [_binding("Src/Alpha.bas", "source", module)],
        ),
    ]

    inventory = scan_inputs(
        _snapshot(),
        _manifests(components=components),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: tree}),
    )

    assert inventory.report.ok
    assert inventory.formal_eligible is True
    assert [(item.source_id, item.component_type, item.vb_name) for item in inventory.components] == [
        ("source.alpha", "standard_module", "Alpha"),
        ("source.menu", "user_form", "MenuForm"),
        ("source.zulu", "class_module", "Zulu"),
    ]
    menu = inventory.components[1]
    assert [member.role for member in menu.members] == ["frm", "frx"]
    assert [member.data for member in menu.members] == [form, resource]
    assert [member.blob_oid for member in menu.members] == [
        _oid(form),
        _oid(resource),
    ]
    assert [member.raw_sha256 for member in menu.members] == [
        hashlib.sha256(form).hexdigest(),
        hashlib.sha256(resource).hexdigest(),
    ]


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


def test_discovered_upstream_component_is_stably_quarantined(tmp_path: Path) -> None:
    data = b'Attribute VB_Name = "Unlisted"\r\n'
    repository = MemoryRepository(
        tmp_path,
        {UPSTREAM_COMMIT: {"Src/Unlisted.bas": data}},
    )

    first = scan_inputs(_snapshot(), _manifests(), repository)
    second = scan_inputs(_snapshot(), _manifests(), repository)

    assert first.report.ok
    assert first.components == second.components
    assert len(first.components) == 1
    discovered = first.components[0]
    assert discovered.source_id.startswith("discovered-")
    assert discovered.origin is Origin.UPSTREAM
    assert discovered.disposition == "quarantine"
    assert discovered.package_id is None


@pytest.mark.parametrize(
    ("tree", "expected_code"),
    [
        (
            {
                "Src/Broken.frm": (
                    b'Attribute VB_Name = "Broken"\r\n'
                    b'OleObjectBlob = "Broken.frx":0000\r\n'
                )
            },
            "FORM_FRX_MISSING",
        ),
        ({"Src/Orphan.frx": b"orphan"}, "FORM_FRX_ORPHAN"),
    ],
)
def test_incomplete_form_bundles_are_excluded(
    tmp_path: Path,
    tree: dict[str, bytes],
    expected_code: str,
) -> None:
    inventory = scan_inputs(
        _snapshot(),
        _manifests(),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: tree}),
    )

    assert expected_code in _codes(inventory)
    assert inventory.components == ()


@pytest.mark.parametrize(
    ("data", "expected_code"),
    [
        (b"Public Sub Main()\r\nEnd Sub\r\n", "VB_NAME_MISSING"),
        (
            b'Attribute VB_Name = "One"\r\nAttribute VB_Name = "Two"\r\n',
            "VB_NAME_DUPLICATE",
        ),
    ],
)
def test_module_requires_exactly_one_anchored_vb_name(
    tmp_path: Path,
    data: bytes,
    expected_code: str,
) -> None:
    inventory = scan_inputs(
        _snapshot(),
        _manifests(),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: {"Src/Bad.bas": data}}),
    )

    assert _codes(inventory) == [expected_code]
    assert inventory.components == ()


def test_vb_name_regex_does_not_accept_an_unanchored_attribute(tmp_path: Path) -> None:
    data = b'prefix Attribute VB_Name = "Hidden"\r\n'

    inventory = scan_inputs(
        _snapshot(),
        _manifests(),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: {"Src/Bad.bas": data}}),
    )

    assert _codes(inventory) == ["VB_NAME_MISSING"]


def test_duplicate_vb_names_exclude_every_colliding_component(tmp_path: Path) -> None:
    tree = {
        "Src/A.bas": b'Attribute VB_Name = "Same"\r\n',
        "Src/B.cls": b'Attribute VB_Name = "same"\r\n',
    }

    inventory = scan_inputs(
        _snapshot(),
        _manifests(),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: tree}),
    )

    assert _codes(inventory) == ["DUPLICATE_VB_NAME"]
    assert inventory.components == ()
    assert inventory.report.diagnostics[0].details["paths"] == (
        "Src/A.bas",
        "Src/B.cls",
    )


def test_explicit_extension_and_component_type_must_match(tmp_path: Path) -> None:
    data = b'Attribute VB_Name = "WrongType"\r\n'
    declared = _component(
        "source.wrong-type",
        "class_module",
        "WrongType",
        [_binding("Src/WrongType.bas", "source", data)],
    )

    inventory = scan_inputs(
        _snapshot(),
        _manifests(components=[declared]),
        MemoryRepository(
            tmp_path,
            {UPSTREAM_COMMIT: {"Src/WrongType.bas": data}},
        ),
    )

    assert "COMPONENT_TYPE_MISMATCH" in _codes(inventory)
    assert inventory.components == ()


def test_form_ole_blob_requires_exact_nfc_filename_spelling(tmp_path: Path) -> None:
    form = (
        b'Attribute VB_Name = "Menu"\r\n'
        b'OleObjectBlob = "menu.frx":0000\r\n'
    )
    tree = {"Src/Menu.frm": form, "Src/Menu.frx": b"resource"}

    inventory = scan_inputs(
        _snapshot(),
        _manifests(),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: tree}),
    )

    assert "FORM_OLE_BLOB_MISMATCH" in _codes(inventory)
    assert inventory.components == ()


def test_form_requires_an_exact_same_stem_frx(tmp_path: Path) -> None:
    form = (
        b'Attribute VB_Name = "Menu"\r\n'
        b'OleObjectBlob = "menu.frx":0000\r\n'
    )
    tree = {"Src/Menu.frm": form, "Src/menu.frx": b"resource"}

    inventory = scan_inputs(
        _snapshot(),
        _manifests(),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: tree}),
    )

    assert "FORM_FRX_MISSING" in _codes(inventory)
    assert "FORM_FRX_ORPHAN" in _codes(inventory)
    assert inventory.components == ()


def test_explicit_bindings_fail_closed_on_oid_or_hash_drift(tmp_path: Path) -> None:
    data = b'Attribute VB_Name = "Bound"\r\n'
    binding = _binding("Src/Bound.bas", "source", data)
    binding["blob_oid"] = "a" * 40
    binding["raw_sha256"] = "b" * 64
    declared = _component(
        "source.bound",
        "standard_module",
        "Bound",
        [binding],
    )

    inventory = scan_inputs(
        _snapshot(),
        _manifests(components=[declared]),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: {"Src/Bound.bas": data}}),
    )

    assert _codes(inventory) == ["MEMBER_BINDING_MISMATCH"]
    assert inventory.components == ()


def test_explicit_vb_name_must_match_source_identity(tmp_path: Path) -> None:
    data = b'Attribute VB_Name = "Actual"\r\n'
    declared = _component(
        "source.identity",
        "standard_module",
        "Declared",
        [_binding("Src/Actual.bas", "source", data)],
    )

    inventory = scan_inputs(
        _snapshot(),
        _manifests(components=[declared]),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: {"Src/Actual.bas": data}}),
    )

    assert "VB_NAME_MISMATCH" in _codes(inventory)
    assert inventory.components == ()


def test_explicit_origin_must_match_the_selected_source_root(tmp_path: Path) -> None:
    data = b'Attribute VB_Name = "Local"\r\n'
    local_path = "catvba_refactor/vba/new/Local.bas"
    declared = _component(
        "source.local",
        "standard_module",
        "Local",
        [_binding(local_path, "source", data)],
        origin="upstream",
    )
    roots = [
        _root(
            "catvba_refactor/vba/new",
            root_id="local-new",
            origin="new",
            default_disposition="candidate",
        )
    ]

    inventory = scan_inputs(
        _snapshot(),
        _manifests(roots=roots, components=[declared]),
        MemoryRepository(tmp_path, {WORK_COMMIT: {local_path: data}}),
    )

    assert _codes(inventory) == ["COMPONENT_ORIGIN_MISMATCH"]
    assert inventory.components == ()


def test_upstream_component_may_be_explicitly_quarantined(tmp_path: Path) -> None:
    data = b'Attribute VB_Name = "Held"\r\n'
    declared = _component(
        "source.held",
        "standard_module",
        "Held",
        [_binding("Src/Held.bas", "source", data)],
        origin="upstream",
        disposition="quarantine",
    )

    inventory = scan_inputs(
        _snapshot(),
        _manifests(components=[declared]),
        MemoryRepository(tmp_path, {UPSTREAM_COMMIT: {"Src/Held.bas": data}}),
    )

    assert inventory.report.ok
    assert len(inventory.components) == 1
    assert inventory.components[0].origin is Origin.UPSTREAM
    assert inventory.components[0].disposition == "quarantine"


def test_form_members_must_come_from_the_exact_same_source_root(
    tmp_path: Path,
) -> None:
    form = (
        b'Attribute VB_Name = "LocalForm"\r\n'
        b'OleObjectBlob = "LocalForm.frx":0000\r\n'
    )
    resource = b"exact-form-resource"
    form_path = "catvba_refactor/vba/new/LocalForm.frm"
    resource_path = "catvba_refactor/vba/new/LocalForm.frx"
    frm_root = _root(
        "catvba_refactor/vba/new",
        root_id="local-forms",
        origin="new",
        default_disposition="candidate",
    )
    frm_root["extensions"] = [".frm"]
    frx_root = _root(
        "catvba_refactor/vba/new",
        root_id="local-resources",
        origin="new",
        default_disposition="candidate",
    )
    frx_root["extensions"] = [".frx"]
    declared = _component(
        "source.local-form",
        "user_form",
        "LocalForm",
        [
            _binding(form_path, "frm", form),
            _binding(resource_path, "frx", resource),
        ],
        origin="new",
    )

    inventory = scan_inputs(
        _snapshot(),
        _manifests(roots=[frm_root, frx_root], components=[declared]),
        MemoryRepository(
            tmp_path,
            {WORK_COMMIT: {form_path: form, resource_path: resource}},
        ),
    )

    assert _codes(inventory) == ["COMPONENT_MEMBER_ROOT_MIXED"]
    assert inventory.components == ()


@pytest.mark.parametrize("stale_path", ["local/foo.bas", "Ｌocal/Ｆoo.bas"])
def test_stale_portable_binding_claim_cannot_reappear_as_discovered_candidate(
    tmp_path: Path,
    stale_path: str,
) -> None:
    data = b'Attribute VB_Name = "Foo"\r\n'
    actual_path = "Local/Foo.bas"
    declared = _component(
        "source.foo",
        "standard_module",
        "Foo",
        [_binding(stale_path, "source", data)],
        origin="new",
    )
    roots = [
        _root(
            "Local",
            root_id="local-new",
            origin="new",
            default_disposition="candidate",
        )
    ]

    inventory = scan_inputs(
        _snapshot(),
        _manifests(roots=roots, components=[declared]),
        MemoryRepository(tmp_path, {WORK_COMMIT: {actual_path: data}}),
    )

    assert _codes(inventory) == ["MEMBER_NOT_FOUND"]
    assert inventory.components == ()


def test_invalid_binding_path_is_diagnosed_without_portable_key_failure(
    tmp_path: Path,
) -> None:
    data = b'Attribute VB_Name = "Foo"\r\n'
    actual_path = "Local/Foo.bas"
    invalid_path = "../Local/Foo.bas"
    declared = _component(
        "source.foo",
        "standard_module",
        "Foo",
        [_binding(invalid_path, "source", data)],
        origin="new",
    )
    roots = [
        _root(
            "Local",
            root_id="local-new",
            origin="new",
            default_disposition="quarantine",
        )
    ]

    first = scan_inputs(
        _snapshot(),
        _manifests(roots=roots, components=[declared]),
        MemoryRepository(tmp_path, {WORK_COMMIT: {actual_path: data}}),
    )
    second = scan_inputs(
        _snapshot(),
        _manifests(roots=roots, components=[declared]),
        MemoryRepository(tmp_path, {WORK_COMMIT: {actual_path: data}}),
    )

    assert first == second
    assert _codes(first) == ["MEMBER_NOT_FOUND", "PATH_TRAVERSAL"]
    assert [component.disposition for component in first.components] == [
        "quarantine"
    ]


def test_ambiguous_text_requires_and_respects_manifest_encoding_decision(
    tmp_path: Path,
) -> None:
    data = b'Attribute VB_Name = "Ambiguous"\r\n\'\xc2\xa9\r\n'
    binding = _binding("Src/Ambiguous.bas", "source", data)
    undecided = _component(
        "source.ambiguous",
        "standard_module",
        "Ambiguous",
        [binding],
    )
    repository = MemoryRepository(
        tmp_path,
        {UPSTREAM_COMMIT: {"Src/Ambiguous.bas": data}},
    )

    rejected = scan_inputs(
        _snapshot(),
        _manifests(components=[undecided]),
        repository,
    )
    accepted = scan_inputs(
        _snapshot(),
        _manifests(
            components=[undecided | {"encoding_decision": "cp936"}],
        ),
        repository,
    )

    assert _codes(rejected) == ["ENC_AMBIGUOUS"]
    assert rejected.components == ()
    assert accepted.report.ok
    assert accepted.components[0].encoding_decision == "cp936"
    assert accepted.components[0].members[0].data == data


def test_candidate_reads_committed_git_blob_not_dirty_worktree(
    git_repo: tuple[Path, str],
) -> None:
    repo_path, commit = git_repo
    snapshot = _snapshot(upstream_commit=commit, work_commit=commit)
    (repo_path / "Src/A.bas").write_bytes(
        b'Attribute VB_Name = "DirtyWorktree"\r\n'
    )

    inventory = scan_inputs(
        snapshot,
        _manifests(),
        GitRepository(repo_path),
    )

    assert inventory.report.ok
    assert inventory.components[0].vb_name == "A"
    assert inventory.components[0].members[0].data.startswith(
        b'Attribute VB_Name = "A"'
    )
    expected_oid = subprocess.run(
        ("git", "rev-parse", f"{commit}:Src/A.bas"),
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert inventory.components[0].members[0].blob_oid == expected_oid


def test_worktree_reads_filesystem_bytes_and_is_never_formal(tmp_path: Path) -> None:
    source = tmp_path / "Src/Diagnostic.bas"
    source.parent.mkdir(parents=True)
    dirty = b'Attribute VB_Name = "Diagnostic"\r\n\'dirty\r\n'
    source.write_bytes(dirty)
    repository = MemoryRepository(tmp_path, {})

    inventory = scan_inputs(
        _snapshot(SnapshotMode.WORKTREE, formal_eligible=True),
        _manifests(),
        repository,
    )

    assert inventory.report.ok
    assert inventory.formal_eligible is False
    assert inventory.components[0].members[0].data == dirty
    assert inventory.components[0].members[0].blob_oid is None
    assert repository.list_calls == []
    assert repository.read_calls == []


def test_worktree_rejects_a_symlink_source_root(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    outside = tmp_path / "outside-root"
    outside.mkdir()
    (outside / "Leaked.bas").write_bytes(
        b'Attribute VB_Name = "Leaked"\r\n'
    )
    repo_path.mkdir()
    _symlink_or_skip(repo_path / "Src", outside, target_is_directory=True)

    inventory = scan_inputs(
        _snapshot(SnapshotMode.WORKTREE),
        _manifests(),
        MemoryRepository(repo_path, {}),
    )

    assert _codes(inventory) == ["SOURCE_SYMLINK_REJECTED"]
    assert inventory.report.diagnostics[0].path == "Src"
    assert inventory.components == ()


def test_worktree_rejects_symlink_directories_and_files(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    source_root = repo_path / "Src"
    outside = tmp_path / "outside-members"
    source_root.mkdir(parents=True)
    outside.mkdir()
    external_file = outside / "External.bas"
    external_file.write_bytes(b'Attribute VB_Name = "External"\r\n')
    _symlink_or_skip(
        source_root / "linked-directory",
        outside,
        target_is_directory=True,
    )
    _symlink_or_skip(source_root / "Linked.bas", external_file)

    inventory = scan_inputs(
        _snapshot(SnapshotMode.WORKTREE),
        _manifests(),
        MemoryRepository(repo_path, {}),
    )

    assert _codes(inventory) == [
        "SOURCE_SYMLINK_REJECTED",
        "SOURCE_SYMLINK_REJECTED",
    ]
    assert {
        diagnostic.path for diagnostic in inventory.report.diagnostics
    } == {"Src/Linked.bas", "Src/linked-directory"}
    assert inventory.components == ()


@pytest.mark.parametrize("mode", [SnapshotMode.CANDIDATE, SnapshotMode.WORKTREE])
def test_portable_path_checks_apply_in_both_modes(
    tmp_path: Path,
    mode: SnapshotMode,
) -> None:
    data = b'Attribute VB_Name = "Reserved"\r\n'
    if mode is SnapshotMode.CANDIDATE:
        repository = MemoryRepository(
            tmp_path,
            {UPSTREAM_COMMIT: {"Src/CON.bas": data}},
        )
    else:
        path = tmp_path / "Src/CON.bas"
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
        repository = MemoryRepository(tmp_path, {})

    inventory = scan_inputs(
        _snapshot(mode),
        _manifests(),
        repository,
    )

    assert "PATH_RESERVED_NAME" in _codes(inventory)
    assert inventory.components == ()


def test_candidate_uses_upstream_commit_only_for_upstream_roots(
    tmp_path: Path,
) -> None:
    upstream = b'Attribute VB_Name = "Upstream"\r\n'
    local = b'Attribute VB_Name = "Local"\r\n'
    roots = [
        _root(),
        _root(
            "catvba_refactor/vba/new",
            root_id="local-new",
            origin="new",
            default_disposition="candidate",
        ),
    ]
    repository = MemoryRepository(
        tmp_path,
        {
            UPSTREAM_COMMIT: {"Src/Upstream.bas": upstream},
            WORK_COMMIT: {"catvba_refactor/vba/new/Local.bas": local},
        },
    )

    inventory = scan_inputs(_snapshot(), _manifests(roots=roots), repository)

    assert inventory.report.ok
    assert repository.list_calls == [
        (UPSTREAM_COMMIT, "Src"),
        (WORK_COMMIT, "catvba_refactor/vba/new"),
    ]
    assert {component.vb_name for component in inventory.components} == {
        "Local",
        "Upstream",
    }
    assert next(
        component for component in inventory.components if component.vb_name == "Local"
    ).disposition == "candidate"
