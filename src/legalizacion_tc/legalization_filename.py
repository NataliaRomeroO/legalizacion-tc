"""Nomenclatura versionada del Excel de salida.

Formato nuevo: ``Formato de Legalización TC {card} - {día} - {MES} - {año}.xlsx``.
Colisiones mismo día → sufijo ``v2``, ``v3``, … (case-insensitive).
Legacy sin día: ``Formato de Legalización TC {card} - {MES} - {año}.xlsx``.
``execution_date()`` usa timezone Bogotá por defecto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .extract_parser import NUM_TO_ES

_LEGALIZATION_PREFIX = "Formato de Legalización TC"
_NEW_PATTERN = re.compile(
    r"^Formato de Legalizaci[oó]n TC (?P<card>\d{4}) - "
    r"(?P<day>\d{1,2}) - (?P<month>[A-Za-zÁÉÍÓÚÑáéíóúñ]+)"
    r"(?: v(?P<version>\d+))? - (?P<year>\d{4})\.xlsx$",
    re.IGNORECASE,
)
_LEGACY_PATTERN = re.compile(
    r"^Formato de Legalizaci[oó]n TC (?P<card>\d{4}) - "
    r"(?P<month>[A-Za-zÁÉÍÓÚÑáéíóúñ]+)\s*-?\s*(?P<year>\d{4})\.xlsx$",
    re.IGNORECASE,
)
_ANY_LEGALIZATION = re.compile(r"^Formato de Legalizaci", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedLegalizationFilename:
    """Componentes parseados de un nombre de archivo Formato de Legalización."""

    card: str
    day: int | None
    month: str
    year: int
    version: int
    is_legacy: bool


def execution_date(
    *,
    as_of: date | None = None,
    timezone: str = "America/Bogota",
) -> date:
    """Fecha de ejecución del pipeline; por defecto hoy en zona horaria de Bogotá."""
    if as_of is not None:
        return as_of
    return datetime.now(ZoneInfo(timezone)).date()


def legalization_filename_base(
    card: str,
    as_of: date,
    *,
    version: int = 1,
) -> str:
    """Genera el nombre base versionado del Excel de salida para la tarjeta y fecha."""
    month = NUM_TO_ES[as_of.month]
    if version <= 1:
        return (
            f"{_LEGALIZATION_PREFIX} {card} - "
            f"{as_of.day} - {month} - {as_of.year}.xlsx"
        )
    return (
        f"{_LEGALIZATION_PREFIX} {card} - "
        f"{as_of.day} - {month} v{version} - {as_of.year}.xlsx"
    )


def resolve_legalization_filename(
    card: str,
    existing_names: set[str],
    as_of: date,
) -> str:
    """Resuelve nombre único incrementando sufijo ``v2``, ``v3``, … si hay colisión."""
    names_lower = {name.casefold() for name in existing_names}
    version = 1
    while True:
        candidate = legalization_filename_base(card, as_of, version=version)
        if candidate.casefold() not in names_lower:
            return candidate
        version += 1


def parse_legalization_filename(name: str) -> ParsedLegalizationFilename | None:
    """Parsea nombre nuevo o legacy de Formato; devuelve ``None`` si no coincide."""
    text = Path(name).name
    match = _NEW_PATTERN.match(text)
    if match:
        version = int(match.group("version") or "1")
        return ParsedLegalizationFilename(
            card=match.group("card"),
            day=int(match.group("day")),
            month=match.group("month").upper(),
            year=int(match.group("year")),
            version=version,
            is_legacy=False,
        )
    match = _LEGACY_PATTERN.match(text)
    if match:
        return ParsedLegalizationFilename(
            card=match.group("card"),
            day=None,
            month=match.group("month").upper(),
            year=int(match.group("year")),
            version=1,
            is_legacy=True,
        )
    return None


def is_legalization_file(name: str, card: str | None = None) -> bool:
    """Indica si el nombre corresponde a un Formato de legalización (no plantilla)."""
    basename = Path(name).name
    if "Plantilla" in basename:
        return False
    if not _ANY_LEGALIZATION.search(basename):
        return False
    if card is None:
        return True
    return card in basename


def output_version_from_filename(name: str) -> int:
    """Extrae el número de versión del nombre de archivo; 1 si no es parseable."""
    parsed = parse_legalization_filename(name)
    if parsed is None:
        return 1
    return parsed.version
