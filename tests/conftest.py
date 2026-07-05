"""Fixtures compartidos de pytest para el pipeline de legalización TC.

Provee: ``settings``, ``card_meta``, factura USD de ejemplo, transacción de prueba,
``fixture_dir`` y ``ensure_fixtures()`` (genera Excel demo vía ``build_fixtures``).
Inyecta ``src/`` en ``sys.path`` al importar.
"""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tests.build_fixtures import ensure_fixtures
from legalizacion_tc.config import Settings, load_settings
from legalizacion_tc.models import CardMetadata, InvoiceData, Transaction


@pytest.fixture(scope="session")
def fixture_dir() -> Path:
    """Directorio de fixtures demo generados para la sesión de pruebas."""
    return ensure_fixtures()


@pytest.fixture
def settings() -> Settings:
    """Instancia de Settings cargada desde entorno."""
    return load_settings()


@pytest.fixture
def card_meta() -> CardMetadata:
    """Metadatos de tarjeta demo 1111."""
    return CardMetadata("1111", "Demo User A", "100-Demo")


@pytest.fixture
def sample_invoice_usd() -> InvoiceData:
    """Factura USD de ejemplo para pruebas de conciliación."""
    return InvoiceData(
        source_filename="proveedor_cloud.pdf",
        numero_factura="INV-123",
        nit_proveedor="900123456",
        razon_social="PROVEEDOR CLOUD SAS",
        moneda="USD",
        valor_base=100.0,
        iva=0.0,
        valor_total_documento=100.0,
        fecha_factura=date(2026, 5, 10),
        legible=True,
    )


@pytest.fixture
def sample_transaction() -> Transaction:
    """Transacción bancaria de ejemplo asociada a factura USD."""
    return Transaction(
        card="1111",
        tx_date=date(2026, 5, 10),
        description="SERVICIO CLOUD DEMO",
        currency="COP",
        amount_cop=400000.0,
        row_index=2,
    )


@pytest.fixture
def invoice_json_path(tmp_path: Path) -> Path:
    """Ruta temporal a JSON de factura completo para pruebas."""
    data = {
        "source_filename": "proveedor_cloud.pdf",
        "numero_factura": "INV-123",
        "nit_proveedor": "900123456",
        "razon_social": "PROVEEDOR CLOUD SAS",
        "moneda": "USD",
        "valor_base": 100.0,
        "iva": 0.0,
        "valor_total_documento": 100.0,
        "fecha_factura": "2026-05-10",
        "detalle_gasto": "TC 1111 SERVICIO APLICACIONES",
        "legible": True,
    }
    path = tmp_path / "proveedor_cloud.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
