"""Tests del parser de preliminar Excel (``extract_parser``): fechas, GMF, layouts."""

import pytest
from datetime import date
from pathlib import Path

import pandas as pd

from legalizacion_tc.extract_parser import (
    _parse_date,
    _parse_original_amount,
    infer_period_from_filename,
    is_gmf_description,
    parse_extract,
)


def test_parse_original_amount_from_description():
    """Verifica parse original amount from description."""
    amount, currency = _parse_original_amount("APP IA SUBSCRIPTION VR MONEDA ORIG 20.0 US")
    assert amount == 20.0
    assert currency == "USD"


def test_parse_date_yyyymmdd_integer():
    """Verifica parse date yyyymmdd integer."""
    assert _parse_date(20260509) == date(2026, 5, 9)


def test_is_gmf_description():
    """Verifica is gmf description."""
    assert is_gmf_description("4X1000 PERSONA JURIDICA")
    assert is_gmf_description("GMF JURIDICO")
    assert not is_gmf_description("WEBAPP* DOMAIN#FAC-700001")


def test_infer_period_from_filename_with_month():
    """Verifica infer period from filename with month."""
    month, year, month_is_default = infer_period_from_filename("Mov TC 1111 Corte 27 de Mayo.xlsx")
    assert month == "MAYO"
    assert year == 2026
    assert month_is_default is False


def test_infer_period_from_filename_without_month():
    """Verifica infer period from filename without month."""
    month, year, month_is_default = infer_period_from_filename("Mov TC 4444.xlsx.xlsx")
    assert month == "ENERO"
    assert month_is_default is True


def test_parse_extract_infers_period_from_transaction_dates(tmp_path: Path):
    """Verifica parse extract infers period from transaction dates."""
    path = tmp_path / "Mov TC 4444.xlsx.xlsx"
    df = pd.DataFrame(
        {
            "FECHA": [
                date(2026, 3, 31),
                date(2026, 4, 9),
                date(2026, 4, 16),
                date(2026, 4, 16),
            ],
            "CONCEPTO": [
                "TRANSPORTE APP",
                "TRANSPORTE APP",
                "TRANSPORTE APP",
                "OLIVIA SANTA BARVARA",
            ],
            "VALOR": [549465.0, 16992.0, 57589.0, 49088.0],
        }
    )
    df.to_excel(path, index=False)

    data = parse_extract(path)
    assert data.card == "4444"
    assert data.period_month == "ABRIL"
    assert data.period_year == 2026
    assert len(data.transactions) == 4


def test_parse_extract_keeps_month_from_filename(fixture_dir):
    """Verifica parse extract keeps month from filename."""
    extract_path = fixture_dir / "Mov TC 1111 Corte 27 de Mayo.xlsx"
    data = parse_extract(extract_path)
    assert data.period_month == "MAYO"
    assert data.period_year == 2026


def test_parse_extract_includes_gmf_rows(fixture_dir):
    """Verifica parse extract includes gmf rows."""
    extract_path = fixture_dir / "Mov TC 1111 Corte 27 de Mayo.xlsx"
    data = parse_extract(extract_path)
    assert data.card == "1111"
    assert len(data.transactions) == 4
    gmf_rows = [tx for tx in data.transactions if tx.is_gmf]
    assert len(gmf_rows) == 1
    assert "4X1000" in gmf_rows[0].description.upper()
    assert data.total_cop == pytest.approx(635000.0)


def test_parse_extract_mixed_date_formats(tmp_path: Path):
    """Verifica parse extract mixed date formats."""
    path = tmp_path / "Mov TC 2222 Corte Junio.xlsx"
    df = pd.DataFrame(
        {
            "FECHA": ["15-jun-26", "10-jun-26", "20260601", "20260529"],
            "CONCEPTO": ["COMPRA A", "COMPRA B", "COMPRA C", "COMPRA D"],
            "VALOR": [100.0, 200.0, 300.0, 400.0],
        }
    )
    df.to_excel(path, index=False)

    data = parse_extract(path)
    assert len(data.transactions) == 4
    assert [tx.tx_date for tx in data.transactions] == [
        date(2026, 6, 15),
        date(2026, 6, 10),
        date(2026, 6, 1),
        date(2026, 5, 29),
    ]
