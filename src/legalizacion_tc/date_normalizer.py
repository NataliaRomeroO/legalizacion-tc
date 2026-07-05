"""Parseo flexible de fechas en extractos Excel y sufijos de ``detalle_gasto``.

Formatos soportados:
- ``datetime`` / ``date`` nativos, enteros Excel serial, ``YYYYMMDD`` compacto.
- ``DD-MMM-YY`` con meses en español e inglés (``15-jun-26``, ``27/05/2026``).
- Sufijo en detalle: ``12 DE MAYO`` (requiere ``default_year`` si falta año).

Años de dos dígitos: ≥70 → 1900s; <70 → 2000s.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd
from dateutil import parser as date_parser

_COMPACT_DATE_RE = re.compile(r"^\d{8}$")
_DMY_ABBREV_RE = re.compile(
    r"^(\d{1,2})[-/](\w{3})[-/](\d{2,4})$",
    re.IGNORECASE,
)

_MONTH_ABBREV = {
    "jan": 1,
    "ene": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "abr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "ago": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
    "dic": 12,
}


def _normalize_raw(value: object) -> str:
    """Convierte valor de celda a texto recortado."""
    return str(value).strip()


def _expand_two_digit_year(year: int) -> int:
    """Expande año de 2 dígitos: ≥70 → 1900s; <70 → 2000s."""
    if year >= 100:
        return year
    return 1900 + year if year >= 70 else 2000 + year


def _parse_compact_yyyymmdd(digits: str) -> date | None:
    """Parsea fecha compacta ``YYYYMMDD``; retorna ``None`` si el formato no coincide."""
    if not _COMPACT_DATE_RE.match(digits):
        return None
    year = int(digits[:4])
    month = int(digits[4:6])
    day = int(digits[6:8])
    return date(year, month, day)


def _parse_dmy_abbrev(text: str) -> date | None:
    """Parsea ``DD-MMM-YY`` con abreviaturas de mes en español o inglés."""
    match = _DMY_ABBREV_RE.match(text)
    if not match:
        return None
    day = int(match.group(1))
    month_key = match.group(2).lower()
    month = _MONTH_ABBREV.get(month_key)
    if month is None:
        return None
    year = _expand_two_digit_year(int(match.group(3)))
    return date(year, month, day)


def _digits_from_numeric(value: int | float) -> str | None:
    """Extrae 8 dígitos de serial Excel numérico; ``None`` si NaN o longitud distinta."""
    if pd.isna(value):
        return None
    digits = str(int(value))
    if len(digits) == 8 and digits.isdigit():
        return digits
    return None


def parse_flexible_date(value: object) -> date:
    """Parsea fecha desde Excel, texto o serial numérico con múltiples formatos.

    Lanza ``ValueError`` si el valor está vacío o es inválido.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        raise ValueError("Fecha vacía o inválida")

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if isinstance(value, (int, float)) and not pd.isna(value):
        digits = _digits_from_numeric(value)
        if digits:
            return _parse_compact_yyyymmdd(digits)

    text = _normalize_raw(value)
    if not text or text.lower() in {"nan", "nat"}:
        raise ValueError("Fecha vacía o inválida")

    compact = _parse_compact_yyyymmdd(text)
    if compact is not None:
        return compact

    abbreviated = _parse_dmy_abbrev(text)
    if abbreviated is not None:
        return abbreviated

    return date_parser.parse(text, dayfirst=True).date()


_SPANISH_MONTH = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

_SPANISH_DETALLE_SUFFIX_RE = re.compile(
    r"(\d{1,2})\s+DE\s+(\w+)\s*$",
    re.IGNORECASE,
)
_NUMERIC_DETALLE_SUFFIX_RE = re.compile(
    r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\s*$",
)


def parse_detalle_date_suffix(
    text: str, default_year: int | None = None
) -> date | None:
    """Extrae fecha al final de ``detalle_gasto`` (español o numérico).

    Formato ``12 DE MAYO`` requiere ``default_year``; retorna ``None`` si no hay coincidencia.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return None

    spanish = _SPANISH_DETALLE_SUFFIX_RE.search(cleaned)
    if spanish:
        month = _SPANISH_MONTH.get(spanish.group(2).lower())
        if month is not None and default_year is not None:
            try:
                return date(default_year, month, int(spanish.group(1)))
            except ValueError:
                return None

    numeric = _NUMERIC_DETALLE_SUFFIX_RE.search(cleaned)
    if numeric:
        day, month, year = (
            int(numeric.group(1)),
            int(numeric.group(2)),
            int(numeric.group(3)),
        )
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None
