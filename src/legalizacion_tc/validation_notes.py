"""Flags y observaciones legibles para el operador y columnas del preliminar Excel.

- ``validation_flag``: OK | REVISAR | NO según status y ``needs_review``.
- ``format_ok_observation`` / ``format_no_observation``: texto por ``match_kind``.
- ``failure_reason_for_unmatched``: categoriza sin factura, fuera de ventana, diferencia
  de monto, ambigüedad, fecha ausente en JSON.
- ``find_near_miss_candidate``: factura cercana en monto pero fuera de tolerancia.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import InvoiceData, MatchResult, Transaction

if TYPE_CHECKING:
    from .config import Settings


def validation_flag(match: MatchResult) -> str:
    """Devuelve la columna Validación del preliminar: OK, REVISAR o NO."""
    if match.status == "GMF":
        return "OK"
    if match.status == "OK" and match.needs_review:
        return "REVISAR"
    if match.status == "OK":
        return "OK"
    if match.suggested_invoice is not None or match.status == "AMBIGUOUS":
        return "REVISAR"
    return "NO"


def _invoice_ref(invoice: InvoiceData) -> str:
    """Texto legible de referencia a factura: número, razón social o archivo origen."""
    numero = str(invoice.numero_factura or "").strip()
    razon = (invoice.razon_social or "").strip()
    if numero and razon:
        return f"{numero} — {razon}"
    return numero or razon or invoice.source_filename


def format_ok_observation(
    match: MatchResult,
    settings: Settings | None = None,
) -> str:
    """Observación positiva según tipo de match (GMF, compuesto, consolidado, etc.)."""
    if match.status == "GMF":
        concept = (match.transaction.description or "4x1000").strip()
        return f"GMF ({concept}) — sin factura requerida"

    invoice = match.invoice
    if invoice is None:
        return ""

    if match.match_kind == "compound" and match.secondary_invoice is not None:
        factura_ref = str(invoice.numero_factura or "").strip()
        recibo_ref = str(match.secondary_invoice.numero_factura or "").strip()
        razon = (invoice.razon_social or "").strip()
        parts = [f"Factura {factura_ref} + recibo propina {recibo_ref}"]
        if razon:
            parts.append(f"— {razon}")
        return " ".join(parts)

    if match.match_kind == "multi_factura" and match.component_invoices:
        refs = ", ".join(
            str(inv.numero_factura or "").strip()
            for inv in match.component_invoices
            if str(inv.numero_factura or "").strip()
        )
        razon = (invoice.razon_social or "").strip()
        parts = [f"Facturas {refs}"]
        if razon:
            parts.append(f"— {razon}")
        return " ".join(parts)

    if invoice.consolidado or (invoice.tipo_documento or "").strip().lower() in {
        "recibo_caja",
        "recibo_caja_menor",
    }:
        numero = str(invoice.numero_factura or "").strip()
        razon = (invoice.razon_social or "").strip()
        label = f"RECIBO DE CAJA {numero}" if numero else "Recibo consolidado"
        if match.match_kind == "consolidated_review" or match.needs_review:
            days = 0
            if invoice.fecha_factura is not None:
                days = (invoice.fecha_factura - match.transaction.tx_date).days
            limit = (
                settings.consolidated_receipt_max_days_after if settings else 30
            )
            base = f"Recibo consolidado {label}"
            if razon:
                base += f" — {razon}"
            return (
                f"{base} — REVISAR: recibo {days} días después del cargo "
                f"(límite automático {limit} días)"
            )
        if razon:
            return f"Recibo consolidado {label} — {razon}"
        return f"Recibo consolidado {label}"

    if match.match_kind == "provider_date_review":
        days = 0
        if invoice.fecha_factura is not None:
            days = abs((match.transaction.tx_date - invoice.fecha_factura).days)
        tolerance = settings.date_tolerance_days if settings else 3
        base = f"Factura {_invoice_ref(invoice)}"
        return (
            f"{base} — REVISAR: fecha factura {days} días del cargo "
            f"(ventana automática ±{tolerance} días)"
        )

    return f"Factura {_invoice_ref(invoice)}"


def format_ambiguous_observation(candidates: list[InvoiceData]) -> str:
    """Texto de ambigüedad listando los candidatos factura encontrados."""
    if not candidates:
        return "Ambigüedad — múltiples candidatos"
    refs = "; ".join(_invoice_ref(inv) for inv in candidates)
    return f"Ambigüedad — candidatos: {refs}"


def _format_amount_pair(
    settings: Settings,
    tx: Transaction,
    invoice: InvoiceData,
) -> tuple[float, float, str]:
    """Par de montos comparables (factura, cargo) y moneda para mensajes al operador."""
    from .reconciliation_engine import _amount_diff_pct, amount_tolerance_for

    invoice_currency = (invoice.moneda or "").upper()
    tx_currency = (tx.original_currency or tx.currency or "").upper()

    if (
        invoice.valor_total_documento is not None
        and tx.amount_original is not None
        and invoice_currency
        and tx_currency
        and invoice_currency == tx_currency
        and invoice_currency != "COP"
    ):
        return (
            invoice.valor_total_documento,
            tx.amount_original,
            invoice_currency,
        )

    if invoice_currency == "COP" and invoice.valor_total_documento is not None:
        return invoice.valor_total_documento, tx.amount_cop, "COP"

    from .reconciliation_engine import _invoice_amount_cop

    invoice_cop = _invoice_amount_cop(settings, invoice, tx)
    if invoice_cop is not None:
        return invoice_cop, tx.amount_cop, "COP"

    return 0.0, tx.amount_cop, invoice_currency or "COP"


def _format_near_miss_line(
    settings: Settings,
    tx: Transaction,
    invoice: InvoiceData,
) -> str:
    """Línea descriptiva cuando hay candidato cercano en monto pero fuera de tolerancia."""
    from .reconciliation_engine import _amount_diff_pct, amount_tolerance_for

    inv_amt, tx_amt, currency = _format_amount_pair(settings, tx, invoice)
    diff_pct = _amount_diff_pct(settings, tx, invoice)
    tolerance = amount_tolerance_for(settings, tx, invoice)
    tol_label = f"{tolerance * 100:.0f}%"
    diff_label = f"{diff_pct * 100:.1f}%"
    return (
        f"Sin match: monto {diff_label} sobre tolerancia {tol_label} — "
        f"candidato {_invoice_ref(invoice)} "
        f"({inv_amt:g} {currency} vs {tx_amt:g} {currency})"
    )


def _format_amount_date_suggestion_line(invoice: InvoiceData) -> str:
    """Mensaje cuando monto y fecha coinciden pero el concepto del extracto difiere."""
    return (
        f"Coincidencia monto/fecha — candidato {_invoice_ref(invoice)} "
        f"(concepto extracto distinto)"
    )


def _is_regular_suggestion_invoice(
    invoice: InvoiceData,
    used: set[str],
) -> bool:
    """Indica si la factura puede usarse como sugerencia (no consolidada, propina ni usada)."""
    from .reconciliation_engine import (
        CONSOLIDATED_DOC_TYPES,
        _is_consolidated_invoice,
        _is_tip_receipt,
    )

    if not invoice.legible:
        return False
    if invoice.source_filename in used:
        return False
    if _is_consolidated_invoice(invoice) or _is_tip_receipt(invoice):
        return False
    tipo = (invoice.tipo_documento or "").strip().lower()
    return tipo not in CONSOLIDATED_DOC_TYPES


def find_amount_date_suggestion_candidate(
    settings: Settings,
    tx: Transaction,
    invoices: list[InvoiceData],
    used_invoices: set[str] | None = None,
) -> InvoiceData | None:
    """Busca factura única con monto y fecha dentro de ventana pero sin match por concepto."""
    from .reconciliation_engine import (
        _amount_diff_pct,
        _amounts_match,
        _date_diff_days,
        _provider_concept_score,
        _within_date_window,
    )

    used = used_invoices or set()
    eligible: list[InvoiceData] = []

    for invoice in invoices:
        if not _is_regular_suggestion_invoice(invoice, used):
            continue
        if not _within_date_window(tx, invoice, settings.date_tolerance_days):
            continue
        if not _amounts_match(settings, tx, invoice):
            continue
        eligible.append(invoice)

    if len(eligible) == 1:
        return eligible[0]

    if len(eligible) <= 1:
        return None

    def rank_key(invoice: InvoiceData) -> tuple[int, float, int]:
        """Clave de orden: mayor score de proveedor, menor diff monto y fecha."""
        return (
            -_provider_concept_score(tx, invoice),
            _amount_diff_pct(settings, tx, invoice),
            _date_diff_days(tx, invoice),
        )

    ranked = sorted(eligible, key=rank_key)
    best_key = rank_key(ranked[0])
    winners = [invoice for invoice in eligible if rank_key(invoice) == best_key]
    if len(winners) == 1:
        return winners[0]
    return None


def find_near_miss_candidate(
    settings: Settings,
    tx: Transaction,
    invoices: list[InvoiceData],
    used_invoices: set[str] | None = None,
) -> InvoiceData | None:
    """Devuelve la factura más cercana en monto fuera de tolerancia, con score de proveedor."""
    from .reconciliation_engine import (
        MIN_PROVIDER_SCORE,
        _amount_diff_pct,
        _amounts_match,
        _date_diff_days,
        _provider_concept_score,
        _within_date_window,
    )

    used = used_invoices or set()
    ranked: list[tuple[InvoiceData, int, float, int]] = []

    for invoice in invoices:
        if not _is_regular_suggestion_invoice(invoice, used):
            continue
        if not _within_date_window(tx, invoice, settings.date_tolerance_days):
            continue
        if _amounts_match(settings, tx, invoice):
            continue

        score = _provider_concept_score(tx, invoice)
        if score < MIN_PROVIDER_SCORE:
            continue

        ranked.append(
            (
                invoice,
                score,
                _amount_diff_pct(settings, tx, invoice),
                _date_diff_days(tx, invoice),
            )
        )

    if not ranked:
        return None

    ranked.sort(key=lambda item: (-item[1], item[2], item[3]))
    return ranked[0][0]


def format_no_observation(
    match: MatchResult,
    settings: Settings,
    invoices: list[InvoiceData],
    used_invoices: set[str] | None = None,
    ambiguous_candidates: list[InvoiceData] | None = None,
) -> str:
    """Observación para movimientos sin match: ambigüedad, near-miss o ventana de fecha."""
    if match.status == "AMBIGUOUS":
        if ambiguous_candidates:
            return format_ambiguous_observation(ambiguous_candidates)
        return match.observacion or "Ambigüedad — múltiples candidatos"

    tx = match.transaction
    reason = match.failure_reason or ""

    if "Ambigüedad" in reason:
        return reason

    near_miss = find_near_miss_candidate(settings, tx, invoices, used_invoices)
    if near_miss is not None:
        return _format_near_miss_line(settings, tx, near_miss)

    amount_date = find_amount_date_suggestion_candidate(
        settings, tx, invoices, used_invoices
    )
    if amount_date is not None:
        return _format_amount_date_suggestion_line(amount_date)

    if reason in {"Diferencia de monto", "Factura no encontrada"} and any(
        inv.legible
        for inv in invoices
        if _within_date_window_for_obs(settings, tx, inv)
    ):
        from .reconciliation_engine import _amounts_match

        in_window = [
            inv
            for inv in invoices
            if inv.legible and _within_date_window_for_obs(settings, tx, inv)
        ]
        if any(not _amounts_match(settings, tx, inv) for inv in in_window):
            return "Diferencia de monto — sin candidato claro por concepto"

    if "Fuera de ventana" in reason:
        return "Fuera de ventana de fecha"
    if "fecha_factura ausente" in reason:
        return reason

    days = settings.date_tolerance_days
    return f"Sin factura en ventana ±{days} días"


def _within_date_window_for_obs(
    settings: Settings, tx: Transaction, invoice: InvoiceData
) -> bool:
    """Wrapper de ventana de fechas para construir observaciones de sin match."""
    from .reconciliation_engine import _within_date_window

    return _within_date_window(tx, invoice, settings.date_tolerance_days)


def failure_reason_for_unmatched(
    settings: Settings,
    tx: Transaction,
    invoices: list[InvoiceData],
    used_invoices: set[str] | None = None,
) -> str:
    """Categoriza la causa de no conciliación para columnas del preliminar Excel."""
    from .reconciliation_engine import (
        _amounts_match,
        _within_date_window,
    )

    date_candidates = [
        inv
        for inv in invoices
        if inv.legible and _within_date_window(tx, inv, settings.date_tolerance_days)
    ]
    if not date_candidates:
        legible_with_date = [
            inv for inv in invoices if inv.legible and inv.fecha_factura is not None
        ]
        if not legible_with_date:
            return "fecha_factura ausente en JSON"
        return "Fuera de ventana de fecha"

    used = used_invoices or set()
    available = [
        inv
        for inv in date_candidates
        if inv.source_filename not in used
    ]
    if not available:
        return "Fuera de ventana de fecha"

    near_miss = find_near_miss_candidate(settings, tx, invoices, used_invoices)
    if near_miss is not None:
        return "Diferencia de monto"

    amount_date = find_amount_date_suggestion_candidate(
        settings, tx, invoices, used_invoices
    )
    if amount_date is not None:
        return "Coincidencia monto/fecha sin concepto claro"

    if any(_amounts_match(settings, tx, inv) for inv in available):
        return "Coincidencia monto/fecha sin concepto claro"

    if any(not _amounts_match(settings, tx, inv) for inv in available):
        return "Diferencia de monto"

    return "Factura no encontrada"


def pick_best_from_candidates(
    settings: Settings,
    tx: Transaction,
    candidates: list[InvoiceData],
    used_invoices: set[str] | None = None,
) -> InvoiceData | None:
    """Elige la mejor factura entre candidatos ambiguos por score, monto y fecha."""
    if not candidates:
        return None
    from .reconciliation_engine import (
        MIN_PROVIDER_SCORE,
        _amount_diff_pct,
        _date_diff_days,
        _provider_concept_score,
    )

    reserved = used_invoices or set()
    available = [
        inv for inv in candidates if inv.source_filename not in reserved
    ]
    if not available:
        return None

    scored = [(inv, _provider_concept_score(tx, inv)) for inv in available]
    best_score = max(score for _, score in scored)
    if best_score < MIN_PROVIDER_SCORE:
        return None

    winners = [inv for inv, score in scored if score == best_score]
    if len(winners) == 1:
        return winners[0]

    ranked = sorted(
        winners,
        key=lambda inv: (
            _amount_diff_pct(settings, tx, inv),
            _date_diff_days(tx, inv),
        ),
    )
    return ranked[0]


def resolve_suggested_invoice(
    settings: Settings,
    match: MatchResult,
    invoices: list[InvoiceData],
    used_invoices: set[str] | None = None,
) -> InvoiceData | None:
    """Factura sugerida para UNMATCHED o AMBIGUOUS según near-miss o desempate."""
    tx = match.transaction
    if match.status == "UNMATCHED":
        near = find_near_miss_candidate(settings, tx, invoices, used_invoices)
        if near is not None:
            return near
        return find_amount_date_suggestion_candidate(
            settings, tx, invoices, used_invoices
        )
    if match.status == "AMBIGUOUS":
        if match.ambiguous_candidates:
            return pick_best_from_candidates(
                settings,
                tx,
                match.ambiguous_candidates,
                used_invoices,
            )
        return None
    return None
