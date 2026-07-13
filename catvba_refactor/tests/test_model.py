from catvba_refactor.macro_build.model import Diagnostic, ValidationReport


def test_diagnostics_have_stable_order() -> None:
    report = ValidationReport(
        diagnostics=(
            Diagnostic("Z_CODE", "b.bas", "second"),
            Diagnostic("A_CODE", "a.bas", "first"),
        )
    )
    assert [d.code for d in report.sorted().diagnostics] == ["A_CODE", "Z_CODE"]
    assert not report.ok
