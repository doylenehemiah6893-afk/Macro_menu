import unicodedata

import pytest

from catvba_refactor.macro_build.errors import SourceError
from catvba_refactor.macro_build.portable_paths import (
    portable_key,
    validate_portable_ascii_paths,
    validate_portable_paths,
)


def _codes(paths: list[str]) -> list[str]:
    return [
        diagnostic.code
        for diagnostic in validate_portable_paths(paths).diagnostics
    ]


def test_portable_key_normalizes_windows_separators_and_unicode_for_matching() -> None:
    assert portable_key(r"Folder\Ａ.bas") == "folder/a.bas"


@pytest.mark.parametrize(
    ("paths", "codes"),
    [
        (["folder/中.bas"], ["PATH_NOT_ASCII"]),
        ([r"folder\A.bas"], ["PATH_SEPARATOR_INVALID"]),
        (["folder/bad\x00.bas"], ["PATH_INVALID_CHARACTER"]),
        (["folder/bad\x7f.bas"], ["PATH_INVALID_CHARACTER"]),
        *(
            ([f"folder/bad{character}.bas"], ["PATH_INVALID_CHARACTER"])
            for character in '<>:"|?*'
        ),
        (["folder/../A.bas"], ["PATH_TRAVERSAL"]),
        (["folder/CON.bas"], ["PATH_RESERVED_NAME"]),
        (["Folder/A.bas", "folder/a.bas"], ["PATH_COLLISION"]),
        (
            ["Ｆｏｏ.bas", "foo.bas"],
            ["PATH_COLLISION", "PATH_NOT_ASCII"],
        ),
    ],
)
def test_portable_ascii_paths_reject_unsafe_evidence_names(
    paths: list[str], codes: list[str]
) -> None:
    report = validate_portable_ascii_paths(paths)

    assert [diagnostic.code for diagnostic in report.diagnostics] == codes


@pytest.mark.parametrize(
    "path",
    ["folder/中.bas", r"folder\A.bas", "folder/bad<.bas"],
)
def test_portable_ascii_validation_does_not_change_source_path_behavior(
    path: str,
) -> None:
    assert validate_portable_paths([path]).ok


@pytest.mark.parametrize(
    "path",
    ["folder/中.bas", r"folder\A.bas", "folder/bad<.bas"],
)
def test_portable_ascii_diagnostics_preserve_stored_name(path: str) -> None:
    report = validate_portable_ascii_paths([path])

    assert report.diagnostics[0].path == path


def test_surrogateescaped_non_utf8_path_is_rejected() -> None:
    assert _codes(["bad-\udcff.bas"]) == ["PATH_INVALID_UTF8"]


def test_empty_path_is_rejected_without_folding_into_an_empty_segment() -> None:
    with pytest.raises(SourceError, match=r"^PATH_EMPTY$"):
        portable_key("")


@pytest.mark.parametrize("path", ["folder/", "folder//A.bas", r"folder\\A.bas"])
def test_empty_stored_segments_are_rejected(path: str) -> None:
    with pytest.raises(SourceError, match=r"^PATH_EMPTY_SEGMENT$"):
        portable_key(path)


def test_leading_spaces_are_not_stripped_from_stored_components() -> None:
    assert portable_key(" Folder/ A.bas") == " folder/ a.bas"
    assert validate_portable_paths(["Folder/A.bas", " Folder/ A.bas"]).ok


def test_nfkc_separator_inside_component_does_not_fabricate_prefix() -> None:
    assert validate_portable_paths(["a", "a／b/c.bas"]).ok


def test_nfkc_separator_inside_component_does_not_fabricate_reserved_name() -> None:
    assert validate_portable_paths(["x／CON.bas"]).ok


def test_nfkc_separator_does_not_collapse_distinct_component_boundaries() -> None:
    assert validate_portable_paths(["a／b", "a/b"]).ok
    assert portable_key("a／b") != portable_key("a/b")
    assert portable_key("a／b") != portable_key("a~1b")


@pytest.mark.parametrize(
    "path",
    [
        "/root/A.bas",
        r"\root\A.bas",
        r"\\server\share\A.bas",
        "C:/A.bas",
        r"C:\A.bas",
        "C:A.bas",
    ],
)
def test_absolute_unc_and_drive_paths_are_rejected(path: str) -> None:
    with pytest.raises(SourceError, match=r"^PATH_ABSOLUTE$"):
        portable_key(path)


@pytest.mark.parametrize(
    "path",
    [".", "..", "x/./y.bas", "x/../y.bas", r"x\..\y.bas"],
)
def test_dot_segments_are_rejected(path: str) -> None:
    with pytest.raises(SourceError, match=r"^PATH_TRAVERSAL$"):
        portable_key(path)


@pytest.mark.parametrize(
    "path",
    ["folder./A.bas", "folder /A.bas", "folder/A.bas.", "folder/A.bas "],
)
def test_trailing_dot_or_space_in_any_segment_is_rejected(path: str) -> None:
    assert _codes([path]) == ["PATH_TRAILING_DOT_SPACE"]


@pytest.mark.parametrize(
    "path",
    [
        "CON.bas",
        "nul",
        "folder/PrN.cls",
        *(f"folder/COM{number}.txt" for number in range(1, 10)),
        *(f"LPT{number}.frm" for number in range(1, 10)),
    ],
)
def test_windows_reserved_basenames_are_rejected(path: str) -> None:
    assert _codes([path]) == ["PATH_RESERVED_NAME"]


def test_names_outside_the_reserved_numeric_range_remain_valid() -> None:
    assert validate_portable_paths(
        ["COM0.bas", "COM10.bas", "LPT0.bas", "LPT10.bas"]
    ).ok


def test_case_only_names_collide() -> None:
    report = validate_portable_paths(["a.bas", "A.bas"])

    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "PATH_COLLISION"
    ]
    assert report.diagnostics[0].details["paths"] == ("A.bas", "a.bas")


def test_nfc_and_decomposed_names_collide_and_diagnostics_store_nfc() -> None:
    composed = "中文é.bas"
    decomposed = "中文e\u0301.bas"

    report = validate_portable_paths([composed, decomposed])

    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "PATH_COLLISION"
    ]
    assert report.diagnostics[0].path == composed
    assert unicodedata.is_normalized("NFC", report.diagnostics[0].path)


def test_distinct_names_that_nfkc_casefold_to_same_key_collide() -> None:
    report = validate_portable_paths(["Ｆｏｏ.bas", "foo.bas"])

    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "PATH_COLLISION"
    ]
    assert report.diagnostics[0].details["paths"] == ("foo.bas", "Ｆｏｏ.bas")


def test_file_and_directory_prefixes_collide_by_portable_key() -> None:
    report = validate_portable_paths(["dir/A.bas", "DIR"])

    assert [diagnostic.code for diagnostic in report.diagnostics] == [
        "PATH_FILE_DIR_COLLISION"
    ]
    assert report.diagnostics[0].details == {
        "directory_path": "dir",
        "file_path": "DIR",
        "nested_paths": ("dir/A.bas",),
    }


def test_diagnostics_are_sorted_by_stable_code_and_nfc_path() -> None:
    report = validate_portable_paths(
        ["z/../bad.bas", "CON.bas", "B.bas ", "/absolute.bas"]
    )
    positions = [
        (diagnostic.code, diagnostic.path)
        for diagnostic in report.diagnostics
    ]

    assert positions == sorted(positions)
    assert positions == [
        ("PATH_ABSOLUTE", "/absolute.bas"),
        ("PATH_RESERVED_NAME", "CON.bas"),
        ("PATH_TRAILING_DOT_SPACE", "B.bas "),
        ("PATH_TRAVERSAL", "z/../bad.bas"),
    ]
