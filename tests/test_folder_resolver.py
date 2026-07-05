"""Tests de resolución de carpetas Drive/local (``folder_resolver``).

Cubre: subcarpetas ``2222 - Nombre``, carpeta plana, filtro ``--card``,
ignorar extracto suelto en raíz del padre.
"""

from pathlib import Path

from legalizacion_tc.folder_resolver import (
    parse_card_subfolder_name,
    resolve_card_folders_local,
)
from tests.build_fixtures import build_minimal_extract, ensure_batch_parent_fixtures


def test_parse_card_subfolder_name():
    """Verifica parse card subfolder name."""
    assert parse_card_subfolder_name("2222 - Demo User B") == "2222"
    assert parse_card_subfolder_name("demo_card") is None


def test_resolve_single_flat_folder(fixture_dir: Path):
    """Verifica resolve single flat folder."""
    contexts = resolve_card_folders_local(fixture_dir)
    assert len(contexts) == 1
    assert contexts[0].local_path == fixture_dir.resolve()
    assert contexts[0].card is None


def test_resolve_batch_parent_folder():
    """Verifica resolve batch parent folder."""
    parent = ensure_batch_parent_fixtures()
    contexts = resolve_card_folders_local(parent)
    assert len(contexts) == 2
    cards = {ctx.card for ctx in contexts}
    assert cards == {"2222", "3333"}


def test_resolve_single_subfolder_from_parent():
    """Verifica resolve single subfolder from parent."""
    parent = ensure_batch_parent_fixtures()
    sub = parent / "2222 - Demo User B"
    contexts = resolve_card_folders_local(sub)
    assert len(contexts) == 1
    assert contexts[0].card == "2222"
    assert contexts[0].local_path == sub.resolve()


def test_resolve_parent_with_card_filter():
    """Verifica resolve parent with card filter."""
    parent = ensure_batch_parent_fixtures()
    contexts = resolve_card_folders_local(parent, card_filter="3333")
    assert len(contexts) == 1
    assert contexts[0].card == "3333"


def test_resolve_parent_ignores_root_extract(tmp_path: Path):
    """Verifica resolve parent ignores root extract."""
    parent = tmp_path / "parent"
    parent.mkdir()
    build_minimal_extract(parent / "Mov TC 2222 Corte Mayo.xlsx", "2222")
    sub = parent / "2222 - Demo User B"
    sub.mkdir()
    build_minimal_extract(sub / "Mov TC 2222 Corte Mayo.xlsx", "2222")
    contexts = resolve_card_folders_local(parent)
    assert len(contexts) == 1
    assert contexts[0].card == "2222"
    assert contexts[0].local_path == sub.resolve()
