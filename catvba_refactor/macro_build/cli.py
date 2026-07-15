from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .audit import AuditReport, audit_catvba
from .canonical import canonical_json_bytes
from .errors import BuildKitError, ExitCode, InfrastructureError
from .generator import generate_sources
from .git_objects import GitRepository, freeze_snapshot
from .handoff import HandoffReceipt, HandoffRequest, issue_target_handoff
from .inventory import scan_inputs
from .kit import assemble_catalog, stage_build_kit, verify_build_kit
from .manifests import ManifestSet, load_and_validate_config
from .model import (
    BuildKitReceipt,
    Diagnostic,
    Inventory,
    ResolvedCatalog,
    ValidationReport,
    VerificationReport,
)
from .policy import validate_catalog
from .resolver import resolve_sources


try:
    __version__ = version("macro-menu")
except PackageNotFoundError:  # pragma: no cover - editable/root install is canonical
    __version__ = "0.1.0"


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_GLOBAL_OPTIONS = frozenset(
    {"--repo-root", "--config-dir", "--schema-dir", "--output-root", "--format"}
)
_HANDOFF_SCALAR_OPTIONS = frozenset(
    {
        "--compare-build-root",
        "--purpose",
        "--supersedes-handoff",
        "--revocation-snapshot",
        "--prepared-record-id",
        "--review-record-id",
        "--created-at",
        "--expires-at",
    }
)


def _global_parent() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        add_help=False,
        allow_abbrev=False,
        argument_default=argparse.SUPPRESS,
    )
    parser.add_argument("--repo-root", type=Path, help="repository root")
    parser.add_argument("--config-dir", type=Path, help="manifest directory")
    parser.add_argument("--schema-dir", type=Path, help="JSON Schema directory")
    parser.add_argument("--output-root", type=Path, help="Build Kit output root")
    parser.add_argument("--format", choices=("text", "json"), help="report format")
    return parser


def build_parser() -> argparse.ArgumentParser:
    common = _global_parent()
    parser = argparse.ArgumentParser(
        prog="macro-menu-build",
        description="Build and audit deterministic CATVBA offline Build Kits",
        parents=[common],
        allow_abbrev=False,
        argument_default=argparse.SUPPRESS,
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser(
        "inventory",
        parents=[common],
        allow_abbrev=False,
        help="inventory fixed Git inputs",
    )
    inventory.add_argument(
        "--worktree", action="store_true", help="diagnostic worktree inventory"
    )

    check = commands.add_parser(
        "check",
        parents=[common],
        allow_abbrev=False,
        help="run the complete offline static check",
    )
    check.add_argument(
        "--worktree", action="store_true", help="diagnostic worktree check"
    )

    commands.add_parser(
        "build-kit",
        parents=[common],
        allow_abbrev=False,
        help="stage a deterministic candidate Kit",
    )

    verify = commands.add_parser(
        "verify-kit",
        parents=[common],
        allow_abbrev=False,
        help="verify a Kit directory or ZIP",
    )
    verify.add_argument("kit", type=Path)

    audit = commands.add_parser(
        "audit-catvba",
        parents=[common],
        allow_abbrev=False,
        help="audit a returned CATVBA read-only",
    )
    audit.add_argument("returned_catvba", type=Path)
    audit.add_argument("--expect", required=True, type=Path, dest="expected_manifest")
    audit.add_argument("--package", dest="package_id")

    handoff = commands.add_parser(
        "create-target-handoff",
        parents=[common],
        allow_abbrev=False,
        help="issue one detached authenticated target handoff",
    )
    handoff.add_argument("primary_build_root", type=Path)
    handoff.add_argument("--compare-build-root", required=True, type=Path)
    handoff.add_argument("--purpose", required=True, choices=("discovery", "formal"))
    handoff.add_argument("--supersedes-handoff", type=Path)
    handoff.add_argument("--revocation-snapshot", required=True, type=Path)
    handoff.add_argument("--prepared-record-id", required=True)
    handoff.add_argument("--review-record-id", required=True)
    handoff.add_argument("--created-at")
    handoff.add_argument("--expires-at", required=True)
    return parser


def _reject_duplicate_global_options(
    parser: argparse.ArgumentParser, argv: list[str]
) -> None:
    seen: set[str] = set()
    for token in argv:
        option = token.split("=", 1)[0]
        if option not in _GLOBAL_OPTIONS:
            continue
        if option in seen:
            parser.error(f"{option} may be specified at most once")
        seen.add(option)


def _reject_duplicate_handoff_options(
    parser: argparse.ArgumentParser, argv: list[str]
) -> None:
    if "create-target-handoff" not in argv:
        return
    seen: set[str] = set()
    for token in argv:
        option = token.split("=", 1)[0]
        if option not in _HANDOFF_SCALAR_OPTIONS:
            continue
        if option in seen:
            parser.error(f"{option} may be specified at most once")
        seen.add(option)


def _format(args: argparse.Namespace) -> str:
    return getattr(args, "format", "text")


def _locations(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    repo_root = getattr(args, "repo_root", _REPOSITORY_ROOT)
    config_dir = getattr(
        args, "config_dir", repo_root / "catvba_refactor" / "config"
    )
    schema_dir = getattr(
        args, "schema_dir", repo_root / "catvba_refactor" / "schemas"
    )
    output_root = getattr(
        args, "output_root", repo_root / "catvba_refactor" / "dist"
    )
    return repo_root, config_dir, schema_dir, output_root


def _diagnostic_key(diagnostic: Diagnostic) -> tuple[str, str, str, bytes]:
    return (
        diagnostic.code,
        diagnostic.path,
        diagnostic.message,
        canonical_json_bytes(diagnostic.details),
    )


def _diagnostics(values: tuple[Diagnostic, ...]) -> list[dict[str, Any]]:
    return [
        {
            "code": item.code,
            "path": item.path,
            "message": item.message,
            "details": item.details,
        }
        for item in sorted(values, key=_diagnostic_key)
    ]


def _text_value(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, (str, int)):
        return str(value)
    return canonical_json_bytes(value).decode("ascii").rstrip("\n")


def _text_report(document: dict[str, Any]) -> str:
    lines: list[str] = []
    for key in sorted(key for key in document if key != "diagnostics"):
        lines.append(f"{key}={_text_value(document[key])}")
    for diagnostic in document.get("diagnostics", []):
        lines.append(
            "diagnostic"
            f"\tcode={_text_value(diagnostic['code'])}"
            f"\tpath={_text_value(diagnostic['path'])}"
            f"\tmessage={_text_value(diagnostic['message'])}"
            f"\tdetails={_text_value(diagnostic['details'])}"
        )
    return "\n".join(lines) + "\n"


def _emit(
    document: dict[str, Any], report_format: str, *, error: bool = False
) -> None:
    stream = sys.stderr if error else sys.stdout
    if report_format == "json":
        stream.write(canonical_json_bytes(document).decode("ascii"))
    else:
        stream.write(_text_report(document))


def _report_document(
    command: str,
    report: ValidationReport | VerificationReport,
    **fields: Any,
) -> dict[str, Any]:
    ok = report.ok and not report.diagnostics
    return {
        "command": command,
        "ok": ok,
        **fields,
        "diagnostics": _diagnostics(report.diagnostics),
    }


def _manifest_failure(
    args: argparse.Namespace, manifests: ManifestSet, **fields: Any
) -> int | None:
    if manifests.report.ok:
        return None
    _emit(
        _report_document(args.command, manifests.report, **fields), _format(args)
    )
    return int(ExitCode.CONFIG)


def _source_failure(
    args: argparse.Namespace, report: ValidationReport, **fields: Any
) -> int | None:
    if report.ok:
        return None
    _emit(_report_document(args.command, report, **fields), _format(args))
    return int(ExitCode.SOURCE)


def _load_source_context(
    args: argparse.Namespace, *, worktree: bool
) -> tuple[ManifestSet, Any, Any, Inventory] | int:
    repo_root, config_dir, schema_dir, _output_root = _locations(args)
    manifests = load_and_validate_config(config_dir, schema_dir)
    failed = _manifest_failure(
        args, manifests, formal_eligible=False, mode="unavailable"
    )
    if failed is not None:
        return failed
    repository = GitRepository(repo_root)
    snapshot = freeze_snapshot(
        repository,
        manifests.project,
        manifests.digest,
        __version__,
        worktree=worktree,
    )
    inventory = scan_inputs(snapshot, manifests, repository)
    return manifests, repository, snapshot, inventory


def _component_records(inventory: Inventory) -> list[dict[str, Any]]:
    return [
        {
            "source_id": component.source_id,
            "vb_name": component.vb_name,
            "component_type": component.component_type,
            "origin": component.origin.value,
            "package_id": component.package_id,
            "disposition": component.disposition,
            "members": [
                {
                    "path": member.path,
                    "role": member.role,
                    "raw_sha256": member.raw_sha256,
                    "blob_oid": member.blob_oid,
                }
                for member in component.members
            ],
        }
        for component in inventory.components
    ]


def _inventory_command(args: argparse.Namespace) -> int:
    context = _load_source_context(args, worktree=getattr(args, "worktree", False))
    if isinstance(context, int):
        return context
    _manifests, _repository, snapshot, inventory = context
    document = _report_document(
        args.command,
        inventory.report,
        formal_eligible=inventory.formal_eligible,
        mode=snapshot.mode.value,
        components=_component_records(inventory),
    )
    _emit(document, _format(args))
    return int(ExitCode.SUCCESS if inventory.report.ok else ExitCode.SOURCE)


def _catalog_context(
    args: argparse.Namespace, *, worktree: bool
) -> tuple[ResolvedCatalog, Inventory] | int:
    context = _load_source_context(args, worktree=worktree)
    if isinstance(context, int):
        return context
    manifests, _repository, snapshot, inventory = context
    failed = _source_failure(
        args,
        inventory.report,
        formal_eligible=inventory.formal_eligible,
        mode=snapshot.mode.value,
    )
    if failed is not None:
        return failed
    resolved = resolve_sources(inventory, manifests)
    failed = _source_failure(
        args,
        resolved.report,
        formal_eligible=inventory.formal_eligible,
        mode=snapshot.mode.value,
    )
    if failed is not None:
        return failed
    generated = generate_sources(resolved, manifests, snapshot)
    failed = _source_failure(
        args,
        generated.report,
        formal_eligible=inventory.formal_eligible,
        mode=snapshot.mode.value,
    )
    if failed is not None:
        return failed
    catalog = assemble_catalog(snapshot, resolved, generated, manifests)
    catalog = replace(catalog, report=validate_catalog(catalog))
    return catalog, inventory


def _check_command(args: argparse.Namespace) -> int:
    context = _catalog_context(args, worktree=getattr(args, "worktree", False))
    if isinstance(context, int):
        return context
    catalog, inventory = context
    document = _report_document(
        args.command,
        catalog.report,
        formal_eligible=inventory.formal_eligible,
        mode=catalog.snapshot.mode.value,
        component_count=len(catalog.components),
    )
    _emit(document, _format(args))
    return int(ExitCode.SUCCESS if catalog.report.ok else ExitCode.SOURCE)


def _receipt_document(receipt: BuildKitReceipt) -> dict[str, Any]:
    return {
        "command": "build-kit",
        "ok": True,
        "formal_eligible": True,
        "target_build_required": True,
        "compile_status": "not-run",
        "release_eligible": False,
        "kit_id": receipt.kit_id,
        "kit_dir": receipt.kit_dir,
        "zip_path": receipt.zip_path,
        "zip_sha256": receipt.zip_sha256,
        "manifest_sha256": receipt.manifest_sha256,
        "diagnostics": [],
    }


def _build_command(args: argparse.Namespace) -> int:
    context = _catalog_context(args, worktree=False)
    if isinstance(context, int):
        return context
    catalog, inventory = context
    failed = _source_failure(
        args,
        catalog.report,
        formal_eligible=inventory.formal_eligible,
        mode=catalog.snapshot.mode.value,
    )
    if failed is not None:
        return failed
    _repo_root, _config_dir, _schema_dir, output_root = _locations(args)
    receipt = stage_build_kit(catalog, output_root)
    _emit(_receipt_document(receipt), _format(args))
    return int(ExitCode.SUCCESS)


def _verify_command(args: argparse.Namespace) -> int:
    report = verify_build_kit(args.kit)
    _emit(_report_document(args.command, report), _format(args))
    verified = report.ok and not report.diagnostics
    return int(ExitCode.SUCCESS if verified else ExitCode.VERIFICATION)


def _audit_document(report: AuditReport) -> dict[str, Any]:
    return {
        "command": "audit-catvba",
        "ok": not report.diagnostics,
        "package_id": report.package_id,
        "file_sha256": report.file_sha256,
        "streams": list(report.streams),
        "modules": list(report.modules),
        "references": list(report.references),
        "reference_verification": {
            "status": report.reference_verification.status,
            "contract_body_digest": (
                report.reference_verification.contract_body_digest
            ),
            "observation_sha256": (
                report.reference_verification.observation_sha256
            ),
            "matched_stable_ids": list(
                report.reference_verification.matched_stable_ids
            ),
        },
        "pcode": {
            "status": report.pcode.status,
            "returncode": report.pcode.returncode,
            "stdout_sha256": report.pcode.stdout_sha256,
            "stderr_sha256": report.pcode.stderr_sha256,
            "diagnostic_only": report.pcode.diagnostic_only,
        },
        "compile_status": "not-run",
        "release_eligible": False,
        "diagnostics": _diagnostics(report.diagnostics),
    }


def _audit_command(args: argparse.Namespace) -> int:
    report = audit_catvba(
        args.returned_catvba,
        args.expected_manifest,
        package_id=getattr(args, "package_id", None),
    )
    _emit(_audit_document(report), _format(args))
    return int(ExitCode.SUCCESS if not report.diagnostics else ExitCode.VERIFICATION)


def _handoff_receipt_document(receipt: HandoffReceipt) -> dict[str, Any]:
    return {
        "command": "create-target-handoff",
        "ok": True,
        "handoff_id": receipt.handoff_id,
        "handoff_path": receipt.handoff_path,
        "handoff_sha256": receipt.handoff_sha256,
        "kit_id": receipt.kit_id,
        "kit_zip_sha256": receipt.kit_zip_sha256,
        "diagnostics": [],
    }


def _current_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_handoff_input(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise InfrastructureError(f"HANDOFF_INPUT_READ_FAILED: {path}") from error


def _create_target_handoff_command(args: argparse.Namespace) -> int:
    supersedes_path = getattr(args, "supersedes_handoff", None)
    created_at = getattr(args, "created_at", None) or _current_utc()
    request = HandoffRequest(
        purpose=args.purpose,
        created_at=created_at,
        expires_at=args.expires_at,
        revocation_snapshot=_read_handoff_input(args.revocation_snapshot),
        prepared_record_id=args.prepared_record_id,
        review_record_id=args.review_record_id,
        supersedes_handoff=(
            _read_handoff_input(supersedes_path)
            if supersedes_path is not None
            else None
        ),
    )
    receipt = issue_target_handoff(
        args.primary_build_root,
        args.compare_build_root,
        request,
        args.output_root,
    )
    _emit(_handoff_receipt_document(receipt), _format(args))
    return int(ExitCode.SUCCESS)


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "inventory":
        return _inventory_command(args)
    if args.command == "check":
        return _check_command(args)
    if args.command == "build-kit":
        return _build_command(args)
    if args.command == "verify-kit":
        return _verify_command(args)
    if args.command == "audit-catvba":
        return _audit_command(args)
    if args.command == "create-target-handoff":
        return _create_target_handoff_command(args)
    raise AssertionError(f"unknown command: {args.command}")


def emit_error(
    error: BuildKitError, report_format: str, command: str
) -> None:
    _emit(
        {
            "command": command,
            "ok": False,
            "error": {
                "exit_code": int(error.exit_code),
                "message": str(error),
                "type": type(error).__name__,
            },
            "diagnostics": [],
        },
        report_format,
        error=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    _reject_duplicate_global_options(parser, arguments)
    _reject_duplicate_handoff_options(parser, arguments)
    args = parser.parse_args(arguments)
    if args.command == "create-target-handoff" and not hasattr(args, "output_root"):
        parser.error("create-target-handoff requires --output-root")
    try:
        return dispatch(args)
    except BuildKitError as error:
        emit_error(error, _format(args), args.command)
        return int(error.exit_code)
