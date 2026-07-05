"""Resuelve carpeta Drive/local en contextos por tarjeta (``CardFolderContext``).

Layouts:
- **Carpeta padre del mes**: subcarpetas ``{4dígitos} - {Titular}`` → una TC cada una.
- **Carpeta plana de una TC**: un solo contexto; tarjeta inferida del nombre.
- Preliminar suelto en raíz del padre se ignora si hay subcarpetas.
- ``--card`` filtra a una subcarpeta específica.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .drive_manager import (
    LOCAL_FOLDER_MIME,
    is_drive_folder,
    list_folder_children,
    list_local_children,
    validate_folder_access,
)

CARD_SUBFOLDER_PATTERN = re.compile(r"^(\d{4})\s*-\s*.+", re.IGNORECASE)
CARD_IN_NAME_PATTERN = re.compile(r"(\d{4})")


@dataclass(frozen=True)
class CardFolderContext:
    """Contexto de procesamiento para una tarjeta en Drive o carpeta local."""

    card: str | None
    folder_id: str | None
    local_path: Path | None
    display_name: str


def parse_card_subfolder_name(name: str) -> str | None:
    """Extrae los 4 dígitos de tarjeta de nombres ``{tarjeta} - {titular}``."""
    match = CARD_SUBFOLDER_PATTERN.match(name.strip())
    return match.group(1) if match else None


def infer_card_from_name(name: str) -> str | None:
    """Infiere el número de tarjeta buscando la primera secuencia de 4 dígitos."""
    match = CARD_IN_NAME_PATTERN.search(name)
    return match.group(1) if match else None


def _card_subfolders(children: list) -> list:
    """Filtra entradas hijas que son subcarpetas con patrón de tarjeta."""
    return [
        entry
        for entry in children
        if getattr(entry, "is_folder", False) and parse_card_subfolder_name(entry.name)
    ]


def _build_contexts_from_subfolders(
    subfolders: list,
    *,
    card_filter: str | None,
) -> list[CardFolderContext]:
    """Construye contextos por subcarpeta y aplica filtro opcional ``--card``."""
    contexts: list[CardFolderContext] = []
    for entry in subfolders:
        card = parse_card_subfolder_name(entry.name)
        if card is None:
            continue
        if entry.mime_type == LOCAL_FOLDER_MIME:
            contexts.append(
                CardFolderContext(
                    card=card,
                    folder_id=None,
                    local_path=Path(entry.file_id),
                    display_name=entry.name,
                )
            )
        elif is_drive_folder(entry):
            contexts.append(
                CardFolderContext(
                    card=card,
                    folder_id=entry.file_id,
                    local_path=None,
                    display_name=entry.name,
                )
            )

    if card_filter:
        contexts = [ctx for ctx in contexts if ctx.card == card_filter]

    if card_filter and not contexts:
        raise ValueError(f"No se encontró subcarpeta para la tarjeta {card_filter}")

    return sorted(contexts, key=lambda ctx: ctx.card or "")


def resolve_card_folders_local(
    local_folder: Path,
    *,
    card_filter: str | None = None,
) -> list[CardFolderContext]:
    """Resuelve contextos de tarjeta desde una carpeta local (padre o plana)."""
    local_folder = local_folder.resolve()
    if not local_folder.is_dir():
        raise FileNotFoundError(f"Carpeta no encontrada: {local_folder}")

    children = list_local_children(local_folder)
    card_subfolders = _card_subfolders(children)

    if card_subfolders:
        return _build_contexts_from_subfolders(card_subfolders, card_filter=card_filter)

    card = infer_card_from_name(local_folder.name)
    return [
        CardFolderContext(
            card=card,
            folder_id=None,
            local_path=local_folder,
            display_name=local_folder.name,
        )
    ]


def resolve_card_folders_drive(
    folder_id: str,
    *,
    card_filter: str | None = None,
) -> list[CardFolderContext]:
    """Resuelve contextos de tarjeta desde una carpeta de Google Drive."""
    folder_name = validate_folder_access(folder_id)
    children = list_folder_children(folder_id)
    card_subfolders = _card_subfolders(children)

    if card_subfolders:
        return _build_contexts_from_subfolders(card_subfolders, card_filter=card_filter)

    card = infer_card_from_name(folder_name) if folder_name else None
    return [
        CardFolderContext(
            card=card,
            folder_id=folder_id,
            local_path=None,
            display_name=folder_name or folder_id,
        )
    ]


def resolve_card_folders(
    *,
    folder_id: str | None = None,
    local_folder: Path | None = None,
    card_filter: str | None = None,
) -> list[CardFolderContext]:
    """Punto de entrada: delega en Drive o local según los argumentos recibidos."""
    if local_folder is not None:
        return resolve_card_folders_local(local_folder, card_filter=card_filter)
    if folder_id:
        return resolve_card_folders_drive(folder_id, card_filter=card_filter)
    raise ValueError("Debe indicar folder_id o local_folder")
