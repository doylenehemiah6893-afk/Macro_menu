from __future__ import annotations

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import catvba_refactor.target_collector.records as records_module

from catvba_refactor.target_collector.canonical import canonical_json_bytes
from catvba_refactor.target_collector.records import (
    LICENSE_IDS,
    POINT_ORDER,
    add_operator_record,
    import_reference_csv,
    record_entitlements,
    record_environment,
    recover_stale_record_lock,
    stable_reference_id,
)


REFERENCE_HEADER = (
    "guid,major,minor,display_name,missing,architecture,source_class,root_kind,"
    "basename,relative_path,path_sha256\n"
)
REFERENCE_ROW = (
    "{00020430-0000-0000-C000-000000000046},2,0,VBA,false,x64,system,"
    "CATIA_INSTALL,vbe7.dll,win_b64/code/bin/vbe7.dll," + "1" * 64 + "\n"
)


@pytest.fixture
def capture(tmp_path: Path) -> Path:
    path = tmp_path / "capture"
    path.mkdir()
    session = {
        "schema_version": 1,
        "session_id": "session-20260715120000-raw",
        "created_at": "2026-07-15T12:00:00Z",
        "capture_status": "in-progress",
        "trust_level": "raw-untrusted",
        "mode": "discovery",
        "package_id": "core",
        "profile_id": "DISCOVERY",
        "bundle_id": "bundle-" + "a" * 24,
        "kit_id": "kit-" + "b" * 16,
        "handoff_id": "handoff-discovery-test",
        "compile_status": "not-run",
        "target_case_status": "not-run",
        "artifact_status": "not-produced",
        "release_eligible": False,
    }
    (path / "session.json").write_bytes(canonical_json_bytes(session))
    return path


def _environment(**updates: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": 1,
        "windows": {"edition": "Windows 11 Enterprise", "build": "22631", "architecture": "Win64"},
        "catia": {"release": "V5-6R2018", "revision": "R28", "build": "B28"},
        "vba": {"generation": "VBA7", "win64": True},
        "pollution_scan": {
            "B30": "absent",
            "x86": "absent",
            "VBA6": "absent",
            "Temp": "absent",
            "user-profile": "absent",
        },
    }
    document.update(updates)
    return document


def _entitlements(rows: tuple[tuple[str, str, str], ...] | None = None) -> io.StringIO:
    rows = rows or tuple((item, "observed-available", "observed-checked-out") for item in LICENSE_IDS)
    text = "license_id,availability,checkout\n"
    text += "".join(",".join(row) + "\n" for row in rows)
    return io.StringIO(text)


def _add_review(capture: Path, tmp_path: Path, name: str, text: str) -> dict[str, object]:
    source = tmp_path / f"{name}.txt"
    source.write_text(text, encoding="utf-8")
    result = add_operator_record(capture, source=source, category="review")
    assert result.ok
    return dict(result.facts)


def test_constants_and_reference_csv_produce_stable_sorted_ids(capture: Path):
    assert POINT_ORDER == (
        "blank-project", "post-form-import", "post-all-import", "post-save", "post-restart"
    )
    assert LICENSE_IDS == ("AB3", "HD2", "MD2", "SPA", "FTA")
    second = (
        "{00020430-0000-0000-C000-000000000047},1,0,Second,false,x64,system,"
        "SYSTEM,second.dll,System32/second.dll," + "2" * 64 + "\n"
    )
    result = import_reference_csv(
        capture, point="blank-project", source=io.StringIO(REFERENCE_HEADER + second + REFERENCE_ROW)
    )
    assert result.ok
    document = json.loads((capture / "references.json").read_text("ascii"))
    observation = document["observations"][0]
    assert observation["point_id"] == "blank-project"
    observed = [item["stable_reference_id"] for item in observation["references"]]
    assert observed == sorted(observed)
    assert observed[0].startswith("reference-")
    assert document["compile_status"] == "not-run"
    assert document["trust_level"] == "raw-untrusted"


@pytest.mark.parametrize(
    "relative_path",
    [
        r"C:\Users\operator\vbe7.dll",
        r"\\server\share\vbe7.dll",
        "Users/operator/vbe7.dll",
        "customer-A/vbe7.dll",
    ],
)
def test_collector_rejects_sensitive_reference_paths(capture: Path, relative_path: str):
    row = REFERENCE_ROW.replace("win_b64/code/bin/vbe7.dll", relative_path)
    result = import_reference_csv(capture, point="blank-project", source=io.StringIO(REFERENCE_HEADER + row))
    assert result.codes == ("COLLECTOR_SENSITIVE_PATH_FORBIDDEN",)
    assert not (capture / "references.json").exists()


@pytest.mark.parametrize(
    "display_name",
    [
        r"Loaded from C:\private\vbe7.dll",
        r"file:///Users/alice/vbe7.dll",
        "Customer Alpha VBA",
        "customer name=Alice",
        "user name: bob",
        "account id=ACME-42",
        "operator login: op01",
    ],
)
def test_reference_rejects_sensitive_free_text(capture: Path, display_name: str):
    row = REFERENCE_ROW.replace(",VBA,false,", f",{display_name},false,")
    assert import_reference_csv(
        capture, point="blank-project", source=io.StringIO(REFERENCE_HEADER + row)
    ).codes == ("COLLECTOR_SENSITIVE_PATH_FORBIDDEN",)


@pytest.mark.parametrize("display_name", ["=HYPERLINK(A1)", "+cmd", "line\tbreak"])
def test_reference_rejects_formula_and_control_display_text(capture: Path, display_name: str):
    row = REFERENCE_ROW.replace(",VBA,false,", f",{display_name},false,")
    assert import_reference_csv(
        capture, point="blank-project", source=io.StringIO(REFERENCE_HEADER + row)
    ).codes == ("COLLECTOR_SENSITIVE_PATH_FORBIDDEN",)


@pytest.mark.parametrize(
    "text",
    [
        r"Screenshot source: \\server\share",
        "Home is $HOME",
        "Saved under /home/alice/capture",
        "customer name: Alice",
        "user name=bob",
        "user id: 42",
        "customer login=alice",
    ],
)
def test_operator_text_rejects_sensitive_paths_and_identity(capture: Path, tmp_path: Path, text: str):
    source = tmp_path / "note.txt"
    source.write_text(text, encoding="utf-8")
    assert add_operator_record(capture, source=source, category="other").codes == (
        "COLLECTOR_SENSITIVE_PATH_FORBIDDEN",
    )


def test_reference_points_are_sequential_closed_and_duplicate_ids_fail(capture: Path):
    skipped = import_reference_csv(
        capture, point="post-form-import", source=io.StringIO(REFERENCE_HEADER + REFERENCE_ROW)
    )
    assert skipped.codes == ("COLLECTOR_POINT_ORDER_INVALID",)
    assert import_reference_csv(
        capture, point="blank-project", source=io.StringIO(REFERENCE_HEADER + REFERENCE_ROW)
    ).ok
    closed = import_reference_csv(
        capture, point="blank-project", source=io.StringIO(REFERENCE_HEADER + REFERENCE_ROW)
    )
    assert closed.codes == ("COLLECTOR_POINT_CLOSED",)

    duplicate = import_reference_csv(
        capture,
        point="post-form-import",
        source=io.StringIO(REFERENCE_HEADER + REFERENCE_ROW + REFERENCE_ROW),
    )
    assert duplicate.codes == ("COLLECTOR_REFERENCE_DUPLICATE",)


def test_reference_missing_is_explicit_and_public_path_fields_are_limited(capture: Path):
    row = REFERENCE_ROW.replace("false,x64", "true,unknown")
    assert import_reference_csv(
        capture, point="blank-project", source=io.StringIO(REFERENCE_HEADER + row)
    ).ok
    item = json.loads((capture / "references.json").read_text("ascii"))["observations"][0]["references"][0]
    assert item["missing"] is True
    assert set(item) == {
        "architecture", "basename", "display_name", "guid", "major", "minor", "missing",
        "path_sha256", "relative_path", "root_kind", "source_class", "stable_reference_id",
    }


def test_environment_is_fixed_to_approved_b28_win64_vba7_and_is_exclusive(capture: Path):
    result = record_environment(capture, _environment())
    assert result.ok
    saved = json.loads((capture / "environment.json").read_text("ascii"))
    assert saved["catia"] == {"build": "B28", "release": "V5-6R2018", "revision": "R28"}
    assert saved["compile_status"] == "not-run"
    assert record_environment(capture, _environment()).codes == ("COLLECTOR_OUTPUT_EXISTS",)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("catia", "build", "B30"),
        ("windows", "architecture", "x86"),
        ("vba", "generation", "VBA6"),
        ("pollution_scan", "Temp", "present"),
        ("pollution_scan", "user-profile", "present"),
    ],
)
def test_environment_rejects_pollution(section: str, field: str, value: object, capture: Path):
    document = _environment()
    assert isinstance(document[section], dict)
    document[section][field] = value  # type: ignore[index]
    assert record_environment(capture, document).codes == ("COLLECTOR_ENVIRONMENT_FORBIDDEN",)


def test_environment_rejects_sensitive_free_text(capture: Path):
    document = _environment()
    document["windows"]["edition"] = r"Windows at C:\Users\operator"  # type: ignore[index]
    assert record_environment(capture, document).codes == ("COLLECTOR_SENSITIVE_PATH_FORBIDDEN",)


def test_environment_rejects_duplicate_json_keys(capture: Path, tmp_path: Path):
    source = tmp_path / "environment.json"
    source.write_text(
        '{"schema_version":1,"schema_version":1,"windows":{},"catia":{},"vba":{},"pollution_scan":{}}',
        encoding="ascii",
    )
    assert record_environment(capture, source).codes == ("COLLECTOR_INPUT_INVALID",)


@pytest.mark.parametrize(("field", "value"), [("edition", "x" * 101), ("build", "1" * 33)])
def test_environment_enforces_schema_text_lengths(capture: Path, field: str, value: str):
    document = _environment()
    document["windows"][field] = value  # type: ignore[index]
    assert record_environment(capture, document).codes == ("COLLECTOR_INPUT_INVALID",)


def test_entitlements_require_exact_five_ids_and_each_availability_checkout(capture: Path):
    assert record_entitlements(capture, _entitlements()).ok
    saved = json.loads((capture / "entitlements.json").read_text("ascii"))
    assert set(saved["licenses"]) == set(LICENSE_IDS)
    assert all(set(value) == {"availability", "checkout"} for value in saved["licenses"].values())
    assert saved["qualification_expression"] == "(AB3 OR HD2 OR MD2) AND SPA AND FTA"

    other = capture.parent / "other"
    other.mkdir()
    (other / "session.json").write_bytes((capture / "session.json").read_bytes())
    rows = tuple((item, "observed-available", "observed-checked-out") for item in LICENSE_IDS[:-1])
    assert record_entitlements(other, _entitlements(rows)).codes == ("COLLECTOR_LICENSE_SET_INVALID",)


@pytest.mark.parametrize(
    ("availability", "checkout"),
    [
        ("observed-unavailable", "observed-checked-out"),
        ("unknown", "observed-checked-out"),
    ],
)
def test_entitlement_availability_checkout_implications(
    capture: Path, availability: str, checkout: str
):
    rows = list((item, "observed-available", "observed-checked-out") for item in LICENSE_IDS)
    rows[0] = ("AB3", availability, checkout)
    assert record_entitlements(capture, _entitlements(tuple(rows))).codes == (
        "COLLECTOR_LICENSE_OBSERVATION_INVALID",
    )


def test_available_but_not_checked_out_is_a_valid_raw_gate_failure_observation(capture: Path):
    rows = list((item, "observed-available", "observed-checked-out") for item in LICENSE_IDS)
    rows[0] = ("AB3", "observed-available", "not-checked-out")
    assert record_entitlements(capture, _entitlements(tuple(rows))).ok


def test_entitlement_schema_matches_checkout_implications():
    from jsonschema import Draft202012Validator

    schema = json.loads(
        (Path(__file__).parents[1] / "schemas" / "collector-entitlements-input.schema.json").read_text(
            "utf-8"
        )
    )
    document = {
        item: {"availability": "observed-available", "checkout": "observed-checked-out"}
        for item in LICENSE_IDS
    }
    Draft202012Validator(schema).validate(document)
    document["AB3"] = {"availability": "observed-available", "checkout": "not-checked-out"}
    Draft202012Validator(schema).validate(document)
    document["AB3"] = {"availability": "observed-unavailable", "checkout": "observed-checked-out"}
    assert list(Draft202012Validator(schema).iter_errors(document))


def test_operator_record_text_is_exclusive_and_image_requires_two_reviews(capture: Path, tmp_path: Path):
    text = tmp_path / "note.txt"
    text.write_text("Operator observation only; Compile was not run.\n", encoding="utf-8")
    first = add_operator_record(capture, source=text, category="environment")
    assert first.ok
    copied = capture / str(first.facts["relative_path"])
    assert copied.read_bytes() == text.read_bytes()
    assert add_operator_record(capture, source=text, category="environment").codes == (
        "COLLECTOR_OPERATOR_RECORD_EXISTS",
    )

    image = tmp_path / "screen.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    assert add_operator_record(capture, source=image, category="reference").codes == (
        "COLLECTOR_REDACTION_REVIEW_REQUIRED",
    )
    review = tmp_path / "screen.redaction-review.json"
    first_review = _add_review(capture, tmp_path, "first-review", "First independent redaction review.")
    second_review = _add_review(capture, tmp_path, "second-review", "Second independent redaction review.")
    review.write_bytes(canonical_json_bytes({
        "schema_version": 1,
        "image_sha256": __import__("hashlib").sha256(image.read_bytes()).hexdigest(),
        "review_record_ids": [first_review["record_id"], second_review["record_id"]],
        "decision": "approved-redacted",
    }))
    assert add_operator_record(capture, source=image, category="reference").ok


def test_operator_image_rejects_nonexistent_or_wrong_category_reviews(capture: Path, tmp_path: Path):
    image = tmp_path / "missing.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    review = tmp_path / "missing.redaction-review.json"
    review.write_bytes(canonical_json_bytes({
        "schema_version": 1,
        "image_sha256": __import__("hashlib").sha256(image.read_bytes()).hexdigest(),
        "review_record_ids": ["record-review-first", "record-review-second"],
        "decision": "approved-redacted",
    }))
    assert add_operator_record(capture, source=image, category="reference").codes == (
        "COLLECTOR_REDACTION_REVIEW_INVALID",
    )
    wrong = tmp_path / "wrong.txt"
    wrong.write_text("ordinary record", encoding="utf-8")
    wrong_result = add_operator_record(capture, source=wrong, category="other")
    valid_review = _add_review(capture, tmp_path, "valid-review", "Independent review.")
    review.write_bytes(canonical_json_bytes({
        "schema_version": 1,
        "image_sha256": __import__("hashlib").sha256(image.read_bytes()).hexdigest(),
        "review_record_ids": [wrong_result.facts["record_id"], valid_review["record_id"]],
        "decision": "approved-redacted",
    }))
    assert add_operator_record(capture, source=image, category="reference").codes == (
        "COLLECTOR_REDACTION_REVIEW_INVALID",
    )


def test_operator_image_rejects_tampered_review_member(capture: Path, tmp_path: Path):
    first = _add_review(capture, tmp_path, "review-a", "First review.")
    second = _add_review(capture, tmp_path, "review-b", "Second review.")
    first_member = capture / str(first["relative_path"])
    first_member.write_text("tampered review", encoding="utf-8")
    image = tmp_path / "tampered.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    sidecar = tmp_path / "tampered.redaction-review.json"
    sidecar.write_bytes(canonical_json_bytes({
        "schema_version": 1,
        "image_sha256": __import__("hashlib").sha256(image.read_bytes()).hexdigest(),
        "review_record_ids": [first["record_id"], second["record_id"]],
        "decision": "approved-redacted",
    }))
    assert add_operator_record(capture, source=image, category="reference").codes == (
        "COLLECTOR_OPERATOR_INDEX_INVALID",
    )


def test_operator_image_rejects_same_reviewer_and_oversize(capture: Path, tmp_path: Path):
    image = tmp_path / "same.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    review = tmp_path / "same.redaction-review.json"
    review.write_bytes(canonical_json_bytes({
        "schema_version": 1,
        "image_sha256": __import__("hashlib").sha256(image.read_bytes()).hexdigest(),
        "review_record_ids": ["record-review-same", "record-review-same"],
        "decision": "approved-redacted",
    }))
    assert add_operator_record(capture, source=image, category="reference").codes == (
        "COLLECTOR_REDACTION_REVIEW_INVALID",
    )
    huge = tmp_path / "huge.txt"
    huge.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    assert add_operator_record(capture, source=huge, category="other").codes == (
        "COLLECTOR_OPERATOR_RECORD_TOO_LARGE",
    )
    binary = tmp_path / "binary.txt"
    binary.write_bytes(b"not-text\x00\xff")
    assert add_operator_record(capture, source=binary, category="other").codes == (
        "COLLECTOR_OPERATOR_RECORD_TYPE_INVALID",
    )


def test_operator_text_allows_redacted_multiline_instructions(capture: Path, tmp_path: Path):
    source = tmp_path / "safe.txt"
    source.write_text("Observation redacted.\r\nCompile status remains not-run.\tChecked.\n", encoding="utf-8")
    assert add_operator_record(capture, source=source, category="other").ok


@pytest.mark.parametrize(
    "csv_text",
    [
        "name,value\nitem, =FORMULA()\n",
        "name,name\none,two\n",
        'name,value\n"unterminated,value\n',
        "name,value\none,two,three\n",
    ],
)
def test_operator_csv_is_strict_bounded_and_formula_safe(
    capture: Path, tmp_path: Path, csv_text: str
):
    source = tmp_path / "observation.csv"
    source.write_text(csv_text, encoding="utf-8")
    assert add_operator_record(capture, source=source, category="other").codes == (
        "COLLECTOR_OPERATOR_RECORD_TYPE_INVALID",
    )


def test_operator_csv_accepts_small_rectangular_observation(capture: Path, tmp_path: Path):
    source = tmp_path / "observation.csv"
    source.write_text("name,value\nstatus,not-run\n", encoding="utf-8")
    assert add_operator_record(capture, source=source, category="other").ok


@pytest.mark.parametrize(
    "text",
    [
        "DSLS endpoint=license.example.invalid",
        "host: workstation-01",
        "10.20.30.40",
        "https://example.invalid/path",
        "person@example.invalid",
        "password=redacted",
        "api key: redacted",
        "/opt/private/capture",
    ],
)
def test_operator_text_rejects_endpoint_secret_and_absolute_paths(
    capture: Path, tmp_path: Path, text: str
):
    source = tmp_path / "unsafe.txt"
    source.write_text(text, encoding="utf-8")
    assert add_operator_record(capture, source=source, category="other").codes == (
        "COLLECTOR_SENSITIVE_PATH_FORBIDDEN",
    )


def test_record_mutations_share_capture_lock(capture: Path):
    lock = capture / ".collector-records.lock"
    lock.write_bytes(b"held")
    assert record_environment(capture, _environment()).codes == ("COLLECTOR_CAPTURE_BUSY",)
    assert not (capture / "environment.json").exists()


def test_lock_fd_remains_open_through_write(capture: Path, monkeypatch: pytest.MonkeyPatch):
    original = records_module._write_exclusive
    observed: list[bool] = []

    def probe(path, document):
        backend = records_module._ACTIVE_BACKEND.get()
        assert backend is not None
        observed.append(os.fstat(backend.lock_fd).st_nlink == 1)
        return original(path, document)

    monkeypatch.setattr(records_module, "_write_exclusive", probe)
    assert record_environment(capture, _environment()).ok
    assert observed == [True]


def test_identity_change_before_publish_rolls_back_new_file(
    capture: Path, monkeypatch: pytest.MonkeyPatch
):
    original = records_module._CaptureWriteBackend.verify
    calls = 0

    def fail_after_publish(self):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise records_module.CollectorError("COLLECTOR_PATH_UNSAFE")
        return original(self)

    monkeypatch.setattr(records_module._CaptureWriteBackend, "verify", fail_after_publish)
    assert record_environment(capture, _environment()).codes == ("COLLECTOR_PATH_UNSAFE",)
    assert not (capture / "environment.json").exists()


def test_explicit_stale_lock_recovery_requires_dead_pid_identity_and_no_staging(capture: Path):
    info = capture.stat()
    lock = capture / ".collector-records.lock"
    lock.write_text(
        "schema_version=1\npid=99999999\nnonce=" + "a" * 32
        + f"\ncapture_dev={info.st_dev}\ncapture_ino={info.st_ino}\n",
        encoding="ascii",
    )
    assert recover_stale_record_lock(capture) is True
    assert not lock.exists()

    lock.write_text(
        "schema_version=1\npid=99999999\nnonce=" + "b" * 32
        + f"\ncapture_dev={info.st_dev}\ncapture_ino={info.st_ino}\n",
        encoding="ascii",
    )
    (capture / ".record-staging-blocked").write_bytes(b"pending")
    with pytest.raises(records_module.CollectorError, match="COLLECTOR_STALE_LOCK_STAGING_PRESENT"):
        recover_stale_record_lock(capture)
    assert lock.exists()


@pytest.mark.parametrize(
    ("handle", "last_error", "wait_result", "expected", "expected_closes"),
    [
        (0, 87, 0, False, []),
        (0, 5, 0, True, []),
        (101, 0, 0x00000102, True, [101]),
        (202, 0, 0x00000000, False, [202]),
        (303, 0, 0xFFFFFFFF, True, [303]),
    ],
)
def test_windows_process_probe_never_uses_kill_and_closes_handles(
    monkeypatch: pytest.MonkeyPatch,
    handle: int,
    last_error: int,
    wait_result: int,
    expected: bool,
    expected_closes: list[int],
):
    class Kernel32:
        def __init__(self):
            self.closed: list[int] = []

        def OpenProcess(self, access, inherit, pid):
            assert access == 0x00101000
            assert inherit is False
            assert pid == 12345
            return handle

        def WaitForSingleObject(self, opened_handle, timeout):
            assert opened_handle == handle
            assert timeout == 0
            return wait_result

        def CloseHandle(self, opened_handle):
            self.closed.append(opened_handle)
            return 1

    kernel32 = Kernel32()
    monkeypatch.setattr(records_module.os, "name", "nt")
    monkeypatch.setattr(records_module.ctypes, "WinDLL", lambda *args, **kwargs: kernel32, raising=False)
    monkeypatch.setattr(records_module.ctypes, "get_last_error", lambda: last_error, raising=False)
    monkeypatch.setattr(
        records_module.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(AssertionError("os.kill forbidden on Windows")),
    )
    assert records_module._process_is_alive(12345) is expected
    assert kernel32.closed == expected_closes


def test_concurrent_operator_adds_never_lose_an_index_entry(capture: Path, tmp_path: Path):
    sources = [tmp_path / "one.txt", tmp_path / "two.txt"]
    for index, source in enumerate(sources):
        source.write_text(f"independent observation {index}", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda source: add_operator_record(capture, source=source, category="other"), sources))
    successes = sum(result.ok for result in results)
    assert successes in {1, 2}
    assert all(result.ok or result.codes == ("COLLECTOR_CAPTURE_BUSY",) for result in results)
    index = json.loads((capture / "operator-records" / "index.json").read_text("ascii"))
    assert len(index["records"]) == successes


def test_operator_input_rejects_symlink_and_hardlink(capture: Path, tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("safe text", encoding="utf-8")
    symlink = tmp_path / "symlink.txt"
    symlink.symlink_to(source)
    assert add_operator_record(capture, source=symlink, category="other").codes == (
        "COLLECTOR_FILE_UNSAFE",
    )
    hardlink = tmp_path / "hardlink.txt"
    os.link(source, hardlink)
    assert add_operator_record(capture, source=hardlink, category="other").codes == (
        "COLLECTOR_FILE_UNSAFE",
    )


def test_stable_reference_id_normalizes_guid_and_cli_lists_commands():
    assert stable_reference_id("{00020430-0000-0000-c000-000000000046}", 2, 0) == stable_reference_id(
        "{00020430-0000-0000-C000-000000000046}", 2, 0
    )
    from catvba_refactor.target_collector.cli import _parser

    help_text = _parser().format_help()
    for command in ("record-environment", "record-entitlements", "import-reference-csv", "add-operator-record"):
        assert command in help_text


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda document: document.update({"compile_status": "passed"}), "COLLECTOR_REFERENCES_INVALID"),
        (lambda document: document.update({"release_eligible": True}), "COLLECTOR_REFERENCES_INVALID"),
        (lambda document: document.update({"point_order": list(reversed(POINT_ORDER))}), "COLLECTOR_REFERENCES_INVALID"),
        (
            lambda document: document["observations"][0]["references"][0].update(
                {"stable_reference_id": "reference-" + "0" * 24}
            ),
            "COLLECTOR_REFERENCES_INVALID",
        ),
    ],
)
def test_reference_append_rejects_tampered_existing_document(
    capture: Path, mutation, code: str
):
    assert import_reference_csv(
        capture, point="blank-project", source=io.StringIO(REFERENCE_HEADER + REFERENCE_ROW)
    ).ok
    path = capture / "references.json"
    document = json.loads(path.read_text("ascii"))
    mutation(document)
    path.write_bytes(canonical_json_bytes(document))
    before = path.read_bytes()
    result = import_reference_csv(
        capture, point="post-form-import", source=io.StringIO(REFERENCE_HEADER + REFERENCE_ROW)
    )
    assert result.codes == (code,)
    assert path.read_bytes() == before


def test_operator_append_rejects_tampered_index_envelope(capture: Path, tmp_path: Path):
    first = tmp_path / "first.txt"
    first.write_text("first", encoding="utf-8")
    assert add_operator_record(capture, source=first, category="other").ok
    index = capture / "operator-records" / "index.json"
    document = json.loads(index.read_text("ascii"))
    document["release_eligible"] = True
    index.write_bytes(canonical_json_bytes(document))
    before = index.read_bytes()
    second = tmp_path / "second.txt"
    second.write_text("second", encoding="utf-8")
    assert add_operator_record(capture, source=second, category="other").codes == (
        "COLLECTOR_OPERATOR_INDEX_INVALID",
    )
    assert index.read_bytes() == before


def test_operator_append_rejects_rehashed_control_text(capture: Path, tmp_path: Path):
    first = tmp_path / "first.txt"
    first.write_text("first", encoding="utf-8")
    assert add_operator_record(capture, source=first, category="other").ok
    index = capture / "operator-records" / "index.json"
    document = json.loads(index.read_text("ascii"))
    record = document["records"][0]
    old_member = capture / record["relative_path"]
    bad = b"bad\x00text"
    digest = __import__("hashlib").sha256(bad).hexdigest()
    new_id = "record-" + __import__("hashlib").sha256(
        ("other\0" + digest).encode("ascii")
    ).hexdigest()[:24]
    new_directory = old_member.parent.with_name(new_id)
    old_member.parent.rename(new_directory)
    new_member = new_directory / old_member.name
    new_member.write_bytes(bad)
    record.update({
        "record_id": new_id,
        "relative_path": f"operator-records/{new_id}/{new_member.name}",
        "sha256": digest,
        "size": len(bad),
    })
    index.write_bytes(canonical_json_bytes(document))
    second = tmp_path / "second.txt"
    second.write_text("second", encoding="utf-8")
    assert add_operator_record(capture, source=second, category="other").codes == (
        "COLLECTOR_OPERATOR_INDEX_INVALID",
    )
