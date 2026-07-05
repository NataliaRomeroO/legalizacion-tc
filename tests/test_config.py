"""Tests de parsing de variables de entorno en ``config``."""

from legalizacion_tc.config import _env_bool, load_settings


def test_env_bool_defaults_true(monkeypatch) -> None:
    """Verifica env bool defaults true."""
    monkeypatch.delenv("FX_SSL_VERIFY", raising=False)
    assert _env_bool("FX_SSL_VERIFY", True) is True


def test_env_bool_parses_false(monkeypatch) -> None:
    """Verifica env bool parses false."""
    monkeypatch.setenv("FX_SSL_VERIFY", "false")
    assert _env_bool("FX_SSL_VERIFY", True) is False


def test_load_settings_fx_ssl_verify_from_env(monkeypatch) -> None:
    """Verifica load settings fx ssl verify from env."""
    monkeypatch.setenv("FX_SSL_VERIFY", "false")
    settings = load_settings()
    assert settings.fx_ssl_verify is False
