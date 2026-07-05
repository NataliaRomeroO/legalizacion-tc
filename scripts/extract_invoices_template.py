#!/usr/bin/env python3
"""Lista facturas sin JSON y crea plantillas en ``.cache/cards/{tarjeta}/invoices/``.

Paso 2 de AGENTS.md: descarga PDFs desde Drive/local, reporta pendientes.
Exit code 2 si faltan JSON; ``--init-templates`` crea stubs para Claude Code.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from legalizacion_tc.config import downloads_cache_dir, invoices_cache_dir
from legalizacion_tc.drive_manager import (
    download_to_cache,
    list_folder_files,
    list_invoice_files,
    list_local_folder,
    parse_folder_id_from_url,
)
from legalizacion_tc.folder_resolver import CardFolderContext, resolve_card_folders
from legalizacion_tc.invoice_loader import missing_invoice_json, save_invoice_json_template


@dataclass
class CardExtractSummary:
    """Resumen de facturas descargadas y JSON pendientes por tarjeta."""
    context: CardFolderContext
    invoice_names: list[str]
    missing: list[str]


def _collect_card_invoices(card_folder: CardFolderContext) -> CardExtractSummary:
    """Descarga facturas de carpeta y detecta JSON faltantes."""
    cache_card = card_folder.card
    if card_folder.local_path:
        files = list_local_folder(card_folder.local_path)
        invoice_files = list_invoice_files(files)
        for inv in invoice_files:
            src = Path(inv.file_id)
            dest = downloads_cache_dir(cache_card) / inv.name
            if src.exists() and not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
    else:
        files = list_folder_files(card_folder.folder_id or "")
        invoice_files = list_invoice_files(files)
        for inv in invoice_files:
            download_to_cache(inv.file_id, inv.name, card=cache_card)

    names = [f.name for f in invoice_files]
    missing = missing_invoice_json(names, card=cache_card)
    return CardExtractSummary(context=card_folder, invoice_names=names, missing=missing)


def main() -> int:
    """Punto de entrada CLI del script."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder-id", help="ID o URL carpeta Drive")
    parser.add_argument("--local-folder", type=Path, help="Carpeta local")
    parser.add_argument(
        "--card",
        help="Procesar solo esta tarjeta dentro de una carpeta padre",
    )
    parser.add_argument("--init-templates", action="store_true")
    args = parser.parse_args()

    if not args.folder_id and args.local_folder is None:
        print("ERROR: Debe indicar --folder-id o --local-folder", file=sys.stderr)
        return 1

    folder_id = parse_folder_id_from_url(args.folder_id) if args.folder_id else None
    contexts = resolve_card_folders(
        folder_id=folder_id,
        local_folder=args.local_folder,
        card_filter=args.card,
    )

    summaries: list[CardExtractSummary] = []
    for card_folder in contexts:
        invoices_cache_dir(card_folder.card).mkdir(parents=True, exist_ok=True)
        downloads_cache_dir(card_folder.card).mkdir(parents=True, exist_ok=True)
        summaries.append(_collect_card_invoices(card_folder))

    total_invoices = sum(len(s.invoice_names) for s in summaries)
    total_missing = sum(len(s.missing) for s in summaries)

    if len(summaries) == 1:
        summary = summaries[0]
        print(f"Tarjeta: {summary.context.card or summary.context.display_name}")
        print(f"Facturas en carpeta: {len(summary.invoice_names)}")
        print(f"Pendientes JSON: {len(summary.missing)}")
        for name in summary.missing:
            print(f"  - {name}")
            if args.init_templates:
                path = save_invoice_json_template(name, card=summary.context.card)
                print(f"    plantilla: {path}")
    else:
        print(f"Tarjetas detectadas: {len(summaries)}")
        print(f"Facturas totales: {total_invoices}")
        print(f"Pendientes JSON: {total_missing}")
        for summary in summaries:
            label = summary.context.card or summary.context.display_name
            print(f"\n--- Tarjeta {label} ({summary.context.display_name}) ---")
            print(f"Facturas: {len(summary.invoice_names)} | Pendientes: {len(summary.missing)}")
            for name in summary.missing:
                print(f"  - {name}")
                if args.init_templates:
                    path = save_invoice_json_template(name, card=summary.context.card)
                    print(f"    plantilla: {path}")

    if total_missing:
        print("\nSiguiente paso: Claude Code debe completar cada JSON en .cache/cards/{tarjeta}/invoices/")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
