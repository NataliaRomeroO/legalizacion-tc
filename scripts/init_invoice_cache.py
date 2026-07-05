#!/usr/bin/env python3
"""Inicializa e imprime rutas de caché por tarjeta (``invoices/``, ``downloads/``).

Resuelve tarjetas desde carpeta Drive/local, ``--card`` aislado, o modo legacy sin tarjeta.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from legalizacion_tc.config import downloads_cache_dir, invoices_cache_dir
from legalizacion_tc.drive_manager import parse_folder_id_from_url
from legalizacion_tc.folder_resolver import resolve_card_folders


def main() -> int:
    """Punto de entrada CLI del script."""
    parser = argparse.ArgumentParser(description="Inicializa cache de facturas por tarjeta")
    parser.add_argument("--folder-id", help="ID o URL carpeta Drive (opcional)")
    parser.add_argument("--local-folder", type=Path, help="Carpeta local (opcional)")
    parser.add_argument(
        "--card",
        help="Inicializar solo esta tarjeta dentro de una carpeta padre",
    )
    args = parser.parse_args()

    cards: list[str | None]
    if args.folder_id or args.local_folder:
        folder_id = parse_folder_id_from_url(args.folder_id) if args.folder_id else None
        contexts = resolve_card_folders(
            folder_id=folder_id,
            local_folder=args.local_folder,
            card_filter=args.card,
        )
        cards = [ctx.card for ctx in contexts]
    elif args.card:
        cards = [args.card]
    else:
        cards = [None]

    for card in cards:
        inv = invoices_cache_dir(card)
        dl = downloads_cache_dir(card)
        label = card or "legacy"
        print(f"Cache lista ({label}): invoices={inv} downloads={dl}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
