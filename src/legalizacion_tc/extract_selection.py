"""Selección del mejor archivo de movimientos cuando hay varios candidatos en carpeta.

Prioridad: **PDF extracto Bancolombia** sobre preliminar ``Mov TC*.xlsx``.
Entre candidatos del mismo tipo: más movimientos → fecha máxima de tx → mtime más reciente.

Patrón PDF: ``{4dígitos}_{MES}{año}.pdf`` (ej. ``1111_MAY2026.pdf``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Literal

from .drive_manager import DriveFile, list_extract_files, list_statement_files
from .extract_loader import parse_movement_source

SourceKind = Literal["pdf", "excel"]


@dataclass
class ExtractSelection:
    """Archivo de movimientos elegido entre candidatos, con motivo y tipo de origen."""

    chosen: DriveFile
    candidates: list[DriveFile]
    reason: str
    source_kind: SourceKind


def _file_mtime(f: DriveFile) -> float:
    """Timestamp de modificación del archivo; 0.0 si no hay metadata ni ruta local."""
    if f.modified_time is not None:
        return f.modified_time
    path = Path(f.file_id)
    if path.exists():
        return path.stat().st_mtime
    return 0.0


def _score_extract(data) -> tuple[int, date, float]:
    """Tupla de ranking: cantidad de movimientos, fecha máxima de tx y placeholder mtime."""
    if data.transactions:
        max_tx_date = max(tx.tx_date for tx in data.transactions)
    else:
        max_tx_date = date.min
    return len(data.transactions), max_tx_date, 0.0


def _select_best_from_candidates(
    candidates: list[DriveFile],
    resolve_path: Callable[[DriveFile], Path],
    *,
    source_kind: SourceKind,
    label: str,
) -> ExtractSelection:
    """Desempata candidatos del mismo tipo: más movimientos → fecha máxima → mtime reciente."""
    if len(candidates) == 1:
        return ExtractSelection(
            chosen=candidates[0],
            candidates=candidates,
            reason=f"único {label} en carpeta",
            source_kind=source_kind,
        )

    scored: list[tuple[DriveFile, object, tuple[int, date, float]]] = []
    for candidate in candidates:
        loaded = parse_movement_source(resolve_path(candidate))
        scored.append((candidate, loaded.data, _score_extract(loaded.data)))

    scored.sort(
        key=lambda item: (
            item[2][0],
            item[2][1],
            _file_mtime(item[0]),
        ),
        reverse=True,
    )
    chosen, chosen_data, _ = scored[0]
    max_date = (
        max(tx.tx_date for tx in chosen_data.transactions).isoformat()
        if chosen_data.transactions
        else "sin movimientos"
    )
    reason = (
        f"{len(chosen_data.transactions)} movimientos, "
        f"fecha máxima {max_date} ({chosen.name})"
    )
    return ExtractSelection(
        chosen=chosen,
        candidates=candidates,
        reason=reason,
        source_kind=source_kind,
    )


def select_best_extract_file(
    files: list[DriveFile],
    resolve_path: Callable[[DriveFile], Path],
) -> ExtractSelection | None:
    """Elige extracto PDF Bancolombia o preliminar Excel según reglas del módulo."""
    statement_candidates = list_statement_files(files)
    if statement_candidates:
        return _select_best_from_candidates(
            statement_candidates,
            resolve_path,
            source_kind="pdf",
            label="extracto PDF",
        )

    excel_candidates = list_extract_files(files)
    if not excel_candidates:
        return None

    return _select_best_from_candidates(
        excel_candidates,
        resolve_path,
        source_kind="excel",
        label="preliminar",
    )
