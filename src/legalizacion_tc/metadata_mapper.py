"""Transforma ``MatchResult`` en filas ``LegalizationRow`` para el Excel contable.

Lógica principal en ``build_legalization_rows``:
- **GMF**: todos los movimientos GMF se consolidan en una fila (NIT Bancolombia).
- **OK simple**: histórico por NIT/razón social; split IVA 19 % en COP cuando aplica.
- **Sin IVA**: moneda extranjera, restaurantes (keywords), ``sin_desglose_iva``.
- **Compound / multi_factura / consolidated**: una o más filas según ``match_kind``.
- **UNMATCHED/AMBIGUOUS**: fila vacía o fila sugerida (``needs_review=True``).

Casos de IVA COP:
- Base homogénea al 19 % → fila gravada + fila exenta si el cargo excede base+IVA.
- Propina usa ``articulo_propina`` de settings.
- ``documento_soporte``: SI para moneda extranjera, NO para COP.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .config import Settings
from .fx_converter import convert_to_cop
from .models import (
    CardMetadata,
    InvoiceData,
    LegalizationRow,
    MatchResult,
    ProviderHistory,
    Transaction,
)
from .nit_utils import index_historico, normalize_nit_key
from .reconciliation_engine import (
    CONSOLIDATED_DOC_TYPES,
    _is_consolidated_invoice,
    amount_tolerance_for,
    _within_amount_tolerance,
    _within_original_amount_tolerance,
)

GMF_NIT = "8909039388"
GMF_RAZON = "BANCOLOMBIA "
GMF_ARTICULO = "5115950001 - GMF IMPUESTOS"

_MONTHS = (
    "ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO|"
    "SEPTIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE"
)
_DATE_PATTERN = re.compile(
    rf"\b\d{{1,2}}\s*(DE\s+)?({_MONTHS})\b|\b\d{{1,2}}\s+DE\s+\w+\b",
    re.IGNORECASE,
)
_CITY_PATTERN = re.compile(
    r"\b(MEDELLIN|MEDELLÍN|BOGOTA|BOGOTÁ|CALI|BARRANQUILLA|CARTAGENA)\b",
    re.IGNORECASE,
)
_NAMED_CONTEXT_PATTERN = re.compile(
    r"\b(VUELO|VUELOS|CELEBRACI[ÓO]N|EVENTO)\b.*\b[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,})+",
    re.IGNORECASE,
)


def _normalize_razon_social(razon: str) -> str:
    """Normaliza razón social: minúsculas, sin puntuación ni espacios extra."""
    text = re.sub(r"[.,]", "", razon.strip().lower())
    return " ".join(text.split())


def _find_history(
    nit: str,
    razon: str,
    historico: dict[str, ProviderHistory],
) -> ProviderHistory | None:
    """Busca registro histórico por NIT normalizado o razón social."""
    if nit and nit in historico:
        return historico[nit]
    nit_key = normalize_nit_key(nit)
    if nit_key and nit_key in historico:
        return historico[nit_key]
    razon_key = _normalize_razon_social(razon)
    if not razon_key:
        return None
    if razon_key in historico:
        return historico[razon_key]
    for history in historico.values():
        if _normalize_razon_social(history.razon_social) == razon_key:
            return history
    return None


def _historico_detalle_is_generic(detalle: str) -> bool:
    """Indica si el detalle del histórico es genérico (sin fecha ni ciudad)."""
    text = detalle.strip()
    if not text:
        return False
    if _DATE_PATTERN.search(text):
        return False
    if _CITY_PATTERN.search(text):
        return False
    if _NAMED_CONTEXT_PATTERN.search(text):
        return False
    return True


def _resolve_detalle_gasto(
    card: str,
    invoice: InvoiceData,
    history: ProviderHistory | None,
    razon_social: str,
) -> str:
    """Resuelve detalle de gasto desde factura, histórico o plantilla por tarjeta."""
    if invoice.detalle_gasto and invoice.detalle_gasto.strip():
        return invoice.detalle_gasto.strip()
    if (
        history
        and history.detalle_gasto
        and _historico_detalle_is_generic(history.detalle_gasto)
    ):
        return history.detalle_gasto.replace("1111", card)
    razon = (razon_social or "").strip() or "PROVEEDOR"
    return f"TC {card} GASTO {razon}"


def _gmf_detalle(card: str) -> str:
    """Genera detalle de gasto estándar para fila GMF consolidada."""
    return f"TC {card} GMF "


RECIBO_CAJA_PREFIX = "RECIBO DE CAJA "

FOREIGN_CURRENCIES = frozenset({"USD", "CLP", "SOL"})


def _format_numero_factura(
    value: str | None, invoice: InvoiceData | None = None
) -> str | int | None:
    """Formatea número de factura; recibos de caja reciben prefijo RECIBO DE CAJA."""
    if not value:
        return ""
    stripped = value.strip()
    tipo = (invoice.tipo_documento or "").lower() if invoice else ""
    if tipo in CONSOLIDATED_DOC_TYPES:
        upper = stripped.upper()
        if upper.startswith("RECIBO DE CAJA"):
            return stripped
        return f"{RECIBO_CAJA_PREFIX}{stripped}"
    if stripped.isdigit():
        return int(stripped)
    return stripped


def _extract_matches_base_plus_iva(
    settings: Settings,
    tx: Transaction,
    invoice: InvoiceData,
) -> bool:
    """Indica si el cargo coincide con base más IVA de la factura."""
    base = invoice.valor_base
    iva = invoice.iva or 0.0
    if base is None:
        return False
    expected = base + iva
    if expected <= 0:
        return False

    moneda = (invoice.moneda or tx.currency or "COP").upper()
    tx_original_currency = (tx.original_currency or tx.currency or "").upper()

    if moneda == "COP":
        return _within_amount_tolerance(
            tx.amount_cop, expected, settings.amount_tolerance_pct
        )

    if (
        tx.amount_original is not None
        and tx_original_currency
        and moneda == tx_original_currency
    ):
        return _within_original_amount_tolerance(
            tx.amount_original, expected, amount_tolerance_for(settings, tx, invoice)
        )

    try:
        expected_cop = convert_to_cop(settings, expected, moneda, tx.tx_date)
    except Exception:
        return False
    return _within_amount_tolerance(
        tx.amount_cop, expected_cop, amount_tolerance_for(settings, tx, invoice)
    )


# Tolerancia solo para decidir si toda la base está gravada al 19%.
# Independiente de AMOUNT_TOLERANCE_PCT (match cargo vs factura).
_IVA_RATE_MATCH_TOLERANCE_PCT = 0.005


def _is_homogeneous_cop_iva(
    base: float,
    iva: float,
    rate: float,
    tolerance_pct: float = _IVA_RATE_MATCH_TOLERANCE_PCT,
) -> bool:
    """Verifica si el IVA corresponde homogéneamente a la tasa COP configurada."""
    if iva <= 0:
        return iva == 0
    expected_iva = base * rate
    return _within_amount_tolerance(iva, expected_iva, tolerance_pct)


def _effective_cop_iva(invoice: InvoiceData) -> float:
    """IVA a desglosar en Excel. Si iva=0, usa otros_impuestos (p. ej. IVA mal clasificado)."""
    iva = invoice.iva or 0.0
    if iva > 0:
        return iva
    return invoice.otros_impuestos or 0.0


def _charge_rounding_eps(charge: float) -> float:
    """Calcula epsilon de redondeo proporcional al monto del cargo."""
    return max(1.0, abs(charge) * 1e-4)


def _should_skip_iva_breakdown(
    invoice: InvoiceData,
    tx: Transaction,
    settings: Settings,
) -> bool:
    """Determina si se omite desglose de IVA (extranjero, restaurante, flag)."""
    moneda = (invoice.moneda or tx.currency or "COP").upper()
    if moneda != "COP":
        return True
    text = " ".join(filter(None, [invoice.detalle_gasto, tx.description])).upper()
    if any(kw in text for kw in settings.restaurant_no_iva_keywords):
        return True
    if invoice.sin_desglose_iva:
        # Restaurante / flag: sin IVA solo si el cargo ≈ base+iva del documento.
        # Si el cargo es mayor (propina/exento embebido), sí desglosar/split.
        base = invoice.valor_base
        iva = invoice.iva or 0.0
        if base is not None and iva > 0:
            expected = base + iva
            if tx.amount_cop > expected and not _within_amount_tolerance(
                tx.amount_cop, expected, settings.amount_tolerance_pct
            ):
                return False
        return True
    return False


def _plan_cop_iva_rows(
    settings: Settings,
    invoice: InvoiceData,
    tx: Transaction,
) -> list[tuple[float, float, float]] | None:
    """Filas COP (valor_base, iva, total) para el Excel.

    Invariante: en toda fila con iva > 0, valor_base + iva == total.
    Si el cargo supera la parte gravada, la diferencia va en una segunda fila
    solo con valor_base (sin IVA).

    None → sin desglose de IVA (COPS = cargo completo).
    """
    if _should_skip_iva_breakdown(invoice, tx, settings):
        return None

    iva = _effective_cop_iva(invoice)
    if iva <= 0:
        return None

    rate = settings.iva_rate_cop
    charge = tx.amount_cop
    eps = _charge_rounding_eps(charge)
    base = invoice.valor_base

    if base is not None and base > 0 and _is_homogeneous_cop_iva(base, iva, rate):
        total = base + iva
        if charge + eps < total:
            return None
        if abs(charge - total) <= eps:
            return [(base, iva, total)]
        return [(base, iva, total), (charge - total, 0.0, charge - total)]

    base_gravada = round(iva / rate)
    if base_gravada <= 0:
        return None
    total_gravada = base_gravada + iva
    remainder = charge - total_gravada
    if remainder < -eps:
        return None
    if remainder <= eps:
        return [(base_gravada, iva, total_gravada)]
    return [(base_gravada, iva, total_gravada), (remainder, 0.0, remainder)]


def _foreign_amount(tx: Transaction, invoice: InvoiceData, moneda: str) -> float | None:
    """Obtiene monto en moneda extranjera desde extracto o factura."""
    tx_original_currency = (tx.original_currency or tx.currency or "").upper()
    if tx.amount_original is not None and tx_original_currency == moneda:
        return tx.amount_original
    if invoice.valor_total_documento is not None:
        return invoice.valor_total_documento
    return invoice.valor_base


def _resolve_monetary_columns(
    settings: Settings,
    tx: Transaction,
    invoice: InvoiceData,
) -> tuple[float | None, float | None, float | None, float, float, float]:
    """Resuelve columnas monetarias USD, CLP, SOL, COP e IVA para Excel."""
    cop_amount = tx.amount_cop
    moneda = (invoice.moneda or tx.currency or "COP").upper()

    if moneda in FOREIGN_CURRENCIES:
        foreign = _foreign_amount(tx, invoice, moneda)
        valor_usd = foreign if moneda == "USD" else None
        valor_clp = foreign if moneda == "CLP" else None
        valor_sol = foreign if moneda == "SOL" else None
        return valor_usd, valor_clp, valor_sol, cop_amount, 0.0, cop_amount

    plan = _plan_cop_iva_rows(settings, invoice, tx)
    if plan is None:
        return 0.0, None, None, cop_amount, 0.0, cop_amount

    base, row_iva, total = plan[0]
    return 0.0, None, None, base, row_iva, total


def _partial_transaction(tx: Transaction, amount_cop: float) -> Transaction:
    """Crea transacción parcial con monto COP específico para filas divididas."""
    return Transaction(
        card=tx.card,
        tx_date=tx.tx_date,
        description=tx.description,
        currency=tx.currency,
        amount_cop=amount_cop,
        row_index=tx.row_index,
        amount_original=tx.amount_original,
        original_currency=tx.original_currency,
    )


def _append_planned_iva_rows(
    regular_rows: list[LegalizationRow],
    card_meta: CardMetadata,
    invoice: InvoiceData,
    tx: Transaction,
    historico: dict[str, ProviderHistory],
    settings: Settings,
    new_nits: list[str],
    plan: list[tuple[float, float, float]],
) -> None:
    """Añade filas de legalización según plan de desglose IVA COP."""
    for base, row_iva, total in plan:
        regular_rows.append(
            _build_legalization_row(
                card_meta,
                invoice,
                _partial_transaction(tx, total),
                historico,
                settings,
                new_nits,
                valor_base_cops=base,
                row_iva=row_iva,
                total_cop=total,
            )
        )


def _aggregated_transaction(group: list[MatchResult]) -> Transaction:
    """Construye transacción agregada sumando montos de grupo consolidado."""
    rep = group[0].transaction
    return Transaction(
        card=rep.card,
        tx_date=min(m.transaction.tx_date for m in group),
        description=rep.description,
        currency=rep.currency,
        amount_cop=sum(m.transaction.amount_cop for m in group),
        row_index=min(m.transaction.row_index for m in group),
        amount_original=rep.amount_original,
        original_currency=rep.original_currency,
    )


def _append_provider_nit(
    new_nits: list[str],
    historico: dict[str, ProviderHistory],
    nit: str,
    history: ProviderHistory | None = None,
) -> None:
    """Registra NIT nuevo si no existe en histórico ni en lista pendiente."""
    # Si ya se encontró un match en el histórico (por NIT o por razón social),
    # el proveedor está registrado; no hay nada que pedir al operador.
    if not nit or history is not None:
        return
    if nit not in historico and nit not in new_nits:
        new_nits.append(nit)


def _documento_soporte_por_moneda(moneda: str | None) -> str:
    """Retorna SI/NO de documento soporte según moneda (extranjero=SI)."""
    return "SI" if (moneda or "COP").upper() != "COP" else "NO"


def _build_unmatched_row(card_meta: CardMetadata, tx: Transaction) -> LegalizationRow:
    """Construye fila Excel para movimiento sin match ni sugerencia."""
    moneda = (tx.currency or "COP").upper()
    tx_original_currency = (tx.original_currency or tx.currency or "").upper()
    if moneda == "USD" or tx_original_currency == "USD":
        valor_usd = tx.amount_original
    else:
        valor_usd = 0.0 if moneda == "COP" else tx.amount_original
    concept = (tx.description or "SIN CONCEPTO").strip().upper()
    return LegalizationRow(
        numero_factura="",
        nit_proveedor="",
        razon_social="",
        detalle_gasto=f"TC {card_meta.card} {concept}",
        articulo_contable="",
        centro_costo=card_meta.centro_costo,
        moneda=moneda,
        valor_base_usd=valor_usd,
        valor_base_clp=None,
        valor_base_cops=tx.amount_cop,
        iva=0.0,
        valor_total_compra_cop=tx.amount_cop,
        documento_soporte="",
        needs_review=True,
    )


def _resolve_articulo_contable(
    invoice: InvoiceData,
    history: ProviderHistory | None,
    settings: Settings,
) -> str:
    """Resuelve artículo contable: propina usa setting, resto desde histórico."""
    if invoice.es_propina:
        return settings.articulo_propina
    return history.articulo_contable if history else ""


def _build_legalization_row(
    card_meta: CardMetadata,
    invoice: InvoiceData,
    tx: Transaction,
    historico: dict[str, ProviderHistory],
    settings: Settings,
    new_nits: list[str],
    *,
    register_provider: bool = True,
    valor_base_cops: float | None = None,
    row_iva: float | None = None,
    total_cop: float | None = None,
) -> LegalizationRow:
    """Construye una fila ``LegalizationRow`` completa desde match y factura."""
    nit = (invoice.nit_proveedor or "").strip()
    history = _find_history(nit, invoice.razon_social or "", historico)
    if history:
        nit = history.nit
    razon = invoice.razon_social or (history.razon_social if history else "")
    detalle = _resolve_detalle_gasto(card_meta.card, invoice, history, razon)
    articulo = _resolve_articulo_contable(invoice, history, settings)
    if register_provider:
        _append_provider_nit(new_nits, historico, nit, history)

    moneda = (invoice.moneda or tx.currency or "COP").upper()
    valor_usd, valor_clp, valor_sol, resolved_base, resolved_iva, resolved_total = (
        _resolve_monetary_columns(settings, tx, invoice)
    )
    if valor_base_cops is not None:
        resolved_base = valor_base_cops
    if row_iva is not None:
        resolved_iva = row_iva
    if total_cop is not None:
        resolved_total = total_cop

    return LegalizationRow(
        numero_factura=_format_numero_factura(invoice.numero_factura, invoice),
        nit_proveedor=nit,
        razon_social=razon,
        detalle_gasto=detalle,
        articulo_contable=articulo,
        centro_costo=card_meta.centro_costo,
        moneda=moneda,
        valor_base_usd=valor_usd,
        valor_base_clp=valor_clp,
        valor_base_sol=valor_sol,
        valor_base_cops=resolved_base,
        iva=resolved_iva,
        valor_total_compra_cop=resolved_total,
        documento_soporte=_documento_soporte_por_moneda(moneda),
    )


def _build_suggested_row(
    card_meta: CardMetadata,
    tx: Transaction,
    invoice: InvoiceData,
    historico: dict[str, ProviderHistory],
    settings: Settings,
) -> LegalizationRow:
    """Construye fila sugerida marcada con ``needs_review=True``."""
    row = _build_legalization_row(
        card_meta,
        invoice,
        tx,
        historico,
        settings,
        [],
        register_provider=False,
    )
    row.needs_review = True
    return row


def build_legalization_rows(
    matches: list[MatchResult],
    card_meta: CardMetadata,
    historico: dict[str, ProviderHistory],
    settings: Settings,
) -> tuple[list[LegalizationRow], list[str]]:
    """Convierte matches conciliados en filas Excel; retorna también NITs nuevos.

    Orden de salida: filas regulares, GMF consolidado al final, unmatched/sugeridas al final.
    """
    historico = index_historico(historico)
    rows: list[LegalizationRow] = []
    regular_rows: list[LegalizationRow] = []
    new_nits: list[str] = []
    gmf_history = historico.get(GMF_NIT)
    gmf_total_cop = 0.0
    has_gmf = False

    consolidated_groups: dict[str, list[MatchResult]] = defaultdict(list)
    for match in matches:
        if match.status != "OK" or match.invoice is None:
            continue
        if _is_consolidated_invoice(match.invoice):
            consolidated_groups[match.invoice.source_filename].append(match)

    emitted_consolidated: set[str] = set()

    for match in matches:
        tx = match.transaction
        cop_amount = tx.amount_cop

        if tx.is_gmf or match.status == "GMF":
            gmf_total_cop += cop_amount
            has_gmf = True
            continue

        if match.status != "OK" or match.invoice is None:
            if match.status in ("UNMATCHED", "AMBIGUOUS"):
                if match.suggested_invoice is not None:
                    regular_rows.append(
                        _build_suggested_row(
                            card_meta,
                            tx,
                            match.suggested_invoice,
                            historico,
                            settings,
                        )
                    )
                else:
                    regular_rows.append(_build_unmatched_row(card_meta, tx))
            continue

        invoice = match.invoice

        if match.match_kind == "multi_factura" and match.component_invoices:
            for comp in match.component_invoices:
                amount = comp.valor_total_documento or 0.0
                partial_tx = _partial_transaction(tx, amount)
                plan = _plan_cop_iva_rows(settings, comp, partial_tx)
                if plan is not None:
                    _append_planned_iva_rows(
                        regular_rows,
                        card_meta,
                        comp,
                        partial_tx,
                        historico,
                        settings,
                        new_nits,
                        plan,
                    )
                else:
                    regular_rows.append(
                        _build_legalization_row(
                            card_meta,
                            comp,
                            partial_tx,
                            historico,
                            settings,
                            new_nits,
                        )
                    )
            continue

        if match.match_kind == "compound" and match.secondary_invoice is not None:
            factura = invoice
            recibo = match.secondary_invoice
            factura_amount = factura.valor_total_documento or 0.0
            recibo_amount = recibo.valor_total_documento or 0.0
            factura_tx = _partial_transaction(tx, factura_amount)
            plan = _plan_cop_iva_rows(settings, factura, factura_tx)
            if plan is not None:
                _append_planned_iva_rows(
                    regular_rows,
                    card_meta,
                    factura,
                    factura_tx,
                    historico,
                    settings,
                    new_nits,
                    plan,
                )
            else:
                regular_rows.append(
                    _build_legalization_row(
                        card_meta,
                        factura,
                        factura_tx,
                        historico,
                        settings,
                        new_nits,
                    )
                )
            regular_rows.append(
                _build_legalization_row(
                    card_meta,
                    recibo,
                    _partial_transaction(tx, recibo_amount),
                    historico,
                    settings,
                    new_nits,
                )
            )
            continue

        if _is_consolidated_invoice(invoice):
            source_key = invoice.source_filename
            if source_key in emitted_consolidated:
                continue
            emitted_consolidated.add(source_key)
            group = consolidated_groups[source_key]
            agg_tx = _aggregated_transaction(group)
            plan = _plan_cop_iva_rows(settings, invoice, agg_tx)
            if plan is not None:
                _append_planned_iva_rows(
                    regular_rows,
                    card_meta,
                    invoice,
                    agg_tx,
                    historico,
                    settings,
                    new_nits,
                    plan,
                )
                n_emitted = len(plan)
            else:
                regular_rows.append(
                    _build_legalization_row(
                        card_meta, invoice, agg_tx, historico, settings, new_nits
                    )
                )
                n_emitted = 1
            if any(m.needs_review for m in group):
                for row in regular_rows[-n_emitted:]:
                    row.needs_review = True
            continue

        plan = _plan_cop_iva_rows(settings, invoice, tx)
        if plan is not None:
            _append_planned_iva_rows(
                regular_rows,
                card_meta,
                invoice,
                tx,
                historico,
                settings,
                new_nits,
                plan,
            )
        else:
            regular_rows.append(
                _build_legalization_row(
                    card_meta, invoice, tx, historico, settings, new_nits
                )
            )
        if match.needs_review:
            n_emitted = len(plan) if plan is not None else 1
            for row in regular_rows[-n_emitted:]:
                row.needs_review = True

    if has_gmf:
        rows.append(
            LegalizationRow(
                numero_factura="",
                nit_proveedor=GMF_NIT,
                razon_social=gmf_history.razon_social if gmf_history else GMF_RAZON,
                detalle_gasto=_gmf_detalle(card_meta.card),
                articulo_contable=(
                    gmf_history.articulo_contable if gmf_history else GMF_ARTICULO
                ),
                centro_costo=card_meta.centro_costo,
                moneda="COP",
                valor_base_usd=None,
                valor_base_clp=None,
                valor_base_cops=gmf_total_cop,
                iva=0.0,
                valor_total_compra_cop=gmf_total_cop,
                documento_soporte=_documento_soporte_por_moneda("COP"),
            )
        )
    rows.extend(regular_rows)

    return rows, new_nits
