"""Tests de validación RUC en facturas peruanas (``invoice_validation``)."""

from legalizacion_tc.invoice_validation import (
    collect_peru_ruc_issues,
    is_peru_invoice,
    peru_ruc_warning_messages,
)
from legalizacion_tc.models import InvoiceData


def _peru_invoice(**kwargs) -> InvoiceData:
    """Helper de prueba: peru invoice."""
    defaults = {
        "source_filename": "boleta.jpeg",
        "moneda": "SOL",
        "legible": True,
        "pais_emisor": "PE",
    }
    defaults.update(kwargs)
    return InvoiceData(**defaults)


def test_is_peru_invoice_by_moneda_or_pais():
    """Verifica is peru invoice by moneda or pais."""
    assert is_peru_invoice(_peru_invoice(pais_emisor=None)) is True
    assert is_peru_invoice(_peru_invoice(moneda="USD", pais_emisor="PE")) is True
    assert is_peru_invoice(_peru_invoice(moneda="COP", pais_emisor="CO")) is False


def test_collect_peru_ruc_issues_when_missing_ruc():
    """Verifica collect peru ruc issues when missing ruc."""
    issues = collect_peru_ruc_issues(
        [
            _peru_invoice(
                source_filename="REST-DEMO.jpeg",
                razon_social="RESTAURANTE DEMO S.A.S",
                nit_proveedor=None,
            )
        ]
    )
    assert len(issues) == 1
    assert issues[0]["source_filename"] == "REST-DEMO.jpeg"
    assert issues[0]["razon_social"] == "RESTAURANTE DEMO S.A.S"
    assert "RUC" in issues[0]["accion"]


def test_collect_peru_ruc_issues_skips_when_ruc_present():
    """Verifica collect peru ruc issues skips when ruc present."""
    issues = collect_peru_ruc_issues(
        [_peru_invoice(nit_proveedor="20987654321")]
    )
    assert issues == []


def test_collect_peru_ruc_issues_skips_illegible():
    """Verifica collect peru ruc issues skips illegible."""
    issues = collect_peru_ruc_issues(
        [_peru_invoice(legible=False, nit_proveedor=None)]
    )
    assert issues == []


def test_peru_ruc_warning_messages():
    """Verifica peru ruc warning messages."""
    issues = [
        {
            "source_filename": "REST-DEMO.jpeg",
            "razon_social": "RESTAURANTE DEMO S.A.S",
            "accion": "Revisar",
        }
    ]
    messages = peru_ruc_warning_messages(issues)
    assert len(messages) == 1
    assert "Factura Perú sin RUC" in messages[0]
    assert "RESTAURANTE DEMO S.A.S" in messages[0]
