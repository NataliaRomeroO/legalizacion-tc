"""Motor de conciliación: enlaza movimientos del extracto con facturas JSON.

Pasadas de matching (en orden):
1. **Simple** — ventana de fecha ±N días + tolerancia de monto; o número de factura en
   descripción bancaria (``DOMAIN#123``).
2. **Ganador único por factura** — una factura no puede conciliar dos movimientos.
3. **Compound (propina)** — factura COP + recibo propina mismo NIT suman el cargo.
4. **Consolidado** — recibo de caja menor cubre 1–6 cargos mismo día (ej. Uber).
5. **Multi-factura** — varias facturas mismo proveedor/fecha suman un solo cargo.
6. **Provider date review** — monto+proveedor OK pero fecha fuera de ±3 días (hasta 3 meses).
7. **Enriquecimiento** — razones de fallo, observaciones y sugerencias para UNMATCHED/AMBIGUOUS.

Casos especiales:
- GMF (4x1000): status ``GMF``, sin factura requerida.
- SOL: tolerancia 12 %; COP/USD: 2 % (vía ``amount_tolerance_for``).
- Moneda original del extracto comparada cuando existe ``VR MONEDA ORIG`` en concepto.
- Ambigüedad: varios candidatos con mismo score → ``AMBIGUOUS``, no auto-OK.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from datetime import date
from itertools import combinations

from dateutil.relativedelta import relativedelta

from .config import Settings
from .fx_converter import convert_to_cop
from .models import ExtractData, InvoiceData, MatchResult, Transaction
from .nit_utils import normalize_nit_key
from .validation_notes import (
    failure_reason_for_unmatched,
    format_ambiguous_observation,
    format_no_observation,
    format_ok_observation,
    resolve_suggested_invoice,
)

DOMAIN_INVOICE_PATTERN = re.compile(r"DOMAIN#(\d+)", re.IGNORECASE)
CONSOLIDATED_DOC_TYPES = frozenset({"recibo_caja_menor", "recibo_caja"})
_TOKEN_PATTERN = re.compile(r"[A-Z0-9]+")
_PROVIDER_STOPWORDS = frozenset(
    {
        "DE",
        "LA",
        "EL",
        "LOS",
        "LAS",
        "Y",
        "DEL",
        "SA",
        "SAS",
        "S",
        "A",
        "LTDA",
        "CIA",
        "COLOMBIA",
        "CO",
        "INC",
        "CORP",
        "THE",
        "E",
    }
)
MIN_PROVIDER_SCORE = 4
NIT_MATCH_SCORE = 1000


def _within_date_window(tx: Transaction, invoice: InvoiceData, days: int) -> bool:
    """Indica si la fecha de la factura cae dentro de la ventana ±N días del movimiento."""
    if invoice.fecha_factura is None:
        return False
    delta = abs((tx.tx_date - invoice.fecha_factura).days)
    return delta <= days


def _invoice_amount_cop(
    settings: Settings, invoice: InvoiceData, tx: Transaction
) -> float | None:
    """Convierte el valor total de la factura a COP usando FX del día de la transacción."""
    if invoice.valor_total_documento is None or invoice.moneda is None:
        return None
    try:
        return convert_to_cop(
            settings,
            invoice.valor_total_documento,
            invoice.moneda,
            tx.tx_date,
        )
    except Exception:
        return None


def _within_amount_tolerance(
    extract_cop: float, invoice_cop: float, tolerance_pct: float
) -> bool:
    """Compara dos montos COP con tolerancia porcentual relativa."""
    if extract_cop == 0:
        return False
    diff = abs(invoice_cop - extract_cop) / abs(extract_cop)
    return diff <= tolerance_pct


def _within_original_amount_tolerance(
    extract_amount: float, invoice_amount: float, tolerance_pct: float
) -> bool:
    """Compara montos en moneda original con tolerancia porcentual."""
    if extract_amount == 0 or invoice_amount == 0:
        return False
    diff = abs(invoice_amount - extract_amount) / abs(extract_amount)
    return diff <= tolerance_pct


def amount_tolerance_for(
    settings: Settings, tx: Transaction, invoice: InvoiceData
) -> float:
    """Retorna la tolerancia de monto según moneda (SOL amplia, resto estándar)."""
    invoice_currency = (invoice.moneda or "").upper()
    if invoice_currency == "SOL":
        return settings.amount_tolerance_pct_sol
    return settings.amount_tolerance_pct


def _description_matches_invoice(tx: Transaction, invoice: InvoiceData) -> bool:
    """Detecta número de factura en descripción bancaria o patrón DOMAIN#."""
    if not invoice.numero_factura:
        return False
    numero = str(invoice.numero_factura).strip()
    if numero and numero in tx.description:
        return True
    domain_match = DOMAIN_INVOICE_PATTERN.search(tx.description)
    return bool(domain_match and domain_match.group(1) == numero)


def _amounts_match(
    settings: Settings, tx: Transaction, invoice: InvoiceData
) -> bool:
    """Evalúa coincidencia de montos en COP, moneda original o vía conversión FX."""
    if _description_matches_invoice(tx, invoice):
        return True

    invoice_currency = (invoice.moneda or "").upper()
    tx_original_currency = (tx.original_currency or tx.currency or "").upper()

    if (
        invoice.valor_total_documento is not None
        and tx.amount_original is not None
        and invoice_currency
        and tx_original_currency
        and invoice_currency == tx_original_currency
        and invoice_currency != "COP"
    ):
        return _within_original_amount_tolerance(
            tx.amount_original,
            invoice.valor_total_documento,
            amount_tolerance_for(settings, tx, invoice),
        )

    if invoice_currency == "COP" and invoice.valor_total_documento is not None:
        return _within_amount_tolerance(
            tx.amount_cop,
            invoice.valor_total_documento,
            settings.amount_tolerance_pct,
        )

    invoice_cop = _invoice_amount_cop(settings, invoice, tx)
    if invoice_cop is None:
        return False
    return _within_amount_tolerance(
        tx.amount_cop, invoice_cop, amount_tolerance_for(settings, tx, invoice)
    )


def _invoice_is_candidate(
    settings: Settings,
    tx: Transaction,
    invoice: InvoiceData,
) -> bool:
    """Determina si una factura es candidata inicial para un movimiento."""
    if not invoice.legible:
        return False
    if _is_consolidated_invoice(invoice):
        return False
    if _is_tip_receipt(invoice):
        return False
    tipo = (invoice.tipo_documento or "").strip().lower()
    if tipo in CONSOLIDATED_DOC_TYPES:
        return False
    description_match = _description_matches_invoice(tx, invoice)
    if description_match:
        return True
    if not _within_date_window(tx, invoice, settings.date_tolerance_days):
        return False
    return _amounts_match(settings, tx, invoice)


def _normalize_description(description: str) -> str:
    """Normaliza la descripción bancaria a mayúsculas y espacios simples."""
    return " ".join(description.upper().split())


def _normalize_concept(text: str) -> str:
    """Elimina caracteres no alfanuméricos del concepto para comparación."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _significant_tokens(text: str) -> list[str]:
    """Extrae tokens alfanuméricos significativos excluyendo stopwords."""
    return [
        token
        for token in _TOKEN_PATTERN.findall(text.upper())
        if len(token) >= MIN_PROVIDER_SCORE and token not in _PROVIDER_STOPWORDS
    ]


def _score_provider_text_against_concept(
    provider_text: str, tx_description: str
) -> int:
    """Puntúa coincidencia de texto de proveedor contra concepto bancario."""
    if not provider_text:
        return 0

    concept_norm = _normalize_concept(tx_description)
    concept_tokens = set(_significant_tokens(tx_description))
    provider_tokens = set(_significant_tokens(provider_text))

    score = 0
    for token in _significant_tokens(provider_text):
        if token in concept_norm:
            score += len(token)

    score += sum(len(token) for token in concept_tokens & provider_tokens)
    return score


def _provider_concept_score(tx: Transaction, invoice: InvoiceData) -> int:
    """Puntúa coincidencia total del proveedor (NIT, razón social, detalle)."""
    concept_norm = _normalize_concept(tx.description)
    if not concept_norm:
        return 0

    nit = re.sub(r"\D", "", invoice.nit_proveedor or "")
    concept_digits = re.sub(r"\D", "", tx.description)
    if nit and len(nit) >= 6 and nit in concept_digits:
        return NIT_MATCH_SCORE

    score = 0
    for provider_text in (
        invoice.razon_social,
        invoice.nombre_comercial,
        invoice.detalle_gasto,
    ):
        score += _score_provider_text_against_concept(
            provider_text or "", tx.description
        )

    return score


def _transaction_matches_invoice_provider(
    tx: Transaction, invoice: InvoiceData
) -> bool:
    """Indica si el proveedor de la factura coincide con el concepto."""
    return _provider_concept_score(tx, invoice) >= MIN_PROVIDER_SCORE


def _provider_name_concept_score(tx: Transaction, invoice: InvoiceData) -> int:
    """Puntúa coincidencia solo por razón social y nombre comercial."""
    score = 0
    for provider_text in (invoice.razon_social, invoice.nombre_comercial):
        score += _score_provider_text_against_concept(
            provider_text or "", tx.description
        )
    return score


def _provider_name_matches(tx: Transaction, invoice: InvoiceData) -> bool:
    """Verifica coincidencia por nombre de proveedor sobre umbral mínimo."""
    return _provider_name_concept_score(tx, invoice) >= MIN_PROVIDER_SCORE


def _invoice_date_review_ok(
    tx: Transaction, invoice: InvoiceData, max_months: int
) -> bool:
    """Valida que la fecha esté dentro de ventana ampliada en meses."""
    if invoice.fecha_factura is None:
        return False
    earlier = min(tx.tx_date, invoice.fecha_factura)
    later = max(tx.tx_date, invoice.fecha_factura)
    deadline = earlier + relativedelta(months=max_months)
    return later <= deadline


def _is_provider_date_review_candidate(
    settings: Settings,
    tx: Transaction,
    invoice: InvoiceData,
    used_invoices: set[str],
) -> bool:
    """Evalúa si la factura es candidata a revisión de fecha proveedor."""
    if not _is_regular_invoice(invoice, used_invoices):
        return False
    if _within_date_window(tx, invoice, settings.date_tolerance_days):
        return False
    if not _invoice_date_review_ok(
        tx, invoice, settings.consolidated_receipt_review_max_months
    ):
        return False
    if not _amounts_match(settings, tx, invoice):
        return False
    return _provider_name_matches(tx, invoice)


def _provider_review_rank_key(
    settings: Settings, tx: Transaction, invoice: InvoiceData
) -> tuple[int, float, int]:
    """Clave de ranking para desempate en revisión de fecha proveedor."""
    return (
        -_provider_name_concept_score(tx, invoice),
        _amount_diff_pct(settings, tx, invoice),
        _date_diff_days(tx, invoice),
    )


def _pick_provider_date_review_invoice(
    settings: Settings,
    tx: Transaction,
    candidates: list[InvoiceData],
) -> InvoiceData | None:
    """Elige la factura ganadora entre candidatos de revisión de fecha."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    ranked = sorted(candidates, key=lambda inv: _provider_review_rank_key(settings, tx, inv))
    best_key = _provider_review_rank_key(settings, tx, ranked[0])
    winners = [
        inv for inv in candidates if _provider_review_rank_key(settings, tx, inv) == best_key
    ]
    if len(winners) == 1:
        return winners[0]
    return None


def _amount_diff_pct(
    settings: Settings, tx: Transaction, invoice: InvoiceData
) -> float:
    """Calcula diferencia porcentual entre monto del extracto y de la factura."""
    if invoice.valor_total_documento is None:
        return float("inf")

    invoice_currency = (invoice.moneda or "").upper()
    tx_original_currency = (tx.original_currency or tx.currency or "").upper()

    if (
        tx.amount_original is not None
        and invoice_currency
        and tx_original_currency
        and invoice_currency == tx_original_currency
        and invoice_currency != "COP"
    ):
        extract_amount = tx.amount_original
        invoice_amount = invoice.valor_total_documento
    elif invoice_currency == "COP":
        extract_amount = tx.amount_cop
        invoice_amount = invoice.valor_total_documento
    else:
        invoice_cop = _invoice_amount_cop(settings, invoice, tx)
        if invoice_cop is None:
            return float("inf")
        extract_amount = tx.amount_cop
        invoice_amount = invoice_cop

    if extract_amount == 0:
        return float("inf")
    return abs(invoice_amount - extract_amount) / abs(extract_amount)


def _date_diff_days(tx: Transaction, invoice: InvoiceData) -> int:
    """Retorna días absolutos entre fecha del movimiento y de la factura."""
    if invoice.fecha_factura is None:
        return 9999
    return abs((tx.tx_date - invoice.fecha_factura).days)


def _claim_rank_key(
    settings: Settings, tx: Transaction, invoice: InvoiceData
) -> tuple[int, float, int, int]:
    """Clave de ranking para reclamaciones factura-movimiento en desempate."""
    return (
        -_provider_concept_score(tx, invoice),
        _amount_diff_pct(settings, tx, invoice),
        _date_diff_days(tx, invoice),
        tx.row_index,
    )


def _invoice_qualifies_for_auto_ok(tx: Transaction, invoice: InvoiceData) -> bool:
    """Determina si el match califica para estado OK automático."""
    if _description_matches_invoice(tx, invoice):
        return True

    nit = re.sub(r"\D", "", invoice.nit_proveedor or "")
    concept_digits = re.sub(r"\D", "", tx.description)
    if nit and len(nit) >= 6 and nit in concept_digits:
        return True

    return _provider_concept_score(tx, invoice) >= MIN_PROVIDER_SCORE


def _build_invoice_winner_map(
    settings: Settings,
    regular_txs: list[Transaction],
    candidates_by_tx: list[list[InvoiceData]],
) -> dict[str, int]:
    """Construye mapa factura→índice del movimiento ganador único."""
    invoice_claimants: dict[str, list[tuple[int, Transaction, InvoiceData]]] = (
        defaultdict(list)
    )
    for tx_idx, (tx, candidates) in enumerate(zip(regular_txs, candidates_by_tx)):
        for invoice in candidates:
            invoice_claimants[invoice.source_filename].append((tx_idx, tx, invoice))

    winners: dict[str, int] = {}
    for inv_key, claimants in invoice_claimants.items():
        best = min(
            claimants,
            key=lambda item: _claim_rank_key(settings, item[1], item[2]),
        )
        winners[inv_key] = best[0]
    return winners


def _resolve_tx_candidates(
    settings: Settings,
    tx: Transaction,
    candidates: list[InvoiceData],
    used_invoices: set[str],
) -> MatchResult:
    """Resuelve candidatos de un movimiento a OK, UNMATCHED o AMBIGUOUS."""
    available = [
        invoice
        for invoice in candidates
        if invoice.source_filename not in used_invoices
    ]

    if len(available) == 1:
        invoice = available[0]
        if _invoice_qualifies_for_auto_ok(tx, invoice):
            used_invoices.add(invoice.source_filename)
            ok_match = MatchResult(
                transaction=tx,
                invoice=invoice,
                status="OK",
                documento_soporte="SI",
            )
            ok_match.observacion = format_ok_observation(ok_match)
            return ok_match
        return MatchResult(
            transaction=tx,
            invoice=None,
            status="UNMATCHED",
            documento_soporte="NO",
            failure_reason="Factura no encontrada",
        )

    if len(available) > 1:
        winner = _resolve_ambiguous_candidates(settings, tx, available)
        if winner is not None and _invoice_qualifies_for_auto_ok(tx, winner):
            used_invoices.add(winner.source_filename)
            ok_match = MatchResult(
                transaction=tx,
                invoice=winner,
                status="OK",
                documento_soporte="SI",
            )
            ok_match.observacion = format_ok_observation(ok_match)
            return ok_match
        return MatchResult(
            transaction=tx,
            invoice=None,
            status="AMBIGUOUS",
            documento_soporte="NO",
            failure_reason="Ambigüedad: múltiples candidatos",
            observacion=format_ambiguous_observation(available),
            ambiguous_candidates=list(available),
        )

    return MatchResult(
        transaction=tx,
        invoice=None,
        status="UNMATCHED",
        documento_soporte="NO",
    )


def _resolve_ambiguous_candidates(
    settings: Settings,
    tx: Transaction,
    candidates: list[InvoiceData],
) -> InvoiceData | None:
    """Desempata candidatos ambiguos por score, monto y fecha."""
    if not candidates:
        return None

    scored = [(inv, _provider_concept_score(tx, inv)) for inv in candidates]
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
    if len(ranked) == 1:
        return ranked[0]

    first_key = (
        _amount_diff_pct(settings, tx, ranked[0]),
        _date_diff_days(tx, ranked[0]),
    )
    second_key = (
        _amount_diff_pct(settings, tx, ranked[1]),
        _date_diff_days(tx, ranked[1]),
    )
    if first_key < second_key:
        return ranked[0]
    return None


def _detalle_matches_concept(tx: Transaction, invoice: InvoiceData) -> bool:
    """Verifica si tokens del detalle de gasto aparecen en el concepto."""
    detalle = invoice.detalle_gasto or ""
    if not detalle.strip():
        return False
    concept_norm = _normalize_concept(tx.description)
    if not concept_norm:
        return False
    for token in _significant_tokens(detalle):
        if token in concept_norm:
            return True
    return False


def _compound_factura_matches_tx(tx: Transaction, factura: InvoiceData) -> bool:
    """Evalúa si la factura compuesta coincide con el movimiento."""
    if _transaction_matches_invoice_provider(tx, factura):
        return True
    return _detalle_matches_concept(tx, factura)


def _compound_context_ok(
    tx: Transaction,
    factura: InvoiceData,
    recibo: InvoiceData,
    settings: Settings,
) -> bool:
    """Valida contexto de match compuesto factura más recibo de propina."""
    if _compound_factura_matches_tx(tx, factura):
        return True
    if _detalle_matches_concept(tx, recibo):
        return True
    if factura.fecha_factura != tx.tx_date:
        return False
    factura_total = factura.valor_total_documento
    recibo_total = recibo.valor_total_documento
    if factura_total is None or recibo_total is None:
        return False
    combined = factura_total + recibo_total
    return _totals_match(tx.amount_cop, combined, settings.amount_tolerance_pct)


def _totals_match(reference: float, actual: float, tolerance_pct: float) -> bool:
    """Compara totales numéricos con tolerancia porcentual relativa."""
    if reference == 0:
        return False
    return abs(actual - reference) / abs(reference) <= tolerance_pct


def _is_consolidated_invoice(invoice: InvoiceData) -> bool:
    """Identifica recibo de caja menor o factura marcada como consolidada."""
    if invoice.es_propina:
        return False
    if invoice.consolidado:
        return True
    tipo = (invoice.tipo_documento or "").strip().lower()
    return tipo in CONSOLIDATED_DOC_TYPES


def _is_tip_receipt(invoice: InvoiceData) -> bool:
    """Indica si el documento es un recibo de propina."""
    return invoice.es_propina


def _same_nit(left: InvoiceData, right: InvoiceData) -> bool:
    """Compara NIT normalizado de dos facturas."""
    left_nit = normalize_nit_key(left.nit_proveedor)
    right_nit = normalize_nit_key(right.nit_proveedor)
    return bool(left_nit and right_nit and left_nit == right_nit)


def _is_regular_invoice(invoice: InvoiceData, used_invoices: set[str]) -> bool:
    """Factura regular elegible: COP, legible, no usada ni consolidada."""
    if not invoice.legible:
        return False
    if invoice.source_filename in used_invoices:
        return False
    if _is_consolidated_invoice(invoice) or _is_tip_receipt(invoice):
        return False
    tipo = (invoice.tipo_documento or "").strip().lower()
    if tipo in CONSOLIDATED_DOC_TYPES:
        return False
    if invoice.valor_total_documento is None:
        return False
    return (invoice.moneda or "COP").upper() == "COP"


def _is_tip_receipt_candidate(
    invoice: InvoiceData, used_invoices: set[str]
) -> bool:
    """Recibo de propina elegible para match compuesto."""
    if not _is_tip_receipt(invoice):
        return False
    if not invoice.legible:
        return False
    if invoice.source_filename in used_invoices:
        return False
    if invoice.valor_total_documento is None:
        return False
    return (invoice.moneda or "COP").upper() == "COP"


def _tip_date_ok(tx: Transaction, recibo: InvoiceData, max_days_after: int) -> bool:
    """Valida fecha del recibo propina dentro de ventana post-movimiento."""
    if recibo.fecha_factura is None:
        return False
    if recibo.fecha_factura.year != tx.tx_date.year:
        return False
    if recibo.fecha_factura < tx.tx_date:
        return False
    return (recibo.fecha_factura - tx.tx_date).days <= max_days_after


def _apply_compound_tip_matches(
    settings: Settings,
    results: list[MatchResult],
    invoices: list[InvoiceData],
    used_invoices: set[str],
) -> None:
    """Aplica pasada de matching: factura COP más propina mismo NIT."""
    for i, result in enumerate(results):
        if result.status != "UNMATCHED":
            continue

        tx = result.transaction
        best: tuple[InvoiceData, InvoiceData, int, int] | None = None

        for factura in invoices:
            if not _is_regular_invoice(factura, used_invoices):
                continue
            if not _within_date_window(tx, factura, settings.date_tolerance_days):
                continue

            factura_total = factura.valor_total_documento
            if factura_total is None or factura_total >= tx.amount_cop:
                continue

            tip_needed = tx.amount_cop - factura_total
            provider_score = _provider_concept_score(tx, factura)
            date_diff = _date_diff_days(tx, factura)

            for recibo in invoices:
                if not _is_tip_receipt_candidate(recibo, used_invoices):
                    continue
                if not _same_nit(factura, recibo):
                    continue
                recibo_total = recibo.valor_total_documento
                if recibo_total is None:
                    continue
                if not _within_amount_tolerance(
                    tip_needed, recibo_total, settings.amount_tolerance_pct
                ):
                    continue
                if not _tip_date_ok(
                    tx, recibo, settings.consolidated_receipt_max_days_after
                ):
                    continue
                combined = factura_total + recibo_total
                if not _totals_match(
                    tx.amount_cop, combined, settings.amount_tolerance_pct
                ):
                    continue
                if not _compound_context_ok(tx, factura, recibo, settings):
                    continue

                candidate = (factura, recibo, provider_score, date_diff)
                if best is None:
                    best = candidate
                    continue
                if candidate[2] > best[2]:
                    best = candidate
                elif candidate[2] == best[2] and candidate[3] < best[3]:
                    best = candidate

        if best is None:
            continue

        factura, recibo, _, _ = best
        used_invoices.add(factura.source_filename)
        used_invoices.add(recibo.source_filename)
        results[i] = MatchResult(
            transaction=tx,
            invoice=factura,
            status="OK",
            documento_soporte="SI",
            secondary_invoice=recibo,
            match_kind="compound",
            observacion=format_ok_observation(
                MatchResult(
                    transaction=tx,
                    invoice=factura,
                    status="OK",
                    documento_soporte="SI",
                    secondary_invoice=recibo,
                    match_kind="compound",
                )
            ),
        )


def _consolidated_tx_date_strict_ok(
    tx: Transaction, invoice: InvoiceData, max_days_after: int
) -> bool:
    """Fecha estricta del recibo consolidado respecto al movimiento."""
    if invoice.fecha_factura is None:
        return False
    if invoice.fecha_factura.year != tx.tx_date.year:
        return False
    if invoice.fecha_factura < tx.tx_date:
        return False
    return (invoice.fecha_factura - tx.tx_date).days <= max_days_after


def _consolidated_review_date_ok(
    charge_date: date, receipt_date: date | None, max_months: int
) -> bool:
    """Valida fecha de revisión del recibo consolidado en meses."""
    if receipt_date is None:
        return False
    if receipt_date < charge_date:
        return False
    if receipt_date.year != charge_date.year:
        if abs(receipt_date.year - charge_date.year) != 1:
            return False
    deadline = charge_date + relativedelta(months=max_months)
    return receipt_date <= deadline


def _consolidated_tx_date_review_ok(
    tx: Transaction, invoice: InvoiceData, max_months: int
) -> bool:
    """Ventana ampliada de fecha recibo versus transacción."""
    return _consolidated_review_date_ok(
        tx.tx_date, invoice.fecha_factura, max_months
    )


def _consolidated_date_strict_ok(
    txs: list[Transaction], invoice: InvoiceData, max_days_after: int
) -> bool:
    """Fecha estricta del recibo respecto al grupo de movimientos."""
    if invoice.fecha_factura is None:
        return False
    last_tx_date = max(tx.tx_date for tx in txs)
    if invoice.fecha_factura.year != last_tx_date.year:
        return False
    if invoice.fecha_factura < last_tx_date:
        return False
    return (invoice.fecha_factura - last_tx_date).days <= max_days_after


def _consolidated_date_review_ok(
    txs: list[Transaction], invoice: InvoiceData, max_months: int
) -> bool:
    """Fecha de revisión del recibo respecto al grupo de movimientos."""
    if invoice.fecha_factura is None:
        return False
    last_tx_date = max(tx.tx_date for tx in txs)
    return _consolidated_review_date_ok(
        last_tx_date, invoice.fecha_factura, max_months
    )


def _is_uber_consolidated_invoice(invoice: InvoiceData) -> bool:
    """Detecta recibo consolidado Uber por texto en campos de proveedor."""
    haystack = " ".join(
        part
        for part in (
            invoice.razon_social,
            invoice.detalle_gasto,
            invoice.nombre_comercial,
        )
        if part
    ).upper()
    return "UBER" in haystack


def _consolidated_peer_concept(tx: Transaction, invoice: InvoiceData) -> bool:
    """Detecta concepto Uber, RIDES o TRIP para pools consolidados."""
    if not _is_uber_consolidated_invoice(invoice):
        return False
    desc = tx.description.upper()
    return "UBER" in desc or "RIDES" in desc or "TRIP" in desc


def _consolidated_pool_eligible(tx: Transaction, invoice: InvoiceData) -> bool:
    """Indica si el movimiento es elegible para pool consolidado."""
    if _transaction_matches_invoice_provider(tx, invoice):
        return True
    return _consolidated_peer_concept(tx, invoice)


def _group_matches_invoice_provider(
    txs: list[Transaction], invoice: InvoiceData
) -> bool:
    """Verifica si algún movimiento del grupo coincide con el proveedor."""
    if not (invoice.razon_social or invoice.nit_proveedor):
        return True
    return any(_transaction_matches_invoice_provider(tx, invoice) for tx in txs)


def _build_consolidated_date_pools(
    results: list[MatchResult],
    matched_indices: set[int],
    invoice: InvoiceData,
    tx_date_ok: Callable[[Transaction, InvoiceData], bool],
) -> dict[date, list[int]]:
    """Agrupa índices UNMATCHED por fecha para matching consolidado."""
    by_date: dict[date, list[int]] = defaultdict(list)
    for i, result in enumerate(results):
        if result.status != "UNMATCHED" or i in matched_indices:
            continue
        tx = result.transaction
        if not tx_date_ok(tx, invoice):
            continue
        by_date[tx.tx_date].append(i)

    pools: dict[date, list[int]] = {}
    for tx_date, indices in by_date.items():
        provider_indices = [
            i
            for i in indices
            if _consolidated_pool_eligible(results[i].transaction, invoice)
        ]
        if provider_indices:
            pools[tx_date] = provider_indices
    return pools


def _find_consolidated_subset(
    settings: Settings,
    results: list[MatchResult],
    indices: list[int],
    invoice: InvoiceData,
    group_date_ok: Callable[[list[Transaction], InvoiceData], bool],
) -> list[int] | None:
    """Busca subconjunto de movimientos cuya suma coincide con el recibo."""
    invoice_total = invoice.valor_total_documento
    if invoice_total is None or not indices:
        return None

    max_size = min(len(indices), settings.consolidated_max_group_size)
    matching_subsets: list[list[int]] = []

    for size in range(1, max_size + 1):
        for combo in combinations(indices, size):
            idx_list = list(combo)
            txs = [results[i].transaction for i in idx_list]
            total = sum(tx.amount_cop for tx in txs)
            if not _totals_match(
                invoice_total, total, settings.amount_tolerance_pct
            ):
                continue
            if not _group_matches_invoice_provider(txs, invoice):
                continue
            if not group_date_ok(txs, invoice):
                continue
            matching_subsets.append(idx_list)

    if len(matching_subsets) == 1:
        return matching_subsets[0]
    return None


def _apply_consolidated_pass(
    settings: Settings,
    results: list[MatchResult],
    consolidated: list[InvoiceData],
    matched_indices: set[int],
    used_invoices: set[str],
    *,
    needs_review: bool,
    match_kind: str,
    tx_date_ok: Callable[[Transaction, InvoiceData], bool],
    group_date_ok: Callable[[list[Transaction], InvoiceData], bool],
) -> None:
    """Ejecuta una pasada de matching consolidado con reglas de fecha."""
    for invoice in consolidated:
        if invoice.source_filename in used_invoices:
            continue
        pools = _build_consolidated_date_pools(
            results, matched_indices, invoice, tx_date_ok
        )
        for tx_date in sorted(pools.keys()):
            available = [i for i in pools[tx_date] if i not in matched_indices]
            subset = _find_consolidated_subset(
                settings, results, available, invoice, group_date_ok
            )
            if subset is None:
                continue

            used_invoices.add(invoice.source_filename)
            for i in subset:
                matched_indices.add(i)
                ok_match = MatchResult(
                    transaction=results[i].transaction,
                    invoice=invoice,
                    status="OK",
                    documento_soporte="SI",
                    match_kind=match_kind,
                    needs_review=needs_review,
                )
                ok_match.observacion = format_ok_observation(
                    ok_match, settings=settings
                )
                results[i] = ok_match
            break


def _apply_consolidated_matches(
    settings: Settings,
    results: list[MatchResult],
    invoices: list[InvoiceData],
    used_invoices: set[str],
) -> None:
    """Orquesta pasadas estricta y de revisión para recibos consolidados."""
    consolidated = [
        inv
        for inv in invoices
        if inv.legible
        and _is_consolidated_invoice(inv)
        and inv.source_filename not in used_invoices
        and inv.valor_total_documento is not None
        and (inv.moneda or "COP").upper() == "COP"
    ]
    if not consolidated:
        return

    consolidated.sort(
        key=lambda inv: (
            inv.fecha_factura or date.min,
            -(inv.valor_total_documento or 0),
        )
    )

    matched_indices: set[int] = set()
    max_days_after = settings.consolidated_receipt_max_days_after
    max_months = settings.consolidated_receipt_review_max_months

    strict_tx_ok = lambda tx, inv: _consolidated_tx_date_strict_ok(
        tx, inv, max_days_after
    )
    strict_group_ok = lambda txs, inv: _consolidated_date_strict_ok(
        txs, inv, max_days_after
    )
    review_tx_ok = lambda tx, inv: _consolidated_tx_date_review_ok(
        tx, inv, max_months
    )
    review_group_ok = lambda txs, inv: _consolidated_date_review_ok(
        txs, inv, max_months
    )

    _apply_consolidated_pass(
        settings,
        results,
        consolidated,
        matched_indices,
        used_invoices,
        needs_review=False,
        match_kind="consolidated",
        tx_date_ok=strict_tx_ok,
        group_date_ok=strict_group_ok,
    )
    _apply_consolidated_pass(
        settings,
        results,
        consolidated,
        matched_indices,
        used_invoices,
        needs_review=True,
        match_kind="consolidated_review",
        tx_date_ok=review_tx_ok,
        group_date_ok=review_group_ok,
    )


def _multi_invoice_group_coherent(invoices: list[InvoiceData]) -> bool:
    """Verifica coherencia de grupo multi-factura (mismo NIT y fecha)."""
    if len(invoices) < 2:
        return False
    nits = {normalize_nit_key(inv.nit_proveedor) for inv in invoices}
    nits.discard("")
    if len(nits) > 1:
        return False
    dates = {inv.fecha_factura for inv in invoices}
    if None in dates or len(dates) > 1:
        return False
    return True


def _multi_invoice_pool(
    settings: Settings,
    tx: Transaction,
    invoices: list[InvoiceData],
    used_invoices: set[str],
) -> list[InvoiceData]:
    """Construye pool de facturas elegibles para match multi-factura."""
    return [
        inv
        for inv in invoices
        if _is_regular_invoice(inv, used_invoices)
        and _transaction_matches_invoice_provider(tx, inv)
        and _within_date_window(tx, inv, settings.date_tolerance_days)
    ]


def _find_multi_invoice_subset(
    settings: Settings,
    tx: Transaction,
    pool: list[InvoiceData],
) -> list[InvoiceData] | None:
    """Busca subconjunto de facturas cuya suma coincide con el cargo."""
    if len(pool) < 2:
        return None

    max_size = min(len(pool), settings.consolidated_max_group_size)
    matching_subsets: list[tuple[int, ...]] = []

    for size in range(2, max_size + 1):
        for combo in combinations(range(len(pool)), size):
            subset = [pool[i] for i in combo]
            total = sum(inv.valor_total_documento or 0.0 for inv in subset)
            if not _totals_match(
                tx.amount_cop, total, settings.amount_tolerance_pct
            ):
                continue
            if not all(
                _transaction_matches_invoice_provider(tx, inv) for inv in subset
            ):
                continue
            if not _multi_invoice_group_coherent(subset):
                continue
            if not all(
                _within_date_window(tx, inv, settings.date_tolerance_days)
                for inv in subset
            ):
                continue
            matching_subsets.append(combo)

    if len(matching_subsets) == 1:
        return [pool[i] for i in matching_subsets[0]]
    return None


def _apply_multi_invoice_matches(
    settings: Settings,
    results: list[MatchResult],
    invoices: list[InvoiceData],
    used_invoices: set[str],
) -> None:
    """Aplica pasada de matching multi-factura a resultados UNMATCHED."""
    for i, result in enumerate(results):
        if result.status != "UNMATCHED":
            continue

        tx = result.transaction
        pool = _multi_invoice_pool(settings, tx, invoices, used_invoices)
        subset = _find_multi_invoice_subset(settings, tx, pool)
        if subset is None:
            continue

        for inv in subset:
            used_invoices.add(inv.source_filename)

        component_invoices = sorted(
            subset,
            key=lambda inv: str(inv.numero_factura or inv.source_filename),
        )
        ok_match = MatchResult(
            transaction=tx,
            invoice=component_invoices[0],
            status="OK",
            documento_soporte="NO",
            match_kind="multi_factura",
            component_invoices=component_invoices,
        )
        ok_match.observacion = format_ok_observation(ok_match, settings=settings)
        results[i] = ok_match


def _apply_provider_date_review_matches(
    settings: Settings,
    results: list[MatchResult],
    invoices: list[InvoiceData],
    used_invoices: set[str],
) -> None:
    """Aplica revisión de fecha proveedor a movimientos UNMATCHED."""
    for i, result in enumerate(results):
        if result.status != "UNMATCHED":
            continue

        tx = result.transaction
        candidates = [
            inv
            for inv in invoices
            if _is_provider_date_review_candidate(settings, tx, inv, used_invoices)
        ]
        winner = _pick_provider_date_review_invoice(settings, tx, candidates)
        if winner is None:
            continue

        used_invoices.add(winner.source_filename)
        ok_match = MatchResult(
            transaction=tx,
            invoice=winner,
            status="OK",
            documento_soporte="SI",
            match_kind="provider_date_review",
            needs_review=True,
        )
        ok_match.observacion = format_ok_observation(ok_match, settings=settings)
        results[i] = ok_match


def _suggestion_priority_key(
    settings: Settings,
    result: MatchResult,
    invoices: list[InvoiceData],
) -> tuple[int, int]:
    """Clave de prioridad para ordenar enriquecimiento de observaciones."""
    tx = result.transaction
    if result.status == "AMBIGUOUS" and result.ambiguous_candidates:
        pool = result.ambiguous_candidates
    else:
        pool = invoices
    best_score = max(
        (_provider_concept_score(tx, inv) for inv in pool if inv.legible),
        default=0,
    )
    return (-best_score, tx.row_index)


def _enrich_unmatched_observations(
    settings: Settings,
    results: list[MatchResult],
    invoices: list[InvoiceData],
    used_invoices: set[str],
) -> None:
    """Añade razones de fallo, observaciones y facturas sugeridas."""
    pending = [
        result
        for result in results
        if result.status in {"UNMATCHED", "AMBIGUOUS"}
    ]
    pending.sort(key=lambda result: _suggestion_priority_key(settings, result, invoices))

    reserved_invoices = set(used_invoices)
    for result in pending:
        if result.status == "UNMATCHED":
            result.failure_reason = failure_reason_for_unmatched(
                settings, result.transaction, invoices, reserved_invoices
            )
        result.observacion = format_no_observation(
            result,
            settings,
            invoices,
            reserved_invoices,
        )
        result.suggested_invoice = resolve_suggested_invoice(
            settings, result, invoices, reserved_invoices
        )
        if result.suggested_invoice is not None:
            reserved_invoices.add(result.suggested_invoice.source_filename)


def reconcile(
    settings: Settings,
    extract: ExtractData,
    invoices: list[InvoiceData],
) -> list[MatchResult]:
    """Concilia cada transacción del extracto con las facturas disponibles.

    GMF se resuelve inline; transacciones regulares pasan por las 6 fases de matching
    documentadas en el docstring del módulo, más enriquecimiento de fallos y sugerencias.
    """
    results: list[MatchResult | None] = []
    regular_txs: list[Transaction] = []
    regular_result_indices: list[int] = []

    for tx in extract.transactions:
        if tx.is_gmf:
            gmf_match = MatchResult(
                transaction=tx,
                invoice=None,
                status="GMF",
                documento_soporte="SI",
            )
            gmf_match.observacion = format_ok_observation(gmf_match)
            results.append(gmf_match)
            continue

        regular_result_indices.append(len(results))
        regular_txs.append(tx)
        results.append(None)

    candidates_by_tx = [
        [
            invoice
            for invoice in invoices
            if _invoice_is_candidate(settings, tx, invoice)
        ]
        for tx in regular_txs
    ]
    invoice_winners = _build_invoice_winner_map(
        settings, regular_txs, candidates_by_tx
    )

    used_invoices: set[str] = set()
    for tx_idx, tx in enumerate(regular_txs):
        filtered_candidates = [
            invoice
            for invoice in candidates_by_tx[tx_idx]
            if invoice_winners.get(invoice.source_filename) == tx_idx
        ]
        match = _resolve_tx_candidates(settings, tx, filtered_candidates, used_invoices)
        results[regular_result_indices[tx_idx]] = match

    finalized: list[MatchResult] = [result for result in results if result is not None]

    # Fase 3: factura COP + recibo propina mismo NIT
    _apply_compound_tip_matches(settings, finalized, invoices, used_invoices)
    # Fase 4: recibo de caja menor cubre varios cargos (ej. Uber)
    _apply_consolidated_matches(settings, finalized, invoices, used_invoices)
    # Fase 5: varias facturas suman un solo cargo
    _apply_multi_invoice_matches(settings, finalized, invoices, used_invoices)
    # Fase 6: monto+proveedor OK pero fecha fuera de ventana estricta
    _apply_provider_date_review_matches(settings, finalized, invoices, used_invoices)
    # Enriquecimiento: razones de fallo, observaciones y facturas sugeridas
    _enrich_unmatched_observations(settings, finalized, invoices, used_invoices)

    return finalized
