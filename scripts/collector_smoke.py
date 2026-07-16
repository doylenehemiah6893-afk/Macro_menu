#!/usr/bin/env python3
"""Build, inspect and execute the pinned deterministic target collector pyz."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

from catvba_refactor.macro_build.errors import BuildKitError
from catvba_refactor.macro_build.git_objects import GitRepository
from catvba_refactor.macro_build.operator_bundle import build_target_collector_pyz
from catvba_refactor.target_collector.canonical import canonical_json_bytes


Builder = Callable[[Path, str], tuple[bytes, tuple[tuple[str, bytes], ...]]]
Runner = Callable[[list[str], Path], dict[str, object]]


def _run(
    argv: list[str], cwd: Path, *, timeout: float = 120
) -> dict[str, object]:
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
            stdout = stdout_file.read(8193)
            stderr = stderr_file.read(8193)
    except OSError:
        return {
            "returncode": None, "stdout": "", "stderr": "COMMAND_NOT_STARTED",
            "stdout_truncated": False, "stderr_truncated": False, "timed_out": False,
        }
    return {
        "returncode": returncode,
        "stdout": stdout[:8192].decode("utf-8", errors="replace"),
        "stderr": stderr[:8192].decode("utf-8", errors="replace"),
        "stdout_truncated": len(stdout) > 8192,
        "stderr_truncated": len(stderr) > 8192,
        "timed_out": timed_out,
    }


def _validate_archive(
    pyz_bytes: bytes, sources: tuple[tuple[str, bytes], ...]
) -> str | None:
    expected = {
        "__main__.py": (
            b"from catvba_refactor.target_collector.cli import main\n"
            b"raise SystemExit(main())\n"
        ),
        "catvba_refactor/__init__.py": b"",
        **{
            f"catvba_refactor/target_collector/{path}": data
            for path, data in sources
        },
    }
    try:
        import io

        with zipfile.ZipFile(io.BytesIO(pyz_bytes)) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)) or set(names) != set(expected):
                return "COLLECTOR_PYZ_MEMBER_SET_INVALID"
            for name, data in expected.items():
                if archive.read(name) != data:
                    return "COLLECTOR_PYZ_MEMBER_DRIFT"
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile):
        return "COLLECTOR_PYZ_INVALID"
    return None


def _atomic_publish(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _write_receipt(path: Path, receipt: dict[str, object]) -> None:
    _atomic_publish(path, canonical_json_bytes(receipt))


def collector_smoke(
    repo_root: Path | str,
    output: Path | str,
    *,
    pyz_output: Path | str | None = None,
    _builder: Builder = build_target_collector_pyz,
    _runner: Runner = _run,
) -> dict[str, object]:
    repo = Path(repo_root).resolve()
    receipt_path = Path(output).resolve()
    receipt: dict[str, object] = {
        "schema_version": 1,
        "ok": False,
        "diagnostics": [],
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "release_eligible": False,
    }
    try:
        commit = GitRepository(repo).resolve_commit("HEAD")
        pyz_bytes, sources = _builder(repo, commit)
    except (BuildKitError, OSError, ValueError):
        receipt["diagnostics"] = [{"code": "COLLECTOR_PYZ_BUILD_FAILED"}]
        _write_receipt(receipt_path, receipt)
        return receipt
    archive_error = _validate_archive(pyz_bytes, sources)
    if archive_error:
        receipt["diagnostics"] = [{"code": archive_error}]
        _write_receipt(receipt_path, receipt)
        return receipt

    with tempfile.TemporaryDirectory(prefix="collector-smoke-", dir=receipt_path.parent) as temporary:
        root = Path(temporary)
        pyz = root / "target-discovery.pyz"
        pyz.write_bytes(pyz_bytes)
        help_result = _runner([sys.executable, os.fspath(pyz), "--help"], repo)
        if help_result.get("returncode") != 0:
            receipt["diagnostics"] = [{"code": "COLLECTOR_PYZ_HELP_FAILED"}]
            _write_receipt(receipt_path, receipt)
            return receipt
        fixture_result = _runner(
            [sys.executable, os.fspath(pyz), "status", "--capture", os.fspath(root / "missing-capture")],
            repo,
        )
        try:
            fixture_document = json.loads(str(fixture_result.get("stdout", "")))
            fixture_codes = [item["code"] for item in fixture_document["diagnostics"]]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            fixture_document = {}
            fixture_codes = []
        if (
            fixture_result.get("returncode") != 3
            or fixture_document.get("ok") is not False
            or fixture_codes != ["COLLECTOR_PATH_UNSAFE"]
        ):
            receipt["diagnostics"] = [{"code": "COLLECTOR_SYNTHETIC_FIXTURE_UNEXPECTED"}]
            _write_receipt(receipt_path, receipt)
            return receipt

    receipt.update(
        {
            "ok": True,
            "diagnostics": [],
            "collector_source_commit": commit,
            "collector_source_file_count": len(sources),
            "collector_pyz_sha256": hashlib.sha256(pyz_bytes).hexdigest(),
            "pyz_help_status": "pass",
            "synthetic_fixture_status": "expected-fail-closed-pass",
        }
    )
    published_pyz: Path | None = None
    try:
        if pyz_output is not None:
            destination = Path(pyz_output).resolve()
            _atomic_publish(destination, pyz_bytes)
            published_pyz = destination
        _write_receipt(receipt_path, receipt)
    except BaseException:
        if published_pyz is not None:
            try:
                published_pyz.unlink()
            except OSError:
                pass
        raise
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pyz-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = collector_smoke(
            args.repo_root, args.output, pyz_output=getattr(args, "pyz_output", None)
        )
    except FileExistsError:
        print("COLLECTOR_SMOKE_OUTPUT_EXISTS", file=sys.stderr)
        return 4
    print(canonical_json_bytes(receipt).decode("ascii"), end="")
    return 0 if receipt["ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
