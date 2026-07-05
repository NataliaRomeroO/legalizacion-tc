"""Genera fixtures Excel de prueba (tarjeta demo 1111 y batch parent 2222/3333).

Idempotente: no sobrescribe si ya existen. Incluye filas GMF, proveedor cloud USD y suscripción software.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from legalizacion_tc.excel_report_builder import create_minimal_template

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "demo_card"
BATCH_PARENT_DIR = Path(__file__).resolve().parent / "fixtures" / "batch_parent"


def build_minimal_extract(path: Path, card: str, rows: list[dict] | None = None) -> None:
    """Genera extracto Excel mínimo con filas indicadas."""
    if rows is None:
        rows = [
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 5, 10),
                "Descripcion": "COMPRA EJEMPLO",
                "Moneda": "COP",
                "Valor": 100000.0,
            }
        ]
    df = pd.DataFrame(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)


def build_extract(path: Path) -> None:
    """Genera extracto Excel demo completo para pruebas."""
    build_minimal_extract(
        path,
        "1111",
        rows=[
            {
                "Tarjeta": "*1111",
                "Fecha": date(2026, 5, 10),
                "Descripcion": "SERVICIO CLOUD DEMO",
                "Moneda": "COP",
                "Valor": 400000.0,
            },
            {
                "Tarjeta": "*1111",
                "Fecha": date(2026, 5, 12),
                "Descripcion": "SERVICIO CLOUD B",
                "Moneda": "COP",
                "Valor": 150000.0,
            },
            {
                "Tarjeta": "*1111",
                "Fecha": date(2026, 5, 15),
                "Descripcion": "4X1000 PERSONA JURIDICA",
                "Moneda": "COP",
                "Valor": 5000.0,
            },
            {
                "Tarjeta": "*1111",
                "Fecha": date(2026, 5, 15),
                "Descripcion": "SUSCRIPCION SOFTWARE",
                "Moneda": "COP",
                "Valor": 80000.0,
            },
        ],
    )


def build_template(path: Path) -> None:
    """Copia plantilla demo del repo al path indicado, o genera mínima si no existe."""
    root = ROOT
    sources = [
        root / "Plantilla Legalizacion TC Demo.xlsx",
        *sorted(root.glob("Plantilla*.xlsx")),
        FIXTURE_DIR / "plantilla_base.xlsx",
    ]
    for source in sources:
        if source.exists() and source.resolve() != path.resolve():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, path)
            return
    create_minimal_template(path)


def ensure_batch_parent_fixtures() -> Path:
    """Asegura fixtures de carpeta padre batch en disco."""
    cards = [
        ("2222 - Demo User B", "2222"),
        ("3333 - Demo User C", "3333"),
    ]
    BATCH_PARENT_DIR.mkdir(parents=True, exist_ok=True)
    for folder_name, card in cards:
        card_dir = BATCH_PARENT_DIR / folder_name
        card_dir.mkdir(parents=True, exist_ok=True)
        extract = card_dir / f"Mov TC {card} Corte Mayo.xlsx"
        if not extract.exists():
            build_minimal_extract(extract, card)
    return BATCH_PARENT_DIR


def ensure_fixtures() -> Path:
    """Asegura fixtures demo_card y retorna su directorio."""
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    extract = FIXTURE_DIR / "Mov TC 1111 Corte 27 de Mayo.xlsx"
    template = FIXTURE_DIR / "plantilla_base.xlsx"
    if not extract.exists():
        build_extract(extract)
    if not template.exists():
        build_template(template)
    ensure_batch_parent_fixtures()
    return FIXTURE_DIR


if __name__ == "__main__":
    path = ensure_fixtures()
    print(f"Fixtures listos en {path}")
