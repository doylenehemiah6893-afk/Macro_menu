import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator


SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "intake-initial-baseline.schema.json"
)
RECORD_PATH = (
    Path(__file__).parents[1]
    / "intake"
    / "records"
    / "2026-07-13-initial-baseline.json"
)
CUTOFF = "abce8ffe37d25cc8f189ae9e9a2a1e942279a5ad"
SRC_TREE = "0f7263465cdd5ecd7dbe5ceff090cad859cc1173"
RESOURCES_TREE = "720c20864bff3c48694acaf780b50518f49b9a60"


def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _valid_record() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "initial_baseline",
        "status": "accepted",
        "recorded_date": "2026-07-13",
        "approver": "approved-reviewer",
        "upstream": {
            "repository": "verysolecd/Macro_menu",
            "ref": "dev",
            "commit": CUTOFF,
        },
        "fork": {
            "repository": "doylenehemiah6893-afk/Macro_menu",
            "ref": "dev",
            "commit": CUTOFF,
        },
        "work_pre_intake_commit": CUTOFF,
        "merge_commit": None,
        "merge_reason": "initial-baseline/no-content-intake",
        "trees": {
            "Src": {"cutoff_oid": SRC_TREE, "work_oid": SRC_TREE},
            "resources": {
                "cutoff_oid": RESOURCES_TREE,
                "work_oid": RESOURCES_TREE,
            },
        },
        "changed_paths": [],
        "override_decisions": [],
        "checks": {
            "remote_refs_equal": True,
            "cutoff_is_work_ancestor": True,
            "src_tree_equal": True,
            "resources_tree_equal": True,
            "reserved_namespace_absent": True,
            "portable_paths": "passed",
            "form_frx_pairs": "passed",
        },
        "superseded_kit_ids": [],
    }


def test_initial_baseline_schema_accepts_no_content_record() -> None:
    assert list(_validator().iter_errors(_valid_record())) == []


def test_repository_initial_baseline_record_matches_schema() -> None:
    record = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    assert list(_validator().iter_errors(record)) == []


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        (lambda value: value.update({"unknown": True}), ""),
        (lambda value: value.update({"merge_commit": "a" * 40}), "merge_commit"),
        (lambda value: value["changed_paths"].append("Src/A.bas"), "changed_paths"),
        (lambda value: value["upstream"].update({"commit": "b" * 40}), "checks"),
    ],
)
def test_initial_baseline_schema_rejects_non_baseline_shapes(
    mutation: Callable[[dict[str, Any]], None], expected_path: str
) -> None:
    record = _valid_record()
    mutation(record)
    assert list(_validator().iter_errors(record)), expected_path
