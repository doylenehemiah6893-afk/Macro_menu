from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path


_APPROVED_REMOTES = frozenset(
    {
        "https://github.com/doylenehemiah6893-afk/Macro_menu",
        "https://github.com/doylenehemiah6893-afk/Macro_menu.git",
        "git@github.com:doylenehemiah6893-afk/Macro_menu",
        "git@github.com:doylenehemiah6893-afk/Macro_menu.git",
    }
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authenticate and bootstrap a Macro_menu resume clone"
    )
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    return parser


def _stdlib_preflight(repo_root: Path, state_path: Path) -> None:
    """Authenticate the repository without importing third-party packages."""
    if platform.python_implementation() != "CPython" or sys.version_info[:2] != (3, 12):
        raise SystemExit("bootstrap requires CPython 3.12")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        lock_path = repo_root / "uv.lock"
        lock_digest = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit("bootstrap state or uv.lock is unreadable") from error
    if (
        not isinstance(state, dict)
        or state.get("repository") != "doylenehemiah6893-afk/Macro_menu"
        or state.get("branch") != "codex/dev-review-report"
        or state.get("approved_cutoff")
        != "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"
        or state.get("lock_digest") != lock_digest
    ):
        raise SystemExit("bootstrap state identity or lock digest is invalid")
    _stdlib_git_preflight(repo_root, state_path, state)


def _sync_dependencies(repo_root: Path) -> None:
    environment = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "UV_CACHE_DIR", "UV_LINK_MODE")
        if name in os.environ
    }
    environment["UV_PROJECT_ENVIRONMENT"] = os.fspath(repo_root / ".venv")
    pinned_head = _git(repo_root, "rev-parse", "--verify", "HEAD^{commit}")
    with tempfile.TemporaryDirectory(prefix="macro-menu-bootstrap-") as temporary:
        project = Path(temporary)
        try:
            project.chmod(0o700)
            for name in ("pyproject.toml", "uv.lock"):
                target = project / name
                target.write_bytes(
                    _git_bytes(repo_root, "show", f"{pinned_head}:{name}")
                )
                target.chmod(0o600)
            result = subprocess.run(
                [
                    "uv",
                    "sync",
                    "--project",
                    os.fspath(project),
                    "--frozen",
                    "--no-install-project",
                ],
                cwd=project,
                check=False,
                env=environment,
            )
        except OSError as error:
            raise SystemExit("uv sync --frozen could not be started") from error
        if result.returncode:
            raise SystemExit(f"uv sync --frozen returned {result.returncode}")


def _git_environment() -> dict[str, str]:
    return {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT")
        if name in os.environ
    } | {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_LITERAL_PATHSPECS": "1",
    }


def _git(repo_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            env=_git_environment(),
        )
    except OSError as error:
        raise SystemExit("git preflight could not be started") from error
    if result.returncode:
        raise SystemExit(f"git {arguments[0]} preflight failed")
    return result.stdout.strip()


def _git_bytes(repo_root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=False,
            capture_output=True,
            env=_git_environment(),
        )
    except OSError as error:
        raise SystemExit("git snapshot read could not be started") from error
    if result.returncode:
        raise SystemExit(f"git {arguments[0]} snapshot read failed")
    return result.stdout


def _stdlib_git_preflight(
    repo_root: Path, state_path: Path, state: dict[str, object]
) -> None:
    cutoff = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"
    if not (repo_root / ".git").exists():
        raise SystemExit("bootstrap requires a complete Git clone")
    if Path(_git(repo_root, "rev-parse", "--show-toplevel")).resolve() != repo_root:
        raise SystemExit("bootstrap repo-root is not the Git toplevel")
    if _git(repo_root, "rev-parse", "--is-shallow-repository") != "false":
        raise SystemExit("bootstrap rejects shallow clones")
    remote = _git(repo_root, "remote", "get-url", "origin")
    if remote not in _APPROVED_REMOTES:
        raise SystemExit("bootstrap origin repository is not approved")
    if _git(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD") != state["branch"]:
        raise SystemExit("bootstrap branch is not approved")
    if _git(repo_root, "for-each-ref", "--format=%(refname)", "refs/replace"):
        raise SystemExit("bootstrap rejects Git replacement refs")
    local_dev = _git(
        repo_root,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        "refs/heads/dev",
    )
    if local_dev and local_dev != f"refs/heads/dev\0{cutoff}":
        raise SystemExit("bootstrap local dev conflicts with the approved cutoff")
    if _git(repo_root, "rev-parse", "--verify", f"{cutoff}^{{commit}}") != cutoff:
        raise SystemExit("bootstrap approved cutoff object is unavailable")
    if (
        _git(repo_root, "rev-parse", f"{cutoff}:Src")
        != "0f7263465cdd5ecd7dbe5ceff090cad859cc1173"
        or _git(repo_root, "rev-parse", f"{cutoff}:resources")
        != "720c20864bff3c48694acaf780b50518f49b9a60"
    ):
        raise SystemExit("bootstrap cutoff trees do not match the intake")
    evidence = state.get("evidence_commit")
    evidence_tree = state.get("evidence_tree")
    head = _git(repo_root, "rev-parse", "HEAD")
    if evidence is None and evidence_tree is None:
        if state.get("revocation_status") != "preparation":
            raise SystemExit("bootstrap state does not identify evidence objects")
    elif isinstance(evidence, str) and isinstance(evidence_tree, str):
        if _git(repo_root, "rev-parse", f"{evidence}^{{tree}}") != evidence_tree:
            raise SystemExit("bootstrap evidence tree does not match state")
        _git(repo_root, "merge-base", "--is-ancestor", evidence, head)
        if head != evidence:
            changed = _git(repo_root, "diff", "--name-only", evidence, head).splitlines()
            if any(
                not path.startswith(("Docs/", "artifacts/", "resume/"))
                for path in changed
            ):
                raise SystemExit("bootstrap delivery commits changed implementation inputs")
    else:
        raise SystemExit("bootstrap state evidence objects are incomplete")
    intake = repo_root / "catvba_refactor/intake/records/2026-07-13-initial-baseline.json"
    try:
        intake_digest = hashlib.sha256(intake.read_bytes()).hexdigest()
    except OSError:
        raise SystemExit("bootstrap intake record is unreadable") from None
    if intake_digest != (
        "ee1405f0e24573566126fabeb1f5a5fdf2b5541082733f9171b54c94c35a9f19"
    ) or state.get("intake_record_digest") != (
        "ee1405f0e24573566126fabeb1f5a5fdf2b5541082733f9171b54c94c35a9f19"
    ):
        raise SystemExit("bootstrap intake digest is invalid")
    try:
        allowed_untracked = state_path.resolve().relative_to(repo_root).as_posix()
    except ValueError as error:
        raise SystemExit("bootstrap state must be inside the repository") from error
    for record in _git(
        repo_root, "status", "--porcelain=v1", "--untracked-files=all"
    ).splitlines():
        if record.startswith("?? ") and record[3:] == allowed_untracked:
            continue
        raise SystemExit("bootstrap working tree is not clean")


def _locked_interpreter(repo_root: Path) -> Path:
    interpreter = (
        repo_root / ".venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else repo_root / ".venv" / "bin" / "python"
    )
    if not interpreter.is_file():
        raise SystemExit("locked project interpreter is unavailable")
    return interpreter


def _run_locked(repo_root: Path, state_path: Path) -> int:
    result = subprocess.run(
        [
            os.fspath(_locked_interpreter(repo_root)),
            os.fspath(Path(__file__).resolve()),
            "--repo-root",
            os.fspath(repo_root),
            "--state",
            os.fspath(state_path),
        ],
        cwd=repo_root,
        check=False,
    )
    return result.returncode


def _running_locked_interpreter(repo_root: Path) -> bool:
    try:
        interpreter = _locked_interpreter(repo_root)
        running_prefix = _normalized_runtime_path(sys.prefix)
        base_prefix = _normalized_runtime_path(sys.base_prefix)
        expected_prefix = _normalized_runtime_path(interpreter.parents[1])
        return running_prefix != base_prefix and running_prefix == expected_prefix
    except SystemExit:
        return False


def _normalized_runtime_path(
    path: str | os.PathLike[str], *, windows: bool | None = None
) -> str:
    if windows is None:
        windows = os.name == "nt"
    path_module = ntpath if windows else os.path
    return path_module.normcase(path_module.abspath(os.fspath(path)))


def _run_authenticated_bootstrap(repo_root: Path, state_path: Path) -> int:
    from catvba_refactor.macro_build.resume import bootstrap_repository

    report = bootstrap_repository(repo_root, state_path)
    document = {
        "ok": report.ok,
        **dict(report.facts),
        "diagnostics": [
            {"code": item.code, "path": item.path, "message": item.message}
            for item in report.diagnostics
        ],
    }
    print(json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if report.ok else 4


def _bootstrap_process(repo_root: Path, state_path: Path) -> int:
    _stdlib_preflight(repo_root, state_path)
    _sync_dependencies(repo_root)
    _stdlib_preflight(repo_root, state_path)
    if _running_locked_interpreter(repo_root):
        return _run_authenticated_bootstrap(repo_root, state_path)
    return _run_locked(repo_root, state_path)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    sys.path.insert(0, str(repo_root))
    state_path = args.state
    if not state_path.is_absolute():
        state_path = repo_root / state_path
    return _bootstrap_process(repo_root, state_path)


if __name__ == "__main__":
    raise SystemExit(main())
