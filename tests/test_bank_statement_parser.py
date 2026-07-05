"""Tests del parser PDF Bancolombia (``bank_statement_parser``).

Verifica GMF incluido, abonos excluidos, conteo de transacciones y ``parse_movement_source``.
"""

from datetime import date
from pathlib import Path

import pytest

from legalizacion_tc.bank_statement_parser import parse_bancolombia_statement
from legalizacion_tc.extract_loader import parse_movement_source
from legalizacion_tc.extract_parser import is_gmf_description

FIXTURE_PDF = (
    Path(__file__).resolve().parent / "fixtures" / "bank_statements" / "4444_MAY2026.pdf"
)


@pytest.fixture
def statement_pdf() -> Path:
    """Fixture o helper: statement pdf."""
    if not FIXTURE_PDF.exists():
        pytest.skip(f"Fixture PDF no encontrado: {FIXTURE_PDF}")
    return FIXTURE_PDF


def test_is_gmf_description_recognizes_gmf_juridico():
    """Verifica is gmf description recognizes gmf juridico."""
    assert is_gmf_description("GMF JURIDICO")
    assert is_gmf_description("4X1000 PERSONA JURIDICA")


def test_parse_bancolombia_statement_card_period_and_count(statement_pdf):
    """Verifica parse bancolombia statement card period and count."""
    data = parse_bancolombia_statement(statement_pdf)
    assert data.card == "4444"
    assert data.period_month == "MAYO"
    assert data.period_year == 2026
    assert len(data.transactions) == 21
    assert data.total_cop == pytest.approx(7893061.47)


def test_parse_bancolombia_statement_includes_gmf_excludes_abono(statement_pdf):
    """Verifica parse bancolombia statement includes gmf excludes abono."""
    data = parse_bancolombia_statement(statement_pdf)
    gmf_rows = [tx for tx in data.transactions if tx.is_gmf]
    assert len(gmf_rows) == 1
    assert gmf_rows[0].description == "GMF JURIDICO"
    assert gmf_rows[0].amount_cop == pytest.approx(31446.47)
    assert not any("ABONO" in tx.description.upper() for tx in data.transactions)


def test_parse_bancolombia_statement_sample_transactions(statement_pdf):
    """Verifica parse bancolombia statement sample transactions."""
    data = parse_bancolombia_statement(statement_pdf)
    uber = [tx for tx in data.transactions if tx.description == "TRANSPORTE APP"]
    assert len(uber) == 6
    assert uber[0].tx_date == date(2026, 5, 7)
    assert uber[0].currency == "COP"


def test_parse_movement_source_pdf_kind(statement_pdf):
    """Verifica parse movement source pdf kind."""
    loaded = parse_movement_source(statement_pdf)
    assert loaded.source_kind == "pdf"
    assert loaded.data.card == "4444"
