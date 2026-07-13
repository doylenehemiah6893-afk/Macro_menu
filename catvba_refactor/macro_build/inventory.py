from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .encoding import decode_vba
from .errors import SourceError
from .git_objects import GitRepository
from .manifests import ManifestSet
from .model import (
    Component,
    Diagnostic,
    InputSnapshot,
    Inventory,
    Origin,
    SnapshotMode,
    SourceMember,
    ValidationReport,
)
from .portable_paths import portable_key, validate_portable_paths


VB_NAME = re.compile(
    r'^Attribute\s+VB_Name\s*=\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*$',
    re.I | re.M,
)
OLE_BLOB = re.compile(
    r'^OleObjectBlob\s*=\s*"([^":]+\.frx)":([0-9A-Fa-f]+)\s*$',
    re.I | re.M,
)


_TYPE_BY_EXTENSION = {
    ".bas": "standard_module",
    ".cls": "class_module",
    ".frm": "user_form",
}
_MEMBER_ORDER = {"source": 0, "frm": 0, "frx": 1}


@dataclass(frozen=True)
class _Root:
    root_id: str
    origin: Origin
    path: str
    extensions: frozenset[str]
    default_disposition: str
    side: str
    index: int


@dataclass(frozen=True)
class _RawMember:
    path: str
    blob_oid: str | None
    raw_sha256: str
    data: bytes
    root: _Root

    def as_member(self, role: str) -> SourceMember:
        return SourceMember(
            path=self.path,
            blob_oid=self.blob_oid,
            raw_sha256=self.raw_sha256,
            role=role,
            data=self.data,
        )


@dataclass(frozen=True)
class _BuiltComponent:
    component: Component
    side: str


def _diagnostic(code: str, path: str, message: str, **details: Any) -> Diagnostic:
    return Diagnostic(code=code, path=path, message=message, details=details)


def _origin(value: Any, path: str, diagnostics: list[Diagnostic]) -> Origin | None:
    try:
        return Origin(value)
    except (TypeError, ValueError):
        diagnostics.append(
            _diagnostic(
                "SOURCE_ROOT_INVALID",
                path,
                "source root has an unsupported origin",
            )
        )
        return None


def _roots(manifests: ManifestSet, diagnostics: list[Diagnostic]) -> tuple[_Root, ...]:
    records = manifests.components.get("source_roots", [])
    if not isinstance(records, list):
        return ()

    roots: list[_Root] = []
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        root_path = record.get("path")
        origin = _origin(
            record.get("origin"),
            f"components.json#/source_roots/{index}/origin",
            diagnostics,
        )
        if not isinstance(root_path, str) or origin is None:
            continue
        root_report = validate_portable_paths((root_path,))
        if not root_report.ok:
            diagnostics.extend(root_report.diagnostics)
            continue
        extensions = record.get("extensions", [])
        if not isinstance(extensions, list):
            continue
        roots.append(
            _Root(
                root_id=str(record.get("root_id", f"root-{index}")),
                origin=origin,
                path=root_path.replace("\\", "/"),
                extensions=frozenset(
                    extension.casefold()
                    for extension in extensions
                    if isinstance(extension, str)
                ),
                default_disposition=str(
                    record.get("default_disposition", "quarantine")
                ),
                side="upstream" if origin is Origin.UPSTREAM else "work",
                index=index,
            )
        )
    return tuple(roots)


def _candidate_members(
    snapshot: InputSnapshot,
    repo: GitRepository,
    root: _Root,
    diagnostics: list[Diagnostic],
) -> list[_RawMember]:
    commit = (
        snapshot.upstream_commit
        if root.side == "upstream"
        else snapshot.work_commit
    )
    members: list[_RawMember] = []
    try:
        entries = repo.list_tree(commit, root.path)
    except SourceError as error:
        diagnostics.append(
            _diagnostic(str(error), root.path, "cannot list committed source root")
        )
        return members

    for path, blob_oid in entries:
        if PurePosixPath(path).suffix.casefold() not in root.extensions:
            continue
        try:
            data = repo.read_blob(commit, path)
        except SourceError as error:
            diagnostics.append(
                _diagnostic(str(error), path, "cannot read committed source member")
            )
            continue
        members.append(
            _RawMember(
                path=path,
                blob_oid=blob_oid,
                raw_sha256=hashlib.sha256(data).hexdigest(),
                data=data,
                root=root,
            )
        )
    return members


def _worktree_members(
    repo: GitRepository,
    root: _Root,
    diagnostics: list[Diagnostic],
) -> list[_RawMember]:
    root_path = repo.root / Path(root.path)
    if not root_path.exists():
        return []
    if not root_path.is_dir():
        diagnostics.append(
            _diagnostic(
                "SOURCE_ROOT_NOT_DIRECTORY",
                root.path,
                "worktree source root is not a directory",
            )
        )
        return []

    members: list[_RawMember] = []
    try:
        paths = sorted(
            (
                path
                for path in root_path.rglob("*")
                if path.is_file()
                and path.suffix.casefold() in root.extensions
            ),
            key=lambda path: path.relative_to(repo.root).as_posix(),
        )
    except OSError as error:
        diagnostics.append(
            _diagnostic(
                "SOURCE_READ_ERROR",
                root.path,
                f"cannot enumerate worktree source root ({type(error).__name__})",
            )
        )
        return []

    for absolute_path in paths:
        relative_path = absolute_path.relative_to(repo.root).as_posix()
        try:
            data = absolute_path.read_bytes()
        except OSError as error:
            diagnostics.append(
                _diagnostic(
                    "SOURCE_READ_ERROR",
                    relative_path,
                    f"cannot read worktree source member ({type(error).__name__})",
                )
            )
            continue
        members.append(
            _RawMember(
                path=relative_path,
                blob_oid=None,
                raw_sha256=hashlib.sha256(data).hexdigest(),
                data=data,
                root=root,
            )
        )
    return members


def _read_members(
    snapshot: InputSnapshot,
    manifests: ManifestSet,
    repo: GitRepository,
    diagnostics: list[Diagnostic],
) -> tuple[_RawMember, ...]:
    members: list[_RawMember] = []
    for root in _roots(manifests, diagnostics):
        if snapshot.mode is SnapshotMode.WORKTREE:
            members.extend(_worktree_members(repo, root, diagnostics))
        else:
            members.extend(_candidate_members(snapshot, repo, root, diagnostics))
    return tuple(sorted(members, key=lambda member: (member.path, member.root.index)))


def _invalid_paths(
    members: tuple[_RawMember, ...], diagnostics: list[Diagnostic]
) -> set[str]:
    report = validate_portable_paths(member.path for member in members)
    diagnostics.extend(report.diagnostics)
    invalid: set[str] = set()
    for diagnostic in report.diagnostics:
        if diagnostic.code == "PATH_COLLISION":
            invalid.update(diagnostic.details.get("paths", ()))
        elif diagnostic.code == "PATH_FILE_DIR_COLLISION":
            file_path = diagnostic.details.get("file_path")
            if isinstance(file_path, str):
                invalid.add(file_path)
            invalid.update(diagnostic.details.get("nested_paths", ()))
        else:
            invalid.add(diagnostic.path)

    # Invalid Unicode paths may have an NFC diagnostic path different from the
    # exact tree spelling. Re-check each exact path to retain fail-closed mapping.
    for member in members:
        try:
            portable_key(member.path)
        except SourceError:
            invalid.add(member.path)
    return invalid


def _identity(
    member: _RawMember,
    declared_encoding: str | None,
    diagnostics: list[Diagnostic],
) -> tuple[str, str] | None:
    try:
        decoded = decode_vba(member.data, declared_encoding)
    except SourceError as error:
        diagnostics.append(
            _diagnostic(
                str(error),
                member.path,
                "VBA source cannot be decoded without replacement",
            )
        )
        return None

    names = VB_NAME.findall(decoded.text)
    if not names:
        diagnostics.append(
            _diagnostic(
                "VB_NAME_MISSING",
                member.path,
                "source must contain exactly one Attribute VB_Name",
            )
        )
        return None
    if len(names) != 1:
        diagnostics.append(
            _diagnostic(
                "VB_NAME_DUPLICATE",
                member.path,
                "source contains more than one Attribute VB_Name",
            )
        )
        return None
    return names[0], decoded.text


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _same_form_stem(frm_path: str, frx_path: str) -> bool:
    frm = PurePosixPath(frm_path)
    frx = PurePosixPath(frx_path)
    return (
        _nfc(str(frm.parent)) == _nfc(str(frx.parent))
        and _nfc(frm.stem) == _nfc(frx.stem)
        and frm.suffix.casefold() == ".frm"
        and frx.suffix.casefold() == ".frx"
    )


def _form_identity(
    frm: _RawMember,
    frx: _RawMember,
    declared_encoding: str | None,
    diagnostics: list[Diagnostic],
) -> str | None:
    identity = _identity(frm, declared_encoding, diagnostics)
    if identity is None:
        return None
    vb_name, text = identity
    blobs = OLE_BLOB.findall(text)
    if not blobs:
        diagnostics.append(
            _diagnostic(
                "FORM_OLE_BLOB_MISSING",
                frm.path,
                "Form must contain exactly one OleObjectBlob binding",
            )
        )
        return None
    if len(blobs) != 1:
        diagnostics.append(
            _diagnostic(
                "FORM_OLE_BLOB_DUPLICATE",
                frm.path,
                "Form contains more than one OleObjectBlob binding",
            )
        )
        return None

    declared_filename = _nfc(blobs[0][0])
    actual_filename = _nfc(PurePosixPath(frx.path).name)
    if declared_filename != actual_filename:
        diagnostics.append(
            _diagnostic(
                "FORM_OLE_BLOB_MISMATCH",
                frm.path,
                "OleObjectBlob filename does not exactly match the paired FRX",
                actual=actual_filename,
                declared=declared_filename,
            )
        )
        return None
    return vb_name


def _binding_matches(
    raw: _RawMember,
    binding: dict[str, Any],
    role: str,
    mode: SnapshotMode,
) -> bool:
    if binding.get("path") != raw.path or binding.get("role") != role:
        return False
    if binding.get("raw_sha256") != raw.raw_sha256:
        return False
    # Worktree diagnostics intentionally have no object identity. The raw hash
    # still reports whether the diagnostic bytes drifted from the declaration.
    if mode is SnapshotMode.CANDIDATE and binding.get("blob_oid") != raw.blob_oid:
        return False
    return True


def _expected_roles(component_type: Any) -> tuple[str, ...] | None:
    if component_type in {"standard_module", "class_module"}:
        return ("source",)
    if component_type == "user_form":
        return ("frm", "frx")
    return None


def _explicit_components(
    snapshot: InputSnapshot,
    manifests: ManifestSet,
    raw_members: tuple[_RawMember, ...],
    invalid_paths: set[str],
    diagnostics: list[Diagnostic],
) -> tuple[list[_BuiltComponent], set[str]]:
    by_path: dict[str, list[_RawMember]] = defaultdict(list)
    for member in raw_members:
        by_path[member.path].append(member)

    records = manifests.components.get("components", [])
    if not isinstance(records, list):
        return [], set()
    built: list[_BuiltComponent] = []
    claimed_paths: set[str] = set()

    for index, record in enumerate(records):
        if not isinstance(record, dict):
            continue
        bindings = record.get("members", [])
        if not isinstance(bindings, list):
            continue
        for binding in bindings:
            if isinstance(binding, dict) and isinstance(binding.get("path"), str):
                claimed_paths.add(binding["path"])

        component_type = record.get("component_type")
        roles = _expected_roles(component_type)
        diagnostic_path = f"components.json#/components/{index}"
        if roles is None:
            continue
        bindings_by_role: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for binding in bindings:
            if isinstance(binding, dict) and isinstance(binding.get("role"), str):
                bindings_by_role[binding["role"]].append(binding)
        if any(len(bindings_by_role[role]) != 1 for role in roles) or set(
            bindings_by_role
        ) != set(roles):
            diagnostics.append(
                _diagnostic(
                    "MEMBER_ROLE_MISMATCH",
                    diagnostic_path,
                    "explicit component member roles do not match its type",
                )
            )
            continue

        selected: dict[str, _RawMember] = {}
        component_invalid = False
        for role in roles:
            binding = bindings_by_role[role][0]
            path = binding.get("path")
            if not isinstance(path, str):
                component_invalid = True
                continue
            matches = by_path.get(path, [])
            if len(matches) != 1:
                diagnostics.append(
                    _diagnostic(
                        "MEMBER_NOT_FOUND" if not matches else "MEMBER_PATH_AMBIGUOUS",
                        path,
                        "explicit member path must resolve to exactly one source member",
                    )
                )
                component_invalid = True
                continue
            raw = matches[0]
            selected[role] = raw
            if path in invalid_paths:
                component_invalid = True
            expected_type = (
                _TYPE_BY_EXTENSION.get(PurePosixPath(path).suffix.casefold())
                if role != "frx"
                else "user_form"
            )
            if expected_type != component_type:
                diagnostics.append(
                    _diagnostic(
                        "COMPONENT_TYPE_MISMATCH",
                        path,
                        "member extension does not match declared component type",
                    )
                )
                component_invalid = True
            if not _binding_matches(raw, binding, role, snapshot.mode):
                diagnostics.append(
                    _diagnostic(
                        "MEMBER_BINDING_MISMATCH",
                        path,
                        "explicit member path, object, hash, or role does not match input",
                    )
                )
                component_invalid = True

        if len(selected) != len(roles):
            continue
        selected_sides = {member.root.side for member in selected.values()}
        if len(selected_sides) != 1:
            diagnostics.append(
                _diagnostic(
                    "COMPONENT_MEMBER_ORIGIN_MIXED",
                    diagnostic_path,
                    "one component cannot mix upstream and work-owned members",
                )
            )
            component_invalid = True

        declared_encoding = record.get("encoding_decision")
        if not isinstance(declared_encoding, str):
            declared_encoding = None
        actual_name: str | None
        if component_type == "user_form":
            frm = selected["frm"]
            frx = selected["frx"]
            if not _same_form_stem(frm.path, frx.path):
                diagnostics.append(
                    _diagnostic(
                        "FORM_FRX_STEM_MISMATCH",
                        frm.path,
                        "Form members must have the exact same NFC stem",
                    )
                )
                component_invalid = True
                actual_name = None
            else:
                actual_name = _form_identity(
                    frm, frx, declared_encoding, diagnostics
                )
        else:
            identity = _identity(
                selected["source"], declared_encoding, diagnostics
            )
            actual_name = identity[0] if identity is not None else None

        declared_name = record.get("vb_name")
        if actual_name is None:
            component_invalid = True
        elif actual_name != declared_name:
            diagnostics.append(
                _diagnostic(
                    "VB_NAME_MISMATCH",
                    selected[roles[0]].path,
                    "parsed VB_Name does not exactly match the manifest identity",
                    actual=actual_name,
                    declared=declared_name,
                )
            )
            component_invalid = True
        if component_invalid:
            continue

        try:
            origin = Origin(record.get("origin"))
        except (TypeError, ValueError):
            continue
        members = tuple(
            sorted(
                (selected[role].as_member(role) for role in roles),
                key=lambda member: (_MEMBER_ORDER[member.role], member.path),
            )
        )
        built.append(
            _BuiltComponent(
                component=Component(
                    source_id=str(record.get("source_id")),
                    origin=origin,
                    component_type=component_type,
                    vb_name=actual_name,
                    members=members,
                    package_id=(
                        str(record["package_id"])
                        if isinstance(record.get("package_id"), str)
                        else None
                    ),
                    disposition=str(record.get("disposition")),
                ),
                side=next(iter(selected_sides)),
            )
        )
    return built, claimed_paths


def _discovered_source_id(root: _Root, path: str) -> str:
    identity = f"{root.root_id}\0{_nfc(path)}".encode("utf-8", errors="strict")
    return f"discovered-{hashlib.sha256(identity).hexdigest()[:32]}"


def _discovered_component(
    raw: _RawMember,
    component_type: str,
    vb_name: str,
    members: tuple[SourceMember, ...],
) -> _BuiltComponent:
    return _BuiltComponent(
        component=Component(
            source_id=_discovered_source_id(raw.root, raw.path),
            origin=raw.root.origin,
            component_type=component_type,
            vb_name=vb_name,
            members=members,
            package_id=None,
            disposition=raw.root.default_disposition,
        ),
        side=raw.root.side,
    )


def _discovered_components(
    raw_members: tuple[_RawMember, ...],
    claimed_paths: set[str],
    invalid_paths: set[str],
    diagnostics: list[Diagnostic],
) -> list[_BuiltComponent]:
    available = [member for member in raw_members if member.path not in claimed_paths]
    forms = [
        member
        for member in available
        if PurePosixPath(member.path).suffix.casefold() == ".frm"
    ]
    resources = [
        member
        for member in available
        if PurePosixPath(member.path).suffix.casefold() == ".frx"
    ]
    consumed_resources: set[tuple[int, str]] = set()
    built: list[_BuiltComponent] = []

    for raw in available:
        suffix = PurePosixPath(raw.path).suffix.casefold()
        if suffix not in {".bas", ".cls"} or raw.path in invalid_paths:
            continue
        identity = _identity(raw, None, diagnostics)
        if identity is None:
            continue
        vb_name, _ = identity
        built.append(
            _discovered_component(
                raw,
                _TYPE_BY_EXTENSION[suffix],
                vb_name,
                (raw.as_member("source"),),
            )
        )

    for frm in forms:
        matches = [
            frx
            for frx in resources
            if frx.root.index == frm.root.index
            and _same_form_stem(frm.path, frx.path)
        ]
        if len(matches) != 1:
            diagnostics.append(
                _diagnostic(
                    "FORM_FRX_MISSING" if not matches else "FORM_FRX_DUPLICATE",
                    frm.path,
                    (
                        "Form requires one exact same-stem FRX"
                        if not matches
                        else "Form has more than one exact same-stem FRX"
                    ),
                )
            )
            continue
        frx = matches[0]
        consumed_resources.add((frx.root.index, frx.path))
        if frm.path in invalid_paths or frx.path in invalid_paths:
            continue
        vb_name = _form_identity(frm, frx, None, diagnostics)
        if vb_name is None:
            continue
        built.append(
            _discovered_component(
                frm,
                "user_form",
                vb_name,
                (frm.as_member("frm"), frx.as_member("frx")),
            )
        )

    for frx in resources:
        if (frx.root.index, frx.path) not in consumed_resources:
            diagnostics.append(
                _diagnostic(
                    "FORM_FRX_ORPHAN",
                    frx.path,
                    "FRX has no exact same-stem Form",
                )
            )
    return built


def _exclude_identity_collisions(
    built: list[_BuiltComponent], diagnostics: list[Diagnostic]
) -> list[_BuiltComponent]:
    excluded: set[int] = set()

    by_source_id: dict[str, list[int]] = defaultdict(list)
    by_vb_name: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, item in enumerate(built):
        by_source_id[item.component.source_id].append(index)
        by_vb_name[(item.side, item.component.vb_name.casefold())].append(index)

    for source_id in sorted(by_source_id):
        indices = by_source_id[source_id]
        if len(indices) < 2:
            continue
        excluded.update(indices)
        paths = tuple(
            sorted(built[index].component.members[0].path for index in indices)
        )
        diagnostics.append(
            _diagnostic(
                "DUPLICATE_SOURCE_ID",
                paths[0],
                f"source_id is not unique: {source_id}",
                paths=paths,
            )
        )

    for (_side, folded_name), indices in sorted(by_vb_name.items()):
        if len(indices) < 2:
            continue
        excluded.update(indices)
        paths = tuple(
            sorted(built[index].component.members[0].path for index in indices)
        )
        diagnostics.append(
            _diagnostic(
                "DUPLICATE_VB_NAME",
                paths[0],
                f"VB_Name is not unique (case-insensitive): {folded_name}",
                paths=paths,
            )
        )

    return [item for index, item in enumerate(built) if index not in excluded]


def scan_inputs(
    snapshot: InputSnapshot,
    manifests: ManifestSet,
    repo: GitRepository,
) -> Inventory:
    """Inventory exact candidate Git blobs or non-formal worktree diagnostics."""
    diagnostics = list(manifests.report.diagnostics)
    raw_members = _read_members(snapshot, manifests, repo, diagnostics)
    invalid_paths = _invalid_paths(raw_members, diagnostics)
    explicit, claimed_paths = _explicit_components(
        snapshot,
        manifests,
        raw_members,
        invalid_paths,
        diagnostics,
    )
    discovered = _discovered_components(
        raw_members,
        claimed_paths,
        invalid_paths,
        diagnostics,
    )
    valid = _exclude_identity_collisions(explicit + discovered, diagnostics)
    components = tuple(
        sorted(
            (item.component for item in valid),
            key=lambda component: (component.source_id, component.vb_name),
        )
    )
    return Inventory(
        components=components,
        report=ValidationReport(tuple(diagnostics)).sorted(),
        formal_eligible=(
            snapshot.mode is SnapshotMode.CANDIDATE
            and snapshot.formal_eligible
        ),
    )
