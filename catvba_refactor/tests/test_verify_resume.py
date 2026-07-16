from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_resume_under_test", ROOT / "scripts/verify_resume.py"
)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _collector_smoke_module():
    path = ROOT / "scripts/collector_smoke.py"
    spec = importlib.util.spec_from_file_location("collector_smoke_under_test", path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _selector_module():
    path = ROOT / "scripts/select_operator_bundle.py"
    spec = importlib.util.spec_from_file_location("selector_under_test", path)
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def _issued_bundle(repo: Path) -> Path:
    root = repo / "artifacts/b28-discovery"
    bundles = root / "bundles"
    bundles.mkdir(parents=True)
    bundle = bundles / "stage"
    bundle.mkdir()
    now = datetime.now(UTC).replace(microsecond=0)
    handoff = {
        "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "handoff_id": "handoff-selector-fixture",
        "revocation_status": "active",
    }
    (bundle / "handoff.json").write_bytes(
        json.dumps(handoff, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii") + b"\n"
    )
    (bundle / "run-discovery.cmd").write_bytes(b"@echo off\r\n")
    (bundle / "target-discovery.pyz").write_bytes(b"fixture-pyz")
    (bundle / "receipts").mkdir()
    (bundle / "receipts/smoke.json").write_bytes(b'{"ok":true}\n')
    provenance = json.dumps(
        {
            "bundle_content_sha256": _fixture_content_digest(bundle),
            "active_ledger_source": "repository-active-handoff-ledger",
            "handoff_id": "handoff-selector-fixture",
            "schema_version": 1,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii") + b"\n"
    digest = hashlib.sha256(provenance).hexdigest()
    bundle_id = "bundle-" + digest[:24]
    (bundle / "provenance.json").write_bytes(provenance)
    _rewrite_sums(bundle)
    bundle.rename(bundles / bundle_id)
    bundle = bundles / bundle_id
    current = {
        "schema_version": 1,
        "bundle_id": bundle_id,
        "bundle_sha256": digest,
        "handoff_id": "handoff-selector-fixture",
    }
    (root / "CURRENT.json").write_text(
        json.dumps(current, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    (root / "active-handoff-ledger.json").write_text(
        json.dumps(
            {
                "active_handoff_ids": ["handoff-selector-fixture"],
                "captured_at": now.isoformat().replace("+00:00", "Z"),
                "schema_version": 1,
                "source": "repository-active-handoff-ledger",
                "withdrawn_handoff_ids": [],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n",
        encoding="ascii",
    )
    return bundle


def _rewrite_sums(bundle: Path) -> None:
    files = sorted(
        path for path in bundle.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    )
    (bundle / "SHA256SUMS").write_bytes(
        b"".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(bundle).as_posix()}\n".encode("ascii")
            for path in files
        )
    )


def _fixture_content_digest(bundle: Path) -> str:
    records = [
        {
            "path": path.relative_to(bundle).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": len(path.read_bytes()),
        }
        for path in sorted(bundle.rglob("*"))
        if path.is_file() and path.name not in {"provenance.json", "SHA256SUMS"}
    ]
    data = (json.dumps(records, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
    return hashlib.sha256(data).hexdigest()


def _write_build(root: Path, label: str = "same") -> dict[str, str]:
    kit = root / "kit-fixed"
    kit.mkdir(parents=True)
    (kit / "manifest.json").write_text(
        json.dumps({"label": label}, sort_keys=True) + "\n", encoding="ascii"
    )
    archive = root / "kit-fixed.zip"
    archive.write_bytes(b"canonical-zip")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_name(archive.name + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="ascii"
    )
    return {"kit_dir": str(kit), "zip_path": str(archive)}


def test_verify_resume_runs_required_stages_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / "resume.json"
    state.write_text(
        json.dumps({"release_eligible": False, "active_bundle_path": None}),
        encoding="ascii",
    )
    calls: list[str] = []

    def fake_execute(stage: str, argv: list[str], cwd: Path) -> dict[str, object]:
        calls.append(stage)
        document: dict[str, object] = {"ok": True}
        if stage == "build-1":
            document.update(_write_build(tmp_path / "out" / "build-1"))
        elif stage == "build-2":
            document.update(_write_build(tmp_path / "out" / "build-2"))
        return {
            "stage": stage,
            "ok": True,
            "returncode": 0,
            "stdout": json.dumps(document),
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(module, "_execute_stage", fake_execute)
    receipt = module.verify_resume(repo, state, tmp_path / "out")

    assert calls == [
        "lock-check", "doctor", "pytest", "inventory", "check", "build-1", "build-2",
        "verify-dir-1", "verify-zip-1", "verify-dir-2", "verify-zip-2",
        "collector-smoke",
    ]
    assert [record["stage"] for record in receipt["stages"]] == [
        "lock-check", "doctor", "pytest", "inventory", "check", "build-1", "build-2",
        "verify-dir-1", "verify-zip-1", "verify-dir-2", "verify-zip-2",
        "compare", "collector-smoke",
    ]
    assert receipt["ok"] is True
    assert receipt["operator_bundle_status"] == "not-built"
    assert receipt["release_eligible"] is False
    assert (tmp_path / "out" / "reproducibility-receipt.json").is_file()


def test_verify_resume_rejects_existing_output_root(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    with pytest.raises(module.ResumeVerificationError, match="OUTPUT_EXISTS"):
        module.verify_resume(tmp_path, tmp_path / "state.json", output)


def test_compare_covers_full_tree_zip_and_sidecar(tmp_path: Path) -> None:
    first = _write_build(tmp_path / "one")
    second = _write_build(tmp_path / "two")
    assert module._compare_builds(first, second)["ok"] is True

    Path(second["kit_dir"]).joinpath("extra.txt").write_text("different", "ascii")
    mismatch = module._compare_builds(first, second)
    assert mismatch["ok"] is False
    assert mismatch["diagnostic"] == "KIT_TREE_MISMATCH"

    Path(second["kit_dir"]).joinpath("extra.txt").unlink()
    Path(second["zip_path"]).write_bytes(b"different-zip")
    mismatch = module._compare_builds(first, second)
    assert mismatch["diagnostic"] == "KIT_ZIP_MISMATCH"

    Path(second["zip_path"]).write_bytes(Path(first["zip_path"]).read_bytes())
    Path(second["zip_path"] + ".sha256").write_text("different\n", "ascii")
    mismatch = module._compare_builds(first, second)
    assert mismatch["diagnostic"] == "KIT_SIDECAR_MISMATCH"


def test_failed_stage_stops_without_claiming_release(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state = repo / "state.json"
    state.write_text('{"release_eligible":false,"active_bundle_path":null}', "ascii")

    def fail(stage: str, argv: list[str], cwd: Path) -> dict[str, object]:
        return {
            "stage": stage, "ok": False, "returncode": 7,
            "stdout": "", "stderr": "stable failure",
            "stdout_truncated": False, "stderr_truncated": False,
        }

    monkeypatch.setattr(module, "_execute_stage", fail)
    receipt = module.verify_resume(repo, state, tmp_path / "out")
    assert receipt["ok"] is False
    assert receipt["release_eligible"] is False
    assert receipt["failed_stage"] == "lock-check"


def test_stage_capture_is_bounded_and_timeout_is_stable(tmp_path: Path) -> None:
    noisy = module._execute_stage(
        "noisy", [sys._base_executable, "-c", "import os; os.write(1,b'x'*100000)"],
        tmp_path, timeout=5,
    )
    assert noisy["ok"] is True and noisy["stdout_truncated"] is True
    assert len(noisy["stdout"].encode()) <= module._CAPTURE_LIMIT
    timeout = module._execute_stage(
        "timeout", [sys._base_executable, "-c", "import time; time.sleep(10)"],
        tmp_path, timeout=0.02,
    )
    assert timeout["ok"] is False
    assert timeout["diagnostic"] == "COMMAND_TIMEOUT"


def test_receipt_atomic_publish_failure_leaves_no_final(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    final = tmp_path / "receipt.json"
    monkeypatch.setattr(module.os, "link", lambda source, target: (_ for _ in ()).throw(OSError()))
    with pytest.raises(module.ResumeVerificationError, match="RECEIPT_WRITE_FAILED"):
        module._write_receipt(tmp_path, {"ok": False})
    assert not final.exists()
    assert list(tmp_path.iterdir()) == []


def test_collector_smoke_rejects_pyz_member_drift(tmp_path: Path) -> None:
    smoke = _collector_smoke_module()
    real_builder = smoke.build_target_collector_pyz

    def drift(repo: Path, commit: str):
        archive, sources = real_builder(repo, commit)
        return archive.replace(b"Native Windows", b"Native Xindows", 1), sources

    receipt = smoke.collector_smoke(ROOT, tmp_path / "receipt.json", _builder=drift)
    assert receipt["ok"] is False
    assert receipt["diagnostics"][0]["code"] in {
        "COLLECTOR_PYZ_INVALID", "COLLECTOR_PYZ_MEMBER_DRIFT"
    }


def test_collector_smoke_fixture_failure_fails_overall(tmp_path: Path) -> None:
    smoke = _collector_smoke_module()
    calls = 0

    def runner(argv: list[str], cwd: Path):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"returncode": 0, "stdout": "help", "stderr": ""}
        return {"returncode": 0, "stdout": '{"ok":true}', "stderr": ""}

    receipt = smoke.collector_smoke(ROOT, tmp_path / "receipt.json", _runner=runner)
    assert receipt["ok"] is False
    assert receipt["diagnostics"] == [
        {"code": "COLLECTOR_SYNTHETIC_FIXTURE_UNEXPECTED"}
    ]


def test_collector_process_capture_is_bounded_and_timeout_is_stable(tmp_path: Path) -> None:
    smoke = _collector_smoke_module()
    noisy = smoke._run(
        [sys._base_executable, "-c", "import os; os.write(2,b'x'*100000)"], tmp_path, timeout=5
    )
    assert noisy["stderr_truncated"] is True
    timed = smoke._run(
        [sys._base_executable, "-c", "import time; time.sleep(10)"], tmp_path, timeout=0.02
    )
    assert timed["timed_out"] is True


def test_collector_receipt_publish_failure_cleans_temporary_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    smoke = _collector_smoke_module()
    monkeypatch.setattr(smoke.os, "link", lambda source, target: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        smoke._write_receipt(tmp_path / "collector.json", {"ok": False})
    assert list(tmp_path.iterdir()) == []


def test_collector_receipt_failure_rolls_back_published_pyz(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    smoke = _collector_smoke_module()
    calls = 0

    def publish(path: Path, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("receipt write failed")
        path.write_bytes(data)

    runner_calls = 0

    def runner(argv: list[str], cwd: Path):
        nonlocal runner_calls
        runner_calls += 1
        if runner_calls == 1:
            return {"returncode": 0, "stdout": "help", "stderr": ""}
        return {
            "returncode": 3,
            "stdout": '{"diagnostics":[{"code":"COLLECTOR_PATH_UNSAFE"}],"ok":false}',
            "stderr": "",
        }

    monkeypatch.setattr(smoke, "_atomic_publish", publish)
    pyz = tmp_path / "target.pyz"
    with pytest.raises(OSError, match="receipt write failed"):
        smoke.collector_smoke(
            ROOT, tmp_path / "receipt.json", pyz_output=pyz, _runner=runner
        )
    assert not pyz.exists()
    assert not (tmp_path / "receipt.json").exists()


def test_operator_bundle_selector_preparation_skips_cleanly(tmp_path: Path) -> None:
    selector = _selector_module()
    output = tmp_path / "github-output"
    snapshot = tmp_path / "snapshot"
    result = selector.select_operator_bundle(tmp_path, output, snapshot)
    assert result == {"available": False, "path": "", "bundle_id": "", "sha256": ""}
    assert output.read_text("ascii") == "available=false\npath=\nbundle_id=\nsha256=\n"
    assert not snapshot.exists()


def test_operator_bundle_selector_emits_one_precise_issued_path(tmp_path: Path) -> None:
    selector = _selector_module()
    bundle = _issued_bundle(tmp_path)
    output = tmp_path / "github-output"
    snapshot = tmp_path / "snapshot"
    expected = {path.relative_to(bundle).as_posix(): path.read_bytes() for path in bundle.rglob("*") if path.is_file()}
    result = selector.select_operator_bundle(tmp_path, output, snapshot)
    assert result["available"] is True
    archive = tmp_path / str(result["path"])
    assert archive == snapshot / "operator-bundle-upload.zip"
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == result["sha256"]
    (bundle / "run-discovery.cmd").write_bytes(b"tampered after selection")
    with zipfile.ZipFile(archive) as selected:
        assert {name: selected.read(name) for name in selected.namelist()} == expected


def test_operator_bundle_selector_fails_if_current_bundle_is_missing(tmp_path: Path) -> None:
    selector = _selector_module()
    bundle = _issued_bundle(tmp_path)
    bundle.rename(bundle.with_name(bundle.name + "-missing"))
    with pytest.raises(selector.SelectionError, match="BUNDLE_MISSING"):
        selector.select_operator_bundle(tmp_path, tmp_path / "github-output", tmp_path / "snapshot")


@pytest.mark.parametrize(
    "relative", ("run-discovery.cmd", "target-discovery.pyz", "receipts/smoke.json")
)
def test_selector_rejects_tree_tamper_even_when_sha_file_is_recomputed(
    tmp_path: Path, relative: str
) -> None:
    selector = _selector_module()
    bundle = _issued_bundle(tmp_path)
    with (bundle / relative).open("ab") as stream:
        stream.write(b"tamper")
    _rewrite_sums(bundle)
    with pytest.raises(selector.SelectionError, match="BUNDLE_CONTENT_DIGEST_MISMATCH"):
        selector.select_operator_bundle(tmp_path, tmp_path / "github-output", tmp_path / "snapshot")


@pytest.mark.parametrize(
    "relative",
    (
        "legacy.catvba", "nested/LEGACY.CATVBA", "source.bas",
        "nested/Source.CLS", "form.frm", "nested/form.FRX",
    ),
)
def test_operator_bundle_selector_rejects_legacy_macro_payload_even_if_hashed(
    tmp_path: Path, relative: str
) -> None:
    selector = _selector_module()
    bundle = _issued_bundle(tmp_path)
    legacy = bundle / relative
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_bytes(b"legacy forbidden payload")
    _rewrite_sums(bundle)
    with pytest.raises(selector.SelectionError, match="BUNDLE_FORBIDDEN_PAYLOAD"):
        selector.select_operator_bundle(tmp_path, tmp_path / "github-output", tmp_path / "snapshot")


def test_selector_rejects_source_mutation_during_stable_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selector = _selector_module()
    bundle = _issued_bundle(tmp_path)
    target = bundle / "run-discovery.cmd"
    fired = False

    def mutate(path: Path) -> None:
        nonlocal fired
        if path == target and not fired:
            fired = True
            path.write_bytes(b"changed during read")

    monkeypatch.setattr(selector, "_STABLE_READ_HOOK", mutate)
    with pytest.raises(selector.SelectionError, match="BUNDLE_FILE_CHANGED"):
        selector.select_operator_bundle(tmp_path, tmp_path / "github-output", tmp_path / "snapshot")
    assert not (tmp_path / "snapshot/operator-bundle-upload.zip").exists()


def test_selector_rejects_hardlinked_bundle_file(tmp_path: Path) -> None:
    selector = _selector_module()
    bundle = _issued_bundle(tmp_path)
    os.link(bundle / "provenance.json", bundle / "linked.json")
    with pytest.raises(selector.SelectionError, match="BUNDLE_FILE_UNSAFE"):
        selector.select_operator_bundle(tmp_path, tmp_path / "github-output", tmp_path / "snapshot")


def test_snapshot_publish_links_unlinks_then_marks_final_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selector = _selector_module()
    events: list[str] = []
    real_link = selector.os.link
    real_unlink = selector.Path.unlink
    real_chmod = selector.Path.chmod

    def link(source, target):
        events.append("link")
        return real_link(source, target)

    def unlink(path, *args, **kwargs):
        events.append("unlink")
        return real_unlink(path, *args, **kwargs)

    def chmod(path, mode, *args, **kwargs):
        events.append(f"chmod-{mode:o}")
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(selector.os, "link", link)
    monkeypatch.setattr(selector.Path, "unlink", unlink)
    monkeypatch.setattr(selector.Path, "chmod", chmod)
    final = tmp_path / "snapshot.zip"
    selector._publish_snapshot(final, b"snapshot")
    assert events[:3] == ["link", "unlink", "chmod-444"]
    assert final.read_bytes() == b"snapshot"


def test_snapshot_unlink_permission_failure_cleans_final_and_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selector = _selector_module()
    _issued_bundle(tmp_path)
    real_unlink = selector.Path.unlink
    failed = False

    def unlink(path, *args, **kwargs):
        nonlocal failed
        if path.name.startswith(".operator-bundle-upload.zip.") and not failed:
            failed = True
            raise PermissionError("simulated Windows read-only unlink")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(selector.Path, "unlink", unlink)
    snapshot = tmp_path / "snapshot"
    with pytest.raises(selector.SelectionError, match="SNAPSHOT_PUBLISH_FAILED"):
        selector.select_operator_bundle(
            tmp_path, tmp_path / "github-output", snapshot
        )
    assert not (tmp_path / "github-output").exists()
    assert list(snapshot.iterdir()) == []
