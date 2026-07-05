#!/usr/bin/env python3
"""CLI de limpieza segura de ``.cache`` con confirmación interactiva.

Modos: ``--output-only`` (default), ``--downloads``, ``--invoices``, ``--legacy``.
``--yes`` omite confirmación; ``--card`` acota downloads/invoices por tarjeta.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from legalizacion_tc.cache_cleanup import (
    clean_downloads,
    clean_invoices,
    clean_legacy,
    clean_output,
)


def _confirm(message: str) -> bool:
    """Solicita confirmación interactiva sí/no al operador."""
    try:
        answer = input(f"{message} [y/N]: ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes", "s", "si", "sí"}


def main() -> int:
    """Punto de entrada CLI del script."""
    parser = argparse.ArgumentParser(
        description="Limpieza segura del cache de legalización TC"
    )
    parser.add_argument(
        "--output-only",
        action="store_true",
        help="Borrar solo .cache/output/ (comportamiento por defecto si no hay otros flags)",
    )
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Borrar rutas legacy .cache/invoices/ y .cache/downloads/",
    )
    parser.add_argument(
        "--downloads",
        action="store_true",
        help="Borrar descargas (.cache/cards/{tarjeta}/downloads/ o legacy)",
    )
    parser.add_argument(
        "--invoices",
        action="store_true",
        help="Borrar JSON de facturas (.cache/cards/{tarjeta}/invoices/)",
    )
    parser.add_argument("--card", help="Limitar --downloads o --invoices a una tarjeta")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirmar operaciones destructivas (--downloads, --invoices) sin preguntar",
    )
    parser.add_argument(
        "--skip-output",
        action="store_true",
        help="No borrar .cache/output/",
    )
    args = parser.parse_args()

    destructive = args.downloads or args.invoices
    clean_output_flag = args.output_only or not destructive

    if args.invoices and not args.yes:
        scope = f"tarjeta {args.card}" if args.card else "todas las tarjetas"
        if not _confirm(
            f"¿Borrar JSON de facturas en cache ({scope})? Esta acción no se puede deshacer."
        ):
            print("Cancelado.", file=sys.stderr)
            return 1

    if args.downloads and not args.yes:
        scope = f"tarjeta {args.card}" if args.card else "todas las tarjetas"
        if not _confirm(f"¿Borrar descargas en cache ({scope})?"):
            print("Cancelado.", file=sys.stderr)
            return 1

    removed: list[Path] = []
    if clean_output_flag and not args.skip_output:
        removed.extend(clean_output(args.card))
    if args.legacy:
        removed.extend(clean_legacy())
    if args.downloads:
        removed.extend(clean_downloads(args.card))
    if args.invoices:
        removed.extend(clean_invoices(args.card))

    if removed:
        for path in removed:
            print(f"Eliminado: {path}")
    else:
        print("Nada que limpiar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
