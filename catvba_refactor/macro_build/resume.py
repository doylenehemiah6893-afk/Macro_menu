from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

from .errors import ConfigError, EvidenceError, InfrastructureError
from .git_objects import GitRepository
from .model import ValidationReport
from .portable_paths import portable_key, validate_portable_ascii_paths


APPROVED_CUTOFF = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"
_REPOSITORY = "doylenehemiah6893-afk/Macro_menu"
_BRANCH = "codex/dev-review-report"
_INTAKE_PATH = "catvba_refactor/intake/records/2026-07-13-initial-baseline.json"
_SRC_TREE = "0f7263465cdd5ecd7dbe5ceff090cad859cc1173"
_RESOURCES_TREE = "720c20864bff3c48694acaf780b50518f49b9a60"
_APPROVED_REMOTES = frozenset(
    {
        "https://github.com/doylenehemiah6893-afk/Macro_menu",
        "https://github.com/doylenehemiah6893-afk/Macro_menu.git",
        "git@github.com:doylenehemiah6893-afk/Macro_menu",
        "git@github.com:doylenehemiah6893-afk/Macro_menu.git",
    }
)


@dataclass(frozen=True, order=True)
class ResumeDiagnostic:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ResumeReport:
    ok: bool
    diagnostics: tuple[ResumeDiagnostic, ...]
    facts: Mapping[str, Any]


_LEDGER_FIELDS = frozenset(
    {
        "schema_version",
        "captured_at",
        "source",
        "active_handoff_ids",
        "withdrawn_handoff_ids",
    }
)
_HANDOFF_ID = re.compile(r"^handoff-[a-z0-9][a-z0-9-]{2,94}$")
_BUNDLE_ID = re.compile(r"^bundle-[0-9a-f]{24}$")
_SOURCE = re.compile(r"^[a-z][a-z0-9._-]{2,127}$")
_UTC_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$"
)
_RAW_CAPTURE_MANIFEST_CONTROL_KEY = portable_key("raw-capture-manifest.json")
_RAW_CAPTURE_SHA256SUMS_PATH = "SHA256SUMS"


def _is_strict_integer(checker: object, instance: object) -> bool:
    del checker
    return type(instance) is int


StrictDraft202012Validator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", _is_strict_integer
    ),
)


def _ledger_error(code: str) -> EvidenceError:
    return EvidenceError(code)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"duplicate JSON key: {key}")
        document[key] = value
    return document


def _read_json(path: Path, *, read_code: str, json_code: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ConfigError(read_code) from error
    try:
        return json.loads(text, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, ValueError) as error:
        raise ConfigError(json_code) from error


def _require_internal_schema_references(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"$ref", "$dynamicRef"} and (
                not isinstance(child, str) or not child.startswith("#")
            ):
                raise ConfigError("RESUME_STATE_SCHEMA_INVALID")
            _require_internal_schema_references(child)
    elif isinstance(value, list):
        for child in value:
            _require_internal_schema_references(child)


def load_resume_state(path: Path, schema_dir: Path) -> dict[str, Any]:
    """Read and strictly validate a resume state without changing the repository."""

    state = _read_json(
        Path(path),
        read_code="RESUME_STATE_READ_ERROR",
        json_code="RESUME_STATE_JSON_INVALID",
    )
    schema = _read_json(
        Path(schema_dir) / "resume-state.schema.json",
        read_code="RESUME_STATE_SCHEMA_READ_ERROR",
        json_code="RESUME_STATE_SCHEMA_INVALID",
    )
    if not isinstance(schema, dict):
        raise ConfigError("RESUME_STATE_SCHEMA_INVALID")
    try:
        Draft202012Validator.check_schema(schema)
        _require_internal_schema_references(schema)
        validator = StrictDraft202012Validator(
            schema,
            format_checker=Draft202012Validator.FORMAT_CHECKER,
        )
        errors = tuple(validator.iter_errors(state))
    except (SchemaError, Unresolvable) as error:
        raise ConfigError("RESUME_STATE_SCHEMA_INVALID") from error
    if errors or not isinstance(state, dict):
        raise ConfigError("RESUME_STATE_INVALID")
    return state


def _utc_timestamp(value: object) -> datetime | None:
    if type(value) is not str or _UTC_TIMESTAMP.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC)


def _handoff_ids(value: object) -> list[str] | None:
    if type(value) is not list:
        return None
    if not all(type(item) is str and _HANDOFF_ID.fullmatch(item) for item in value):
        return None
    if len(value) != len(set(value)):
        return None
    return value


def validate_active_ledger(
    document: Mapping[str, Any], *, effective_at: datetime
) -> ValidationReport:
    """Validate a current handoff ledger and its cross-field time semantics.

    JSON Schema owns the serialized shape contract.  This function repeats the
    security-relevant shape checks before enforcing facts that JSON Schema
    cannot express: disjoint active/withdrawn sets and a non-future capture.
    """

    if (
        not isinstance(document, Mapping)
        or frozenset(document) != _LEDGER_FIELDS
        or document.get("schema_version") != 1
        or type(document.get("schema_version")) is not int
        or type(document.get("source")) is not str
        or _SOURCE.fullmatch(document["source"]) is None
    ):
        raise _ledger_error("HANDOFF_LEDGER_INVALID")

    active = _handoff_ids(document.get("active_handoff_ids"))
    withdrawn = _handoff_ids(document.get("withdrawn_handoff_ids"))
    captured_at = _utc_timestamp(document.get("captured_at"))
    if active is None or withdrawn is None or captured_at is None:
        raise _ledger_error("HANDOFF_LEDGER_INVALID")
    if (
        not isinstance(effective_at, datetime)
        or effective_at.tzinfo is None
        or effective_at.utcoffset() is None
    ):
        raise _ledger_error("HANDOFF_LEDGER_EFFECTIVE_TIME_INVALID")
    if set(active) & set(withdrawn):
        raise _ledger_error("HANDOFF_LEDGER_ID_OVERLAP")
    if captured_at > effective_at.astimezone(UTC):
        raise _ledger_error("HANDOFF_LEDGER_CAPTURED_IN_FUTURE")
    return ValidationReport()


def validate_raw_capture_manifest(
    document: Mapping[str, Any],
) -> ValidationReport:
    """After schema validation, enforce cross-member portable path semantics."""

    if not isinstance(document, Mapping) or type(document.get("members")) is not list:
        raise EvidenceError("RAW_CAPTURE_MANIFEST_INVALID")
    paths: list[str] = []
    for member in document["members"]:
        if not isinstance(member, Mapping) or type(member.get("path")) is not str:
            raise EvidenceError("RAW_CAPTURE_MANIFEST_INVALID")
        paths.append(member["path"])

    if paths.count(_RAW_CAPTURE_SHA256SUMS_PATH) != 1:
        raise EvidenceError("RAW_CAPTURE_SHA256SUMS_MEMBER_INVALID")
    if not validate_portable_ascii_paths(paths).ok:
        raise EvidenceError("RAW_CAPTURE_PATH_NAMESPACE_INVALID")
    if any(
        portable_key(path) == _RAW_CAPTURE_MANIFEST_CONTROL_KEY for path in paths
    ):
        raise EvidenceError("RAW_CAPTURE_CONTROL_PATH_RESERVED")
    return ValidationReport()


def _resume_report(
    diagnostics: list[ResumeDiagnostic], facts: dict[str, Any]
) -> ResumeReport:
    stable = tuple(sorted(diagnostics))
    return ResumeReport(not stable, stable, MappingProxyType(dict(sorted(facts.items()))))


def _diagnostic(code: str, path: str, message: str) -> ResumeDiagnostic:
    return ResumeDiagnostic(code=code, path=path, message=message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise InfrastructureError(f"RESUME_FILE_READ_FAILED: {path}") from error
    return digest.hexdigest()


def _git_text(repo: GitRepository, *arguments: str) -> str:
    return str(repo._run(*arguments, text=True)).strip()


def approved_repository_remote(remote_url: object) -> bool:
    """Accept only the two explicit GitHub transport forms for this repository."""
    return type(remote_url) is str and remote_url in _APPROVED_REMOTES


def _intake_is_exact(document: object) -> bool:
    if not isinstance(document, Mapping):
        return False
    try:
        return (
            document["schema_version"] == 1
            and document["record_type"] == "initial_baseline"
            and document["status"] == "accepted"
            and document["upstream"]["repository"] == "verysolecd/Macro_menu"
            and document["upstream"]["commit"] == APPROVED_CUTOFF
            and document["fork"]["repository"] == _REPOSITORY
            and document["fork"]["commit"] == APPROVED_CUTOFF
            and document["trees"]["Src"]["cutoff_oid"] == _SRC_TREE
            and document["trees"]["Src"]["work_oid"] == _SRC_TREE
            and document["trees"]["resources"]["cutoff_oid"] == _RESOURCES_TREE
            and document["trees"]["resources"]["work_oid"] == _RESOURCES_TREE
        )
    except (KeyError, TypeError):
        return False


def _internal_path(repo_root: Path, relative: object) -> Path | None:
    if type(relative) is not str or not validate_portable_ascii_paths((relative,)).ok:
        return None
    root = repo_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _canonical_control(path: Path) -> dict[str, Any]:
    """Read one canonical ASCII control document without accepting a rewrite."""

    data = path.read_bytes()
    document = json.loads(data.decode("ascii"), object_pairs_hook=_unique_object)
    expected = (
        json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")
    if type(document) is not dict or data != expected:
        raise ValueError("noncanonical control")
    return document


def _issued_bundle_records(bundle: Path) -> tuple[tuple[str, bytes], ...]:
    """Read a portable, immutable bundle tree for doctor verification."""

    try:
        root_info = bundle.lstat()
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
            raise OSError
        records: list[tuple[str, bytes]] = []
        for path in sorted(
            bundle.rglob("*"),
            key=lambda item: item.relative_to(bundle).as_posix().encode("ascii"),
        ):
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise OSError
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError
            relative = path.relative_to(bundle).as_posix()
            if not validate_portable_ascii_paths((relative,)).ok:
                raise OSError
            records.append((relative, path.read_bytes()))
    except (OSError, UnicodeError):
        raise ValueError("unsafe bundle tree") from None
    if not records:
        raise ValueError("empty bundle tree")
    return tuple(records)


def _bundle_member_digest(records: tuple[tuple[str, bytes], ...]) -> str:
    return hashlib.sha256(
        (
            json.dumps(
                [
                    {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
                    for path, data in records
                ],
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
    ).hexdigest()


def _bundle_sums(records: tuple[tuple[str, bytes], ...]) -> bytes:
    return b"".join(
        f"{hashlib.sha256(data).hexdigest()}  {path}\n".encode("ascii")
        for path, data in records
        if path != "SHA256SUMS"
    )


def _active_delivery_diagnostics(
    root: Path,
    state: Mapping[str, Any],
    now: datetime,
    *,
    enforce_authorization: bool = True,
) -> list[ResumeDiagnostic]:
    """Bind issued state to immutable bytes and, optionally, live authorization."""

    diagnostics: list[ResumeDiagnostic] = []
    bundle = _internal_path(root, state["active_bundle_path"])
    receipt = _internal_path(root, state["last_reproducibility_receipt"])
    control_root = root / "artifacts/b28-discovery"
    current = control_root / "CURRENT.json"
    ledger = control_root / "active-handoff-ledger.json"
    if bundle is None or not bundle.is_dir() or bundle.is_symlink():
        return [_diagnostic("RESUME_ACTIVE_BUNDLE_INVALID", str(state["active_bundle_path"]), "active bundle path is unsafe or unavailable")]
    if bundle.parent != control_root / "bundles" or _BUNDLE_ID.fullmatch(bundle.name) is None:
        return [_diagnostic("RESUME_ACTIVE_BUNDLE_INVALID", str(state["active_bundle_path"]), "active bundle must use the issued bundles layout")]
    if receipt is None or receipt.is_symlink() or not receipt.is_file():
        return [_diagnostic("RESUME_REPRO_RECEIPT_INVALID", str(state["last_reproducibility_receipt"]), "issued state requires a regular reproducibility receipt")]
    try:
        receipt.relative_to(bundle / "receipts")
    except ValueError:
        return [_diagnostic("RESUME_REPRO_RECEIPT_INVALID", str(state["last_reproducibility_receipt"]), "reproducibility receipt must be inside the active bundle")]
    try:
        provenance_path = bundle / "provenance.json"
        handoff_path = bundle / "handoff.json"
        paths = (provenance_path, handoff_path, current)
        if enforce_authorization:
            paths = (*paths, ledger)
        if any(not path.is_file() or path.is_symlink() for path in paths):
            raise OSError("control missing or unsafe")
        provenance_bytes = provenance_path.read_bytes()
        provenance = _canonical_control(provenance_path)
        handoff_bytes = handoff_path.read_bytes()
        handoff = _canonical_control(handoff_path)
        current_document = _canonical_control(current)
        ledger_document = _canonical_control(ledger) if enforce_authorization else None
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return [_diagnostic("RESUME_ACTIVE_CONTROL_INVALID", "artifacts/b28-discovery", "issued control files are missing, unsafe, or noncanonical")]
    provenance_digest = hashlib.sha256(provenance_bytes).hexdigest()
    handoff_digest = hashlib.sha256(handoff_bytes).hexdigest()
    bundle_id = "bundle-" + provenance_digest[:24]
    bindings = (
        bundle.name == bundle_id,
        state["bundle_digest"] == provenance_digest,
        state["active_kit_id"] == provenance.get("kit_id"),
        state["kit_zip_digest"] == provenance.get("kit_zip_sha256"),
        state["active_handoff_id"] == provenance.get("handoff_id"),
        state["handoff_digest"] == handoff_digest == provenance.get("handoff_sha256"),
        state["expiry"] == handoff.get("expires_at") == provenance.get("handoff_expires_at"),
        current_document == {
            "schema_version": 1,
            "bundle_id": bundle_id,
            "bundle_sha256": provenance_digest,
            "handoff_id": state["active_handoff_id"],
        },
        handoff.get("handoff_id") == state["active_handoff_id"],
        handoff.get("revocation_status") == "active",
    )
    if not all(bindings):
        diagnostics.append(_diagnostic("RESUME_ACTIVE_BINDING_MISMATCH", "artifacts/b28-discovery", "state, CURRENT, provenance, and handoff must bind one identity"))
    try:
        records = _issued_bundle_records(bundle)
        file_map = dict(records)
        content = tuple(
            (path, data)
            for path, data in records
            if path not in {"provenance.json", "SHA256SUMS"}
        )
        kit_id = provenance.get("kit_id")
        if (
            file_map.get("SHA256SUMS") != _bundle_sums(records)
            or _bundle_member_digest(content) != provenance.get("bundle_content_sha256")
            or type(kit_id) is not str
            or hashlib.sha256(file_map[f"{kit_id}.zip"]).hexdigest() != provenance.get("kit_zip_sha256")
            or file_map[f"{kit_id}.zip.sha256"] != f"{provenance['kit_zip_sha256']}  {kit_id}.zip\n".encode("ascii")
            or hashlib.sha256(file_map["target-discovery.pyz"]).hexdigest() != provenance.get("collector_pyz_sha256")
            or file_map["target-discovery.pyz.sha256"] != f"{provenance['collector_pyz_sha256']}  target-discovery.pyz\n".encode("ascii")
        ):
            raise ValueError("bundle integrity mismatch")
    except (KeyError, TypeError, ValueError):
        diagnostics.append(_diagnostic("RESUME_ACTIVE_BUNDLE_INTEGRITY_INVALID", str(state["active_bundle_path"]), "bundle content, checksum, Kit, or collector binding is invalid"))
    if not enforce_authorization:
        return diagnostics
    assert ledger_document is not None
    active = ledger_document.get("active_handoff_ids")
    withdrawn = ledger_document.get("withdrawn_handoff_ids")
    source = provenance.get("active_ledger_source")
    captured_at = _utc_timestamp(ledger_document.get("captured_at"))
    observed_revocation = "unavailable"
    if (
        frozenset(ledger_document) != _LEDGER_FIELDS
        or ledger_document.get("schema_version") != 1
        or type(active) is not list
        or type(withdrawn) is not list
        or not all(type(item) is str and _HANDOFF_ID.fullmatch(item) for item in active + withdrawn)
        or len(active) != len(set(active))
        or len(withdrawn) != len(set(withdrawn))
        or set(active) & set(withdrawn)
        or ledger_document.get("source") != source
        or type(source) is not str
        or _SOURCE.fullmatch(source) is None
        or captured_at is None
    ):
        diagnostics.append(_diagnostic("RESUME_ACTIVE_LEDGER_INVALID", "artifacts/b28-discovery/active-handoff-ledger.json", "active ledger is not a canonical compatible control"))
    elif captured_at > now.astimezone(UTC):
        diagnostics.append(_diagnostic("RESUME_ACTIVE_LEDGER_FUTURE", "artifacts/b28-discovery/active-handoff-ledger.json", "active ledger is captured in the future"))
    elif now.astimezone(UTC) - captured_at > timedelta(hours=24):
        diagnostics.append(_diagnostic("RESUME_ACTIVE_LEDGER_STALE", "artifacts/b28-discovery/active-handoff-ledger.json", "active ledger is older than 24 hours"))
    elif state["active_handoff_id"] in withdrawn:
        diagnostics.append(_diagnostic("RESUME_ACTIVE_HANDOFF_WITHDRAWN", "artifacts/b28-discovery/active-handoff-ledger.json", "active handoff is withdrawn"))
        observed_revocation = "withdrawn"
    elif state["active_handoff_id"] not in active:
        diagnostics.append(_diagnostic("RESUME_ACTIVE_HANDOFF_INACTIVE", "artifacts/b28-discovery/active-handoff-ledger.json", "active handoff is not active in the ledger"))
    else:
        observed_revocation = "active"
    expiry = _utc_timestamp(state["expiry"])
    if expiry is None or expiry <= now.astimezone(UTC):
        diagnostics.append(_diagnostic("RESUME_HANDOFF_EXPIRED", "expiry", "active handoff is expired"))
        observed_revocation = "expired"
    if state["revocation_status"] != observed_revocation:
        diagnostics.append(_diagnostic("RESUME_REVOCATION_STATUS_MISMATCH", "revocation_status", "state revocation status does not match current handoff control"))
    return diagnostics


def _inspect_repository(
    repo_root: Path,
    state_path: Path,
    *,
    now: datetime,
    allow_missing_dev: bool,
    scope: str,
) -> ResumeReport:
    root = Path(repo_root).resolve()
    diagnostics: list[ResumeDiagnostic] = []
    facts: dict[str, Any] = {
        "approved_cutoff": APPROVED_CUTOFF,
        "branch": None,
        "head": None,
        "local_dev": None,
        "origin_dev": None,
        "repository": None,
        "scope": scope,
    }
    if scope not in {"development", "delivery"}:
        return _resume_report(
            [_diagnostic("RESUME_SCOPE_INVALID", "scope", "scope must be development or delivery")],
            facts,
        )
    if not (root / ".git").exists():
        return _resume_report(
            [_diagnostic("RESUME_GIT_CLONE_REQUIRED", ".git", "a complete Git clone is required")],
            facts,
        )
    if now.tzinfo is None or now.utcoffset() is None:
        return _resume_report(
            [_diagnostic("RESUME_TIME_INVALID", "now", "doctor time must be timezone-aware")],
            facts,
        )
    schema_dir = root / "catvba_refactor" / "schemas"
    try:
        state = load_resume_state(Path(state_path), schema_dir)
    except ConfigError as error:
        return _resume_report(
            [_diagnostic(str(error), os.fspath(state_path), "resume state validation failed")],
            facts,
        )
    if state["repository"] != _REPOSITORY or state["branch"] != _BRANCH:
        diagnostics.append(
            _diagnostic("RESUME_STATE_IDENTITY_INVALID", os.fspath(state_path), "state repository or branch is not approved")
        )
    repo = GitRepository(root)
    try:
        if Path(_git_text(repo, "rev-parse", "--show-toplevel")).resolve() != root:
            diagnostics.append(_diagnostic("RESUME_REPOSITORY_ROOT_INVALID", ".git", "repo-root is not the Git toplevel"))
        if _git_text(repo, "rev-parse", "--is-shallow-repository") != "false":
            diagnostics.append(_diagnostic("RESUME_SHALLOW_CLONE_FORBIDDEN", ".git/shallow", "shallow clones cannot resume governed work"))
        remote_url = _git_text(repo, "remote", "get-url", "origin")
        facts["repository"] = _REPOSITORY if approved_repository_remote(remote_url) else None
        if facts["repository"] is None:
            diagnostics.append(_diagnostic("RESUME_REPOSITORY_IDENTITY_MISMATCH", "origin", "origin is not the approved repository"))
        branch = _git_text(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
        facts["branch"] = branch
        if branch != _BRANCH:
            diagnostics.append(_diagnostic("RESUME_BRANCH_MISMATCH", "HEAD", "checkout is not the approved work branch"))
        head = repo.resolve_commit("HEAD")
        facts["head"] = head
        evidence_commit = state["evidence_commit"]
        if evidence_commit is not None:
            _git_text(repo, "merge-base", "--is-ancestor", evidence_commit, head)
            if repo.tree_oid(evidence_commit) != state["evidence_tree"]:
                diagnostics.append(_diagnostic("RESUME_EVIDENCE_TREE_MISMATCH", "HEAD", "evidence commit tree does not match state"))
            governed = tuple(json.loads((root / "catvba_refactor/config/project.json").read_text(encoding="utf-8"))["governed_paths"])
            if head != evidence_commit:
                changed = tuple(line for line in _git_text(repo, "diff", "--name-only", evidence_commit, head, "--", *governed).splitlines() if line)
                if changed:
                    diagnostics.append(_diagnostic("RESUME_GOVERNED_HISTORY_CHANGED", changed[0], "post-evidence commits changed governed inputs"))
        replacements = repo.replace_refs()
        if replacements:
            diagnostics.append(_diagnostic("RESUME_REPLACE_REFS_PRESENT", replacements[0], "Git replacement refs are forbidden"))
        origin_dev = repo.ref_oid("refs/remotes/origin/dev")
        facts["origin_dev"] = origin_dev
        local_dev = repo.ref_oid("refs/heads/dev")
        facts["local_dev"] = local_dev
        if local_dev is None:
            if not allow_missing_dev:
                diagnostics.append(_diagnostic("RESUME_BASELINE_REF_MISSING", "refs/heads/dev", "approved local baseline ref is missing"))
        elif local_dev != APPROVED_CUTOFF:
            diagnostics.append(_diagnostic("RESUME_BASELINE_REF_CONFLICT", "refs/heads/dev", "local dev does not equal the approved cutoff"))
        if state["approved_cutoff"] != APPROVED_CUTOFF:
            diagnostics.append(_diagnostic("RESUME_CUTOFF_MISMATCH", "approved_cutoff", "state cutoff is not approved"))
        if repo.resolve_commit(APPROVED_CUTOFF) != APPROVED_CUTOFF:
            diagnostics.append(_diagnostic("RESUME_CUTOFF_OBJECT_INVALID", APPROVED_CUTOFF, "approved cutoff commit object is unavailable"))
        if _git_text(repo, "rev-parse", f"{APPROVED_CUTOFF}:Src") != _SRC_TREE or _git_text(repo, "rev-parse", f"{APPROVED_CUTOFF}:resources") != _RESOURCES_TREE:
            diagnostics.append(_diagnostic("RESUME_CUTOFF_TREE_MISMATCH", APPROVED_CUTOFF, "approved Src/resources trees do not match intake"))
    except (InfrastructureError, OSError, UnicodeError, json.JSONDecodeError) as error:
        diagnostics.append(_diagnostic("RESUME_GIT_INSPECTION_FAILED", ".git", str(error)))

    intake_path = _internal_path(root, state["intake_record_path"])
    if state["intake_record_path"] != _INTAKE_PATH or intake_path is None:
        diagnostics.append(_diagnostic("RESUME_INTAKE_PATH_INVALID", str(state["intake_record_path"]), "state must bind the committed initial intake record"))
    else:
        try:
            intake_bytes = intake_path.read_bytes()
            intake = json.loads(intake_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
            if hashlib.sha256(intake_bytes).hexdigest() != state["intake_record_digest"]:
                diagnostics.append(_diagnostic("RESUME_INTAKE_DIGEST_MISMATCH", _INTAKE_PATH, "intake digest does not match state"))
            if not _intake_is_exact(intake):
                diagnostics.append(_diagnostic("RESUME_INTAKE_CONTENT_INVALID", _INTAKE_PATH, "intake does not authenticate the approved cutoff and trees"))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            diagnostics.append(_diagnostic("RESUME_INTAKE_READ_FAILED", _INTAKE_PATH, "intake record is unavailable or invalid"))

    lock_path = root / "uv.lock"
    try:
        if _sha256(lock_path) != state["lock_digest"]:
            diagnostics.append(_diagnostic("RESUME_LOCK_DIGEST_MISMATCH", "uv.lock", "lock digest does not match state"))
    except InfrastructureError:
        diagnostics.append(_diagnostic("RESUME_LOCK_READ_FAILED", "uv.lock", "uv.lock is unavailable"))
    if platform.python_implementation() != "CPython" or sys.version_info[:2] != (3, 12):
        diagnostics.append(_diagnostic("RESUME_PYTHON_MISMATCH", "python", "CPython 3.12 is required"))
    uv_executable = _resolve_uv_executable()
    try:
        if uv_executable is None:
            raise OSError("uv is unavailable")
        uv_result = subprocess.run(
            [uv_executable, "--version"], check=False, capture_output=True, text=True,
            env=_uv_environment(),
        )
        if uv_result.returncode:
            diagnostics.append(_diagnostic("RESUME_UV_MISMATCH", "uv", "pinned uv version check failed"))
        elif uv_result.stdout.strip() != state["uv_requirement"]:
            diagnostics.append(_diagnostic("RESUME_UV_MISMATCH", "uv", "pinned uv version does not match state"))
    except OSError:
        diagnostics.append(_diagnostic("RESUME_UV_MISMATCH", "uv", "required uv is unavailable"))

    try:
        project = json.loads((root / "catvba_refactor/config/project.json").read_text(encoding="utf-8"))
        governed_paths = tuple(project["governed_paths"])
        if not validate_portable_ascii_paths(governed_paths).ok:
            diagnostics.append(_diagnostic("RESUME_GOVERNED_PATHS_INVALID", "catvba_refactor/config/project.json", "governed paths are not portable literals"))
        else:
            governed_status = repo.status_for(governed_paths)
            if governed_status:
                diagnostics.append(
                    _diagnostic(
                        "RESUME_GOVERNED_TREE_DIRTY",
                        governed_status[0][3:],
                        "governed working tree is dirty",
                    )
                )
            else:
                tracked_status = repo.tracked_status()
            if not governed_status and tracked_status:
                diagnostics.append(
                    _diagnostic(
                        "RESUME_TRACKED_TREE_DIRTY",
                        tracked_status[0][3:],
                        "tracked working tree is dirty",
                    )
                )
    except (OSError, ValueError, KeyError, InfrastructureError):
        diagnostics.append(_diagnostic("RESUME_PROJECT_CONFIG_INVALID", "catvba_refactor/config/project.json", "project configuration cannot be inspected"))

    for field in ("active_bundle_path", "last_reproducibility_receipt"):
        relative = state[field]
        if relative is not None:
            artifact = _internal_path(root, relative)
            if artifact is None or not artifact.exists():
                diagnostics.append(_diagnostic("RESUME_ACTIVE_ARTIFACT_MISSING", str(relative), "state references a missing artifact"))
    if state["active_bundle_path"] is None and scope == "delivery":
        diagnostics.append(
            _diagnostic(
                "RESUME_DELIVERY_NOT_ISSUED",
                "active_bundle_path",
                "delivery scope requires an active issued bundle",
            )
        )
    elif state["active_bundle_path"] is not None:
        diagnostics.extend(
            _active_delivery_diagnostics(
                root,
                state,
                now,
                enforce_authorization=scope == "delivery",
            )
        )
    facts["release_eligible"] = state["release_eligible"]
    return _resume_report(diagnostics, facts)


def doctor_repository(
    repo_root: Path,
    state_path: Path,
    *,
    now: datetime,
    scope: str = "delivery",
) -> ResumeReport:
    """Verify stable development state or strict live delivery authorization."""
    return _inspect_repository(
        repo_root,
        state_path,
        now=now,
        allow_missing_dev=False,
        scope=scope,
    )


def _frozen_sync(repo_root: Path) -> ResumeDiagnostic | None:
    uv_executable = _resolve_uv_executable()
    if uv_executable is None:
        return _diagnostic("RESUME_FROZEN_SYNC_FAILED", "uv.lock", "uv could not be started")
    environment = _uv_environment()
    environment["UV_PROJECT_ENVIRONMENT"] = os.fspath(repo_root / ".venv")
    repository = GitRepository(repo_root)
    try:
        with tempfile.TemporaryDirectory(prefix="macro-menu-resume-") as temporary:
            project = Path(temporary)
            project.chmod(0o700)
            for name in ("pyproject.toml", "uv.lock"):
                target = project / name
                target.write_bytes(repository.read_blob("HEAD", name))
                target.chmod(0o600)
            result = subprocess.run(
                [
                    uv_executable,
                    "sync",
                    "--project",
                    os.fspath(project),
                    "--frozen",
                    "--no-install-project",
                ],
                cwd=project,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
    except (OSError, InfrastructureError):
        return _diagnostic("RESUME_FROZEN_SYNC_FAILED", "uv.lock", "uv could not be started")
    if result.returncode:
        return _diagnostic(
            "RESUME_FROZEN_SYNC_FAILED",
            "uv.lock",
            f"uv sync --frozen returned {result.returncode}",
        )
    return None


def _resolve_uv_executable() -> str | None:
    """Resolve uv from an authenticated explicit path or the parent PATH."""

    if "MACRO_MENU_UV_EXECUTABLE" in os.environ:
        explicit = os.environ["MACRO_MENU_UV_EXECUTABLE"]
        candidate = Path(explicit)
        if not candidate.is_absolute():
            return None
        candidates = (candidate,)
        if os.name == "nt" and candidate.name and candidate.suffix == "":
            candidates += (candidate.with_name(candidate.name + ".exe"),)
        for resolved in candidates:
            if resolved.is_file():
                return os.fspath(resolved)
        return None
    names = ("uv.exe", "uv") if os.name == "nt" else ("uv",)
    for name in names:
        executable = shutil.which(name)
        if executable is not None:
            return executable
    return None


def _uv_environment() -> dict[str, str]:
    return {
        name: os.environ[name]
        for name in (
            "PATH",
            "SYSTEMROOT",
            "PATHEXT",
            "TEMP",
            "TMP",
            "UV_CACHE_DIR",
            "UV_LINK_MODE",
        )
        if name in os.environ
    }


def bootstrap_repository(
    repo_root: Path,
    state_path: Path,
    *,
    clock: Any = None,
) -> ResumeReport:
    """Authenticate a clone, sync locked dependencies, and create only approved dev."""
    root = Path(repo_root).resolve()
    read_clock = clock or (lambda: datetime.now(UTC))
    now = read_clock()
    preflight = _inspect_repository(
        root,
        state_path,
        now=now,
        allow_missing_dev=True,
        scope="development",
    )
    if not preflight.ok:
        return preflight
    sync_error = _frozen_sync(root)
    if sync_error is not None:
        return _resume_report([sync_error], dict(preflight.facts))
    postflight_now = read_clock()
    postflight = _inspect_repository(
        root,
        state_path,
        now=postflight_now,
        allow_missing_dev=True,
        scope="development",
    )
    if not postflight.ok:
        return postflight
    repo = GitRepository(root)
    if repo.ref_oid("refs/heads/dev") is None:
        try:
            repo.create_ref("refs/heads/dev", APPROVED_CUTOFF)
        except InfrastructureError:
            return _resume_report(
                [_diagnostic("RESUME_BASELINE_REF_CREATE_FAILED", "refs/heads/dev", "compare-and-create of approved baseline failed")],
                dict(postflight.facts),
            )
    return _inspect_repository(
        root,
        state_path,
        now=postflight_now,
        allow_missing_dev=False,
        scope="development",
    )
