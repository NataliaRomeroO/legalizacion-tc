"""Modelos de dominio compartidos por todo el pipeline de legalización TC.

Estructuras de datos entre extracto bancario, facturas JSON, conciliación y Excel:
- ``Transaction`` / ``ExtractData``: movimientos del preliminar Excel o PDF Bancolombia.
- ``InvoiceData``: factura extraída por Claude Code (sin montos COP; vienen del extracto).
- ``MatchResult``: resultado de conciliación (OK, UNMATCHED, AMBIGUOUS, GMF) con variantes
  ``match_kind`` (simple, compound, multi_factura, consolidated, provider_date_review).
- ``LegalizationRow``: fila del Excel contable de salida.
- ``PipelineResult``: agregado final con links Drive, warnings y contadores de dedup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Transaction:
    """Un cargo de tarjeta de crédito parseado del extracto."""
    card: str
    tx_date: date
    description: str
    currency: str
    amount_cop: float
    row_index: int = 0
    amount_original: Optional[float] = None
    original_currency: Optional[str] = None
    is_gmf: bool = False


@dataclass
class ExtractData:
    """Extracto parseado (PDF o Excel) con lista de transacciones y total COP."""

    card: str
    period_month: str
    period_year: int
    transactions: list[Transaction]
    total_cop: float
    source_filename: str


@dataclass
class InvoiceData:
    """Factura leída desde JSON; montos en moneda del documento (no COP)."""

    source_filename: str
    numero_factura: Optional[str] = None
    nit_proveedor: Optional[str] = None
    razon_social: Optional[str] = None
    nombre_comercial: Optional[str] = None
    moneda: Optional[str] = None
    valor_base: Optional[float] = None
    iva: float = 0.0
    otros_impuestos: float = 0.0
    valor_total_documento: Optional[float] = None
    fecha_factura: Optional[date] = None
    detalle_gasto: Optional[str] = None
    tipo_documento: Optional[str] = None
    consolidado: bool = False
    es_propina: bool = False
    sin_desglose_iva: bool = False
    legible: bool = False
    pais_emisor: Optional[str] = None


@dataclass
class CardMetadata:
    """Metadatos de tarjeta desde el Sheet de control (solicitante y centro de costo)."""

    card: str
    solicitante: str
    centro_costo: str


@dataclass
class ProviderHistory:
    """Registro histórico de un proveedor para detalle y artículo contable."""

    nit: str
    razon_social: str = ""
    detalle_gasto: str = ""
    articulo_contable: str = ""
    fecha_ultima: str = ""
    archivo_origen: str = ""


@dataclass
class MatchResult:
    """Resultado de conciliar un movimiento con cero o más facturas.

    ``status``: OK | UNMATCHED | AMBIGUOUS | GMF.
    ``match_kind``: simple | compound | multi_factura | consolidated |
    consolidated_review | provider_date_review.
    """

    transaction: Transaction
    invoice: Optional[InvoiceData]
    status: str
    documento_soporte: str
    failure_reason: str = ""
    secondary_invoice: Optional[InvoiceData] = None
    match_kind: str = "simple"
    observacion: str = ""
    needs_review: bool = False
    suggested_invoice: Optional[InvoiceData] = None
    ambiguous_candidates: list[InvoiceData] = field(default_factory=list)
    component_invoices: list[InvoiceData] = field(default_factory=list)


@dataclass
class LegalizationRow:
    """Fila del Excel contable de salida tras conciliar un movimiento."""

    numero_factura: str | int | None
    nit_proveedor: str
    razon_social: str
    detalle_gasto: str
    articulo_contable: str
    centro_costo: str
    moneda: str
    valor_base_cops: float
    iva: float
    valor_total_compra_cop: float
    documento_soporte: str
    valor_base_usd: Optional[float] = None
    valor_base_clp: Optional[float] = None
    valor_base_sol: Optional[float] = None
    needs_review: bool = False


@dataclass
class PipelineResult:
    """Resultado agregado de una corrida de legalización para una tarjeta."""

    extract: ExtractData
    card_meta: Optional[CardMetadata] = None
    matches: list[MatchResult] = field(default_factory=list)
    legalization_rows: list[LegalizationRow] = field(default_factory=list)
    output_filename: str = ""
    output_path: str = ""
    legalization_file_link: str = ""
    warnings: list[str] = field(default_factory=list)
    new_provider_nits: list[str] = field(default_factory=list)
    facturas_peru_sin_ruc: list[dict] = field(default_factory=list)
    legalization_mode: str = "create"
    batch_label: str = ""
    appended_row_count: int = 0
    skipped_already_legalized_count: int = 0
    output_version: int = 1
    extract_selected: str = ""
    extract_file_link: str = ""
    extract_update_mode: str = ""
    extract_source_kind: str = ""
