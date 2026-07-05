"""Validación de facturas peruanas: RUC del emisor obligatorio en boletas legibles.

Perú detectado por ``pais_emisor=PE`` o moneda SOL con ``legible=True``.
Facturas ilegibles no generan warning (operador debe re-extraer).
"""

from __future__ import annotations

from .models import InvoiceData

_PERU_RUC_ACCION = "Revisar boleta y completar RUC del emisor en nit_proveedor"


def is_peru_invoice(invoice: InvoiceData) -> bool:
    """Detecta factura peruana por ``pais_emisor=PE`` o moneda SOL con documento legible."""
    if (invoice.pais_emisor or "").upper() == "PE":
        return True
    return (invoice.moneda or "").upper() == "SOL" and invoice.legible


def collect_peru_ruc_issues(invoices: list[InvoiceData]) -> list[dict]:
    """Recopila boletas peruanas legibles sin RUC en ``nit_proveedor``."""
    issues: list[dict] = []
    for invoice in invoices:
        if not invoice.legible or not is_peru_invoice(invoice):
            continue
        if (invoice.nit_proveedor or "").strip():
            continue
        issues.append(
            {
                "source_filename": invoice.source_filename,
                "razon_social": invoice.razon_social or "",
                "accion": _PERU_RUC_ACCION,
            }
        )
    return issues


def peru_ruc_warning_messages(issues: list[dict]) -> list[str]:
    """Genera mensajes legibles para warnings de RUC faltante en facturas Perú."""
    messages: list[str] = []
    for issue in issues:
        label = issue.get("razon_social") or issue.get("source_filename") or "factura"
        messages.append(f"Factura Perú sin RUC: {label} ({issue.get('source_filename', '')})")
    return messages
