"""Tests de orquestación ``run_pipeline``: local, batch, caché por tarjeta, JSON incompletos."""

import pytest

from legalizacion_tc.config import downloads_cache_dir, invoices_cache_dir, output_cache_dir
from legalizacion_tc.run_pipeline import run_pipeline
from tests.build_fixtures import (
    build_minimal_extract,
    build_template,
    ensure_batch_parent_fixtures,
)


def test_run_pipeline_single_local_dry_run(fixture_dir):
    """Verifica run pipeline single local dry run."""
    outcomes = run_pipeline(
        local_folder=fixture_dir,
        skip_invoice_check=True,
        dry_run=True,
    )
    assert len(outcomes) == 1
    assert outcomes[0].error is None
    assert outcomes[0].result is not None
    assert outcomes[0].result.extract.card == "1111"


def test_run_pipeline_batch_local_dry_run():
    """Verifica run pipeline batch local dry run."""
    parent = ensure_batch_parent_fixtures()
    outcomes = run_pipeline(
        local_folder=parent,
        skip_invoice_check=True,
        dry_run=True,
    )
    assert len(outcomes) == 2
    cards = {o.result.extract.card for o in outcomes if o.result}
    assert cards == {"2222", "3333"}
    assert all(o.error is None for o in outcomes)


def test_cache_dirs_per_card():
    """Verifica cache dirs per card."""
    assert invoices_cache_dir("2222").name == "invoices"
    assert invoices_cache_dir("2222").parent.name == "2222"
    assert downloads_cache_dir("3333").parent.name == "3333"
    assert output_cache_dir("2222").parent.name == "output"


def test_run_pipeline_raises_on_incomplete_templates(tmp_path, monkeypatch):
    """Verifica run pipeline raises on incomplete templates."""
    from legalizacion_tc import invoice_loader
    from legalizacion_tc.folder_resolver import CardFolderContext
    from legalizacion_tc.invoice_loader import save_invoice_json_template
    from legalizacion_tc.run_pipeline import IncompleteInvoicesError, run_pipeline_for_card

    card_dir = tmp_path / "1111_local"
    card_dir.mkdir()
    build_minimal_extract(card_dir / "Mov TC 1111.xlsx", "1111")
    build_template(card_dir / "plantilla_base.xlsx")
    (card_dir / "factura.pdf").write_bytes(b"%PDF")

    inv_dir = tmp_path / "invoices"
    inv_dir.mkdir()
    monkeypatch.setattr(invoice_loader, "invoices_cache_dir", lambda card=None: inv_dir)
    save_invoice_json_template("factura.pdf")

    context = CardFolderContext(
        card="1111",
        folder_id=None,
        local_path=card_dir,
        display_name="1111",
    )
    with pytest.raises(IncompleteInvoicesError) as exc_info:
        run_pipeline_for_card(context, dry_run=True)
    assert exc_info.value.incomplete == ["factura.pdf"]
