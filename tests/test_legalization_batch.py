"""Tests de etiquetas de lote/corte en Excel (``legalization_batch``)."""

from datetime import date

from legalizacion_tc.legalization_batch import (
    corte_batch_label,
    current_batch_label,
    execution_batch_label,
    execution_period_month,
    max_corte_number,
    parse_batch_label,
    relabel_existing_rows,
)


def test_current_batch_label():
    """Verifica current batch label."""
    assert current_batch_label("JUNIO") == "Legalizado en junio"


def test_execution_period_month():
    """Verifica execution period month."""
    assert execution_period_month(as_of=date(2026, 7, 2)) == "JULIO"
    assert execution_batch_label(as_of=date(2026, 7, 2)) == "Legalizado en julio"


def test_relabel_first_to_second_run():
    """Verifica relabel first to second run."""
    labels = ["Legalizado en junio", "Legalizado en junio"]
    assert relabel_existing_rows(labels, "JUNIO") == [
        "Legalizado en junio corte 1",
        "Legalizado en junio corte 1",
    ]


def test_relabel_third_run():
    """Verifica relabel third run."""
    labels = [
        "Legalizado en junio corte 1",
        "Legalizado en junio",
        None,
    ]
    assert relabel_existing_rows(labels, "JUNIO") == [
        "Legalizado en junio corte 1",
        "Legalizado en junio corte 2",
        "Legalizado en junio corte 2",
    ]


def test_legacy_empty_label_gets_corte_when_same_month_batch_exists():
    """Verifica legacy empty label gets corte when same month batch exists."""
    assert relabel_existing_rows(["Legalizado en mayo", None, ""], "MAYO") == [
        "Legalizado en mayo corte 1",
        "Legalizado en mayo corte 1",
        "Legalizado en mayo corte 1",
    ]


def test_legacy_empty_label_unchanged_without_same_month_batch():
    """Verifica legacy empty label unchanged without same month batch."""
    assert relabel_existing_rows([None, ""], "MAYO") == [None, ""]


def test_relabel_preserves_other_execution_month():
    """Verifica relabel preserves other execution month."""
    labels = ["Legalizado en junio", "Legalizado en junio corte 1"]
    assert relabel_existing_rows(labels, "JULIO") == labels


def test_relabel_july_promotes_only_july_current():
    """Verifica relabel july promotes only july current."""
    labels = [
        "Legalizado en junio",
        "Legalizado en julio",
        "Legalizado en julio corte 1",
    ]
    assert relabel_existing_rows(labels, "JULIO") == [
        "Legalizado en junio",
        "Legalizado en julio corte 2",
        "Legalizado en julio corte 1",
    ]


def test_max_corte_number():
    """Verifica max corte number."""
    labels = [
        "Legalizado en junio corte 1",
        "Legalizado en junio corte 3",
        "Legalizado en junio",
    ]
    assert max_corte_number(labels, "JUNIO") == 3


def test_parse_batch_label():
    """Verifica parse batch label."""
    assert parse_batch_label("Legalizado en junio", "JUNIO") == ("current", None)
    assert parse_batch_label("Legalizado en junio corte 2", "JUNIO") == ("corte", 2)
    assert parse_batch_label("Otro texto", "JUNIO") is None
    assert parse_batch_label("Legalizado en junio", "JULIO") is None
