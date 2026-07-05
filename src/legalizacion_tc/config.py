"""Configuración central del pipeline: rutas de caché y parámetros de negocio.

Lee variables desde ``.env`` vía ``load_settings()``. Los tolerancias de conciliación
(2 % COP, 12 % SOL, ±3 días de fecha) y reglas de IVA/restaurantes se definen aquí.

Casos relevantes:
- ``invoices_cache_dir(card)`` / ``downloads_cache_dir(card)``: layout por tarjeta
  bajo ``.cache/cards/{tarjeta}/``; sin ``card`` usa rutas legacy planas.
- ``amount_tolerance_pct_sol`` mayor que COP por ruido FX en soles peruanos.
- ``restaurant_no_iva_keywords``: gastos de representación sin split de IVA 19 %.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def repo_root() -> Path:
    """Raíz del repositorio (dos niveles arriba de este módulo)."""
    return Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    """Directorio raíz de caché (``.cache``); lo crea si no existe."""
    path = repo_root() / ".cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def invoices_cache_dir(card: str | None = None) -> Path:
    """Caché de JSON de facturas; con ``card`` usa layout por tarjeta."""
    if card:
        path = cache_dir() / "cards" / card / "invoices"
    else:
        path = cache_dir() / "invoices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def downloads_cache_dir(card: str | None = None) -> Path:
    """Caché de archivos descargados de Drive; con ``card`` usa subcarpeta por tarjeta."""
    if card:
        path = cache_dir() / "cards" / card / "downloads"
    else:
        path = cache_dir() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_cache_dir(card: str | None = None) -> Path:
    """Caché de salidas del pipeline (Excel legalizado); opcionalmente por tarjeta."""
    if card:
        path = cache_dir() / "output" / card
    else:
        path = cache_dir() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class Settings:
    """Parámetros inmutables del pipeline cargados desde el entorno."""

    gcp_project_id: str
    service_account_email: str
    plantilla_drive_file_id: str
    control_sheet_id: str
    control_sheet_tab_tarjetas: str
    control_sheet_tab_historico: str
    historico_drive_folder_id: str
    frankfurter_base_url: str
    amount_tolerance_pct: float
    amount_tolerance_pct_sol: float
    date_tolerance_days: int
    consolidated_receipt_max_days_after: int
    consolidated_receipt_review_max_months: int
    consolidated_max_group_size: int
    iva_rate_cop: float
    restaurant_no_iva_keywords: tuple[str, ...]
    timezone: str
    solicitud_para: str = "Empresa Demo S.A.S"
    articulo_propina: str = ""
    fx_ssl_verify: bool = True


def _env_bool(name: str, default: bool) -> bool:
    """Interpreta variable de entorno como booleano (``1``, ``true``, ``yes``, ``on``)."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _parse_keyword_list(raw: str | None, default: str) -> tuple[str, ...]:
    """Convierte lista CSV de palabras clave a tupla en mayúsculas; omite entradas vacías."""
    value = raw if raw is not None else default
    return tuple(
        part.strip().upper()
        for part in value.split(",")
        if part.strip()
    )


def load_settings() -> Settings:
    """Carga ``.env`` desde la raíz del repo y devuelve ``Settings`` con defaults seguros."""
    load_dotenv(repo_root() / ".env")
    return Settings(
        gcp_project_id=os.getenv("GCP_PROJECT_ID", ""),
        service_account_email=os.getenv(
            "SERVICE_ACCOUNT_EMAIL",
            "",
        ),
        plantilla_drive_file_id=os.getenv("PLANTILLA_DRIVE_FILE_ID", ""),
        control_sheet_id=os.getenv(
            "CONTROL_SHEET_ID",
            "",
        ),
        control_sheet_tab_tarjetas=os.getenv("CONTROL_SHEET_TAB_TARJETAS", "Tarjetas"),
        control_sheet_tab_historico=os.getenv(
            "CONTROL_SHEET_TAB_HISTORICO", "historico_proveedores"
        ),
        historico_drive_folder_id=os.getenv("HISTORICO_DRIVE_FOLDER_ID", ""),
        frankfurter_base_url=os.getenv(
            "FRANKFURTER_BASE_URL", "https://api.frankfurter.dev/v2"
        ),
        amount_tolerance_pct=float(os.getenv("AMOUNT_TOLERANCE_PCT", "0.02")),
        amount_tolerance_pct_sol=float(os.getenv("AMOUNT_TOLERANCE_PCT_SOL", "0.12")),
        date_tolerance_days=int(os.getenv("DATE_TOLERANCE_DAYS", "3")),
        consolidated_receipt_max_days_after=int(
            os.getenv("CONSOLIDATED_RECEIPT_MAX_DAYS_AFTER", "30")
        ),
        consolidated_receipt_review_max_months=int(
            os.getenv("CONSOLIDATED_RECEIPT_REVIEW_MAX_MONTHS", "3")
        ),
        consolidated_max_group_size=int(os.getenv("CONSOLIDATED_MAX_GROUP_SIZE", "6")),
        iva_rate_cop=float(os.getenv("IVA_RATE_COP", "0.19")),
        restaurant_no_iva_keywords=_parse_keyword_list(
            os.getenv("RESTAURANT_NO_IVA_KEYWORDS"),
            "RESTAURANTE,ALMUERZO,CENA,COMIDA,GASTO DE REPRESENTACION",
        ),
        timezone=os.getenv("TZ", "America/Bogota"),
        articulo_propina=os.getenv(
            "ARTICULO_PROPINA", "0000000000 - GASTOS NO DEDUCIBLES"
        ),
        fx_ssl_verify=_env_bool("FX_SSL_VERIFY", True),
    )
