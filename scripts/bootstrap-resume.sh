#!/bin/sh
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/bootstrap_resume.py" --repo-root "$SCRIPT_DIR/.." --state "$SCRIPT_DIR/../resume/state.json"
