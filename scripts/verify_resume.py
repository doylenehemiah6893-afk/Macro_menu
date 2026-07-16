#!/usr/bin/env python3
"""Run the fresh-clone reproducibility checks and write one canonical receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


_CAPTURE_LIMIT = 32 * 1024
_RECEIPT = "reproducibility-receipt.json"


class ResumeVerificationError(RuntimeError):
    """A stable, operator-facing orchestration failure."""


def _canonical_bytes(document: object) -> bytes:
    return (
        json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")


def _bounded(data: bytes) -> tuple[str, bool]:
    truncated = len(data) > _CAPTURE_LIMIT
    if truncated:
        data = data[:_CAPTURE_LIMIT]
    return data.decode("utf-8", errors="replace"), truncated


def _execute_stage(
    stage: str, argv: list[str], cwd: Path, *, timeout: float = 1800
) -> dict[str, object]:
    """Execute one explicit command without shell interpretation."""

    try:
        with tempfile.TemporaryFile(dir=cwd) as stdout_file, tempfile.TemporaryFile(dir=cwd) as stderr_file:
            process = subprocess.Popen(argv, cwd=cwd, stdout=stdout_file, stderr=stderr_file)
            timed_out = False
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                returncode = process.wait()
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout_bytes = stdout_file.read(_CAPTURE_LIMIT + 1)
            stderr_bytes = stderr_file.read(_CAPTURE_LIMIT + 1)
    except OSError:
        return {
            "stage": stage,
            "ok": False,
            "returncode": None,
            "stdout": "",
            "stderr": "COMMAND_NOT_STARTED",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "diagnostic": "COMMAND_NOT_STARTED",
        }
    stdout, stdout_truncated = _bounded(stdout_bytes)
    stderr, stderr_truncated = _bounded(stderr_bytes)
    return {
        "stage": stage,
        "ok": returncode == 0 and not timed_out,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "diagnostic": "COMMAND_TIMEOUT" if timed_out else None,
    }


def _json_stdout(record: dict[str, object]) -> dict[str, object] | None:
    try:
        document = json.loads(str(record["stdout"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _file_map(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise ResumeVerificationError("KIT_TREE_INVALID")
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise ResumeVerificationError("KIT_TREE_INVALID")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def _compare_builds(
    first: dict[str, str], second: dict[str, str]
) -> dict[str, object]:
    """Compare every Kit file plus the deterministic ZIP and sidecar bytes."""

    try:
        if _file_map(Path(first["kit_dir"])) != _file_map(Path(second["kit_dir"])):
            return {"stage": "compare", "ok": False, "diagnostic": "KIT_TREE_MISMATCH"}
        first_zip = Path(first["zip_path"])
        second_zip = Path(second["zip_path"])
        if first_zip.read_bytes() != second_zip.read_bytes():
            return {"stage": "compare", "ok": False, "diagnostic": "KIT_ZIP_MISMATCH"}
        if first_zip.with_name(first_zip.name + ".sha256").read_bytes() != second_zip.with_name(
            second_zip.name + ".sha256"
        ).read_bytes():
            return {"stage": "compare", "ok": False, "diagnostic": "KIT_SIDECAR_MISMATCH"}
    except (KeyError, OSError, ResumeVerificationError):
        return {"stage": "compare", "ok": False, "diagnostic": "KIT_COMPARISON_INVALID"}
    return {
        "stage": "compare",
        "ok": True,
        "diagnostic": None,
        "kit_tree_sha256": hashlib.sha256(
            _canonical_bytes(_file_map(Path(first["kit_dir"])))
        ).hexdigest(),
        "kit_zip_sha256": hashlib.sha256(Path(first["zip_path"]).read_bytes()).hexdigest(),
        "kit_sidecar_sha256": hashlib.sha256(
            Path(first["zip_path"] + ".sha256").read_bytes()
        ).hexdigest(),
    }


def _build_artifacts(
    record: dict[str, object], expected_root: Path
) -> dict[str, str] | None:
    document = _json_stdout(record)
    if document is None:
        return None
    try:
        kit_dir = Path(str(document["kit_dir"])).resolve()
        zip_path = Path(str(document["zip_path"])).resolve()
    except (KeyError, OSError):
        return None
    expected = expected_root.resolve()
    if kit_dir.parent != expected or zip_path.parent != expected:
        return None
    if not kit_dir.is_dir() or not zip_path.is_file():
        return None
    return {"kit_dir": os.fspath(kit_dir), "zip_path": os.fspath(zip_path)}


def _atomic_publish(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        temporary.unlink()
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _write_receipt(output_root: Path, receipt: dict[str, object]) -> None:
    path = output_root / _RECEIPT
    try:
        _atomic_publish(path, _canonical_bytes(receipt))
    except OSError as error:
        raise ResumeVerificationError("RECEIPT_WRITE_FAILED") from error


def verify_resume(
    repo_root: Path | str,
    state_path: Path | str,
    output_root: Path | str,
) -> dict[str, object]:
    """Verify governed implementation and deterministic Kit generation."""

    repo = Path(repo_root).resolve()
    state_file = Path(state_path)
    if not state_file.is_absolute():
        state_file = repo / state_file
    output = Path(output_root).resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ResumeVerificationError("OUTPUT_EXISTS") from error
    except OSError as error:
        raise ResumeVerificationError("OUTPUT_CREATE_FAILED") from error

    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        receipt = _failed_receipt("state-check", [], "STATE_INVALID")
        _write_receipt(output, receipt)
        return receipt

    commands: list[tuple[str, list[str]]] = [
        ("lock-check", ["uv", "lock", "--check"]),
        (
            "doctor",
            [
                "uv", "run", "macro-menu-build", "doctor", "--state",
                os.fspath(state_file), "--format", "json",
            ],
        ),
        ("pytest", ["uv", "run", "pytest", "-q"]),
        ("inventory", ["uv", "run", "macro-menu-build", "inventory", "--format", "json"]),
        ("check", ["uv", "run", "macro-menu-build", "check", "--format", "json"]),
        (
            "build-1",
            ["uv", "run", "macro-menu-build", "build-kit", "--output-root", os.fspath(output / "build-1"), "--format", "json"],
        ),
        (
            "build-2",
            ["uv", "run", "macro-menu-build", "build-kit", "--output-root", os.fspath(output / "build-2"), "--format", "json"],
        ),
    ]
    stages: list[dict[str, object]] = []
    builds: list[dict[str, str]] = []
    for stage, argv in commands:
        record = _execute_stage(stage, argv, repo)
        stages.append(record)
        if not record.get("ok"):
            receipt = _failed_receipt(
                stage, stages, str(record.get("diagnostic") or "COMMAND_FAILED")
            )
            _write_receipt(output, receipt)
            return receipt
        if stage.startswith("build-"):
            artifacts = _build_artifacts(record, output / stage)
            if artifacts is None:
                receipt = _failed_receipt(stage, stages, "BUILD_RECEIPT_INVALID")
                _write_receipt(output, receipt)
                return receipt
            builds.append(artifacts)

    verification_commands = (
        ("verify-dir-1", builds[0]["kit_dir"]),
        ("verify-zip-1", builds[0]["zip_path"]),
        ("verify-dir-2", builds[1]["kit_dir"]),
        ("verify-zip-2", builds[1]["zip_path"]),
    )
    for stage, target in verification_commands:
        record = _execute_stage(
            stage,
            ["uv", "run", "macro-menu-build", "verify-kit", target, "--format", "json"],
            repo,
        )
        stages.append(record)
        if not record.get("ok"):
            receipt = _failed_receipt(
                stage, stages, str(record.get("diagnostic") or "COMMAND_FAILED")
            )
            _write_receipt(output, receipt)
            return receipt

    comparison = _compare_builds(builds[0], builds[1])
    stages.append(comparison)
    if not comparison["ok"]:
        receipt = _failed_receipt("compare", stages, str(comparison["diagnostic"]))
        _write_receipt(output, receipt)
        return receipt

    collector = _execute_stage(
        "collector-smoke",
        [
            "uv", "run", "python", os.fspath(repo / "scripts/collector_smoke.py"),
            "--repo-root", os.fspath(repo),
            "--output", os.fspath(output / "collector-smoke-receipt.json"),
        ],
        repo,
    )
    stages.append(collector)
    if not collector.get("ok"):
        receipt = _failed_receipt(
            "collector-smoke", stages,
            str(collector.get("diagnostic") or "COMMAND_FAILED"),
        )
        _write_receipt(output, receipt)
        return receipt

    active_bundle = state.get("active_bundle_path")
    receipt = {
        "schema_version": 1,
        "ok": True,
        "failed_stage": None,
        "diagnostics": [],
        "stages": stages,
        "operator_bundle_status": "available" if active_bundle else "not-built",
        "active_bundle_path": active_bundle,
        "release_eligible": False,
        "compile_status": "not-run",
        "target_case_status": "not-run",
    }
    _write_receipt(output, receipt)
    return receipt


def _failed_receipt(
    stage: str, stages: list[dict[str, object]], diagnostic: str
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "ok": False,
        "failed_stage": stage,
        "diagnostics": [{"code": diagnostic, "stage": stage}],
        "stages": stages,
        "operator_bundle_status": "not-built",
        "active_bundle_path": None,
        "release_eligible": False,
        "compile_status": "not-run",
        "target_case_status": "not-run",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = verify_resume(args.repo_root, args.state, args.output_root)
    except ResumeVerificationError as error:
        print(str(error), file=sys.stderr)
        return 4
    print(_canonical_bytes(receipt).decode("ascii"), end="")
    return 0 if receipt["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
