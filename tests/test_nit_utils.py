"""Tests de normalización NIT/RUC e indexación de histórico (``nit_utils``)."""

from legalizacion_tc.models import ProviderHistory
from legalizacion_tc.nit_utils import index_historico, is_peruvian_ruc, normalize_nit_key


def test_normalize_nit_key_colombian_with_dash():
    """Verifica normalize nit key colombian with dash."""
    assert normalize_nit_key("900111111-0") == "900111111"
    assert normalize_nit_key("900222222-0") == "900222222"


def test_normalize_nit_key_colombian_without_dash():
    """Verifica normalize nit key colombian without dash."""
    assert normalize_nit_key("900111111") == "900111111"


def test_normalize_nit_key_with_dots_and_spaces():
    """Verifica normalize nit key with dots and spaces."""
    assert normalize_nit_key("900.111.111-0") == "900111111"


def test_normalize_nit_key_peruvian_ruc():
    """Verifica normalize nit key peruvian ruc."""
    assert normalize_nit_key("20123456789") == "20123456789"


def test_is_peruvian_ruc_valid():
    """Verifica is peruvian ruc valid."""
    assert is_peruvian_ruc("20987654321") is True
    assert is_peruvian_ruc("20123456789") is True


def test_is_peruvian_ruc_rejects_colombian_nit():
    """Verifica is peruvian ruc rejects colombian nit."""
    assert is_peruvian_ruc("900111111") is False
    assert is_peruvian_ruc("") is False
    assert is_peruvian_ruc(None) is False


def test_normalize_nit_key_foreign_with_dash():
    """Verifica normalize nit key foreign with dash."""
    assert normalize_nit_key("511111111111-99") == "511111111111"


def test_normalize_nit_key_colombian_ten_digits_with_verification_digit():
    """Verifica normalize nit key colombian ten digits with verification digit."""
    assert normalize_nit_key("9004444449") == "900444444"
    assert normalize_nit_key("9005555555") == "900555555"
    assert normalize_nit_key("900444444-9") == "900444444"
    assert normalize_nit_key("900555555-5") == "900555555"


def test_index_historico_registers_raw_and_normalized_keys():
    """Verifica index historico registers raw and normalized keys."""
    history = ProviderHistory(
        nit="900111111",
        razon_social="PROVEEDOR HOTEL SAS",
        detalle_gasto="TC 3333 ALOJAMIENTO",
        articulo_contable="5195200001 - GASTOS DE REPRESENTACION",
    )
    indexed = index_historico({"900111111": history})

    assert indexed["900111111"] is history
    assert indexed["proveedor hotel sas"] is history
