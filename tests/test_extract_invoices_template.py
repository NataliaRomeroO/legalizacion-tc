"""Tests de agrupación batch en ``extract_invoices_template``."""

from legalizacion_tc.folder_resolver import resolve_card_folders_local
from tests.build_fixtures import ensure_batch_parent_fixtures


def test_extract_summary_batch_grouping():
    """Verifica extract summary batch grouping."""
    parent = ensure_batch_parent_fixtures()
    contexts = resolve_card_folders_local(parent)
    assert len(contexts) == 2
    cards = sorted(ctx.card or "" for ctx in contexts)
    assert cards == ["2222", "3333"]
