from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from catvba_refactor.macro_build import operator_bundle as operator_bundle_module
from catvba_refactor.macro_build.canonical import canonical_json_bytes
from catvba_refactor.macro_build.errors import InfrastructureError, VerificationError
from catvba_refactor.macro_build.handoff import HandoffRequest
from catvba_refactor.macro_build.generator import generate_sources
from catvba_refactor.macro_build.kit import stage_build_kit
from catvba_refactor.macro_build.manifests import ManifestSet
from catvba_refactor.macro_build.model import Origin, ResolvedSourceSet, ValidationReport
from catvba_refactor.macro_build.operator_bundle import (
    OperatorBundleRequest,
    build_operator_bundle,
)
from catvba_refactor.tests.test_handoff import issue_target_handoff
from catvba_refactor.tests.test_kit import _catalog
from catvba_refactor.target_collector.raw_validation import (
    COMPILE_POINTS,
    ENVELOPE,
    TARGET_CASE_IDS,
)


NOW = datetime(2026, 7, 15, 12, 2, tzinfo=UTC)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _build(request: OperatorBundleRequest):
    return build_operator_bundle(request, _clock=lambda: NOW)


def _write_valid_skeleton(root: Path) -> None:
    root.mkdir()
    _write_json(root / "compile-result.json", {
        **ENVELOPE,
        "records": [{
            "record_id": f"record-compile-{point}", "point": point,
            "status": "not-run", "started_at": None, "ended_at": None,
            "catia_operator_record_id": None, "vbe_operator_record_id": None,
            "error_stage": None, "error_module": None,
            "redacted_error_summary": None,
        } for point in COMPILE_POINTS],
    })
    _write_json(root / "test-results.json", {
        **ENVELOPE,
        "records": [{
            "case_id": case_id, "status": "not-run", "execution_point": "not-run",
            "observations": [], "started_at": None, "ended_at": None,
            "operator_record_id": None,
        } for case_id in TARGET_CASE_IDS],
    })
    _write_json(root / "artifact-manifest.json", {
        **ENVELOPE, "artifact": None, "files": [],
    })


@pytest.fixture
def bundle_request(tmp_path: Path) -> OperatorBundleRequest:
    issuance = {
        "schema_version": 1,
        "captured_at": "2026-07-15T11:59:00Z",
        "source": "repository-active-handoff-ledger",
        "active_handoff_ids": [],
        "withdrawn_handoff_ids": ["handoff-withdrawn-example"],
    }
    issuance_path = tmp_path / "revocation-snapshot.json"
    _write_json(issuance_path, issuance)

    skeleton = tmp_path / "session-skeleton"
    _write_valid_skeleton(skeleton)

    source_repo = Path(__file__).resolve().parents[2]
    repository = tmp_path / "repo"
    (repository / "catvba_refactor").mkdir(parents=True)
    for name in ("target_collector", "schemas", "templates"):
        shutil.copytree(
            source_repo / "catvba_refactor" / name,
            repository / "catvba_refactor" / name,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    tutorials = repository / "operator-tutorials"
    tutorials.mkdir()
    for name in (
        "README_TARGET_B28.md", "QUICKSTART_B28.md",
        "SECURITY_AND_REDACTION.md", "TROUBLESHOOTING.md",
    ):
        (tutorials / name).write_text(f"# {name}\nPython 3.12 / B28 discovery only.\n", "utf-8")
    (repository / "run-discovery.cmd").write_text(
        "@py -3.12 target-discovery.pyz %*\r\n", "ascii", newline=""
    )
    (repository / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="ascii")
    for command in (
        ("git", "init", "--initial-branch=codex/dev-review-report"),
        ("git", "config", "user.name", "Bundle Tests"),
        ("git", "config", "user.email", "bundle@example.invalid"),
        ("git", "add", "."),
        ("git", "commit", "-m", "fixture"),
    ):
        subprocess.run(command, cwd=repository, check=True, capture_output=True)

    head = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repository, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ("git", "rev-parse", "HEAD^{tree}"), cwd=repository, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    catalog = _catalog()[0]
    catalog = replace(catalog, snapshot=replace(
        catalog.snapshot,
        upstream_commit="abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad",
        fork_dev_commit="abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad",
        work_commit=head,
        work_tree=tree,
    ))
    nongenerated = tuple(
        component for component in catalog.components
        if component.origin is not Origin.GENERATED
    )
    generated = generate_sources(
        ResolvedSourceSet(nongenerated, (), ValidationReport()),
        ManifestSet(
            project={"schema_version": 1},
            components={"schema_version": 1, "source_roots": [], "components": []},
            packages={"schema_version": 1, "packages": list(catalog.packages)},
            tools={"schema_version": 1, "tools": list(catalog.tools)},
            digest=catalog.snapshot.manifest_digest,
            report=ValidationReport(),
        ),
        catalog.snapshot,
    )
    catalog = replace(catalog, components=(*nongenerated, *generated.components))
    primary_root = tmp_path / "build-a"
    comparison_root = tmp_path / "build-b"
    stage_build_kit(catalog, primary_root)
    stage_build_kit(catalog, comparison_root)
    receipt = issue_target_handoff(
        primary_root,
        comparison_root,
        HandoffRequest(
            purpose="discovery",
            created_at="2026-07-15T12:00:00Z",
            expires_at="2026-07-22T12:00:00Z",
            revocation_snapshot=issuance_path.read_bytes(),
            prepared_record_id="record-handoff-prepared",
            review_record_id="record-handoff-reviewed",
        ),
        tmp_path / "handoffs",
    )
    handoff = Path(receipt.handoff_path)
    ledger = {
        **issuance,
        "captured_at": "2026-07-15T12:01:00Z",
        "active_handoff_ids": [receipt.handoff_id],
    }
    ledger_path = tmp_path / "active-handoff-ledger.json"
    _write_json(ledger_path, ledger)

    return OperatorBundleRequest(
        primary_build_root=primary_root,
        comparison_build_root=comparison_root,
        handoff=handoff,
        active_ledger=ledger_path,
        issuance_revocation_snapshot=issuance_path,
        session_skeleton=skeleton,
        output_root=tmp_path / "bundle-output",
        repo_root=repository,
        tutorials=tutorials,
        run_script=repository / "run-discovery.cmd",
        generation_record_id="record-bundle-generation",
        test_record_id="record-target-collector-tests",
        review_record_id="record-bundle-independent-review",
    )


def test_operator_bundle_contains_complete_target_code_and_tutorials(
    bundle_request: OperatorBundleRequest,
) -> None:
    receipt = _build(bundle_request)
    members = {
        path.relative_to(receipt.bundle_dir).as_posix()
        for path in receipt.bundle_dir.rglob("*") if path.is_file()
    }
    assert "source/target_collector/cli.py" in members
    assert "schemas/raw-capture-manifest.schema.json" in members
    assert "README_TARGET_B28.md" in members
    assert "target-discovery.pyz" in members
    assert "session-skeleton.zip" in members
    assert "revocation-snapshot.json" in members
    assert "handoff.json" in members
    assert not any(path.casefold().endswith((".catvba", ".frx", ".bas", ".cls", ".frm")) for path in members)


def test_bundle_and_pyz_are_deterministic_with_source_parity(
    bundle_request: OperatorBundleRequest,
    tmp_path: Path,
) -> None:
    first = _build(bundle_request)
    second = _build(replace(bundle_request, output_root=tmp_path / "other"))
    assert first.bundle_id == second.bundle_id
    assert first.bundle_sha256 == second.bundle_sha256
    assert first.bundle_dir.joinpath("target-discovery.pyz").read_bytes() == second.bundle_dir.joinpath("target-discovery.pyz").read_bytes()
    with zipfile.ZipFile(first.bundle_dir / "target-discovery.pyz") as archive:
        pyz_sources = {
            name.removeprefix("catvba_refactor/"): archive.read(name)
            for name in archive.namelist() if name.startswith("catvba_refactor/target_collector/")
        }
    disk_sources = {
        path.relative_to(first.bundle_dir / "source").as_posix(): path.read_bytes()
        for path in (first.bundle_dir / "source" / "target_collector").rglob("*.py")
    }
    assert pyz_sources == disk_sources
    help_result = subprocess.run(
        (sys.executable, str(first.bundle_dir / "target-discovery.pyz"), "--help"),
        check=True, capture_output=True, text=True,
    )
    assert "finalize-raw" in help_result.stdout


def test_bundle_is_byte_identical_across_distinct_build_root_inodes(
    bundle_request: OperatorBundleRequest,
    tmp_path: Path,
) -> None:
    copied_primary = tmp_path / "copied-build-a"
    copied_comparison = tmp_path / "copied-build-b"
    shutil.copytree(bundle_request.primary_build_root, copied_primary)
    shutil.copytree(bundle_request.comparison_build_root, copied_comparison)

    original_roots = (
        bundle_request.primary_build_root,
        bundle_request.comparison_build_root,
    )
    copied_roots = (copied_primary, copied_comparison)
    assert all(
        (original.stat().st_dev, original.stat().st_ino)
        != (copied.stat().st_dev, copied.stat().st_ino)
        and not original.samefile(copied)
        for original, copied in zip(original_roots, copied_roots, strict=True)
    )

    first = _build(bundle_request)
    second = _build(replace(
        bundle_request,
        primary_build_root=copied_primary,
        comparison_build_root=copied_comparison,
        output_root=tmp_path / "copied-roots-output",
    ))

    def bundle_files(root: Path) -> dict[str, bytes]:
        return {
            path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(
                root.rglob("*"), key=lambda item: item.as_posix().encode("ascii")
            )
            if path.is_file()
        }

    assert first.bundle_id == second.bundle_id
    assert bundle_files(first.bundle_dir) == bundle_files(second.bundle_dir)
    for relative in (
        "SHA256SUMS",
        "provenance.json",
        "receipts/build-reproducibility.json",
        "receipts/verifier-summary.json",
        "receipts/target-collector-tests.json",
    ):
        assert (
            first.bundle_dir.joinpath(relative).read_bytes()
            == second.bundle_dir.joinpath(relative).read_bytes()
        )

    reproducibility = json.loads(
        (first.bundle_dir / "receipts" / "build-reproducibility.json").read_text("ascii")
    )
    serialized = canonical_json_bytes(reproducibility)
    assert reproducibility["primary_build_record_id"].endswith("-primary")
    assert reproducibility["comparison_build_record_id"].endswith("-comparison")
    assert (
        reproducibility["primary_authenticated_content_sha256"]
        == reproducibility["comparison_authenticated_content_sha256"]
    )
    assert (
        reproducibility["primary_kit_identity"]
        == reproducibility["comparison_kit_identity"]
    )
    assert b"root_identity" not in serialized
    assert b"st_dev" not in serialized
    assert b"st_ino" not in serialized
    assert all(
        os.fsencode(str(root)) not in serialized
        for root in (*original_roots, *copied_roots)
    )


def test_provenance_binds_handoff_ledgers_skeleton_and_boundaries(
    bundle_request: OperatorBundleRequest,
) -> None:
    receipt = _build(bundle_request)
    root = receipt.bundle_dir
    provenance = json.loads((root / "provenance.json").read_text("ascii"))
    handoff = json.loads(bundle_request.handoff.read_text("ascii"))
    ledger = bundle_request.active_ledger.read_bytes()
    snapshot = bundle_request.issuance_revocation_snapshot.read_bytes()
    assert receipt.bundle_id == "bundle-" + _sha(canonical_json_bytes(provenance))[:24]
    assert provenance["handoff_id"] == handoff["handoff_id"]
    assert provenance["handoff_sha256"] == _sha(bundle_request.handoff.read_bytes())
    assert provenance["issuance_revocation_snapshot_sha256"] == _sha(snapshot)
    assert provenance["active_ledger_source"] == json.loads(ledger)["source"]
    assert provenance["compile_status"] == "not-run"
    assert provenance["target_case_status"] == "not-run"
    assert provenance["artifact_status"] == "not-produced"
    assert provenance["release_eligible"] is False
    skeleton_members = [
        {"path": p.relative_to(bundle_request.session_skeleton).as_posix(), "sha256": _sha(p.read_bytes()), "size": p.stat().st_size}
        for p in sorted(bundle_request.session_skeleton.rglob("*"), key=lambda p: p.as_posix().encode("ascii")) if p.is_file()
    ]
    assert provenance["session_skeleton_members"] == skeleton_members
    summary = json.loads((root / "receipts" / "verifier-summary.json").read_text("ascii"))
    recomputed = {
        label: _sha(canonical_json_bytes(record))
        for label, record in summary["verifiers"].items()
    }
    assert summary["verifier_report_digests"] == recomputed
    assert len(set(recomputed.values())) == 4
    assert receipt.active_ledger_sha256 == _sha(ledger)
    assert receipt.active_ledger_captured_at == json.loads(ledger)["captured_at"]


@pytest.mark.parametrize(
    ("field", "code"),
    (
        ("tutorials", "OPERATOR_BUNDLE_TUTORIALS_INVALID"),
        ("run_script", "OPERATOR_BUNDLE_RUN_SCRIPT_INVALID"),
    ),
)
def test_missing_production_content_has_stable_error(
    bundle_request: OperatorBundleRequest,
    tmp_path: Path,
    field: str,
    code: str,
) -> None:
    with pytest.raises(VerificationError, match=code):
        _build(replace(bundle_request, **{field: tmp_path / "missing"}))


def test_operator_bundle_rejects_mismatched_dual_builds(
    bundle_request: OperatorBundleRequest,
) -> None:
    kit_zip = next(bundle_request.comparison_build_root.glob("kit-*.zip"))
    data = bytearray(kit_zip.read_bytes())
    data[-1] ^= 1
    kit_zip.write_bytes(data)
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_BUILD_MISMATCH"):
        _build(bundle_request)


@pytest.mark.parametrize("comparison", ("same", "ancestor"))
def test_operator_bundle_requires_independent_build_roots(
    bundle_request: OperatorBundleRequest,
    comparison: str,
) -> None:
    other = (
        bundle_request.primary_build_root
        if comparison == "same"
        else bundle_request.primary_build_root.parent
    )
    with pytest.raises(
        VerificationError, match="OPERATOR_BUNDLE_BUILD_ROOTS_NOT_INDEPENDENT"
    ):
        _build(replace(bundle_request, comparison_build_root=other))


def test_ignored_collector_cache_does_not_change_pinned_source(
    bundle_request: OperatorBundleRequest,
) -> None:
    cache = bundle_request.repo_root / "catvba_refactor" / "target_collector" / "__pycache__"
    cache.mkdir()
    (cache / "junk.pyc").write_bytes(b"not source")

    receipt = _build(bundle_request)

    assert not (receipt.bundle_dir / "source" / "target_collector" / "__pycache__").exists()


def test_tracked_collector_change_is_rejected(
    bundle_request: OperatorBundleRequest,
) -> None:
    source = bundle_request.repo_root / "catvba_refactor" / "target_collector" / "cli.py"
    source.write_bytes(source.read_bytes() + b"# dirty\n")

    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_COLLECTOR_TRACKED_DIRTY"):
        _build(bundle_request)


def test_deleted_tracked_collector_source_is_rejected(
    bundle_request: OperatorBundleRequest,
) -> None:
    (bundle_request.repo_root / "catvba_refactor" / "target_collector" / "cli.py").unlink()
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_COLLECTOR_TRACKED_DIRTY"):
        _build(bundle_request)


def test_git_environment_injection_is_ignored(
    bundle_request: OperatorBundleRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_DIR", str(bundle_request.repo_root / "not-a-git-dir"))
    assert _build(bundle_request).bundle_id.startswith("bundle-")


def test_replace_refs_are_rejected(bundle_request: OperatorBundleRequest) -> None:
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=bundle_request.repo_root,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    subprocess.run(
        ("git", "update-ref", f"refs/replace/{head}", head),
        cwd=bundle_request.repo_root, check=True, capture_output=True,
    )
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_GIT_REPLACE_REFS_FORBIDDEN"):
        _build(bundle_request)


def test_hardlinked_kit_input_is_rejected(
    bundle_request: OperatorBundleRequest,
) -> None:
    primary = next(bundle_request.primary_build_root.glob("kit-*.zip.sha256"))
    comparison = next(bundle_request.comparison_build_root.glob("kit-*.zip.sha256"))
    comparison.unlink()
    os.link(primary, comparison)
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_SIDECAR_INVALID"):
        _build(bundle_request)


def test_post_capture_ledger_mutation_does_not_change_bundle_bytes(
    bundle_request: OperatorBundleRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stable = operator_bundle_module._stable_file
    original = bundle_request.active_ledger.read_bytes()
    mutated = False

    def mutate_after_capture(path: Path, code: str):
        nonlocal mutated
        result = stable(path, code)
        if path == bundle_request.active_ledger and not mutated:
            mutated = True
            path.write_bytes(b"mutated after stable capture\n")
        return result

    monkeypatch.setattr(operator_bundle_module, "_stable_file", mutate_after_capture)
    receipt = _build(bundle_request)
    assert receipt.active_ledger_sha256 == _sha(original)


def test_post_capture_kit_mutation_does_not_change_frozen_bundle(
    bundle_request: OperatorBundleRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stable = operator_bundle_module._stable_file
    primary_zip = next(bundle_request.primary_build_root.glob("kit-*.zip"))
    original = primary_zip.read_bytes()
    mutated = False

    def mutate_after_capture(path: Path, code: str):
        nonlocal mutated
        result = stable(path, code)
        if path == primary_zip and not mutated:
            mutated = True
            path.write_bytes(b"corrupt after stable capture")
        return result

    monkeypatch.setattr(operator_bundle_module, "_stable_file", mutate_after_capture)
    receipt = _build(bundle_request)
    bundled = receipt.bundle_dir / f"{receipt.kit_id}.zip"
    assert bundled.read_bytes() == original


def test_pinned_collector_rejects_nonpython_tracked_member(
    bundle_request: OperatorBundleRequest,
) -> None:
    extra = bundle_request.repo_root / "catvba_refactor" / "target_collector" / "payload.bin"
    extra.write_bytes(b"not Python")
    subprocess.run(
        ("git", "add", "."), cwd=bundle_request.repo_root,
        check=True, capture_output=True,
    )
    subprocess.run(
        ("git", "commit", "-m", "add nonpy"), cwd=bundle_request.repo_root,
        check=True, capture_output=True,
    )
    head = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=bundle_request.repo_root,
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_COLLECTOR_NONPY_FORBIDDEN"):
        operator_bundle_module._pinned_collector_files(bundle_request.repo_root, head)


def test_oversize_and_member_flood_fail_before_publication(
    bundle_request: OperatorBundleRequest,
    tmp_path: Path,
) -> None:
    oversized = tmp_path / "oversized.cmd"
    with oversized.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_RUN_SCRIPT_INVALID"):
        _build(replace(bundle_request, run_script=oversized))
    assert not bundle_request.output_root.exists()

    for index in range(513):
        (bundle_request.session_skeleton / f"flood-{index:04}.json").write_bytes(b"{}\n")
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_SKELETON_INVALID"):
        _build(bundle_request)
    assert not bundle_request.output_root.exists()


def test_nonstdlib_import_is_rejected() -> None:
    with pytest.raises(
        VerificationError, match="OPERATOR_BUNDLE_COLLECTOR_THIRD_PARTY_IMPORT"
    ):
        operator_bundle_module._collector_imports((("bad.py", b"import requests\n"),))


@pytest.mark.parametrize(
    ("now", "code"),
    (
        (datetime(2026, 7, 15, 12, 0, 30, tzinfo=UTC), "OPERATOR_BUNDLE_LEDGER_CAPTURED_IN_FUTURE"),
        (datetime(2026, 7, 16, 13, 0, tzinfo=UTC), "OPERATOR_BUNDLE_LEDGER_STALE"),
        (datetime(2026, 7, 22, 12, 0, tzinfo=UTC), "OPERATOR_BUNDLE_HANDOFF_EXPIRED"),
    ),
)
def test_operator_bundle_enforces_trusted_current_time(
    bundle_request: OperatorBundleRequest,
    now: datetime,
    code: str,
) -> None:
    with pytest.raises(VerificationError, match=code):
        build_operator_bundle(bundle_request, _clock=lambda: now)


@pytest.mark.parametrize("mutation", ("missing", "extra", "tampered"))
def test_operator_bundle_requires_exact_discovery_skeleton(
    bundle_request: OperatorBundleRequest,
    mutation: str,
) -> None:
    skeleton = bundle_request.session_skeleton
    if mutation == "missing":
        (skeleton / "compile-result.json").unlink()
    elif mutation == "extra":
        _write_json(skeleton / "session.json", {"schema_version": 1})
    else:
        document = json.loads((skeleton / "test-results.json").read_text("ascii"))
        document["records"][0]["status"] = "passed"
        _write_json(skeleton / "test-results.json", document)

    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_SKELETON_INVALID"):
        _build(bundle_request)


def test_operator_bundle_rejects_inactive_or_stale_handoff(
    bundle_request: OperatorBundleRequest,
) -> None:
    ledger = json.loads(bundle_request.active_ledger.read_text("ascii"))
    ledger["active_handoff_ids"] = []
    _write_json(bundle_request.active_ledger, ledger)
    with pytest.raises(VerificationError, match="OPERATOR_BUNDLE_HANDOFF_INACTIVE"):
        _build(bundle_request)


def test_operator_bundle_rejects_existing_output_without_overwrite(
    bundle_request: OperatorBundleRequest,
) -> None:
    bundle_request.output_root.mkdir()
    with pytest.raises(InfrastructureError, match="OPERATOR_BUNDLE_OUTPUT_EXISTS"):
        _build(bundle_request)


def test_publish_race_never_replaces_competing_output(
    bundle_request: OperatorBundleRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish = operator_bundle_module._atomic_publish

    def race(staging: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "competitor.txt").write_text("keep", encoding="ascii")
        publish(staging, destination)

    monkeypatch.setattr(operator_bundle_module, "_atomic_publish", race)
    with pytest.raises(InfrastructureError, match="OPERATOR_BUNDLE_OUTPUT_EXISTS"):
        _build(bundle_request)

    assert [path.name for path in bundle_request.output_root.iterdir()] == ["competitor.txt"]
    assert (bundle_request.output_root / "competitor.txt").read_text("ascii") == "keep"


def test_failed_build_leaves_final_output_absent(
    bundle_request: OperatorBundleRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write = operator_bundle_module._write_file
    calls = 0

    def fail_mid_stage(root: Path, relative: str, data: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 4:
            raise InfrastructureError("INJECTED_STAGE_FAILURE")
        write(root, relative, data)

    monkeypatch.setattr(operator_bundle_module, "_write_file", fail_mid_stage)
    with pytest.raises(InfrastructureError, match="INJECTED_STAGE_FAILURE"):
        _build(bundle_request)

    assert not bundle_request.output_root.exists()


def test_sha256sums_excludes_itself_and_covers_every_other_file(
    bundle_request: OperatorBundleRequest,
) -> None:
    receipt = _build(bundle_request)
    root = receipt.bundle_dir
    lines = (root / "SHA256SUMS").read_text("ascii").splitlines()
    names = [line.split("  ", 1)[1] for line in lines]
    expected = sorted(
        (p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS"),
        key=str.encode,
    )
    assert names == expected
    assert "SHA256SUMS" not in names
