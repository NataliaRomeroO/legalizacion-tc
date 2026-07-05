"""I/O con Google Drive y clasificación de archivos en carpetas de tarjeta.

``DriveFile``: descriptor unificado; en modo local ``file_id`` es la ruta absoluta.
Funciones clave:
- ``list_extract_files`` / ``list_statement_files`` / ``list_invoice_files``.
- ``find_base_legalization_file``: prioridad manual legacy ``MAYO- 2026`` > versionado.
- PDFs de extracto excluidos de la lista de facturas (``STATEMENT_PATTERN``).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from .config import downloads_cache_dir
from .google_auth import drive_service

EXTRACT_PATTERN = re.compile(r"^Mov[\s._-]*TC", re.IGNORECASE)
LEGALIZATION_PATTERN = re.compile(r"^Formato de Legalizaci", re.IGNORECASE)
INVOICE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
STATEMENT_PATTERN = re.compile(r"^\d{4}_[A-Z]{3}\d{4}\.pdf$", re.IGNORECASE)


DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
LOCAL_FOLDER_MIME = "inode/directory"


@dataclass
class DriveFile:
    """Descriptor unificado de archivo o carpeta en Drive o en disco local."""

    file_id: str
    name: str
    mime_type: str
    is_folder: bool = False
    modified_time: float | None = None


def parse_folder_id_from_url(url_or_id: str) -> str:
    """Extrae el ID de carpeta desde una URL de Drive o devuelve el texto tal cual."""
    text = url_or_id.strip()
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", text)
    if match:
        return match.group(1)
    match = re.search(r"id=([a-zA-Z0-9_-]+)", text)
    if match:
        return match.group(1)
    return text


def validate_folder_access(folder_id: str) -> str:
    """Verifica acceso a la carpeta y devuelve su nombre visible en Drive."""
    meta = drive_service().files().get(fileId=folder_id, fields="id,name", supportsAllDrives=True).execute()
    return meta.get("name", "")


def is_drive_folder(entry: DriveFile) -> bool:
    """Indica si la entrada corresponde a una carpeta en Google Drive."""
    return entry.mime_type == DRIVE_FOLDER_MIME


def list_folder_children(folder_id: str) -> list[DriveFile]:
    """Lista archivos y subcarpetas directos de una carpeta Drive (paginado)."""
    service = drive_service()
    results: list[DriveFile] = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for item in response.get("files", []):
            mime_type = item.get("mimeType", "")
            is_folder = mime_type == DRIVE_FOLDER_MIME
            modified_raw = item.get("modifiedTime")
            modified_time = None
            if modified_raw:
                from datetime import datetime

                modified_time = datetime.fromisoformat(
                    modified_raw.replace("Z", "+00:00")
                ).timestamp()
            results.append(
                DriveFile(
                    file_id=item["id"],
                    name=item["name"],
                    mime_type=mime_type,
                    is_folder=is_folder,
                    modified_time=modified_time,
                )
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return results


def list_folder_files(folder_id: str) -> list[DriveFile]:
    """Lista solo archivos (sin subcarpetas) dentro de una carpeta Drive."""
    return [entry for entry in list_folder_children(folder_id) if not is_drive_folder(entry)]


def download_file(file_id: str, dest: Path) -> Path:
    """Descarga un archivo de Drive al path local indicado."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = drive_service().files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    dest.write_bytes(buffer.getvalue())
    return dest


def download_to_cache(
    file_id: str, filename: str, card: str | None = None
) -> Path:
    """Descarga a ``.cache`` bajo la subcarpeta de downloads de la tarjeta."""
    dest = downloads_cache_dir(card) / filename
    return download_file(file_id, dest)


def update_file(file_id: str, local_path: Path) -> str:
    """Sobrescribe un Excel existente en Drive con el archivo local."""
    media = MediaFileUpload(
        str(local_path),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=True,
    )
    updated = (
        drive_service()
        .files()
        .update(fileId=file_id, media_body=media, fields="id", supportsAllDrives=True)
        .execute()
    )
    return updated["id"]


def upload_file(local_path: Path, folder_id: str, filename: Optional[str] = None) -> str:
    """Sube un Excel nuevo a la carpeta Drive indicada y devuelve su file_id."""
    name = filename or local_path.name
    media = MediaFileUpload(
        str(local_path),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        resumable=True,
    )
    metadata = {"name": name, "parents": [folder_id]}
    created = (
        drive_service()
        .files()
        .create(body=metadata, media_body=media, fields="id", supportsAllDrives=True)
        .execute()
    )
    return created["id"]


def copy_drive_file(source_file_id: str, dest_name: str, folder_id: str) -> str:
    """Copia un archivo en Drive con nuevo nombre dentro de la carpeta destino."""
    body = {"name": dest_name, "parents": [folder_id]}
    copied = (
        drive_service()
        .files()
        .copy(fileId=source_file_id, body=body, fields="id", supportsAllDrives=True)
        .execute()
    )
    return copied["id"]


def list_extract_files(files: list[DriveFile]) -> list[DriveFile]:
    """Filtra preliminares Excel cuyo nombre coincide con ``Mov TC*``."""
    return [
        f
        for f in files
        if f.name.lower().endswith((".xlsx", ".xlsm"))
        and EXTRACT_PATTERN.search(f.name)
    ]


def list_statement_files(files: list[DriveFile]) -> list[DriveFile]:
    """Filtra PDFs de extracto Bancolombia con patrón ``{tarjeta}_{MES}{año}.pdf``."""
    return [
        f
        for f in files
        if f.name.lower().endswith(".pdf")
        and STATEMENT_PATTERN.match(f.name)
    ]


def find_extract_file(files: list[DriveFile]) -> Optional[DriveFile]:
    """Devuelve el primer preliminar Excel encontrado en la lista, si existe."""
    extracts = list_extract_files(files)
    return extracts[0] if extracts else None


# Manual reference: "MAYO- 2026" (no space before hyphen). Generated: "MAYO - 2026".
_MANUAL_LEGACY_NAME = re.compile(
    r"Formato de Legalizaci[oó]n TC \d{4} - [A-Za-zÁÉÍÓÚÑáéíóúñ]+-\s*\d{4}",
    re.IGNORECASE,
)
_VERSIONED_NAME = re.compile(
    r"Formato de Legalizaci[oó]n TC \d{4} - \d{1,2} - ",
    re.IGNORECASE,
)


def list_legalization_files(files: list[DriveFile], card: str) -> list[DriveFile]:
    """Lista Formatos de legalización de la tarjeta, excluyendo plantillas."""
    candidates = [
        f
        for f in files
        if LEGALIZATION_PATTERN.search(f.name)
        and card in f.name
        and "Plantilla" not in f.name
    ]
    return sorted(candidates, key=lambda f: f.modified_time or 0.0, reverse=True)


def find_base_legalization_file(
    files: list[DriveFile],
    card: str,
    *,
    exclude_name: str | None = None,
) -> Optional[DriveFile]:
    """Elige el Excel base para copiar una nueva versión del Formato.

    Prioridad: legacy manual (MAYO- 2026) > versionado más reciente > otro legacy.
    """
    candidates = [
        f
        for f in list_legalization_files(files, card)
        if exclude_name is None or f.name != exclude_name
    ]
    if not candidates:
        return None

    manual = [f for f in candidates if _MANUAL_LEGACY_NAME.search(f.name)]
    if manual:
        return max(manual, key=lambda f: f.modified_time or 0.0)

    versioned = [f for f in candidates if _VERSIONED_NAME.search(f.name)]
    if versioned:
        return max(versioned, key=lambda f: f.modified_time or 0.0)

    return max(candidates, key=lambda f: f.modified_time or 0.0)


def find_legalization_file(
    files: list[DriveFile],
    card: str,
    preferred_name: str | None = None,
) -> Optional[DriveFile]:
    """Localiza un Formato existente; prioriza coincidencia exacta de nombre."""
    candidates = list_legalization_files(files, card)
    if not candidates:
        return None
    if preferred_name:
        exact = [f for f in candidates if f.name == preferred_name]
        if exact:
            return exact[0]
    return candidates[0]


def list_invoice_files(files: list[DriveFile]) -> list[DriveFile]:
    """Lista imágenes/PDF de soporte excluyendo extractos bancarios."""
    invoices: list[DriveFile] = []
    for f in files:
        suffix = Path(f.name).suffix.lower()
        if suffix not in INVOICE_EXTENSIONS:
            continue
        if STATEMENT_PATTERN.match(f.name):
            continue
        invoices.append(f)
    return invoices


def list_local_children(folder: Path) -> list[DriveFile]:
    """Emula ``list_folder_children`` leyendo un directorio del disco local."""
    results: list[DriveFile] = []
    for path in sorted(folder.iterdir()):
        if path.is_file():
            mtime = path.stat().st_mtime
            results.append(
                DriveFile(
                    file_id=str(path),
                    name=path.name,
                    mime_type="",
                    is_folder=False,
                    modified_time=mtime,
                )
            )
        elif path.is_dir():
            results.append(
                DriveFile(
                    file_id=str(path),
                    name=path.name,
                    mime_type=LOCAL_FOLDER_MIME,
                    is_folder=True,
                )
            )
    return results


def list_local_folder(folder: Path) -> list[DriveFile]:
    """Lista solo archivos (sin subcarpetas) de un directorio local."""
    return [entry for entry in list_local_children(folder) if not entry.is_folder]


def folder_link(folder_id: str) -> str:
    """URL pública de navegación a una carpeta de Google Drive."""
    return f"https://drive.google.com/drive/folders/{folder_id}"


def file_link(file_id: str) -> str:
    """URL pública de visualización de un archivo en Google Drive."""
    return f"https://drive.google.com/file/d/{file_id}/view"
