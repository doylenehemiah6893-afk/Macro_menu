from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, overload

from catvba_refactor.macro_build.errors import InfrastructureError, SourceError
from catvba_refactor.macro_build.model import InputSnapshot, SnapshotMode
from catvba_refactor.macro_build.portable_paths import validate_portable_ascii_paths


def _git_environment() -> dict[str, str]:
    """Build the minimal environment permitted for local Git reads."""
    return {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT")
        if name in os.environ
    } | {
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_LITERAL_PATHSPECS": "1",
    }


class GitRepository:
    """Read committed objects and status from a local Git repository."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def command_environment(self) -> dict[str, str]:
        """Return a fresh copy of the fail-closed Git environment."""
        return _git_environment()

    @overload
    def _run(self, *args: str, text: Literal[False] = False) -> bytes: ...

    @overload
    def _run(self, *args: str, text: Literal[True]) -> str: ...

    def _run(self, *args: str, text: bool = False) -> bytes | str:
        """Run a read-only Git subcommand without a shell."""
        subcommand = args[0] if args else "<missing>"
        try:
            result = subprocess.run(
                ["git", *args],
                cwd=self.root,
                check=False,
                capture_output=True,
                text=text,
                env=_git_environment(),
            )
        except OSError as exc:
            raise InfrastructureError(
                f"git {subcommand} could not be started ({type(exc).__name__})"
            ) from exc
        if result.returncode:
            raise InfrastructureError(
                f"git {subcommand} failed with return code {result.returncode}"
            )
        return result.stdout

    def replace_refs(self) -> tuple[str, ...]:
        """List replacement refs without allowing them to affect object reads."""
        output = self._run(
            "for-each-ref", "--format=%(refname)", "refs/replace", text=True
        )
        return tuple(sorted(line for line in output.splitlines() if line))

    def ref_oid(self, ref: str) -> str | None:
        """Resolve an exact ref name, returning ``None`` only when absent."""
        output = self._run(
            "for-each-ref", "--format=%(refname)%00%(objectname)", ref, text=True
        )
        matches = []
        for line in output.splitlines():
            name, separator, oid = line.partition("\0")
            if separator and name == ref:
                matches.append(oid)
        if len(matches) > 1:
            raise InfrastructureError("git for-each-ref returned duplicate exact refs")
        return matches[0] if matches else None

    def create_ref(self, ref: str, oid: str) -> None:
        """Create one absent ref using Git's compare-and-swap zero old OID."""
        self._run("update-ref", ref, oid, "0" * 40)

    def resolve_commit(self, ref: str) -> str:
        """Resolve a revision to its exact commit object ID."""
        return self._run(
            "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}", text=True
        ).strip()

    def tree_oid(self, commit: str) -> str:
        """Return the exact tree object ID for a commit."""
        return self._run(
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{commit}^{{tree}}",
            text=True,
        ).strip()

    def list_tree(self, commit: str, prefix: str) -> tuple[tuple[str, str], ...]:
        """List recursive tree paths and object IDs below a prefix."""
        output = self._run("ls-tree", "-rz", commit, "--", prefix)
        entries: list[tuple[str, str]] = []
        for record in output.split(b"\0"):
            if not record:
                continue
            try:
                metadata, raw_path = record.split(b"\t", 1)
                _mode, _object_type, raw_oid = metadata.split(b" ", 2)
                path = raw_path.decode("utf-8", errors="surrogateescape")
                oid = raw_oid.decode("ascii")
            except (UnicodeDecodeError, ValueError) as exc:
                raise InfrastructureError("git ls-tree returned malformed output") from exc
            entries.append((path, oid))
        return tuple(sorted(entries, key=lambda entry: entry[0]))

    def read_blob(self, commit: str, path: str) -> bytes:
        """Read a path exactly as stored in a committed tree."""
        return self._run("show", f"{commit}:{path}")

    def status_for(self, paths: tuple[str, ...]) -> tuple[str, ...]:
        """Return stable porcelain records for the governed paths."""
        output = self._run(
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *paths,
        )
        return _status_records(output)

    def tracked_status(self) -> tuple[str, ...]:
        """Return status records for tracked files across the entire checkout."""
        output = self._run(
            "status", "--porcelain=v1", "-z", "--untracked-files=no"
        )
        return _status_records(output)


def _status_records(output: bytes) -> tuple[str, ...]:
    fields = iter(output.split(b"\0"))
    records: list[str] = []
    for field in fields:
        if not field:
            continue
        if _is_rename_or_copy(field):
            second_path = next(fields, b"")
            if not second_path:
                raise InfrastructureError("git status returned malformed output")
            field = b"\0".join((field, second_path))
        records.append(field.decode("utf-8", errors="surrogateescape"))
    return tuple(sorted(records, key=_status_path))


def _is_rename_or_copy(record: bytes) -> bool:
    return len(record) >= 3 and (
        record[0:1] in (b"R", b"C") or record[1:2] in (b"R", b"C")
    )


def _status_path(record: str) -> str:
    if len(record) >= 3 and record[2] == " ":
        return record[3:]
    return record


def freeze_snapshot(
    repo: GitRepository,
    project: Mapping[str, Any],
    manifest_digest: str,
    tool_version: str,
    worktree: bool = False,
    expected_work_commit: str | None = None,
) -> InputSnapshot:
    """Freeze the local refs that define a candidate or diagnostic snapshot."""
    if repo.replace_refs():
        raise SourceError("replace refs are forbidden")
    governed_paths = tuple(project["governed_paths"])
    if not validate_portable_ascii_paths(governed_paths).ok:
        raise SourceError("governed paths must be repository-relative portable literals")
    current_head = repo.resolve_commit("HEAD")
    if expected_work_commit is not None and current_head != expected_work_commit:
        raise SourceError("formal input HEAD changed before snapshot freeze")
    work_commit = expected_work_commit or current_head
    upstream_ref = project["upstream_ref"]
    fork_dev_ref = project["fork_dev_ref"]
    upstream_commit = repo.resolve_commit(upstream_ref)
    if fork_dev_ref == upstream_ref:
        fork_dev_commit = upstream_commit
    else:
        fork_dev_commit = repo.resolve_commit(fork_dev_ref)
    work_tree = repo.tree_oid(work_commit)

    if not worktree and repo.status_for(governed_paths):
        raise SourceError("candidate snapshot requires a clean governed tree")
    if fork_dev_commit != upstream_commit:
        raise SourceError("fork dev does not match the declared upstream cutoff")

    return InputSnapshot(
        mode=SnapshotMode.WORKTREE if worktree else SnapshotMode.CANDIDATE,
        upstream_repository=project["upstream_repository"],
        upstream_ref=upstream_ref,
        upstream_commit=upstream_commit,
        fork_repository=project["fork_repository"],
        fork_dev_commit=fork_dev_commit,
        work_repository=project["work_repository"],
        work_branch=project["work_branch"],
        work_commit=work_commit,
        work_tree=work_tree,
        manifest_digest=manifest_digest,
        tool_version=tool_version,
        formal_eligible=not worktree,
    )
