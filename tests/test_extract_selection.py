"""Tests de selección de extracto (``extract_selection``): PDF > Excel, desempates."""

from datetime import date
from pathlib import Path

from legalizacion_tc.drive_manager import DriveFile
import pytest

from legalizacion_tc.extract_selection import select_best_extract_file
from tests.build_fixtures import build_minimal_extract


def test_select_best_extract_by_movement_count(tmp_path):
    """Verifica select best extract by movement count."""
    card = "2222"
    extract_a = tmp_path / "Mov TC 2222 corte 1.xlsx"
    extract_b = tmp_path / "Mov TC 2222 corte 2.xlsx"
    build_minimal_extract(
        extract_a,
        card,
        rows=[
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 1),
                "Descripcion": "COMPRA A",
                "Moneda": "COP",
                "Valor": 100.0,
            },
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 2),
                "Descripcion": "COMPRA B",
                "Moneda": "COP",
                "Valor": 200.0,
            },
        ],
    )
    build_minimal_extract(
        extract_b,
        card,
        rows=[
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 1),
                "Descripcion": "COMPRA A",
                "Moneda": "COP",
                "Valor": 100.0,
            },
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 2),
                "Descripcion": "COMPRA B",
                "Moneda": "COP",
                "Valor": 200.0,
            },
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 10),
                "Descripcion": "COMPRA C",
                "Moneda": "COP",
                "Valor": 300.0,
            },
        ],
    )
    files = [
        DriveFile(str(extract_a), extract_a.name, "", modified_time=1.0),
        DriveFile(str(extract_b), extract_b.name, "", modified_time=2.0),
    ]
    selection = select_best_extract_file(files, lambda f: Path(f.file_id))
    assert selection is not None
    assert selection.chosen.name == extract_b.name
    assert "3 movimientos" in selection.reason


def test_select_best_extract_tiebreaker_by_max_date(tmp_path):
    """Verifica select best extract tiebreaker by max date."""
    card = "2222"
    extract_a = tmp_path / "Mov TC 2222 a.xlsx"
    extract_b = tmp_path / "Mov TC 2222 b.xlsx"
    build_minimal_extract(
        extract_a,
        card,
        rows=[
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 1),
                "Descripcion": "COMPRA A",
                "Moneda": "COP",
                "Valor": 100.0,
            },
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 5),
                "Descripcion": "COMPRA B",
                "Moneda": "COP",
                "Valor": 200.0,
            },
        ],
    )
    build_minimal_extract(
        extract_b,
        card,
        rows=[
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 1),
                "Descripcion": "COMPRA C",
                "Moneda": "COP",
                "Valor": 150.0,
            },
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 6, 20),
                "Descripcion": "COMPRA D",
                "Moneda": "COP",
                "Valor": 250.0,
            },
        ],
    )
    files = [
        DriveFile(str(extract_a), extract_a.name, "", modified_time=2.0),
        DriveFile(str(extract_b), extract_b.name, "", modified_time=1.0),
    ]
    selection = select_best_extract_file(files, lambda f: Path(f.file_id))
    assert selection is not None
    assert selection.chosen.name == extract_b.name


def test_select_best_extract_prefers_pdf_over_excel(tmp_path):
    """Verifica select best extract prefers pdf over excel."""
    card = "4444"
    pdf_path = tmp_path / "4444_MAY2026.pdf"
    excel_path = tmp_path / "Mov TC 4444 Corte Mayo.xlsx"
    fixture_pdf = (
        Path(__file__).resolve().parent
        / "fixtures"
        / "bank_statements"
        / "4444_MAY2026.pdf"
    )
    if not fixture_pdf.exists():
        pytest.skip(f"Fixture PDF no encontrado: {fixture_pdf}")
    pdf_path.write_bytes(fixture_pdf.read_bytes())
    build_minimal_extract(
        excel_path,
        card,
        rows=[
            {
                "Tarjeta": f"*{card}",
                "Fecha": date(2026, 5, 10),
                "Descripcion": "COMPRA EJEMPLO",
                "Moneda": "COP",
                "Valor": 100.0,
            }
        ],
    )
    files = [
        DriveFile(str(excel_path), excel_path.name, "", modified_time=1.0),
        DriveFile(str(pdf_path), pdf_path.name, "", modified_time=1.0),
    ]
    selection = select_best_extract_file(files, lambda f: Path(f.file_id))
    assert selection is not None
    assert selection.source_kind == "pdf"
    assert selection.chosen.name == pdf_path.name
