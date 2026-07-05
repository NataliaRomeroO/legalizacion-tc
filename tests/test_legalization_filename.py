"""Tests de nombres versionados del Excel de legalización (``legalization_filename``)."""

from datetime import date

from legalizacion_tc.legalization_filename import (
    execution_date,
    is_legalization_file,
    legalization_filename_base,
    output_version_from_filename,
    parse_legalization_filename,
    resolve_legalization_filename,
)


def test_legalization_filename_base_without_version():
    """Verifica legalization filename base without version."""
    name = legalization_filename_base("1111", date(2026, 7, 2))
    assert name == "Formato de Legalización TC 1111 - 2 - JULIO - 2026.xlsx"


def test_legalization_filename_base_with_version():
    """Verifica legalization filename base with version."""
    name = legalization_filename_base("1111", date(2026, 7, 2), version=2)
    assert name == "Formato de Legalización TC 1111 - 2 - JULIO v2 - 2026.xlsx"


def test_day_without_leading_zero():
    """Verifica day without leading zero."""
    name = legalization_filename_base("2222", date(2026, 7, 9))
    assert " - 9 - JULIO - " in name
    assert " - 09 - " not in name


def test_resolve_without_collision():
    """Verifica resolve without collision."""
    name = resolve_legalization_filename("1111", set(), date(2026, 7, 2))
    assert name == "Formato de Legalización TC 1111 - 2 - JULIO - 2026.xlsx"
    assert output_version_from_filename(name) == 1


def test_resolve_v2_and_v3():
    """Verifica resolve v2 and v3."""
    existing = {
        "Formato de Legalización TC 1111 - 2 - JULIO - 2026.xlsx",
    }
    name_v2 = resolve_legalization_filename("1111", existing, date(2026, 7, 2))
    assert name_v2 == "Formato de Legalización TC 1111 - 2 - JULIO v2 - 2026.xlsx"
    assert output_version_from_filename(name_v2) == 2

    existing.add(name_v2)
    name_v3 = resolve_legalization_filename("1111", existing, date(2026, 7, 2))
    assert name_v3 == "Formato de Legalización TC 1111 - 2 - JULIO v3 - 2026.xlsx"
    assert output_version_from_filename(name_v3) == 3


def test_resolve_case_insensitive_collision():
    """Verifica resolve case insensitive collision."""
    existing = {"formato de legalización tc 1111 - 2 - julio - 2026.xlsx"}
    name = resolve_legalization_filename("1111", existing, date(2026, 7, 2))
    assert "v2" in name


def test_parse_new_and_legacy():
    """Verifica parse new and legacy."""
    parsed = parse_legalization_filename(
        "Formato de Legalización TC 1111 - 2 - JULIO v2 - 2026.xlsx"
    )
    assert parsed is not None
    assert parsed.card == "1111"
    assert parsed.day == 2
    assert parsed.month == "JULIO"
    assert parsed.year == 2026
    assert parsed.version == 2
    assert parsed.is_legacy is False

    legacy = parse_legalization_filename(
        "Formato de Legalización TC 1111 - MAYO - 2026.xlsx"
    )
    assert legacy is not None
    assert legacy.day is None
    assert legacy.month == "MAYO"
    assert legacy.is_legacy is True


def test_is_legalization_file():
    """Verifica is legalization file."""
    assert is_legalization_file(
        "Formato de Legalización TC 1111 - 2 - JULIO - 2026.xlsx", "1111"
    )
    assert is_legalization_file(
        "Formato de Legalización TC 1111 - MAYO - 2026.xlsx", "1111"
    )
    assert not is_legalization_file(
        "Formato de Legalización TC 1111 - MAYO - 2026.xlsx", "2222"
    )
    assert not is_legalization_file(
        "Plantilla Formato de Legalización TC #### - MAYO - 2026.xlsx", "1111"
    )


def test_execution_date_override():
    """Verifica execution date override."""
    assert execution_date(as_of=date(2026, 7, 2)) == date(2026, 7, 2)
