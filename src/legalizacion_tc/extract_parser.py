"""Parser del preliminar Excel ``Mov TC*.xlsx`` → ``ExtractData``.

Detecta automáticamente layout de columnas (4+ variantes: LOR, PLAZO, TC/Fecha, solo COP).
Extrae tarjeta del nombre de archivo si falta columna; periodo del filename o mayoría de fechas.
GMF vía ``4X1000`` o ``GMF`` en descripción; montos cero se omiten.
``row_index`` = fila Excel (idx+2) para write-back de Validación/Observaciones.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from .date_normalizer import parse_flexible_date
from .models import ExtractData, Transaction

FOUR_X1000 = "4X1000"
ORIGINAL_AMOUNT_PATTERN = re.compile(
    r"VR MONEDA ORIG\s+([\d.]+)\s*(US|USD|EU|EUR|GB|GBP)?",
    re.IGNORECASE,
)
ORIGINAL_CURRENCY_SUFFIX = {
    "US": "USD",
    "USD": "USD",
    "EU": "EUR",
    "EUR": "EUR",
    "GB": "GBP",
    "GBP": "GBP",
}
MONTHS_ES = {
    "enero": "ENERO",
    "febrero": "FEBRERO",
    "marzo": "MARZO",
    "abril": "ABRIL",
    "mayo": "MAYO",
    "junio": "JUNIO",
    "julio": "JULIO",
    "agosto": "AGOSTO",
    "septiembre": "SEPTIEMBRE",
    "octubre": "OCTUBRE",
    "noviembre": "NOVIEMBRE",
    "diciembre": "DICIEMBRE",
}
NUM_TO_ES = {
    1: "ENERO",
    2: "FEBRERO",
    3: "MARZO",
    4: "ABRIL",
    5: "MAYO",
    6: "JUNIO",
    7: "JULIO",
    8: "AGOSTO",
    9: "SEPTIEMBRE",
    10: "OCTUBRE",
    11: "NOVIEMBRE",
    12: "DICIEMBRE",
}


def _clean_card(value: object) -> str:
    """Normaliza número de tarjeta quitando asteriscos iniciales."""
    text = str(value).strip()
    return text.lstrip("*")


def _parse_date(value: object) -> date:
    """Delega parseo de fecha al normalizador flexible."""
    return parse_flexible_date(value)


def _parse_original_amount(description: str) -> tuple[float | None, str | None]:
    """Extrae monto y moneda original del patrón ``VR MONEDA ORIG`` en la descripción."""
    match = ORIGINAL_AMOUNT_PATTERN.search(description)
    if not match:
        return None, None
    amount = float(match.group(1))
    suffix = (match.group(2) or "US").upper()
    return amount, ORIGINAL_CURRENCY_SUFFIX.get(suffix, suffix)


def _parse_amount(value: object) -> float:
    """Convierte celda de monto a float; NaN o vacío retorna 0.0."""
    if pd.isna(value):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    return float(text)


def is_gmf_description(description: str) -> bool:
    """Detecta movimientos GMF por ``4X1000`` o la palabra ``GMF`` en la descripción."""
    upper = description.upper()
    return FOUR_X1000 in upper or "GMF" in upper


def _resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    """Mapea columnas del preliminar Excel a claves lógicas (card, date, desc, etc.).

    Soporta layouts LOR, PLAZO, TC/Fecha y formato simplificado solo COP.
    """
    upper = {str(col).strip().upper(): col for col in df.columns}
    if "LOR" in upper or "NÚMERO DE PRODUCTO" in upper or "NUMERO DE PRODUCTO" in upper:
        return {
            "card": upper.get("NÚMERO DE PRODUCTO") or upper.get("NUMERO DE PRODUCTO") or df.columns[0],
            "date": upper.get("FECHA") or df.columns[1],
            "desc": upper.get("CONCEPTO") or df.columns[2],
            "currency": upper.get("MONEDA") or df.columns[3],
            "amount": upper.get("LOR") or upper.get("VALOR") or df.columns[4],
        }
    # Formato alternativo: FECHA, CONCEPTO, MONEDA, PLAZO/monto, ...
    if "PLAZO" in upper:
        return {
            "card": None,  # se infiere del nombre de archivo
            "date": upper.get("FECHA") or df.columns[0],
            "desc": upper.get("CONCEPTO") or df.columns[1],
            "currency": upper.get("MONEDA") or df.columns[2],
            "amount": upper["PLAZO"],
        }
    # Formato TC / Fecha de la transacción / Descripción / Valor
    if "TC" in upper and any(k.startswith("FECHA") for k in upper):
        fecha_col = next(upper[k] for k in upper if k.startswith("FECHA"))
        desc_col = upper.get("DESCRIPCIÓN") or upper.get("DESCRIPCION") or df.columns[2]
        return {
            "card": upper["TC"],
            "date": fecha_col,
            "desc": desc_col,
            "currency": None,
            "amount": upper.get("VALOR") or df.columns[3],
        }
    # Formato simplificado COP: solo FECHA, CONCEPTO, VALOR (sin columna moneda)
    if len(df.columns) == 3 or ("VALOR" in upper and "MONEDA" not in upper):
        return {
            "card": None,  # se infiere del nombre de archivo
            "date": upper.get("FECHA") or df.columns[0],
            "desc": upper.get("CONCEPTO") or df.columns[1],
            "currency": None,  # siempre COP
            "amount": upper.get("VALOR") or df.columns[2],
        }
    return {
        "card": df.columns[0],
        "date": df.columns[1],
        "desc": df.columns[2],
        "currency": df.columns[3],
        "amount": df.columns[4],
    }


def infer_period_from_filename(filename: str) -> tuple[str, int, bool]:
    """Infiere mes y año del nombre de archivo; tercer valor indica si el mes fue default."""
    lower = filename.lower()
    month = "ENERO"
    found = False
    for key, label in MONTHS_ES.items():
        if key in lower:
            month = label
            found = True
            break
    year_match = re.search(r"(20\d{2})", filename)
    year = int(year_match.group(1)) if year_match else date.today().year
    return month, year, not found


def _infer_period_from_transactions(
    transactions: list[Transaction],
) -> tuple[str, int]:
    """Deriva mes/año del periodo por mayoría de fechas en las transacciones."""
    month_num = Counter(tx.tx_date.month for tx in transactions).most_common(1)[0][0]
    year = Counter(tx.tx_date.year for tx in transactions).most_common(1)[0][0]
    return NUM_TO_ES[month_num], year


def _infer_card_from_filename(filename: str) -> str:
    """Extrae últimos 4 dígitos de tarjeta del nombre de archivo; ``0000`` si no hay match."""
    match = re.search(r"\.?(\d{4})", filename)
    return match.group(1) if match else "0000"


def parse_extract(path: Path) -> ExtractData:
    """Parsea preliminar ``Mov TC*.xlsx`` a ``ExtractData`` con transacciones y totales.

    Omite filas sin fecha/descripción y montos cero; infiere tarjeta y periodo si faltan.
    """
    df = pd.read_excel(path, header=0)
    if df.empty:
        raise ValueError(f"Extracto vacío: {path}")

    cols = _resolve_columns(df)
    if cols["card"] is None:
        card = _infer_card_from_filename(path.name)
    else:
        card = _clean_card(df[cols["card"]].dropna().iloc[0])
    period_month, period_year, month_is_default = infer_period_from_filename(path.name)

    all_transactions: list[Transaction] = []
    for idx, row in df.iterrows():
        if pd.isna(row[cols["date"]]) or pd.isna(row[cols["desc"]]):
            continue
        description = str(row[cols["desc"]]).strip()
        amount = _parse_amount(row[cols["amount"]])
        if amount == 0:
            continue
        currency = (str(row[cols["currency"]]).strip() if not pd.isna(row[cols["currency"]]) else "COP") if cols["currency"] is not None else "COP"
        amount_original, original_currency = _parse_original_amount(description)
        if amount_original is None and currency.upper() != "COP":
            original_currency = currency.upper()
        all_transactions.append(
            Transaction(
                card=(card if cols["card"] is None or pd.isna(row[cols["card"]]) else _clean_card(row[cols["card"]])),
                tx_date=_parse_date(row[cols["date"]]),
                description=description,
                currency=currency,
                amount_cop=amount,
                row_index=int(idx) + 2,
                amount_original=amount_original,
                original_currency=original_currency,
                is_gmf=is_gmf_description(description),
            )
        )

    if month_is_default and all_transactions:
        period_month, period_year = _infer_period_from_transactions(all_transactions)

    total_cop = sum(tx.amount_cop for tx in all_transactions)
    return ExtractData(
        card=card,
        period_month=period_month,
        period_year=period_year,
        transactions=all_transactions,
        total_cop=total_cop,
        source_filename=path.name,
    )
