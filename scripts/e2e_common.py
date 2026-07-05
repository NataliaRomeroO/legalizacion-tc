#!/usr/bin/env python3
"""Utilidades compartidas para scripts E2E locales.

``resolve_e2e_folder``: elige carpeta con extracto; prefiere nombre con ``1111``.
Ignora ``.venv``, ``.cache``, ``tests`` al escanear candidatos.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def add_folder_argument(parser: argparse.ArgumentParser) -> None:
    """Agrega argumento --folder al parser de argparse."""
    parser.add_argument(
        "--folder",
        type=str,
        default=None,
        help="Ruta a carpeta de tarjeta (relativa al repo o absoluta). "
        "Si se omite, usa la única carpeta con extracto Mov TC o la que contenga 1111.",
    )


def resolve_e2e_folder(folder_arg: str | None) -> Path:
    """Resuelve carpeta E2E desde argumento o candidatos del repo."""
    if folder_arg:
        path = Path(folder_arg)
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        else:
            path = path.resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"Carpeta no encontrada: {path}")
        return path

    candidates: list[Path] = []
    for entry in sorted(ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in {".venv", ".cache", ".cursor", "tests", "src", "scripts", "docs"}:
            continue
        if any(entry.glob("Mov TC*.xlsx")) or any(entry.glob("Mov*.xlsx")):
            candidates.append(entry)

    if not candidates:
        raise FileNotFoundError(
            "No se encontró carpeta de prueba en el repo. "
            'Indique una con: run_e2e.bat "1111 - Demo User A"'
        )

    if len(candidates) == 1:
        return candidates[0]

    for path in candidates:
        if "1111" in path.name.upper():
            return path

    names = ", ".join(p.name for p in candidates)
    raise FileNotFoundError(
        f"Hay varias carpetas candidatas ({names}). "
        'Indique una explícitamente: run_e2e.bat "nombre-carpeta"'
    )


def infer_card_from_folder(folder: Path) -> str | None:
    """Infiere número de tarjeta desde nombre de carpeta o extracto."""
    match = re.search(r"(\d{4})", folder.name)
    if match:
        return match.group(1)
    for xlsx in folder.glob("Mov TC*.xlsx"):
        card_match = re.search(r"(\d{4})", xlsx.name)
        if card_match:
            return card_match.group(1)
    return None
