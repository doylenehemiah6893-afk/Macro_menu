from pathlib import Path
import subprocess
import tomllib

ROOT = Path(__file__).parents[2]


def test_root_project_is_the_only_python_project() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    assert project["project"]["scripts"]["macro-menu-build"] == (
        "catvba_refactor.macro_build.cli:main"
    )
    assert not (ROOT / "catvba_refactor/pyproject.toml").exists()
    assert not (ROOT / "catvba_refactor/uv.lock").exists()


def test_generated_paths_are_ignored() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "catvba_refactor/build/probe"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_vba_attributes_preserve_bytes() -> None:
    result = subprocess.run(
        ["git", "check-attr", "text", "--", "probe.bas", "probe.frx"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "probe.bas: text: unset" in result.stdout
    assert "probe.frx: text: unset" in result.stdout
