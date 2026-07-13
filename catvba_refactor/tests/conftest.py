import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> tuple[Path, str]:
    repo_path = tmp_path / "fixture repo"
    source_path = repo_path / "Src/A.bas"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(
        b'Attribute VB_Name = "A"\r\n'
        b"Public Sub Main()\r\n"
        b"End Sub\r\n"
    )

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

    dev_oid = subprocess.run(
        ("git", "rev-parse", "dev"),
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo_path, dev_oid
