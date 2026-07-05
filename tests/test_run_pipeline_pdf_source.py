"""Tests de integración: pipeline con PDF como fuente (sin update de preliminar)."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from legalizacion_tc.drive_manager import DriveFile
from legalizacion_tc.folder_resolver import CardFolderContext
from legalizacion_tc.run_pipeline import run_pipeline_for_card
from tests.build_fixtures import build_minimal_extract

FIXTURE_PDF = (
    Path(__file__).resolve().parent / "fixtures" / "bank_statements" / "4444_MAY2026.pdf"
)
FOLDER_ID = "folder-drive-pdf"


@pytest.fixture
def pdf_card_setup(tmp_path, monkeypatch):
    """Fixture o helper: pdf card setup."""
    if not FIXTURE_PDF.exists():
        pytest.skip(f"Fixture PDF no encontrado: {FIXTURE_PDF}")

    card = "4444"
    pdf_name = "4444_MAY2026.pdf"
    pdf_local = tmp_path / pdf_name
    shutil.copy(FIXTURE_PDF, pdf_local)

    excel_name = "Mov TC 4444 Corte Mayo.xlsx"
    excel_local = tmp_path / excel_name
    build_minimal_extract(
        excel_local,
        card,
        rows=[
            {
                "Tarjeta": f"*{card}",
                "Fecha": "2026-05-10",
                "Descripcion": "COMPRA EJEMPLO",
                "Moneda": "COP",
                "Valor": 100000.0,
            }
        ],
    )

    pdf_file = DriveFile(
        file_id=str(pdf_local),
        name=pdf_name,
        mime_type="application/pdf",
    )
    excel_file = DriveFile(
        file_id=str(excel_local),
        name=excel_name,
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    update_calls: list[tuple[str, Path]] = []

    def fake_list_folder_files(folder_id: str) -> list[DriveFile]:
        """Fixture o helper: fake list folder files."""
        assert folder_id == FOLDER_ID
        return [pdf_file, excel_file]

    def fake_download_to_cache(file_id: str, name: str, card: str | None = None) -> Path:
        """Fixture o helper: fake download to cache."""
        dest = tmp_path / "cache" / (card or "x") / "downloads" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if name == pdf_name:
            shutil.copy(pdf_local, dest)
        elif name == excel_name:
            shutil.copy(excel_local, dest)
        return dest

    def fake_update_file(file_id: str, path: Path) -> str:
        """Fixture o helper: fake update file."""
        update_calls.append((file_id, Path(path)))
        return file_id

    def fake_upload_file(path: Path, folder_id: str, name: str) -> str:
        """Fixture o helper: fake upload file."""
        return "uploaded-legalization-id"

    def fake_file_link(file_id: str) -> str:
        """Fixture o helper: fake file link."""
        return f"https://drive.google.com/file/d/{file_id}/view"

    def fake_create_minimal_template(path: Path) -> None:
        """Fixture o helper: fake create minimal template."""
        path.parent.mkdir(parents=True, exist_ok=True)
        from legalizacion_tc.excel_report_builder import create_minimal_template

        create_minimal_template(path)

    def fake_download_file(_file_id: str, dest: Path) -> None:
        """Fixture o helper: fake download file."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        from legalizacion_tc.excel_report_builder import create_minimal_template

        create_minimal_template(dest)

    monkeypatch.setattr(
        "legalizacion_tc.run_pipeline.list_folder_files",
        fake_list_folder_files,
    )
    monkeypatch.setattr(
        "legalizacion_tc.run_pipeline.download_to_cache",
        fake_download_to_cache,
    )
    monkeypatch.setattr("legalizacion_tc.run_pipeline.update_file", fake_update_file)
    monkeypatch.setattr("legalizacion_tc.run_pipeline.upload_file", fake_upload_file)
    monkeypatch.setattr("legalizacion_tc.run_pipeline.file_link", fake_file_link)
    monkeypatch.setattr(
        "legalizacion_tc.run_pipeline.create_minimal_template",
        fake_create_minimal_template,
    )
    monkeypatch.setattr(
        "legalizacion_tc.run_pipeline.download_file",
        fake_download_file,
    )
    monkeypatch.setattr(
        "legalizacion_tc.run_pipeline.get_card_metadata",
        lambda *_args, **_kwargs: __import__(
            "legalizacion_tc.models", fromlist=["CardMetadata"]
        ).CardMetadata("4444", "Demo User D", "100-Demo"),
    )
    monkeypatch.setattr(
        "legalizacion_tc.run_pipeline.load_historico",
        lambda *_args, **_kwargs: {},
    )

    context = CardFolderContext(
        card=card,
        folder_id=FOLDER_ID,
        local_path=None,
        display_name="4444 - Demo User D",
    )
    return {
        "context": context,
        "update_calls": update_calls,
    }


def test_pipeline_pdf_source_skips_preliminar_update(pdf_card_setup):
    """Verifica pipeline pdf source skips preliminar update."""
    setup = pdf_card_setup
    with patch(
        "legalizacion_tc.run_pipeline.apply_extract_review_columns"
    ) as mock_apply:
        result = run_pipeline_for_card(
            setup["context"],
            skip_invoice_check=True,
            dry_run=False,
        )

    mock_apply.assert_not_called()
    assert result.extract_source_kind == "pdf"
    assert result.extract_selected == "4444_MAY2026.pdf"
    assert result.extract.card == "4444"
    assert len(result.extract.transactions) == 21
    assert not setup["update_calls"]
    assert any("extracto PDF" in warning for warning in result.warnings)
