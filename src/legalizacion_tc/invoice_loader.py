"""Carga y validación de JSON de facturas en ``.cache/cards/{tarjeta}/invoices/``.

- ``InvoiceJsonSchema`` (Pydantic): rechaza campos COP prohibidos (``valor_cop``, etc.).
- ``incomplete_invoice_json``: plantilla sin ``legible``, fecha o valor total.
- ``missing_invoice_json``: PDF en Drive sin JSON correspondiente.
- Infiere ``es_propina``, ``pais_emisor`` (SOL→PE, COP→CO) y normaliza RUC peruano.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, field_validator

from .config import invoices_cache_dir
from .models import InvoiceData
from .nit_utils import is_peruvian_ruc

_PERU_RUC_PREFIXES = ("10", "15", "17", "20")


class InvoiceJsonSchema(BaseModel):
    """Esquema Pydantic del JSON de factura en caché; sin montos COP prohibidos."""

    source_filename: str
    numero_factura: str | None = None
    nit_proveedor: str | None = None
    razon_social: str | None = None
    nombre_comercial: str | None = None
    moneda: str | None = None
    valor_base: float | None = None
    iva: float = 0.0
    otros_impuestos: float = 0.0
    valor_total_documento: float | None = None
    fecha_factura: str | None = None
    detalle_gasto: str | None = None
    tipo_documento: str | None = None
    consolidado: bool = False
    es_propina: bool = False
    sin_desglose_iva: bool = False
    legible: bool = False
    pais_emisor: str | None = None

    @field_validator("moneda")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        """Normaliza código de moneda a mayúsculas."""
        if value is None:
            return None
        return value.strip().upper()

    @field_validator("pais_emisor")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        """Normaliza código de país emisor a mayúsculas."""
        if value is None:
            return None
        return value.strip().upper()


def _parse_invoice_date(value: str | None) -> date | None:
    """Parsea fecha ISO ``YYYY-MM-DD``; ``None`` si el valor está vacío."""
    if not value:
        return None
    return date.fromisoformat(value)


def _infer_es_propina(parsed: InvoiceJsonSchema) -> bool:
    """Detecta propina por la palabra PROPINA en ``detalle_gasto``."""
    detalle = (parsed.detalle_gasto or "").upper()
    return "PROPINA" in detalle


def _infer_pais_emisor(parsed: InvoiceJsonSchema) -> str | None:
    """Infiere país emisor (PE/CO) desde campo explícito o moneda SOL/COP si legible."""
    if parsed.pais_emisor:
        return parsed.pais_emisor
    moneda = (parsed.moneda or "").upper()
    if moneda == "SOL" and parsed.legible:
        return "PE"
    if moneda == "COP" and parsed.legible:
        return "CO"
    return None


def _normalize_provider_tax_id(value: str | None, pais: str | None) -> str | None:
    """Deja solo dígitos del NIT/RUC; retorna ``None`` si queda vacío."""
    if not value:
        return None
    cleaned = re.sub(r"\D", "", value.strip())
    if not cleaned:
        return None
    if (pais or "").upper() == "PE":
        return cleaned
    return cleaned


def _ruc_format_valid(value: str | None) -> bool:
    """Valida prefijo de RUC peruano (10, 15, 17 o 20) además de longitud 11."""
    if not value or not is_peruvian_ruc(value):
        return False
    digits = re.sub(r"\D", "", value)
    return digits[:2] in _PERU_RUC_PREFIXES


def load_invoice_json(path: Path) -> InvoiceData:
    """Carga y valida JSON de factura; rechaza campos COP legacy y enriquece metadatos."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    forbidden = {"valor_cop", "valor_total_cop", "valor_total"}
    if forbidden.intersection(raw.keys()):
        raise ValueError(
            f"JSON inválido {path.name}: no incluir montos COP ni campo valor_total legacy"
        )
    parsed = InvoiceJsonSchema.model_validate(raw)
    es_propina = parsed.es_propina or _infer_es_propina(parsed)
    pais_emisor = _infer_pais_emisor(parsed)
    nit = _normalize_provider_tax_id(parsed.nit_proveedor, pais_emisor)
    return InvoiceData(
        source_filename=parsed.source_filename,
        numero_factura=parsed.numero_factura,
        nit_proveedor=nit,
        razon_social=parsed.razon_social,
        nombre_comercial=parsed.nombre_comercial,
        moneda=parsed.moneda,
        valor_base=parsed.valor_base,
        iva=parsed.iva,
        otros_impuestos=parsed.otros_impuestos,
        valor_total_documento=parsed.valor_total_documento,
        fecha_factura=_parse_invoice_date(parsed.fecha_factura),
        detalle_gasto=parsed.detalle_gasto,
        tipo_documento=parsed.tipo_documento,
        consolidado=parsed.consolidado,
        es_propina=es_propina,
        sin_desglose_iva=parsed.sin_desglose_iva,
        legible=parsed.legible,
        pais_emisor=pais_emisor,
    )


def load_invoices_from_cache(
    expected_filenames: Iterable[str] | None = None,
    card: str | None = None,
) -> list[InvoiceData]:
    """Carga JSON de ``.cache/cards/{card}/invoices/``; filtra por stems esperados si se indica."""
    cache = invoices_cache_dir(card)
    invoices: list[InvoiceData] = []
    expected_stems = {Path(name).stem for name in (expected_filenames or [])}
    for path in sorted(cache.glob("*.json")):
        if expected_stems and path.stem not in expected_stems:
            continue
        invoices.append(load_invoice_json(path))
    return invoices


def is_incomplete_invoice(invoice: InvoiceData) -> bool:
    """True si falta legibilidad, fecha de factura o valor total del documento."""
    if not invoice.legible:
        return True
    if invoice.fecha_factura is None:
        return True
    if invoice.valor_total_documento is None:
        return True
    return False


def incomplete_invoice_json(
    invoice_filenames: Iterable[str], card: str | None = None
) -> list[str]:
    """Lista PDFs cuyo JSON existe pero está incompleto según ``is_incomplete_invoice``."""
    cache = invoices_cache_dir(card)
    incomplete: list[str] = []
    for name in invoice_filenames:
        stem = Path(name).stem
        json_path = cache / f"{stem}.json"
        if not json_path.exists():
            continue
        invoice = load_invoice_json(json_path)
        if is_incomplete_invoice(invoice):
            incomplete.append(name)
    return incomplete


def missing_invoice_json(
    invoice_filenames: Iterable[str], card: str | None = None
) -> list[str]:
    """Lista PDFs en Drive sin JSON correspondiente en caché."""
    cache = invoices_cache_dir(card)
    missing: list[str] = []
    for name in invoice_filenames:
        stem = Path(name).stem
        json_path = cache / f"{stem}.json"
        if not json_path.exists():
            json_path_alt = cache / name
            if not json_path_alt.exists() and not (cache / f"{name}.json").exists():
                missing.append(name)
    return missing


def save_invoice_json_template(filename: str, card: str | None = None) -> Path:
    """Crea plantilla JSON vacía para extracción manual de una factura."""
    path = invoices_cache_dir(card) / f"{Path(filename).stem}.json"
    template = {
        "source_filename": filename,
        "numero_factura": None,
        "nit_proveedor": None,
        "razon_social": None,
        "moneda": None,
        "valor_base": None,
        "iva": 0.0,
        "otros_impuestos": 0.0,
        "valor_total_documento": None,
        "fecha_factura": None,
        "detalle_gasto": None,
        "tipo_documento": None,
        "consolidado": False,
        "es_propina": False,
        "sin_desglose_iva": False,
        "legible": False,
        "pais_emisor": None,
    }
    path.write_text(json.dumps(template, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
