"""Tests de conversión FX Frankfurter v2 (``fx_converter``): SSL, COP passthrough."""

from datetime import date
from unittest.mock import MagicMock, patch

from legalizacion_tc.config import Settings
from legalizacion_tc.fx_converter import convert_to_cop


def _settings(*, fx_ssl_verify: bool) -> Settings:
    """Helper de prueba: settings."""
    return Settings(
        gcp_project_id="test",
        service_account_email="test@test.iam.gserviceaccount.com",
        plantilla_drive_file_id="",
        control_sheet_id="",
        control_sheet_tab_tarjetas="Tarjetas",
        control_sheet_tab_historico="historico_proveedores",
        historico_drive_folder_id="",
        frankfurter_base_url="https://api.frankfurter.dev/v2",
        amount_tolerance_pct=0.02,
        amount_tolerance_pct_sol=0.12,
        date_tolerance_days=3,
        consolidated_receipt_max_days_after=30,
        consolidated_receipt_review_max_months=3,
        consolidated_max_group_size=6,
        iva_rate_cop=0.19,
        restaurant_no_iva_keywords=(
            "RESTAURANTE",
            "ALMUERZO",
            "CENA",
            "COMIDA",
            "GASTO DE REPRESENTACION",
        ),
        timezone="America/Bogota",
        fx_ssl_verify=fx_ssl_verify,
    )


@patch("legalizacion_tc.fx_converter.httpx.get")
def test_convert_to_cop_v2_rate_endpoint(mock_get: MagicMock) -> None:
    """Verifica convert to cop v2 rate endpoint."""
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "date": "2026-05-28",
        "base": "USD",
        "quote": "COP",
        "rate": 3646.52,
    }
    mock_get.return_value = mock_response

    result = convert_to_cop(_settings(fx_ssl_verify=True), 20.0, "USD", date(2026, 5, 28))

    assert result == 72930.4
    mock_get.assert_called_once_with(
        "https://api.frankfurter.dev/v2/rate/USD/COP",
        params={"date": "2026-05-28"},
        timeout=30.0,
        verify=True,
    )


@patch("legalizacion_tc.fx_converter.httpx.get")
def test_convert_to_cop_uses_ssl_verify_from_settings(mock_get: MagicMock) -> None:
    """Verifica convert to cop uses ssl verify from settings."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"rate": 4100.0}
    mock_get.return_value = mock_response

    convert_to_cop(_settings(fx_ssl_verify=True), 100.0, "USD", date(2026, 5, 10))

    assert mock_get.call_args.kwargs["verify"] is True


@patch("legalizacion_tc.fx_converter.httpx.get")
def test_convert_to_cop_can_disable_ssl_verify(mock_get: MagicMock) -> None:
    """Verifica convert to cop can disable ssl verify."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"rate": 4100.0}
    mock_get.return_value = mock_response

    convert_to_cop(_settings(fx_ssl_verify=False), 100.0, "USD", date(2026, 5, 10))

    assert mock_get.call_args.kwargs["verify"] is False


def test_convert_to_cop_skips_http_for_cop() -> None:
    """Verifica convert to cop skips http for cop."""
    assert (
        convert_to_cop(_settings(fx_ssl_verify=True), 50000.0, "COP", date(2026, 5, 10))
        == 50000.0
    )
