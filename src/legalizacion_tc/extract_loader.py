"""Enruta archivo de movimientos al parser correcto (PDF Bancolombia o preliminar Excel).

Retorna ``LoadedExtract`` con ``source_kind`` ``pdf`` | ``excel``.
Sufijos no soportados lanzan ``ValueError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .bank_statement_parser import parse_bancolombia_statement
from .extract_parser import parse_extract
from .models import ExtractData

SourceKind = Literal["pdf", "excel"]


@dataclass
class LoadedExtract:
    """Resultado de parsear un archivo de movimientos (PDF o Excel)."""

    data: ExtractData
    source_kind: SourceKind
    source_path: Path


def parse_movement_source(path: Path) -> LoadedExtract:
    """Enruta PDF Bancolombia o preliminar Excel al parser correspondiente.

    Sufijos no soportados lanzan ``ValueError``.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return LoadedExtract(
            data=parse_bancolombia_statement(path),
            source_kind="pdf",
            source_path=path,
        )
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return LoadedExtract(
            data=parse_extract(path),
            source_kind="excel",
            source_path=path,
        )
    raise ValueError(f"Formato de origen de movimientos no soportado: {path.name}")
