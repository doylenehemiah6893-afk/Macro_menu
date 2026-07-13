import subprocess
from pathlib import Path

import pytest

from catvba_refactor.macro_build.errors import InfrastructureError, SourceError
from catvba_refactor.macro_build.git_objects import GitRepository, freeze_snapshot
from catvba_refactor.macro_build.model import SnapshotMode


PROJECT = {
    "upstream_repository": "verysolecd/Macro_menu",
    "upstream_ref": "dev",
    "fork_repository": "doylenehemiah6893-afk/Macro_menu",
    "fork_dev_ref": "dev",
    "work_repository": "doylenehemiah6893-afk/Macro_menu",
    "work_branch": "codex/dev-review-report",
    "governed_paths": ["Src", "catvba_refactor"],
}


def _git(repo_path: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_candidate_reads_committed_blob_and_rejects_dirty_governed_path(
    git_repo: tuple[Path, str],
) -> None:
    repo_path, dev_oid = git_repo
    repo = GitRepository(repo_path)

    assert repo.read_blob(dev_oid, "Src/A.bas").startswith(
        b'Attribute VB_Name = "A"'
    )
    (repo_path / "Src/A.bas").write_bytes(b"dirty")
    assert repo.status_for(("Src", "catvba_refactor")) == (" M Src/A.bas",)

    with pytest.raises(
        SourceError, match="^candidate snapshot requires a clean governed tree$"
    ):
        freeze_snapshot(repo, PROJECT, "a" * 64, "0.1.0")


def test_worktree_snapshot_is_never_formal(
    git_repo: tuple[Path, str],
) -> None:
    repo_path, dev_oid = git_repo
    (repo_path / "Src/A.bas").write_bytes(b"dirty diagnostic data")

    snapshot = freeze_snapshot(
        GitRepository(repo_path), PROJECT, "a" * 64, "0.1.0", worktree=True
    )

    assert snapshot.mode is SnapshotMode.WORKTREE
    assert snapshot.formal_eligible is False
    assert snapshot.upstream_commit == snapshot.fork_dev_commit == dev_oid


def test_candidate_snapshot_records_exact_commits_and_tree_once(
    git_repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path, dev_oid = git_repo
    repo = GitRepository(repo_path)
    calls: list[str] = []
    resolve_commit = repo.resolve_commit

    def record_resolve(ref: str) -> str:
        calls.append(ref)
        return resolve_commit(ref)

    monkeypatch.setattr(repo, "resolve_commit", record_resolve)
    snapshot = freeze_snapshot(repo, PROJECT, "b" * 64, "0.1.0")

    assert calls == ["HEAD", "dev"]
    assert snapshot.mode is SnapshotMode.CANDIDATE
    assert snapshot.formal_eligible is True
    assert snapshot.upstream_repository == PROJECT["upstream_repository"]
    assert snapshot.upstream_ref == PROJECT["upstream_ref"]
    assert snapshot.upstream_commit == snapshot.fork_dev_commit == dev_oid
    assert snapshot.fork_repository == PROJECT["fork_repository"]
    assert snapshot.work_repository == PROJECT["work_repository"]
    assert snapshot.work_branch == PROJECT["work_branch"]
    assert snapshot.work_commit == dev_oid
    assert snapshot.work_tree == repo.tree_oid(dev_oid)
    assert snapshot.manifest_digest == "b" * 64
    assert snapshot.tool_version == "0.1.0"


def test_snapshot_rejects_fork_dev_that_differs_from_upstream_cutoff(
    git_repo: tuple[Path, str],
) -> None:
    repo_path, _ = git_repo
    extra_path = repo_path / "Src/B.bas"
    extra_path.write_bytes(b'Attribute VB_Name = "B"\r\n')
    _git(repo_path, "add", "Src/B.bas")
    _git(repo_path, "commit", "-m", "fixture: advance work branch")
    project = PROJECT | {"upstream_ref": "HEAD"}

    with pytest.raises(
        SourceError, match="^fork dev does not match the declared upstream cutoff$"
    ):
        freeze_snapshot(GitRepository(repo_path), project, "c" * 64, "0.1.0")


def test_lists_and_reads_committed_paths_with_spaces_and_non_ascii(
    git_repo: tuple[Path, str],
) -> None:
    repo_path, _ = git_repo
    expected_data = b'Attribute VB_Name = "Spaced"\r\n'
    paths = ("Src/a spaced name.bas", "Src/\u4e2d\u6587\u6a21\u5757.bas")
    for path in paths:
        (repo_path / path).write_bytes(expected_data)
    _git(repo_path, "add", *paths)
    _git(repo_path, "commit", "-m", "fixture: add portable names")

    repo = GitRepository(repo_path)
    commit = repo.resolve_commit("HEAD")
    entries = repo.list_tree(commit, "Src")

    assert tuple(path for path, _ in entries) == (
        "Src/A.bas",
        "Src/a spaced name.bas",
        "Src/\u4e2d\u6587\u6a21\u5757.bas",
    )
    entries_by_path = dict(entries)
    for path in paths:
        assert repo.read_blob(commit, path) == expected_data
        assert len(entries_by_path[path]) == 40


def test_status_records_are_unquoted_and_sorted_by_path(
    git_repo: tuple[Path, str],
) -> None:
    repo_path, _ = git_repo
    (repo_path / "Src/z spaced.bas").write_bytes(b"z")
    (repo_path / "Src/\u4e2d\u6587.bas").write_bytes(b"zh")
    (repo_path / "Src/A.bas").write_bytes(b"modified")

    assert GitRepository(repo_path).status_for(("Src",)) == (
        " M Src/A.bas",
        "?? Src/z spaced.bas",
        "?? Src/\u4e2d\u6587.bas",
    )


def test_git_failure_reports_subcommand_and_return_code_without_environment(
    git_repo: tuple[Path, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo_path, _ = git_repo
    monkeypatch.setenv("MACRO_MENU_SECRET", "must-not-leak")

    with pytest.raises(InfrastructureError) as raised:
        GitRepository(repo_path).resolve_commit("missing-ref")

    message = str(raised.value)
    assert "git rev-parse" in message
    assert "return code 128" in message
    assert "MACRO_MENU_SECRET" not in message
    assert "must-not-leak" not in message
