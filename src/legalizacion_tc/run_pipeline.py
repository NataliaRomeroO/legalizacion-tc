"""Orquestador end-to-end de legalización por carpeta de tarjeta (Drive o local).

Flujo por tarjeta:
1. Resolver subcarpetas (``folder_resolver``) y elegir extracto (PDF > Excel).
2. Validar JSON de facturas en caché (salvo ``--skip-invoice-extraction``).
3. Conciliar movimientos (``reconciliation_engine``) y deduplicar contra Formatos previos.
4. Mapear a filas Excel (``metadata_mapper``), generar/merge workbook y subir a Drive.
5. Actualizar columnas Validación/Observaciones del preliminar solo si origen es Excel.
6. Emitir reporte JSON en stdout para el operador / Claude Code.

Códigos de salida CLI: 0 OK, 1 error, 2 JSON faltantes, 3 tarjeta desconocida,
4 JSON incompletos (plantillas vacías).
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import load_settings, output_cache_dir, repo_root
from .drive_manager import (
    DriveFile,
    download_file,
    download_to_cache,
    file_link,
    find_base_legalization_file,
    list_extract_files,
    list_folder_files,
    list_invoice_files,
    list_legalization_files,
    list_local_folder,
    parse_folder_id_from_url,
    update_file,
    upload_file,
)
from .excel_report_builder import (
    build_legalization_workbook,
    create_minimal_template,
)
from .extract_loader import parse_movement_source
from .extract_selection import select_best_extract_file
from .extract_updater import apply_extract_review_columns
from .folder_resolver import CardFolderContext, resolve_card_folders
from .invoice_loader import (
    incomplete_invoice_json,
    load_invoices_from_cache,
    missing_invoice_json,
)
from .invoice_validation import collect_peru_ruc_issues, peru_ruc_warning_messages
from .legalization_batch import execution_batch_label
from .legalization_dedup import filter_matches_for_append, legalized_state_from_paths
from .legalization_filename import (
    execution_date,
    is_legalization_file,
    output_version_from_filename,
    resolve_legalization_filename,
)
from .metadata_mapper import build_legalization_rows
from .models import PipelineResult
from .pipeline_report import print_batch_pipeline_report, print_pipeline_report
from .reference_loader import find_reference_legalization, load_historico_from_reference
from .reconciliation_engine import reconcile
from .sheets_manager import get_card_metadata, load_historico


class UnknownCardError(Exception):
    """Tarjeta no registrada en Sheet de control (Drive) o metadatos locales."""

    pass


class MissingInvoicesError(Exception):
    """Faltan JSON de facturas en caché antes de ejecutar el pipeline."""

    def __init__(self, missing: list[str], card: str | None = None):
        """Guarda lista de facturas sin JSON y tarjeta opcional para el mensaje CLI."""
        self.missing = missing
        self.card = card
        super().__init__(f"Faltan JSON de facturas: {', '.join(missing)}")


class IncompleteInvoicesError(Exception):
    """JSON de facturas presentes pero con plantillas vacías (Paso 3 incompleto)."""

    def __init__(self, incomplete: list[str], card: str | None = None):
        """Guarda lista de JSON incompletos y tarjeta opcional (exit code 4)."""
        self.incomplete = incomplete
        self.card = card
        super().__init__(
            f"JSON de facturas incompletos (plantillas vacías): {', '.join(incomplete)}"
        )


@dataclass
class CardPipelineOutcome:
    """Resultado por tarjeta en ejecución batch: éxito (``result``) o error capturado."""

    context: CardFolderContext
    result: PipelineResult | None = None
    error: BaseException | None = None


def _find_local_template(local_folder: Path) -> Path | None:
    """Busca plantilla base en carpeta local, repo o fixtures de demo."""
    candidates = [
        local_folder / "plantilla_base.xlsx",
        *sorted(repo_root().glob("Plantilla*.xlsx")),
        repo_root() / "tests" / "fixtures" / "demo_card" / "plantilla_base.xlsx",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _resolve_card_folder_files(
    card_folder: CardFolderContext,
) -> tuple[list, Path | None]:
    """Lista archivos de la carpeta (Drive o local) y plantilla si aplica."""
    if card_folder.local_path:
        files = list_local_folder(card_folder.local_path)
        template = _find_local_template(card_folder.local_path)
    else:
        files = list_folder_files(card_folder.folder_id or "")
        template = None
    return files, template


def _effective_card(card_folder: CardFolderContext, parsed_card: str) -> str:
    """Tarjeta efectiva: prioriza número parseado del extracto si difiere del contexto."""
    if card_folder.card and card_folder.card != parsed_card:
        return parsed_card
    return card_folder.card or parsed_card


def _resolve_extract_path(
    card_folder: CardFolderContext,
    extract_file,
    cache_card: str | None,
) -> Path:
    """Ruta al extracto: path local directo o descarga a caché por tarjeta (Drive)."""
    if card_folder.local_path:
        return Path(extract_file.file_id)
    return download_to_cache(extract_file.file_id, extract_file.name, card=cache_card)


def _safe_cache_name(name: str) -> str:
    """Sanitiza nombre de archivo para paths temporales de dedup/merge en caché."""
    return re.sub(r"[^\w.\-]+", "_", name)


def _collect_legalization_paths_for_dedup(
    *,
    files: list,
    card: str,
    out_dir: Path,
    is_local: bool,
) -> list[Path]:
    """Recopila Formatos previos (Drive, local y caché) para construir ``LegalizedState``.

    Descarga copias ``_dedup_src_*`` en Drive; evita duplicados por path resuelto.
    """
    paths: list[Path] = []
    seen: set[str] = set()

    for entry in list_legalization_files(files, card):
        if is_local:
            path = Path(entry.file_id)
        else:
            path = out_dir / f"_dedup_src_{_safe_cache_name(entry.name)}"
            download_file(entry.file_id, path)
        if path.exists() and str(path.resolve()) not in seen:
            paths.append(path)
            seen.add(str(path.resolve()))

    if out_dir.exists():
        for path in sorted(out_dir.glob("*.xlsx")):
            if not is_legalization_file(path.name, card):
                continue
            if path.name.startswith("_dedup_src_"):
                continue
            resolved = str(path.resolve())
            if resolved not in seen and path.exists():
                paths.append(path)
                seen.add(resolved)

    return paths


def _resolve_base_workbook_path(
    *,
    files: list,
    card: str,
    out_name: str,
    out_dir: Path,
    is_local: bool,
) -> Path | None:
    """Resuelve Formato base para merge (excluye el nombre de salida de esta ejecución)."""
    base = find_base_legalization_file(files, card, exclude_name=out_name)
    if base is None:
        return None
    if is_local:
        path = Path(base.file_id)
        return path if path.exists() else None
    path = out_dir / f"_merge_src_{_safe_cache_name(base.name)}"
    download_file(base.file_id, path)
    return path if path.exists() else None


def _upload_extract_to_drive(
    extract: DriveFile,
    extract_path: Path,
    upload_folder_id: str | None,
    *,
    is_local: bool,
) -> tuple[str, str]:
    """Sube preliminar actualizado a Drive; vacío en modo local o sin folder_id.

    Solo aplica cuando origen es Excel (no PDF). Retorna (link, modo 'update').
    """
    if is_local or not upload_folder_id:
        return "", ""
    update_file(extract.file_id, extract_path)
    return file_link(extract.file_id), "update"


def run_pipeline_for_card(
    card_folder: CardFolderContext,
    *,
    skip_invoice_check: bool = False,
    dry_run: bool = False,
    template_path: Path | None = None,
    settings=None,
) -> PipelineResult:
    """Ejecuta legalización completa para una carpeta de tarjeta.

    Flujo: extracto (PDF > Excel), validación JSON, conciliación, dedup GMF/merge,
    generación Excel y subida a Drive (salvo ``dry_run`` o local).

    Raises:
        FileNotFoundError: sin extracto PDF/Excel en la carpeta.
        MissingInvoicesError: faltan JSON de facturas (salvo skip_invoice_check).
        IncompleteInvoicesError: plantillas JSON sin completar.
        UnknownCardError: tarjeta no está en Sheet de control (modo Drive).
    """
    settings = settings or load_settings()
    warnings: list[str] = []
    legalization_file_link = ""
    extract_file_link = ""
    extract_update_mode = ""

    files, local_template = _resolve_card_folder_files(card_folder)
    cache_card: str | None = card_folder.card

    def resolve_extract_path(extract_file) -> Path:
        """Closure: delega en ``_resolve_extract_path`` con contexto de tarjeta."""
        return _resolve_extract_path(card_folder, extract_file, cache_card)

    selection = select_best_extract_file(files, resolve_extract_path)
    if selection is None:
        label = card_folder.display_name
        raise FileNotFoundError(
            f"No se encontró extracto PDF ni preliminar Mov TC en {label}"
        )

    extract = selection.chosen
    extract_selected = extract.name
    extract_source_kind = selection.source_kind
    if len(selection.candidates) > 1:
        label = "Extracto PDF" if extract_source_kind == "pdf" else "Preliminar"
        warnings.append(f"{label} elegido: {selection.reason}")
    if extract_source_kind == "pdf" and list_extract_files(files):
        warnings.append(
            "Origen: extracto PDF (prioridad sobre Mov TC); preliminar no actualizado"
        )

    invoice_names = [f.name for f in list_invoice_files(files)]
    extract_path = resolve_extract_path(extract)

    if card_folder.local_path:
        template_path = template_path or local_template
    else:
        extract_path = download_to_cache(extract.file_id, extract.name, card=cache_card)

    loaded_extract = parse_movement_source(extract_path)
    extract_data = loaded_extract.data
    extract_source_kind = loaded_extract.source_kind
    cache_card = _effective_card(card_folder, extract_data.card)

    if not card_folder.local_path:
        extract_path = download_to_cache(extract.file_id, extract.name, card=cache_card)
        for inv in list_invoice_files(files):
            download_to_cache(inv.file_id, inv.name, card=cache_card)

    if card_folder.local_path:
        card_meta = _local_card_metadata(extract_data.card)
        if card_meta is None:
            raise UnknownCardError(
                f"Tarjeta {extract_data.card} no registrada en metadatos locales."
            )
        reference = find_reference_legalization(card_folder.local_path, extract_data.card)
        historico = load_historico_from_reference(reference) if reference else {}
        if template_path is None:
            template_path = local_template
    else:
        card_meta = get_card_metadata(
            settings.control_sheet_id,
            extract_data.card,
            settings.control_sheet_tab_tarjetas,
        )
        if card_meta is None:
            raise UnknownCardError(
                f"Tarjeta {extract_data.card} no registrada en Sheet de control. "
                "Actualice la pestaña Tarjetas y reintente."
            )
        historico = load_historico(
            settings.control_sheet_id, settings.control_sheet_tab_historico
        )

    if not skip_invoice_check:
        missing = missing_invoice_json(invoice_names, card=cache_card)
        if missing:
            raise MissingInvoicesError(missing, card=cache_card)
        incomplete = incomplete_invoice_json(invoice_names, card=cache_card)
        if incomplete:
            raise IncompleteInvoicesError(incomplete, card=cache_card)

    invoices = load_invoices_from_cache(invoice_names, card=cache_card)
    facturas_peru_sin_ruc = collect_peru_ruc_issues(invoices)
    warnings.extend(peru_ruc_warning_messages(facturas_peru_sin_ruc))
    matches = reconcile(settings, extract_data, invoices)
    matches = sorted(
        matches,
        key=lambda m: (m.transaction.is_gmf, m.transaction.tx_date, m.transaction.description),
    )

    out_dir = output_cache_dir(cache_card)
    out_dir.mkdir(parents=True, exist_ok=True)
    as_of = execution_date(timezone=settings.timezone)
    existing_names = {f.name for f in list_legalization_files(files, extract_data.card)}
    for path in out_dir.glob("*.xlsx"):
        if is_legalization_file(path.name, extract_data.card):
            existing_names.add(path.name)
    out_name = resolve_legalization_filename(
        extract_data.card, existing_names, as_of
    )
    output_version = output_version_from_filename(out_name)
    if card_folder.local_path:
        warnings.append(
            "Salida generada en .cache/output/ para no sobrescribir la referencia manual."
        )
    out_path = out_dir / out_name
    batch_label = execution_batch_label(timezone=settings.timezone)

    prior_paths = _collect_legalization_paths_for_dedup(
        files=files,
        card=extract_data.card,
        out_dir=out_dir,
        is_local=bool(card_folder.local_path),
    )
    base_path = _resolve_base_workbook_path(
        files=files,
        card=extract_data.card,
        out_name=out_name,
        out_dir=out_dir,
        is_local=bool(card_folder.local_path),
    )
    legalization_mode = "create"
    skipped_already_legalized = 0
    matches_for_rows = matches
    if prior_paths:
        state = legalized_state_from_paths(
            prior_paths, default_year=extract_data.period_year
        )
        matches_for_rows, skipped_already_legalized = filter_matches_for_append(
            matches, state
        )
        if skipped_already_legalized:
            warnings.append(
                f"{skipped_already_legalized} movimiento(s) ya legalizado(s) omitido(s)"
            )

    legalization_rows, new_nits = build_legalization_rows(
        matches_for_rows, card_meta, historico, settings
    )

    if prior_paths and not legalization_rows:
        warnings.append("Sin movimientos nuevos para legalizar")

    if template_path is None:
        if settings.plantilla_drive_file_id:
            template_path = out_dir / "plantilla_base.xlsx"
            download_file(settings.plantilla_drive_file_id, template_path)
        else:
            template_path = out_dir / "plantilla_base.xlsx"
            if not template_path.exists():
                create_minimal_template(template_path)
                warnings.append(
                    "Se usó plantilla mínima local; configure PLANTILLA_DRIVE_FILE_ID"
                )

    upload_folder_id = card_folder.folder_id
    if not dry_run:
        if extract_source_kind == "excel":
            apply_extract_review_columns(extract_path, matches)
            extract_file_link, extract_update_mode = _upload_extract_to_drive(
                extract,
                extract_path,
                upload_folder_id,
                is_local=bool(card_folder.local_path),
            )
        elif extract_source_kind == "pdf":
            warnings.append("Origen: extracto PDF; preliminar no actualizado")

        if legalization_rows:
            build_legalization_workbook(
                settings,
                template_path,
                out_path,
                extract_data,
                card_meta,
                legalization_rows,
                existing_workbook_path=base_path,
            )
            if upload_folder_id:
                file_id = upload_file(out_path, upload_folder_id, out_name)
                legalization_file_link = file_link(file_id)

    return PipelineResult(
        extract=extract_data,
        card_meta=card_meta,
        matches=matches,
        legalization_rows=legalization_rows,
        output_filename=out_name,
        output_path=str(out_path),
        legalization_file_link=legalization_file_link,
        warnings=warnings,
        new_provider_nits=new_nits,
        facturas_peru_sin_ruc=facturas_peru_sin_ruc,
        legalization_mode=legalization_mode,
        batch_label=batch_label,
        appended_row_count=len(legalization_rows),
        skipped_already_legalized_count=skipped_already_legalized,
        output_version=output_version,
        extract_selected=extract_selected,
        extract_file_link=extract_file_link,
        extract_update_mode=extract_update_mode,
        extract_source_kind=extract_source_kind,
    )


def run_pipeline(
    *,
    folder_id: str | None = None,
    local_folder: Path | None = None,
    skip_invoice_check: bool = False,
    dry_run: bool = False,
    template_path: Path | None = None,
    card_filter: str | None = None,
) -> list[CardPipelineOutcome]:
    """Resuelve contextos por tarjeta y ejecuta ``run_pipeline_for_card`` en cada uno.

    Errores por tarjeta se capturan en ``CardPipelineOutcome.error`` sin abortar el batch.
    """
    if not folder_id and local_folder is None:
        raise ValueError("Debe indicar --folder-id o --local-folder")

    settings = load_settings()
    contexts = resolve_card_folders(
        folder_id=folder_id,
        local_folder=local_folder,
        card_filter=card_filter,
    )
    outcomes: list[CardPipelineOutcome] = []

    for card_folder in contexts:
        try:
            result = run_pipeline_for_card(
                card_folder,
                skip_invoice_check=skip_invoice_check,
                dry_run=dry_run,
                template_path=template_path,
                settings=settings,
            )
            outcomes.append(CardPipelineOutcome(context=card_folder, result=result))
        except BaseException as exc:
            outcomes.append(CardPipelineOutcome(context=card_folder, error=exc))

    return outcomes


def _local_card_metadata(card: str):
    """Metadatos de tarjeta en modo local (fixtures demo); None si no está definida."""
    from .models import CardMetadata

    defaults = {
        "1111": CardMetadata("1111", "Demo User A", "100-Demo"),
        "5555": CardMetadata("5555", "Demo User B", "100-Demo"),
        "2222": CardMetadata("2222", "Demo User B", "100-Demo"),
        "3333": CardMetadata(
            "3333", "Demo User C", "100-Demo"
        ),
        "4444": CardMetadata("4444", "Demo User D", "100-Demo"),
        "6666": CardMetadata("6666", "Demo User B", "100-Demo"),
    }
    return defaults.get(card)


def main(argv: list[str] | None = None) -> int:
    """CLI: imprime reporte JSON (single o batch) y retorna código de salida.

    Códigos: 0 OK, 1 error genérico/batch parcial, 2 JSON faltantes,
    3 tarjeta desconocida, 4 JSON incompletos (plantillas vacías).
    """
    parser = argparse.ArgumentParser(description="Pipeline legalización TC")
    parser.add_argument("--folder-id", help="ID o URL de carpeta Drive")
    parser.add_argument("--local-folder", type=Path, help="Carpeta local (pruebas)")
    parser.add_argument(
        "--card",
        help="Procesar solo esta tarjeta dentro de una carpeta padre",
    )
    parser.add_argument(
        "--skip-invoice-extraction",
        action="store_true",
        help="Omitir validación de JSON en cache (ejecutar tras Claude Code)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--template", type=Path, help="Ruta plantilla xlsx")
    args = parser.parse_args(argv)

    folder_id = parse_folder_id_from_url(args.folder_id) if args.folder_id else None
    try:
        outcomes = run_pipeline(
            folder_id=folder_id,
            local_folder=args.local_folder,
            skip_invoice_check=args.skip_invoice_extraction,
            dry_run=args.dry_run,
            template_path=args.template,
            card_filter=args.card,
        )
        if len(outcomes) == 1:
            outcome = outcomes[0]
            if outcome.error is not None:
                raise outcome.error
            print_pipeline_report(outcome.result)
            return 0

        print_batch_pipeline_report(outcomes)
        if any(o.error is not None for o in outcomes):
            return 1
        return 0
    except MissingInvoicesError as exc:
        card_label = f" (tarjeta {exc.card})" if exc.card else ""
        print(
            f"PENDING_INVOICES{card_label}: {len(exc.missing)} facturas sin JSON",
            file=sys.stderr,
        )
        for name in exc.missing:
            print(f"  - {name}", file=sys.stderr)
        print(
            "Acción: Claude Code debe leer cada factura y crear el JSON correspondiente.",
            file=sys.stderr,
        )
        return 2
    except IncompleteInvoicesError as exc:
        card_label = f" (tarjeta {exc.card})" if exc.card else ""
        print(
            f"INCOMPLETE_INVOICES{card_label}: {len(exc.incomplete)} JSON sin completar",
            file=sys.stderr,
        )
        for name in exc.incomplete:
            print(f"  - {name}", file=sys.stderr)
        print(
            "Acción: completar Paso 3 (legible, fecha_factura, valor_total_documento) "
            "en .cache/cards/{tarjeta}/invoices/",
            file=sys.stderr,
        )
        return 4
    except UnknownCardError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
