"""Tests de detección de JSON incompletos/plantilla (``invoice_loader``)."""

import json

import pytest

from legalizacion_tc.invoice_loader import (
    incomplete_invoice_json,
    is_incomplete_invoice,
    save_invoice_json_template,
)
from legalizacion_tc.models import InvoiceData


def test_is_incomplete_invoice_template():
    """Verifica is incomplete invoice template."""
    template = InvoiceData(source_filename="x.pdf", legible=False)
    assert is_incomplete_invoice(template) is True


def test_is_incomplete_invoice_complete():
    """Verifica is incomplete invoice complete."""
    from datetime import date

    complete = InvoiceData(
        source_filename="x.pdf",
        legible=True,
        fecha_factura=date(2026, 6, 10),
        valor_total_documento=100.0,
    )
    assert is_incomplete_invoice(complete) is False


def test_incomplete_invoice_json_detects_template(tmp_path, monkeypatch):
    """Verifica incomplete invoice json detects template."""
    from legalizacion_tc import invoice_loader

    monkeypatch.setattr(invoice_loader, "invoices_cache_dir", lambda card=None: tmp_path)
    save_invoice_json_template("factura.pdf", card=None)
    assert incomplete_invoice_json(["factura.pdf"]) == ["factura.pdf"]


def test_incomplete_invoice_json_ignores_complete(tmp_path, monkeypatch):
    """Verifica incomplete invoice json ignores complete."""
    from legalizacion_tc import invoice_loader

    monkeypatch.setattr(invoice_loader, "invoices_cache_dir", lambda card=None: tmp_path)
    (tmp_path / "factura.json").write_text(
        json.dumps(
            {
                "source_filename": "factura.pdf",
                "numero_factura": "F1",
                "moneda": "COP",
                "valor_total_documento": 100.0,
                "fecha_factura": "2026-06-10",
                "legible": True,
            }
        ),
        encoding="utf-8",
    )
    assert incomplete_invoice_json(["factura.pdf"]) == []
