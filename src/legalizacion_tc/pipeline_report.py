"""Reporte JSON en stdout para operador y Claude Code.

``build_pipeline_report`` determina ``status``:
- ``success``: todos OK o GMF; o dedup omitió todo con filas previas.
- ``partial``: sin soporte, artículo vacío, needs_review o proveedores nuevos en histórico.
- ``error``: sin filas y sin dedup previo.

Incluye links Drive, movimientos sin soporte, GMF, warnings Perú RUC y pendientes histórico.
"""

from __future__ import annotations

import json

from .folder_resolver import CardFolderContext
from .models import LegalizationRow, MatchResult, PipelineResult

_HISTORICO_ACCION = (
    "Agregar en pestaña historico_proveedores del Sheet de control "
    "(nit, razon_social, detalle_gasto, articulo_contable)"
)


def _format_cop(amount: float) -> str:
    """Formatea un monto COP legible para mensajes al operador."""
    return f"${amount:,.0f} COP".replace(",", ".")


def _is_conciliated_row(row: LegalizationRow) -> bool:
    """Indica si la fila tiene NIT y número de factura (conciliación completa)."""
    return bool((row.nit_proveedor or "").strip() and row.numero_factura not in (None, ""))


def _build_sin_soporte_entries(
    matches: list[MatchResult],
) -> tuple[list[dict], list[str]]:
    """Construye listas estructurada y legible de movimientos sin factura soporte."""
    structured: list[dict] = []
    readable: list[str] = []
    for match in matches:
        if match.status not in ("UNMATCHED", "AMBIGUOUS"):
            continue
        tx = match.transaction
        concepto = tx.description or ""
        monto = tx.amount_cop
        fecha = tx.tx_date.isoformat()
        motivo = match.failure_reason or "Sin factura"
        structured.append(
            {
                "concepto": concepto,
                "monto_cop": monto,
                "fecha": fecha,
                "motivo": motivo,
            }
        )
        readable.append(f"{concepto} — {_format_cop(monto)} — {motivo}")
    return structured, readable


def _build_proveedores_pendientes_historico(
    rows: list[LegalizationRow], new_nits: list[str]
) -> list[dict]:
    """Proveedores nuevos sin artículo contable que requieren acción en el Sheet."""
    # Solo pedir acción al operador cuando la fila conciliada no tiene artículo
    # contable — si el Excel ya lo tiene, el proveedor estaba en el Sheet.
    nits_sin_articulo = {
        row.nit_proveedor
        for row in rows
        if _is_conciliated_row(row) and not (row.articulo_contable or "").strip()
        and row.nit_proveedor
    }
    razon_by_nit = {
        row.nit_proveedor: row.razon_social
        for row in rows
        if row.nit_proveedor
    }
    pendientes: list[dict] = []
    for nit in new_nits:
        if nit not in nits_sin_articulo:
            continue
        pendientes.append(
            {
                "nit": nit,
                "razon_social": razon_by_nit.get(nit, ""),
                "accion": _HISTORICO_ACCION,
            }
        )
    return pendientes


def _build_gmf_entries(matches: list[MatchResult]) -> list[dict]:
    """Lista movimientos GMF (4x1000) para el reporte JSON."""
    entries: list[dict] = []
    for match in matches:
        if match.status != "GMF":
            continue
        tx = match.transaction
        entries.append(
            {
                "concepto": tx.description or "",
                "monto_cop": tx.amount_cop,
                "fecha": tx.tx_date.isoformat(),
            }
        )
    return entries


def _build_summary(
    invoice_matched: int,
    gmf_count: int,
    sin_factura: int,
    gmf_consolidated: bool,
) -> str:
    """Texto resumen legible con conteos de conciliados, GMF y sin factura."""
    parts: list[str] = []
    if invoice_matched:
        label = "factura conciliada" if invoice_matched == 1 else "facturas conciliadas"
        parts.append(f"{invoice_matched} {label}")
    if gmf_count:
        label = "movimiento GMF" if gmf_count == 1 else "movimientos GMF"
        gmf_text = f"{gmf_count} {label}"
        if gmf_consolidated and gmf_count > 1:
            gmf_text += " (consolidados en 1 fila Excel)"
        parts.append(gmf_text)
    if sin_factura:
        label = "movimiento sin factura" if sin_factura == 1 else "movimientos sin factura"
        parts.append(f"{sin_factura} {label}")
    return ", ".join(parts) if parts else "Sin movimientos"


def build_pipeline_report(result: PipelineResult) -> dict:
    """Construye el dict JSON de stdout: status, summary, warnings, links y revisiones."""
    invoice_matched = [m for m in result.matches if m.status == "OK"]
    gmf_matches = [m for m in result.matches if m.status == "GMF"]
    sin_soporte = [
        m for m in result.matches if m.status in ("UNMATCHED", "AMBIGUOUS")
    ]
    movimientos_sin_soporte, documento_no = _build_sin_soporte_entries(result.matches)
    movimientos_gmf = _build_gmf_entries(result.matches)
    gmf_consolidated = len(gmf_matches) > 1
    proveedores_pendientes = _build_proveedores_pendientes_historico(
        result.legalization_rows, result.new_provider_nits
    )
    new_nit_set = set(result.new_provider_nits)
    articulo_vacio = [
        row.nit_proveedor
        for row in result.legalization_rows
        if (
            _is_conciliated_row(row)
            and not row.articulo_contable
            and row.nit_proveedor
            and row.nit_proveedor not in new_nit_set
        )
    ]

    warnings = list(result.warnings)
    if proveedores_pendientes:
        count = len(proveedores_pendientes)
        label = "proveedor" if count == 1 else "proveedores"
        warnings.append(
            f"Agregar {count} {label} en historico_proveedores del Sheet de control"
        )
    if result.facturas_peru_sin_ruc:
        count = len(result.facturas_peru_sin_ruc)
        label = "factura peruana" if count == 1 else "facturas peruanas"
        warnings.append(f"{count} {label} legible(s) sin RUC en nit_proveedor")

    if not result.legalization_rows:
        if (
            result.legalization_mode == "append"
            and result.skipped_already_legalized_count > 0
        ):
            status = "success"
        else:
            status = "error"
    elif sin_soporte or proveedores_pendientes or articulo_vacio:
        status = "partial"
    elif any(m.status == "OK" and m.needs_review for m in result.matches):
        status = "partial"
    elif all(m.status in ("OK", "GMF") for m in result.matches):
        status = "success"
    else:
        status = "partial"

    return {
        "status": status,
        "card": result.extract.card,
        "output_file": result.output_filename,
        "output_path": result.output_path,
        "legalization_file_link": result.legalization_file_link,
        "transaction_count": len(result.matches),
        "matched_count": len(invoice_matched),
        "gmf_count": len(gmf_matches),
        "sin_factura_count": len(sin_soporte),
        "unmatched_count": len(sin_soporte),
        "summary": _build_summary(
            len(invoice_matched), len(gmf_matches), len(sin_soporte), gmf_consolidated
        ),
        "documento_soporte_no": documento_no,
        "movimientos_sin_soporte": movimientos_sin_soporte,
        "movimientos_gmf": movimientos_gmf,
        "proveedores_pendientes_historico": proveedores_pendientes,
        "facturas_peru_sin_ruc": result.facturas_peru_sin_ruc,
        "articulo_contable_vacio": list(dict.fromkeys(articulo_vacio)),
        "checkpoint_note": "Revisar fila checkpoint en Excel (debe ser ~0)",
        "warnings": warnings,
        "legalization_mode": result.legalization_mode,
        "batch_label": result.batch_label,
        "appended_row_count": result.appended_row_count,
        "skipped_already_legalized_count": result.skipped_already_legalized_count,
        "output_version": result.output_version,
        "extract_selected": result.extract_selected,
        "extract_file_link": result.extract_file_link,
        "extract_update_mode": result.extract_update_mode,
        "extract_source_kind": result.extract_source_kind,
    }


def print_pipeline_report(result: PipelineResult) -> None:
    """Imprime en stdout el reporte JSON de una corrida de legalización."""
    report = build_pipeline_report(result)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _batch_entry(
    context: CardFolderContext,
    outcome: PipelineResult | BaseException,
) -> dict:
    """Entrada de reporte para una tarjeta en modo batch (éxito o excepción)."""
    card = context.card or context.display_name
    if isinstance(outcome, BaseException):
        return {
            "status": "error",
            "card": card,
            "folder": context.display_name,
            "error": str(outcome),
            "error_type": type(outcome).__name__,
        }
    report = build_pipeline_report(outcome)
    report["folder"] = context.display_name
    return report


def print_batch_pipeline_report(outcomes) -> None:
    """Imprime en stdout un arreglo JSON con el reporte de cada tarjeta procesada."""
    entries = []
    for outcome in outcomes:
        error = outcome.error
        payload = outcome.result if error is None else error
        entries.append(_batch_entry(outcome.context, payload))
    print(json.dumps(entries, indent=2, ensure_ascii=False))
