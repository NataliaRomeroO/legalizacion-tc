"""Conversión de moneda extranjera a COP vía API Frankfurter (fecha del movimiento).

- COP: retorno directo sin llamada HTTP.
- SOL se aliasa a PEN (ISO 4217).
- Fallos de red/HTTP propagan excepción; la conciliación los trata como no-match.
"""

from __future__ import annotations

from datetime import date

import httpx

from .config import Settings

ISO_CURRENCY_ALIASES = {"SOL": "PEN"}


def convert_to_cop(
    settings: Settings,
    amount: float,
    currency: str,
    on_date: date,
) -> float:
    """Convierte monto a COP usando Frankfurter en la fecha del movimiento.

    COP retorna el monto sin HTTP; SOL se aliasa a PEN. Errores de red/HTTP propagan excepción.
    """
    currency = currency.upper()
    if currency == "COP":
        return amount
    currency = ISO_CURRENCY_ALIASES.get(currency, currency)

    url = f"{settings.frankfurter_base_url.rstrip('/')}/rate/{currency}/COP"
    params = {"date": on_date.isoformat()}
    response = httpx.get(
        url, params=params, timeout=30.0, verify=settings.fx_ssl_verify
    )
    response.raise_for_status()
    data = response.json()
    return amount * float(data["rate"])
