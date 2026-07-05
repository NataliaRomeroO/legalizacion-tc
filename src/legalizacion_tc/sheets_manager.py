"""Lectura del Sheet de control: tarjetas (solicitante, centro costo) e histórico proveedores.

Pestañas configurables vía ``Settings``: ``Tarjetas!A:C`` y
``historico_proveedores!A:F``. Números de tarjeta sin asterisco inicial.
"""

from __future__ import annotations

from typing import Optional

from .google_auth import sheets_service
from .models import CardMetadata, ProviderHistory
from .nit_utils import index_historico


def _read_sheet_values(spreadsheet_id: str, range_name: str) -> list[list[str]]:
    """Lee celdas de una pestaña del Sheet de control vía API de Google Sheets."""
    result = (
        sheets_service()
        .spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )
    return result.get("values", [])


def load_tarjetas(
    spreadsheet_id: str, tab_name: str = "Tarjetas"
) -> dict[str, CardMetadata]:
    """Carga mapeo tarjeta → solicitante y centro de costo desde la pestaña Tarjetas."""
    rows = _read_sheet_values(spreadsheet_id, f"{tab_name}!A:C")
    mapping: dict[str, CardMetadata] = {}
    for row in rows[1:]:
        if len(row) < 3:
            continue
        card = str(row[0]).strip().lstrip("*")
        mapping[card] = CardMetadata(
            card=card,
            solicitante=row[1].strip(),
            centro_costo=row[2].strip(),
        )
    return mapping


def get_card_metadata(
    spreadsheet_id: str, card: str, tab_name: str = "Tarjetas"
) -> Optional[CardMetadata]:
    """Devuelve metadatos de una tarjeta o ``None`` si no está en el Sheet."""
    return load_tarjetas(spreadsheet_id, tab_name).get(card)


def load_historico(
    spreadsheet_id: str, tab_name: str = "historico_proveedores"
) -> dict[str, ProviderHistory]:
    """Carga histórico de proveedores indexado por NIT desde el Sheet de control."""
    rows = _read_sheet_values(spreadsheet_id, f"{tab_name}!A:F")
    mapping: dict[str, ProviderHistory] = {}
    for row in rows[1:]:
        if not row:
            continue
        nit = row[0].strip()
        mapping[nit] = ProviderHistory(
            nit=nit,
            razon_social=row[1].strip() if len(row) > 1 else "",
            detalle_gasto=row[2].strip() if len(row) > 2 else "",
            articulo_contable=row[3].strip() if len(row) > 3 else "",
            fecha_ultima=row[4].strip() if len(row) > 4 else "",
            archivo_origen=row[5].strip() if len(row) > 5 else "",
        )
    return index_historico(mapping)
