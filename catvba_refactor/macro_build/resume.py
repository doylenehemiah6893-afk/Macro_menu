from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
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


def _inspect_repository(
    repo_root: Path,
    state_path: Path,
    *,
    now: datetime,
    allow_missing_dev: bool,
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
    }
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
    try:
        uv_result = subprocess.run(
            ["uv", "--version"], check=False, capture_output=True, text=True,
            env={name: os.environ[name] for name in ("PATH", "SYSTEMROOT") if name in os.environ},
        )
        if uv_result.returncode or uv_result.stdout.strip() != state["uv_requirement"]:
            diagnostics.append(_diagnostic("RESUME_UV_MISMATCH", "uv", "installed uv does not match state"))
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
    expiry = state["expiry"]
    if expiry is not None:
        expires = _utc_timestamp(expiry)
        if expires is None or expires <= now.astimezone(UTC):
            diagnostics.append(_diagnostic("RESUME_HANDOFF_EXPIRED", "expiry", "active handoff is expired"))
    facts["release_eligible"] = state["release_eligible"]
    return _resume_report(diagnostics, facts)


def doctor_repository(
    repo_root: Path, state_path: Path, *, now: datetime
) -> ResumeReport:
    """Read-only verification of a fresh-clone resume environment."""
    return _inspect_repository(
        repo_root, state_path, now=now, allow_missing_dev=False
    )


def _frozen_sync(repo_root: Path) -> ResumeDiagnostic | None:
    environment = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "UV_CACHE_DIR", "UV_LINK_MODE")
        if name in os.environ
    }
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
                    "uv",
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
        root, state_path, now=now, allow_missing_dev=True
    )
    if not preflight.ok:
        return preflight
    sync_error = _frozen_sync(root)
    if sync_error is not None:
        return _resume_report([sync_error], dict(preflight.facts))
    postflight_now = read_clock()
    postflight = _inspect_repository(
        root, state_path, now=postflight_now, allow_missing_dev=True
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
        root, state_path, now=postflight_now, allow_missing_dev=False
    )
