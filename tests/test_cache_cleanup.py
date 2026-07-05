"""Tests de limpieza de caché: output preserva invoices; legacy paths."""

from legalizacion_tc import cache_cleanup


def test_clean_output_preserves_invoices(tmp_path, monkeypatch):
    """Verifica clean output preserves invoices."""
    monkeypatch.setattr(cache_cleanup, "cache_dir", lambda: tmp_path)
    monkeypatch.setattr(
        cache_cleanup,
        "output_cache_dir",
        lambda card=None: tmp_path / "output" / card if card else tmp_path / "output",
    )

    invoices_dir = tmp_path / "cards" / "3333" / "invoices"
    invoices_dir.mkdir(parents=True)
    invoice_file = invoices_dir / "factura.json"
    invoice_file.write_text("{}", encoding="utf-8")

    output_dir = tmp_path / "output" / "3333"
    output_dir.mkdir(parents=True)
    (output_dir / "Formato.xlsx").write_text("x", encoding="utf-8")

    removed = cache_cleanup.clean_output()
    assert output_dir in removed or tmp_path / "output" in removed
    assert not output_dir.exists()
    assert invoice_file.exists()


def test_clean_invoices_removes_json(tmp_path, monkeypatch):
    """Verifica clean invoices removes json."""
    monkeypatch.setattr(
        cache_cleanup,
        "invoices_cache_dir",
        lambda card=None: tmp_path / "cards" / (card or "0000") / "invoices",
    )

    invoices_dir = tmp_path / "cards" / "3333" / "invoices"
    invoices_dir.mkdir(parents=True)
    (invoices_dir / "factura.json").write_text("{}", encoding="utf-8")

    removed = cache_cleanup.clean_invoices("3333")
    assert invoices_dir in removed
    assert not invoices_dir.exists()


def test_clean_legacy_removes_legacy_paths(tmp_path, monkeypatch):
    """Verifica clean legacy removes legacy paths."""
    monkeypatch.setattr(cache_cleanup, "cache_dir", lambda: tmp_path)

    legacy_invoices = tmp_path / "invoices"
    legacy_downloads = tmp_path / "downloads"
    legacy_invoices.mkdir()
    legacy_downloads.mkdir()
    (legacy_invoices / "old.json").write_text("{}", encoding="utf-8")

    removed = cache_cleanup.clean_legacy()
    assert legacy_invoices in removed
    assert legacy_downloads in removed
    assert not legacy_invoices.exists()
