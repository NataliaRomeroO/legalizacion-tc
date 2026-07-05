"""Autenticación Google API vía Application Default Credentials (cuenta de servicio).

Requiere ``GOOGLE_APPLICATION_CREDENTIALS`` apuntando al JSON de la SA.
Expone clientes Drive v3 y Sheets v4 con scopes de lectura/escritura.
"""

from googleapiclient.discovery import build
import google.auth

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _base_credentials(scopes: list[str]):
    """Obtiene credenciales ADC (cuenta de servicio) con los scopes indicados."""
    credentials, _ = google.auth.default(scopes=scopes)
    return credentials


def drive_service():
    """Cliente Drive API v3 con permisos de lectura/escritura."""
    return build(
        "drive", "v3", credentials=_base_credentials(DRIVE_SCOPES), cache_discovery=False
    )


def sheets_service():
    """Cliente Sheets API v4 con permisos de lectura/escritura."""
    return build(
        "sheets",
        "v4",
        credentials=_base_credentials(SHEETS_SCOPES),
        cache_discovery=False,
    )
