"""Normalización de NIT colombiano / RUC peruano e indexación del histórico de proveedores.

Casos de normalización:
- NIT con guión: se toma solo la parte base antes del dígito de verificación.
- NIT jurídico colombiano (10 dígitos, empieza en 8 o 9): se trunca a 9 dígitos.
- RUC peruano: 11 dígitos numéricos (``is_peruvian_ruc``).
- ``index_historico``: indexa por NIT crudo, NIT normalizado y razón social en minúsculas.
"""

from __future__ import annotations

import re

from .models import ProviderHistory


def normalize_nit_key(nit: str | None) -> str:
    """Devuelve clave canónica de NIT/RUC para lookup en histórico."""
    if not nit:
        return ""
    cleaned = re.sub(r"[.\s]", "", nit.strip())
    if "-" in cleaned:
        base = cleaned.split("-", 1)[0]
        return re.sub(r"\D", "", base)
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) == 10 and digits[0] in ("8", "9"):
        return digits[:9]
    return digits


def is_peruvian_ruc(value: str | None) -> bool:
    """Indica si el valor es un RUC peruano válido (11 dígitos numéricos)."""
    if not value:
        return False
    digits = re.sub(r"\D", "", value.strip())
    return len(digits) == 11 and digits.isdigit()


def index_historico(raw: dict[str, ProviderHistory]) -> dict[str, ProviderHistory]:
    """Indexa histórico por NIT crudo, NIT normalizado y razón social en minúsculas."""
    indexed: dict[str, ProviderHistory] = {}
    for key, history in raw.items():
        if key and key not in indexed:
            indexed[key] = history
        nit = (history.nit or key or "").strip()
        if nit and nit not in indexed:
            indexed[nit] = history
        normalized = normalize_nit_key(nit)
        if normalized and normalized not in indexed:
            indexed[normalized] = history
        razon_key = history.razon_social.strip().lower()
        if razon_key and razon_key not in indexed:
            indexed[razon_key] = history
    return indexed
