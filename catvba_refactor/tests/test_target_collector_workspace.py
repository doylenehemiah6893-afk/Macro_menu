from __future__ import annotations

import hashlib
import json
import os
import platform
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from catvba_refactor.target_collector.canonical import (
    CollectorError,
    canonical_json_bytes,
    parse_canonical_json_bytes,
)
from catvba_refactor.target_collector.workspace import (
    init_capture,
    preflight,
    status,
)
from catvba_refactor.target_collector.cli import main as collector_main


NOW = "2026-07-15T18:00:00Z"
FIXED_NOW = datetime(2026, 7, 15, 18, 0, 0, tzinfo=UTC)
HANDOFF_ID = "handoff-current-example"
SHA = "a" * 64
SHA_B = "b" * 64
GIT = "c" * 40
TREE = "d" * 40
CUTOFF = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_canonical(path: Path, value: object) -> bytes:
    data = canonical_json_bytes(value)
    path.write_bytes(data)
    return data


def _runtime_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform, "python_implementation", lambda: "CPython")


def _fixed_clock() -> datetime:
    return FIXED_NOW


def _make_bundle(tmp_path: Path, *, member_path: str = "templates/readme.txt") -> dict[str, Path]:
    bundle = tmp_path / "bundle"
    bundle.mkdir(parents=True)
    member_data = b"operator skeleton\n"
    skeleton = bundle / "session-skeleton.zip"
    with zipfile.ZipFile(skeleton, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(member_path, member_data)

    handoff = {
        "schema_version": 1,
        "handoff_id": HANDOFF_ID,
        "purpose": "discovery",
        "created_at": "2026-07-15T17:00:00Z",
        "expires_at": "2026-07-22T17:00:00Z",
        "revocation_status": "active",
        "revocation_snapshot_sha256": SHA,
        "kit_id": "kit-0123456789abcdef",
        "catalog_sha256": SHA,
        "manifest_sha256": SHA_B,
        "manifest_digest": SHA,
        "zip_sha256": SHA_B,
        "zip_sidecar_sha256": SHA,
        "work_commit": GIT,
        "work_tree": TREE,
        "work_branch": "codex/dev-review-report",
        "upstream_cutoff": CUTOFF,
        "fork_dev_cutoff": CUTOFF,
        "package_id": "core",
        "target": "CATIA R2018/VBA7 64",
        "compile_status": "not-run",
        "release_eligible": False,
        "generation_command": "macro-menu-build issue-handoff",
        "primary_directory_verifier_report_digest": SHA,
        "comparison_directory_verifier_report_digest": SHA,
        "primary_zip_verifier_report_digest": SHA,
        "comparison_zip_verifier_report_digest": SHA,
        "prepared_record_id": "record-handoff-prepared",
        "review_record_id": "record-handoff-reviewed",
        "reference_contract": {
            "status": "discovery-required",
            "contract_id": "reference-contract-core",
            "contract_version": 1,
            "contract_body_digest": SHA,
            "reference_definitions": [],
            "observations": None,
            "transitions": None,
            "path_policy": {
                "allowed_root_kinds": ["catia-install", "windows-install", "system"],
                "allow_user_paths": False,
            },
            "approval": None,
        },
    }
    handoff_data = _write_canonical(bundle / "handoff.json", handoff)
    provenance = {
        "schema_version": 1,
        "repository": "doylenehemiah6893-afk/Macro_menu",
        "branch": "codex/dev-review-report",
        "evidence_commit": GIT,
        "evidence_tree": TREE,
        "approved_cutoff": CUTOFF,
        "kit_id": "kit-0123456789abcdef",
        "catalog_sha256": SHA,
        "manifest_sha256": SHA_B,
        "manifest_digest": SHA,
        "kit_zip_sha256": SHA_B,
        "kit_sidecar_sha256": SHA,
        "handoff_id": HANDOFF_ID,
        "handoff_sha256": _sha(handoff_data),
        "handoff_created_at": handoff["created_at"],
        "handoff_expires_at": handoff["expires_at"],
        "issuance_revocation_snapshot_sha256": SHA,
        "active_ledger_schema_version": 1,
        "active_ledger_source": "repository-active-handoff-ledger",
        "python_requirement": "CPython 3.12",
        "collector_source_commit": GIT,
        "collector_source_sha256": SHA,
        "collector_pyz_sha256": SHA_B,
        "session_skeleton_sha256": _sha(skeleton.read_bytes()),
        "session_skeleton_members": [
            {"path": member_path, "sha256": _sha(member_data), "size": len(member_data)}
        ],
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
        "tutorials_sha256": SHA,
        "templates_sha256": SHA_B,
        "schemas_sha256": SHA,
        "generation_record_id": "record-bundle-generation",
        "test_record_id": "record-target-collector-tests",
        "review_record_id": "record-bundle-review",
    }
    provenance_data = _write_canonical(bundle / "provenance.json", provenance)
    bundle_id = "bundle-" + _sha(provenance_data)[:24]
    current = tmp_path / "CURRENT.json"
    _write_canonical(
        current,
        {
            "schema_version": 1,
            "bundle_id": bundle_id,
            "bundle_sha256": _sha(provenance_data),
            "handoff_id": HANDOFF_ID,
        },
    )
    ledger = tmp_path / "active-handoff-ledger.json"
    _write_canonical(
        ledger,
        {
            "schema_version": 1,
            "captured_at": "2026-07-15T17:30:00Z",
            "source": "repository-active-handoff-ledger",
            "active_handoff_ids": [HANDOFF_ID],
            "withdrawn_handoff_ids": [],
        },
    )
    return {"bundle": bundle, "current": current, "ledger": ledger}


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix().encode("ascii")
        digest.update(relative + b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_canonical_json_requires_unique_keys_and_fixed_bytes():
    assert canonical_json_bytes({"z": 1, "a": "\N{SNOWMAN}"}) == b'{"a":"\\u2603","z":1}\n'
    with pytest.raises(CollectorError, match="COLLECTOR_JSON_DUPLICATE_KEY"):
        parse_canonical_json_bytes(b'{"a":1,"a":2}\n')
    with pytest.raises(CollectorError, match="COLLECTOR_NONCANONICAL_JSON"):
        parse_canonical_json_bytes(b'{"z":1, "a":2}\n')
    with pytest.raises(CollectorError, match="COLLECTOR_JSON_INVALID"):
        parse_canonical_json_bytes(b'{"n":' + b"9" * 129 + b"}\n")
    with pytest.raises(CollectorError, match="COLLECTOR_JSON_LIMIT_EXCEEDED"):
        parse_canonical_json_bytes(("[" * 65 + "0" + "]" * 65 + "\n").encode("ascii"))


def test_preflight_requires_windows_cpython_312(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _make_bundle(tmp_path)
    monkeypatch.setattr(platform, "python_implementation", lambda: "PyPy")
    result = preflight(**inputs, _clock=_fixed_clock)
    assert result.exit_code == 4
    assert result.codes == ("COLLECTOR_CPYTHON_REQUIRED",)


def test_preflight_authenticates_bundle_and_external_current_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    result = preflight(**inputs, _clock=_fixed_clock)
    assert result.ok
    assert result.facts["handoff_id"] == HANDOFF_ID


@pytest.mark.parametrize("condition", ["stale", "withdrawn", "current-mismatch", "hash-mismatch"])
def test_preflight_rejects_untrusted_or_stale_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    if condition in {"stale", "withdrawn"}:
        ledger = json.loads(inputs["ledger"].read_text(encoding="ascii"))
        if condition == "stale":
            ledger["captured_at"] = "2026-07-14T17:59:59Z"
        else:
            ledger["active_handoff_ids"] = []
            ledger["withdrawn_handoff_ids"] = [HANDOFF_ID]
        _write_canonical(inputs["ledger"], ledger)
    elif condition == "current-mismatch":
        current = json.loads(inputs["current"].read_text(encoding="ascii"))
        current["handoff_id"] = "handoff-different-example"
        _write_canonical(inputs["current"], current)
    else:
        with inputs["bundle"].joinpath("session-skeleton.zip").open("ab") as stream:
            stream.write(b"tamper")
    result = preflight(**inputs, _clock=_fixed_clock)
    assert not result.ok


def test_init_capture_never_modifies_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    before = _tree_digest(inputs["bundle"])
    capture = tmp_path / "capture"
    result = init_capture(**inputs, capture=capture, _clock=_fixed_clock)
    assert result.ok
    assert _tree_digest(inputs["bundle"]) == before
    session = parse_canonical_json_bytes((capture / "session.json").read_bytes())
    assert session["capture_status"] == "in-progress"
    assert session["trust_level"] == "raw-untrusted"
    assert session["compile_status"] == "not-run"
    assert session["release_eligible"] is False
    assert (capture / "templates" / "readme.txt").read_bytes() == b"operator skeleton\n"
    assert status(capture).ok


def test_init_capture_rejects_existing_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    capture = tmp_path / "capture"
    capture.mkdir()
    result = init_capture(**inputs, capture=capture, _clock=_fixed_clock)
    assert result.codes == ("COLLECTOR_OUTPUT_EXISTS",)


@pytest.mark.parametrize(
    "member_path",
    ["/absolute.txt", "C:/drive.txt", "//server/share.txt", "../escape.txt", "a/../../escape.txt"],
)
def test_init_capture_rejects_unsafe_member_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member_path: str
):
    inputs = _make_bundle(tmp_path, member_path=member_path)
    _runtime_windows(monkeypatch)
    capture = tmp_path / "capture"
    result = init_capture(**inputs, capture=capture, _clock=_fixed_clock)
    assert result.codes == ("COLLECTOR_MEMBER_PATH_INVALID",)
    assert not capture.exists()


def test_preflight_rejects_symlink_nonregular_oversize_and_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _runtime_windows(monkeypatch)
    inputs = _make_bundle(tmp_path / "hash")
    provenance = json.loads((inputs["bundle"] / "provenance.json").read_text("ascii"))
    provenance["session_skeleton_members"][0]["sha256"] = "0" * 64
    provenance_data = _write_canonical(inputs["bundle"] / "provenance.json", provenance)
    current = json.loads(inputs["current"].read_text("ascii"))
    current["bundle_id"] = "bundle-" + _sha(provenance_data)[:24]
    current["bundle_sha256"] = _sha(provenance_data)
    _write_canonical(inputs["current"], current)
    assert init_capture(**inputs, capture=tmp_path / "bad-hash", _clock=_fixed_clock).codes == (
        "COLLECTOR_MEMBER_HASH_MISMATCH",
    )

    inputs = _make_bundle(tmp_path / "large")
    provenance = json.loads((inputs["bundle"] / "provenance.json").read_text("ascii"))
    provenance["session_skeleton_members"][0]["size"] = 65 * 1024 * 1024
    provenance_data = _write_canonical(inputs["bundle"] / "provenance.json", provenance)
    current = json.loads(inputs["current"].read_text("ascii"))
    current["bundle_id"] = "bundle-" + _sha(provenance_data)[:24]
    current["bundle_sha256"] = _sha(provenance_data)
    _write_canonical(inputs["current"], current)
    assert init_capture(**inputs, capture=tmp_path / "too-large", _clock=_fixed_clock).codes == (
        "COLLECTOR_FILE_TOO_LARGE",
    )

    if hasattr(os, "symlink"):
        inputs = _make_bundle(tmp_path / "link")
        skeleton = inputs["bundle"] / "session-skeleton.zip"
        real = skeleton.with_suffix(".real")
        skeleton.rename(real)
        try:
            skeleton.symlink_to(real.name)
        except OSError:
            pytest.skip("symlink creation unavailable")
        assert preflight(**inputs, _clock=_fixed_clock).codes == ("COLLECTOR_PATH_UNSAFE",)


def test_init_capture_rejects_zip_symlink_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    skeleton = inputs["bundle"] / "session-skeleton.zip"
    info = zipfile.ZipInfo("templates/readme.txt")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(skeleton, "w") as archive:
        archive.writestr(info, b"operator skeleton\n")
    provenance = json.loads((inputs["bundle"] / "provenance.json").read_text("ascii"))
    provenance["session_skeleton_sha256"] = _sha(skeleton.read_bytes())
    provenance_data = _write_canonical(inputs["bundle"] / "provenance.json", provenance)
    current = json.loads(inputs["current"].read_text("ascii"))
    current["bundle_id"] = "bundle-" + _sha(provenance_data)[:24]
    current["bundle_sha256"] = _sha(provenance_data)
    _write_canonical(inputs["current"], current)
    assert init_capture(**inputs, capture=tmp_path / "capture", _clock=_fixed_clock).codes == (
        "COLLECTOR_MEMBER_UNSAFE",
    )


@pytest.mark.parametrize("relation", ["equal", "inside", "contains"])
def test_init_capture_rejects_bundle_capture_overlap_without_changing_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relation: str
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    before = _tree_digest(inputs["bundle"])
    if relation == "equal":
        capture = inputs["bundle"]
    elif relation == "inside":
        capture = inputs["bundle"] / "capture"
    else:
        capture = tmp_path
    result = init_capture(**inputs, capture=capture, _clock=_fixed_clock)
    assert result.codes == ("COLLECTOR_PATH_OVERLAP",)
    assert _tree_digest(inputs["bundle"]) == before


@pytest.mark.parametrize("extra", ["extra.txt", "empty/"])
def test_init_capture_rejects_unlisted_or_directory_zip_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    skeleton = inputs["bundle"] / "session-skeleton.zip"
    with zipfile.ZipFile(skeleton, "a") as archive:
        archive.writestr(extra, b"" if extra.endswith("/") else b"extra")
    _rebind_skeleton(inputs)
    assert init_capture(**inputs, capture=tmp_path / "capture", _clock=_fixed_clock).codes == (
        "COLLECTOR_MEMBER_EXTRA",
    )


def _rebind_skeleton(inputs: dict[str, Path]) -> None:
    skeleton = inputs["bundle"] / "session-skeleton.zip"
    provenance = json.loads((inputs["bundle"] / "provenance.json").read_text("ascii"))
    provenance["session_skeleton_sha256"] = _sha(skeleton.read_bytes())
    provenance_data = _write_canonical(inputs["bundle"] / "provenance.json", provenance)
    current = json.loads(inputs["current"].read_text("ascii"))
    current["bundle_id"] = "bundle-" + _sha(provenance_data)[:24]
    current["bundle_sha256"] = _sha(provenance_data)
    _write_canonical(inputs["current"], current)


def _rewrite_provenance(inputs: dict[str, Path], provenance: dict[str, object]) -> None:
    data = _write_canonical(inputs["bundle"] / "provenance.json", provenance)
    current = json.loads(inputs["current"].read_text("ascii"))
    current["bundle_id"] = "bundle-" + _sha(data)[:24]
    current["bundle_sha256"] = _sha(data)
    _write_canonical(inputs["current"], current)


def test_init_capture_rejects_duplicate_zip_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    skeleton = inputs["bundle"] / "session-skeleton.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(skeleton, "a") as archive:
            archive.writestr("templates/readme.txt", b"operator skeleton\n")
    _rebind_skeleton(inputs)
    assert init_capture(**inputs, capture=tmp_path / "capture", _clock=_fixed_clock).codes == (
        "COLLECTOR_MEMBER_DUPLICATE",
    )


@pytest.mark.parametrize(
    "member_path",
    [
        "CON.txt",
        "dir/com1.log",
        "nul",
        "bad<name.txt",
        "bad|name.txt",
        "bad?name.txt",
        "bad*name.txt",
        "bad\x01name.txt",
        "bad\x7fname.txt",
        "a./name.txt",
    ],
)
def test_init_capture_rejects_windows_nonportable_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member_path: str
):
    inputs = _make_bundle(tmp_path, member_path=member_path)
    _runtime_windows(monkeypatch)
    assert init_capture(**inputs, capture=tmp_path / "capture", _clock=_fixed_clock).codes == (
        "COLLECTOR_MEMBER_PATH_INVALID",
    )


@pytest.mark.parametrize("member_path", ["session.json", "Session.JSON", "session.json/child.txt"])
def test_init_capture_reserves_session_control_namespace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, member_path: str
):
    inputs = _make_bundle(tmp_path, member_path=member_path)
    _runtime_windows(monkeypatch)
    assert init_capture(**inputs, capture=tmp_path / "capture", _clock=_fixed_clock).codes == (
        "COLLECTOR_MEMBER_PATH_COLLISION",
    )


def test_preflight_rejects_symlink_ancestor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    real = tmp_path / "real"
    inputs = _make_bundle(real)
    _runtime_windows(monkeypatch)
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    linked_inputs = {key: linked / value.relative_to(real) for key, value in inputs.items()}
    assert preflight(**linked_inputs, _clock=_fixed_clock).codes == ("COLLECTOR_PATH_UNSAFE",)


def test_status_rejects_unknown_or_closed_session_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    capture = tmp_path / "capture"
    assert init_capture(**inputs, capture=capture, _clock=_fixed_clock).ok
    session = json.loads((capture / "session.json").read_text("ascii"))
    session["unknown"] = True
    _write_canonical(capture / "session.json", session)
    assert status(capture).codes == ("COLLECTOR_SESSION_INVALID",)
    session.pop("unknown")
    session["capture_status"] = "closed"
    _write_canonical(capture / "session.json", session)
    assert status(capture).codes == ("COLLECTOR_SESSION_INVALID",)


def test_preflight_rejects_unknown_provenance_and_handoff_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    provenance = json.loads((inputs["bundle"] / "provenance.json").read_text("ascii"))
    provenance["unknown"] = True
    _rewrite_provenance(inputs, provenance)
    assert preflight(**inputs, _clock=_fixed_clock).codes == ("COLLECTOR_PROVENANCE_INVALID",)

    inputs = _make_bundle(tmp_path / "binding")
    handoff = json.loads((inputs["bundle"] / "handoff.json").read_text("ascii"))
    handoff["catalog_sha256"] = "f" * 64
    handoff_data = _write_canonical(inputs["bundle"] / "handoff.json", handoff)
    provenance = json.loads((inputs["bundle"] / "provenance.json").read_text("ascii"))
    provenance["handoff_sha256"] = _sha(handoff_data)
    _rewrite_provenance(inputs, provenance)
    assert preflight(**inputs, _clock=_fixed_clock).codes == (
        "COLLECTOR_HANDOFF_BINDING_MISMATCH",
    )


def test_init_validates_all_members_before_staging_and_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    skeleton = inputs["bundle"] / "session-skeleton.zip"
    second = b"second\n"
    with zipfile.ZipFile(skeleton, "a", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("templates/second.txt", second)
    provenance = json.loads((inputs["bundle"] / "provenance.json").read_text("ascii"))
    provenance["session_skeleton_sha256"] = _sha(skeleton.read_bytes())
    provenance["session_skeleton_members"].append(
        {"path": "templates/second.txt", "sha256": "0" * 64, "size": len(second)}
    )
    _rewrite_provenance(inputs, provenance)
    capture = tmp_path / "capture"
    assert init_capture(**inputs, capture=capture, _clock=_fixed_clock).codes == (
        "COLLECTOR_MEMBER_HASH_MISMATCH",
    )
    assert not capture.exists()
    assert list(tmp_path.glob(".capture.staging-*")) == []
    provenance["session_skeleton_members"][1]["sha256"] = _sha(second)
    _rewrite_provenance(inputs, provenance)
    assert init_capture(**inputs, capture=capture, _clock=_fixed_clock).ok


@pytest.mark.parametrize("mutation", ["compressed", "extra", "encrypted"])
def test_init_rejects_unsupported_zip_features(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    skeleton = inputs["bundle"] / "session-skeleton.zip"
    info = zipfile.ZipInfo("templates/readme.txt")
    if mutation == "compressed":
        info.compress_type = zipfile.ZIP_DEFLATED
    elif mutation == "extra":
        info.extra = b"\x01\x00\x00\x00"
    else:
        info.flag_bits = 1
    with zipfile.ZipFile(skeleton, "w") as archive:
        archive.writestr(info, b"operator skeleton\n")
    if mutation == "encrypted":
        payload = bytearray(skeleton.read_bytes())
        payload[6] |= 1
        central = payload.index(b"PK\x01\x02")
        payload[central + 8] |= 1
        skeleton.write_bytes(payload)
    _rebind_skeleton(inputs)
    result = init_capture(**inputs, capture=tmp_path / "capture", _clock=_fixed_clock)
    assert result.codes in {("COLLECTOR_MEMBER_UNSUPPORTED",), ("COLLECTOR_SKELETON_INVALID",)}


def test_malformed_ledger_and_untrusted_operation_time_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    ledger = json.loads(inputs["ledger"].read_text("ascii"))
    ledger["active_handoff_ids"] = [{}]
    _write_canonical(inputs["ledger"], ledger)
    assert preflight(**inputs, _clock=_fixed_clock).codes == ("COLLECTOR_LEDGER_INVALID",)
    assert preflight(**inputs, _clock=lambda: datetime(2026, 7, 15, 18, 0, 0)).codes == (
        "COLLECTOR_CLOCK_INVALID",
    )
    with pytest.raises(TypeError):
        preflight(**inputs, observed_at=NOW)  # type: ignore[call-arg]
    with pytest.raises(SystemExit) as rejected:
        collector_main(
            [
                "preflight",
                "--bundle",
                str(inputs["bundle"]),
                "--current",
                str(inputs["current"]),
                "--revocation-ledger",
                str(inputs["ledger"]),
                "--observed-at",
                NOW,
            ]
        )
    assert rejected.value.code == 2


def test_reparse_attribute_and_case_insensitive_overlap_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    inputs = _make_bundle(tmp_path)
    _runtime_windows(monkeypatch)
    original = Path.lstat
    target = inputs["current"]

    class ReparseStat:
        def __init__(self, wrapped):
            self._wrapped = wrapped
            self.st_file_attributes = 0x400

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

    def fake_lstat(path: Path):
        result = original(path)
        return ReparseStat(result) if path == target else result

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    assert preflight(**inputs, _clock=_fixed_clock).codes == ("COLLECTOR_PATH_UNSAFE",)
    monkeypatch.setattr(Path, "lstat", original)
    case_capture = inputs["bundle"].parent / inputs["bundle"].name.upper() / "capture"
    assert init_capture(**inputs, capture=case_capture, _clock=_fixed_clock).codes == (
        "COLLECTOR_PATH_OVERLAP",
    )
