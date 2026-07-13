from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, overload

from catvba_refactor.macro_build.errors import InfrastructureError, SourceError
from catvba_refactor.macro_build.model import InputSnapshot, SnapshotMode


class GitRepository:
    """Read committed objects and status from a local Git repository."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

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
        records = tuple(
            record.decode("utf-8", errors="surrogateescape")
            for record in output.split(b"\0")
            if record
        )
        return tuple(sorted(records, key=_status_path))


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
) -> InputSnapshot:
    """Freeze the local refs that define a candidate or diagnostic snapshot."""
    work_commit = repo.resolve_commit("HEAD")
    upstream_ref = project["upstream_ref"]
    fork_dev_ref = project["fork_dev_ref"]
    upstream_commit = repo.resolve_commit(upstream_ref)
    if fork_dev_ref == upstream_ref:
        fork_dev_commit = upstream_commit
    else:
        fork_dev_commit = repo.resolve_commit(fork_dev_ref)
    work_tree = repo.tree_oid(work_commit)

    if not worktree and repo.status_for(tuple(project["governed_paths"])):
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
