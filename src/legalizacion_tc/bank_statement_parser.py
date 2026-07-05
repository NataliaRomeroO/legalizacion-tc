"""Parser del extracto PDF Bancolombia → ``ExtractData``.

Extrae tarjeta (``TARJETA: ****1111``), periodo (``Hasta: DD/MM/YYYY``) y transacciones
vía regex de autorizaciones y líneas GMF. Excluye abonos (montos terminados en ``-``).
PDF vacío o sin transacciones → ``ValueError``.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pypdf import PdfReader

from .date_normalizer import parse_flexible_date
from .extract_parser import (
    NUM_TO_ES,
    _infer_card_from_filename,
    _parse_original_amount,
    infer_period_from_filename,
    is_gmf_description,
)
from .models import ExtractData, Transaction

CARD_PATTERN = re.compile(r"TARJETA:\s*\*+(\d{4})", re.IGNORECASE)
PERIOD_END_PATTERN = re.compile(
    r"Hasta:\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
AMOUNT_TOKEN = r"(\d{1,3}(?:,\d{3})*\.\d{2}-?)"
AUTH_TRANSACTION = re.compile(
    rf"^(\d{{6}})\s+(\d{{2}}/\d{{2}}/\d{{4}})\s+(.+?)\s+{AMOUNT_TOKEN}\s",
    re.MULTILINE,
)
GMF_TRANSACTION = re.compile(
    rf"^(\d{{2}}/\d{{2}}/\d{{4}})\s+(GMF\s+\S+)\s+{AMOUNT_TOKEN}\s",
    re.MULTILINE,
)
TRANSACTIONS_HEADER = re.compile(
    r"N[uú]mero de\s*\n?\s*Autorizaci[oó]n",
    re.IGNORECASE,
)


def _extract_pdf_text(path: Path) -> str:
    """Concatena texto extraíble de todas las páginas del PDF."""
    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _parse_amount_token(token: str) -> float | None:
    """Parsea token de monto Bancolombia; ``None`` si vacío o abono (termina en ``-``)."""
    cleaned = token.strip()
    if not cleaned or cleaned.endswith("-"):
        return None
    return float(cleaned.replace(",", ""))


def _parse_tx_date(value: str) -> date:
    """Parsea fecha de transacción del extracto PDF."""
    return parse_flexible_date(value)


def _extract_card(text: str, filename: str) -> str:
    """Obtiene últimos 4 dígitos de tarjeta del PDF o del nombre de archivo."""
    match = CARD_PATTERN.search(text)
    if match:
        return match.group(1)
    return _infer_card_from_filename(filename)


def _extract_period(text: str, filename: str) -> tuple[str, int]:
    """Deriva mes/año del encabezado ``Hasta:`` o del nombre de archivo."""
    match = PERIOD_END_PATTERN.search(text)
    if match:
        end_date = _parse_tx_date(match.group(1))
        return NUM_TO_ES[end_date.month], end_date.year
    month, year, _ = infer_period_from_filename(filename)
    return month, year


def _transaction_section(text: str) -> str:
    """Recorta texto desde el encabezado de transacciones; retorna texto completo si no hay match."""
    match = TRANSACTIONS_HEADER.search(text)
    if match:
        return text[match.end() :]
    return text


def _iter_bancolombia_transactions(section: str) -> list[tuple[date, str, float]]:
    """Extrae filas GMF y de autorización; excluye abonos y montos ≤ 0."""
    rows: list[tuple[date, str, float]] = []

    for match in GMF_TRANSACTION.finditer(section):
        amount = _parse_amount_token(match.group(3))
        if amount is None or amount <= 0:
            continue
        rows.append(
            (
                _parse_tx_date(match.group(1)),
                match.group(2).strip(),
                amount,
            )
        )

    for match in AUTH_TRANSACTION.finditer(section):
        amount = _parse_amount_token(match.group(4))
        if amount is None or amount <= 0:
            continue
        description = match.group(3).strip()
        rows.append(
            (
                _parse_tx_date(match.group(2)),
                description,
                amount,
            )
        )

    rows.sort(key=lambda item: (item[0], item[1]))
    return rows


def parse_bancolombia_statement(path: Path) -> ExtractData:
    """Parsea extracto PDF Bancolombia a ``ExtractData``.

    PDF vacío o sin transacciones lanza ``ValueError``.
    """
    text = _extract_pdf_text(path)
    if not text.strip():
        raise ValueError(f"PDF sin texto extraíble: {path}")

    card = _extract_card(text, path.name)
    period_month, period_year = _extract_period(text, path.name)
    section = _transaction_section(text)
    parsed_rows = _iter_bancolombia_transactions(section)
    if not parsed_rows:
        raise ValueError(
            f"No se encontraron movimientos en el extracto Bancolombia: {path.name}"
        )

    transactions: list[Transaction] = []
    for row_idx, (tx_date, description, amount_cop) in enumerate(parsed_rows, start=2):
        amount_original, original_currency = _parse_original_amount(description)
        currency = original_currency or "COP"
        transactions.append(
            Transaction(
                card=card,
                tx_date=tx_date,
                description=description,
                currency=currency,
                amount_cop=amount_cop,
                row_index=row_idx,
                amount_original=amount_original,
                original_currency=original_currency,
                is_gmf=is_gmf_description(description),
            )
        )

    total_cop = sum(tx.amount_cop for tx in transactions)
    return ExtractData(
        card=card,
        period_month=period_month,
        period_year=period_year,
        transactions=transactions,
        total_cop=total_cop,
        source_filename=path.name,
    )
