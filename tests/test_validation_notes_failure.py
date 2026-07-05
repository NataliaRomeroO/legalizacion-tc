"""Tests de ``failure_reason_for_unmatched``: fecha ausente y fuera de ventana."""

from datetime import date

from legalizacion_tc.config import load_settings
from legalizacion_tc.models import InvoiceData, Transaction
from legalizacion_tc.validation_notes import failure_reason_for_unmatched


def test_failure_reason_missing_fecha_factura():
    """Verifica failure reason missing fecha factura."""
    settings = load_settings()
    tx = Transaction(
        card="3333",
        tx_date=date(2026, 6, 10),
        description="SMILE NOGAL",
        currency="COP",
        amount_cop=308306.0,
    )
    invoices = [
        InvoiceData(
            source_filename="SMILE.pdf",
            legible=True,
            fecha_factura=None,
            valor_total_documento=308306.0,
            moneda="COP",
        )
    ]
    assert failure_reason_for_unmatched(settings, tx, invoices) == "fecha_factura ausente en JSON"


def test_failure_reason_outside_date_window():
    """Verifica failure reason outside date window."""
    settings = load_settings()
    tx = Transaction(
        card="3333",
        tx_date=date(2026, 6, 10),
        description="SMILE NOGAL",
        currency="COP",
        amount_cop=308306.0,
    )
    invoices = [
        InvoiceData(
            source_filename="SMILE.pdf",
            legible=True,
            fecha_factura=date(2026, 5, 1),
            valor_total_documento=308306.0,
            moneda="COP",
        )
    ]
    assert failure_reason_for_unmatched(settings, tx, invoices) == "Fuera de ventana de fecha"
