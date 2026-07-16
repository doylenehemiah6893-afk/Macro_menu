"""Command-line interface for the native Windows discovery collector."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from .records import (
    add_operator_record,
    import_reference_csv,
    record_entitlements,
    record_environment,
)
from .workspace import CollectorResult, init_capture, preflight, status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="target-discovery",
        description="Native Windows CPython 3.12 B28 raw discovery collector",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "init-capture"):
        command = commands.add_parser(name)
        command.add_argument("--bundle", type=Path, required=True)
        command.add_argument("--current", type=Path, required=True)
        command.add_argument("--revocation-ledger", dest="ledger", type=Path, required=True)
        if name == "init-capture":
            command.add_argument("--capture", type=Path, required=True)
    status_command = commands.add_parser("status")
    status_command.add_argument("--capture", type=Path, required=True)
    environment_command = commands.add_parser("record-environment")
    environment_command.add_argument("--capture", type=Path, required=True)
    environment_command.add_argument("--input", type=Path, required=True)
    entitlements_command = commands.add_parser("record-entitlements")
    entitlements_command.add_argument("--capture", type=Path, required=True)
    entitlements_command.add_argument("--input", type=Path, required=True)
    references_command = commands.add_parser("import-reference-csv")
    references_command.add_argument("--capture", type=Path, required=True)
    references_command.add_argument("--point", choices=(
        "blank-project", "post-form-import", "post-all-import", "post-save", "post-restart"
    ), required=True)
    references_command.add_argument("--input", type=Path, required=True)
    operator_command = commands.add_parser("add-operator-record")
    operator_command.add_argument("--capture", type=Path, required=True)
    operator_command.add_argument("--input", type=Path, required=True)
    operator_command.add_argument("--category", choices=(
        "session", "environment", "entitlement", "reference", "review", "state", "other"
    ), required=True)
    return parser


def _document(result: CollectorResult) -> dict[str, object]:
    return {
        "ok": result.ok,
        "exit_code": result.exit_code,
        "diagnostics": [
            {"code": item.code, "path": item.path, "message": item.message}
            for item in result.diagnostics
        ],
        "facts": dict(result.facts),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "preflight":
        result = preflight(
            bundle=args.bundle,
            current=args.current,
            ledger=args.ledger,
        )
    elif args.command == "init-capture":
        result = init_capture(
            bundle=args.bundle,
            current=args.current,
            ledger=args.ledger,
            capture=args.capture,
        )
    elif args.command == "status":
        result = status(args.capture)
    elif args.command == "record-environment":
        result = record_environment(args.capture, args.input)
    elif args.command == "record-entitlements":
        result = record_entitlements(args.capture, args.input)
    elif args.command == "import-reference-csv":
        result = import_reference_csv(args.capture, point=args.point, source=args.input)
    else:
        result = add_operator_record(args.capture, source=args.input, category=args.category)
    print(json.dumps(_document(result), ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return result.exit_code
