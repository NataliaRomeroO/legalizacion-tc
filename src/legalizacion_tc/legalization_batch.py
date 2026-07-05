"""Etiquetas de lote en columna Legalizado del Excel (múltiples corridas mismo mes).

Primera corrida: ``Legalizado en {mes}``.
Re-ejecución mismo mes: filas previas → ``Legalizado en {mes} corte 1``, nuevas filas
con etiqueta de ejecución actual. Meses distintos no se relabelan.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Iterable
from zoneinfo import ZoneInfo

from .extract_parser import NUM_TO_ES

_LABEL_PREFIX = "Legalizado en "


def month_label_lower(period_month: str) -> str:
    """Normaliza el mes del periodo a minúsculas para etiquetas de lote."""
    return period_month.strip().lower()


def execution_period_month(
    *,
    as_of: date | None = None,
    timezone: str = "America/Bogota",
) -> str:
    """Nombre del mes en español para la corrida actual (ej. ``mayo``)."""
    if as_of is not None:
        return NUM_TO_ES[as_of.month]
    today = datetime.now(ZoneInfo(timezone)).date()
    return NUM_TO_ES[today.month]


def current_batch_label(period_month: str) -> str:
    """Etiqueta de lote sin número de corte: ``Legalizado en {mes}``."""
    return f"{_LABEL_PREFIX}{month_label_lower(period_month)}"


def execution_batch_label(
    *,
    as_of: date | None = None,
    timezone: str = "America/Bogota",
) -> str:
    """Etiqueta de lote para la ejecución actual según fecha y zona horaria."""
    return current_batch_label(execution_period_month(as_of=as_of, timezone=timezone))


def corte_batch_label(period_month: str, corte: int) -> str:
    """Etiqueta con número de corte: ``Legalizado en {mes} corte {n}``."""
    return f"{current_batch_label(period_month)} corte {corte}"


def _label_pattern(period_month: str) -> re.Pattern[str]:
    """Expresión regular para parsear etiquetas de lote de un mes dado."""
    mes = re.escape(month_label_lower(period_month))
    return re.compile(rf"^{_LABEL_PREFIX}{mes}(?: corte (\d+))?$", re.IGNORECASE)


def parse_batch_label(label: str | None, period_month: str) -> tuple[str, int | None] | None:
    """Parsea etiqueta de columna Legalizado; devuelve tipo y número de corte si aplica."""
    if label is None:
        return None
    text = str(label).strip()
    if not text:
        return None
    match = _label_pattern(period_month).match(text)
    if not match:
        return None
    if match.group(1):
        return ("corte", int(match.group(1)))
    return ("current", None)


def max_corte_number(labels: Iterable[str | None], period_month: str) -> int:
    """Mayor número de corte existente en las etiquetas del mes indicado."""
    highest = 0
    for label in labels:
        parsed = parse_batch_label(label, period_month)
        if parsed and parsed[0] == "corte":
            highest = max(highest, parsed[1])
    return highest


def _has_execution_month_batch(
    labels: Iterable[str | None], execution_month: str
) -> bool:
    """Indica si ya hay alguna fila etiquetada con el mes de ejecución."""
    for label in labels:
        parsed = parse_batch_label(label, execution_month)
        if parsed is not None:
            return True
    return False


def relabel_existing_rows(
    labels: list[str | None], execution_month: str
) -> list[str | None]:
    """Promueve etiquetas del mes de ejecución a corte; otros meses quedan intactos."""
    next_corte = max_corte_number(labels, execution_month) + 1
    promoted = corte_batch_label(execution_month, next_corte)
    has_batch = _has_execution_month_batch(labels, execution_month)
    result: list[str | None] = []
    for label in labels:
        if label is None or str(label).strip() == "":
            if has_batch:
                result.append(promoted)
            else:
                result.append(label)
            continue
        parsed = parse_batch_label(label, execution_month)
        if parsed is None:
            result.append(label)
        elif parsed[0] == "current":
            result.append(promoted)
        else:
            result.append(label)
    return result
