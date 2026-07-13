import re

import pytest

from catvba_refactor.macro_build.runtime_contract import (
    CORE_STATES,
    ERROR_CODES,
    EXTENSION_STATES,
    FLEET_STATES,
    MAX_ARRAY_ITEMS,
    MAX_DEPTH,
    MAX_DISPLAY_LINES,
    MAX_STRING_LENGTH,
    MAX_TOTAL_NODES,
    PROTOCOL_VERSION,
    canonical_runtime_id,
    control_name,
    page_name,
)


def test_protocol_limits_error_codes_and_states_are_frozen() -> None:
    assert PROTOCOL_VERSION == "MM/1"
    assert MAX_DEPTH == 8
    assert MAX_STRING_LENGTH == 4096
    assert MAX_ARRAY_ITEMS == 256
    assert MAX_TOTAL_NODES == 2048
    assert MAX_DISPLAY_LINES == 500
    assert ERROR_CODES == {
        0: "OK",
        10: "CANCELLED",
        20: "NOT_APPLICABLE",
        30: "CAPABILITY_UNAVAILABLE",
        40: "VALIDATION_FAILED",
        50: "STATE_CHANGED",
        60: "TOOL_FAILED",
        70: "INTERNAL_ERROR",
        80: "LIMIT_REACHED",
        90: "UNKNOWN_COMMAND",
    }
    assert CORE_STATES == ("READY", "BLOCKED")
    assert EXTENSION_STATES == ("NOT_PROBED", "READY", "UNAVAILABLE", "BROKEN")
    assert FLEET_STATES == ("READY", "DEGRADED", "BLOCKED")


@pytest.mark.parametrize(
    ("factory", "stable_id", "expected"),
    [
        (
            control_name,
            "core.healthcheck",
            "btn_core_healthcheck_935fb1b1",
        ),
        (
            page_name,
            "core.general",
            "pg_core_general_635cb7db",
        ),
        (
            control_name,
            "core.punctuation-test",
            "btn_core_punctuation_test_adff9b78",
        ),
        (
            page_name,
            "core.punctuation_test",
            "pg_core_punctuation_test_80491805",
        ),
        (
            control_name,
            "core.abcdefghijklmnopqrstuvwxyz0123456789.one",
            "btn_core_abcdefghijklmnopqrstu_aaff1b93",
        ),
        (
            control_name,
            "core.abcdefghijklmnopqrstuvwxyz0123456789.two",
            "btn_core_abcdefghijklmnopqrstu_9a90f130",
        ),
    ],
)
def test_runtime_names_follow_the_approved_golden_formula(
    factory: object, stable_id: str, expected: str
) -> None:
    assert callable(factory)
    actual = factory(stable_id)

    assert actual == expected
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", actual)
    assert len(actual) <= 40


def test_colliding_26_character_slugs_have_distinct_hash_suffixes() -> None:
    first = control_name("core.abcdefghijklmnopqrstuvwxyz0123456789.one")
    second = control_name("core.abcdefghijklmnopqrstuvwxyz0123456789.two")

    assert first[:31] == second[:31] == "btn_core_abcdefghijklmnopqrstu_"
    assert first != second


def test_canonical_runtime_id_uses_nfkc_and_casefold_for_comparison() -> None:
    assert canonical_runtime_id("ＣＯＲＥ.HealthCheck") == "core.healthcheck"
    assert canonical_runtime_id("core.healthcheck") == "core.healthcheck"


@pytest.mark.parametrize("value", ["", "   ", 1, None])
def test_canonical_runtime_id_rejects_empty_or_non_string_values(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        canonical_runtime_id(value)


@pytest.mark.parametrize(
    "stable_id",
    [
        "Core.healthcheck",
        "核心.健康检查",
        "core healthcheck",
        "1core.healthcheck",
        "ab",
        "core." + "x" * 60,
    ],
)
@pytest.mark.parametrize("factory", [control_name, page_name])
def test_runtime_names_reject_schema_invalid_stable_ids(
    factory: object, stable_id: str
) -> None:
    assert callable(factory)
    with pytest.raises(ValueError, match="stable ID"):
        factory(stable_id)
