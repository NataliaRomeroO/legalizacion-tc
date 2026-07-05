"""Tests de ``parse_flexible_date``: formatos Excel, español y dayfirst."""

from datetime import date, datetime

import pytest

from legalizacion_tc.date_normalizer import parse_flexible_date


def test_parse_flexible_date_user_formats():
    """Verifica parse flexible date user formats."""
    assert parse_flexible_date("15-jun-26") == date(2026, 6, 15)
    assert parse_flexible_date("10-jun-26") == date(2026, 6, 10)
    assert parse_flexible_date("20260601") == date(2026, 6, 1)
    assert parse_flexible_date("20260529") == date(2026, 5, 29)
    assert parse_flexible_date(20260601) == date(2026, 6, 1)
    assert parse_flexible_date(20260601.0) == date(2026, 6, 1)


def test_parse_flexible_date_datetime_objects():
    """Verifica parse flexible date datetime objects."""
    assert parse_flexible_date(datetime(2026, 6, 15, 12, 0)) == date(2026, 6, 15)
    assert parse_flexible_date(date(2026, 5, 9)) == date(2026, 5, 9)


def test_parse_flexible_date_spanish_abbrev():
    """Verifica parse flexible date spanish abbrev."""
    assert parse_flexible_date("15-jun-26") == date(2026, 6, 15)
    assert parse_flexible_date("01-jul-26") == date(2026, 7, 1)


def test_parse_flexible_date_dayfirst_fallback():
    """Verifica parse flexible date dayfirst fallback."""
    assert parse_flexible_date("27/05/2026") == date(2026, 5, 27)


def test_parse_flexible_date_invalid():
    """Verifica parse flexible date invalid."""
    with pytest.raises(ValueError):
        parse_flexible_date(None)
    with pytest.raises(ValueError):
        parse_flexible_date("")
