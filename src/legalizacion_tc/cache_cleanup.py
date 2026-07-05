"""Limpieza de subárboles en ``.cache`` entre corridas.

Funciones: ``clean_output``, ``clean_downloads``, ``clean_invoices``, ``clean_legacy``.
``--card`` acota downloads/invoices; ``clean_legacy`` elimina rutas planas pre-cards.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .config import cache_dir, downloads_cache_dir, invoices_cache_dir, output_cache_dir


def _remove_path(path: Path) -> None:
    """Elimina archivo o directorio si existe en disco."""
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def clean_output(card: str | None = None) -> list[Path]:
    """Borra caché de salida Excel; opcionalmente solo la subcarpeta de una tarjeta."""
    removed: list[Path] = []
    if card:
        targets = [output_cache_dir(card)]
    else:
        output_root = cache_dir() / "output"
        targets = [output_root] if output_root.exists() else []
        if output_root.exists():
            for child in output_root.iterdir():
                if child.is_dir():
                    targets.append(child)
    for target in targets:
        if target.exists():
            removed.append(target)
            _remove_path(target)
    return removed


def clean_legacy() -> list[Path]:
    """Elimina rutas planas legacy de invoices/downloads en la raíz de ``.cache``."""
    removed: list[Path] = []
    for relative in ("invoices", "downloads"):
        path = cache_dir() / relative
        if path.exists():
            removed.append(path)
            _remove_path(path)
    return removed


def clean_downloads(card: str | None = None) -> list[Path]:
    """Borra descargas de Drive en caché; acotado por tarjeta si se indica."""
    removed: list[Path] = []
    if card:
        targets = [downloads_cache_dir(card)]
    else:
        targets = [cache_dir() / "downloads"]
        cards_root = cache_dir() / "cards"
        if cards_root.exists():
            for card_dir in cards_root.iterdir():
                if card_dir.is_dir():
                    downloads = card_dir / "downloads"
                    if downloads.exists():
                        targets.append(downloads)
    for target in targets:
        if target.exists():
            removed.append(target)
            _remove_path(target)
    return removed


def clean_invoices(card: str | None = None) -> list[Path]:
    """Borra JSON de facturas en caché; acotado por tarjeta si se indica."""
    removed: list[Path] = []
    if card:
        targets = [invoices_cache_dir(card)]
    else:
        targets = []
        cards_root = cache_dir() / "cards"
        if cards_root.exists():
            for card_dir in cards_root.iterdir():
                if card_dir.is_dir():
                    invoices = card_dir / "invoices"
                    if invoices.exists():
                        targets.append(invoices)
    for target in targets:
        if target.exists():
            removed.append(target)
            _remove_path(target)
    return removed
