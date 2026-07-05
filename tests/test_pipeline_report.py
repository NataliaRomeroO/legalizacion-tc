"""Tests del reporte JSON stdout (``pipeline_report``): status, warnings, sin soporte."""

from datetime import date

from legalizacion_tc.models import (
    CardMetadata,
    ExtractData,
    InvoiceData,
    LegalizationRow,
    MatchResult,
    PipelineResult,
    Transaction,
)
from legalizacion_tc.pipeline_report import build_pipeline_report


def test_pipeline_report_includes_movimientos_sin_soporte():
    """Verifica pipeline report includes movimientos sin soporte."""
    unmatched_tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 12),
        description="RESTAURANTE SIN FACTURA",
        currency="COP",
        amount_cop=85000.0,
        row_index=5,
    )
    ok_tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 10),
        description="SERVICIO CLOUD DEMO",
        currency="COP",
        amount_cop=400000.0,
        row_index=2,
    )
    result = PipelineResult(
        extract=ExtractData(
            card="1111",
            period_month="MAYO",
            period_year=2026,
            transactions=[ok_tx, unmatched_tx],
            total_cop=493500.0,
            source_filename="mov.xlsx",
        ),
        card_meta=CardMetadata("1111", "Demo User A", "100-Demo"),
        matches=[
            MatchResult(
                transaction=ok_tx,
                invoice=None,
                status="OK",
                documento_soporte="SI",
            ),
            MatchResult(
                transaction=unmatched_tx,
                invoice=None,
                status="UNMATCHED",
                documento_soporte="NO",
                failure_reason="Factura no encontrada",
            ),
        ],
        legalization_rows=[
            LegalizationRow(
                numero_factura="INV-123",
                nit_proveedor="900123456",
                razon_social="AWS",
                detalle_gasto="TC 1111 GASTO AWS",
                articulo_contable="5135950002",
                centro_costo="100-Demo",
                moneda="COP",
                valor_base_cops=400000.0,
                iva=0.0,
                valor_total_compra_cop=400000.0,
                documento_soporte="NO",
            ),
            LegalizationRow(
                numero_factura="",
                nit_proveedor="",
                razon_social="",
                detalle_gasto="TC 1111 RESTAURANTE SIN FACTURA",
                articulo_contable="",
                centro_costo="100-Demo",
                moneda="COP",
                valor_base_cops=85000.0,
                iva=0.0,
                valor_total_compra_cop=85000.0,
                documento_soporte="",
            ),
        ],
        output_filename="Formato de Legalización TC 1111 - MAYO - 2026.xlsx",
        output_path="/tmp/out.xlsx",
        legalization_file_link="https://drive.google.com/file/d/abc123/view",
    )

    report = build_pipeline_report(result)
    assert report["status"] == "partial"
    assert report["legalization_file_link"] == "https://drive.google.com/file/d/abc123/view"
    assert report["matched_count"] == 1
    assert report["gmf_count"] == 0
    assert report["sin_factura_count"] == 1
    assert report["unmatched_count"] == 1
    assert len(report["movimientos_sin_soporte"]) == 1
    entry = report["movimientos_sin_soporte"][0]
    assert entry["concepto"] == "RESTAURANTE SIN FACTURA"
    assert entry["monto_cop"] == 85000.0
    assert entry["fecha"] == "2026-05-12"
    assert entry["motivo"] == "Factura no encontrada"
    assert len(report["documento_soporte_no"]) == 1
    assert "RESTAURANTE SIN FACTURA" in report["documento_soporte_no"][0]
    assert "Factura no encontrada" in report["documento_soporte_no"][0]


def test_pipeline_report_proveedores_pendientes_historico():
    """Verifica pipeline report proveedores pendientes historico."""
    result = PipelineResult(
        extract=ExtractData(
            card="1111",
            period_month="MAYO",
            period_year=2026,
            transactions=[],
            total_cop=50000.0,
            source_filename="mov.xlsx",
        ),
        card_meta=CardMetadata("1111", "Demo User A", "100-Demo"),
        matches=[
            MatchResult(
                transaction=Transaction(
                    card="1111",
                    tx_date=date(2026, 5, 10),
                    description="PROVEEDOR NUEVO",
                    currency="COP",
                    amount_cop=50000.0,
                    row_index=2,
                ),
                invoice=None,
                status="OK",
                documento_soporte="SI",
            )
        ],
        legalization_rows=[
            LegalizationRow(
                numero_factura="FAC-001",
                nit_proveedor="9001111111",
                razon_social="PROVEEDOR NUEVO SAS",
                detalle_gasto="TC 1111 GASTO PROVEEDOR NUEVO SAS",
                articulo_contable="",
                centro_costo="100-Demo",
                moneda="COP",
                valor_base_cops=50000.0,
                iva=0.0,
                valor_total_compra_cop=50000.0,
                documento_soporte="SI",
            )
        ],
        new_provider_nits=["9001111111"],
        output_filename="out.xlsx",
        output_path="/tmp/out.xlsx",
    )
    report = build_pipeline_report(result)
    assert report["status"] == "partial"
    assert len(report["proveedores_pendientes_historico"]) == 1
    entry = report["proveedores_pendientes_historico"][0]
    assert entry["nit"] == "9001111111"
    assert entry["razon_social"] == "PROVEEDOR NUEVO SAS"
    assert "historico_proveedores" in entry["accion"]
    assert report["articulo_contable_vacio"] == []
    assert any("historico_proveedores" in w for w in report["warnings"])


def test_pipeline_report_no_pendientes_when_historico_known():
    """Verifica pipeline report no pendientes when historico known."""
    result = PipelineResult(
        extract=ExtractData(
            card="1111",
            period_month="MAYO",
            period_year=2026,
            transactions=[],
            total_cop=50000.0,
            source_filename="mov.xlsx",
        ),
        matches=[
            MatchResult(
                transaction=Transaction(
                    card="1111",
                    tx_date=date(2026, 5, 10),
                    description="AWS",
                    currency="COP",
                    amount_cop=50000.0,
                    row_index=2,
                ),
                invoice=None,
                status="OK",
                documento_soporte="SI",
            )
        ],
        legalization_rows=[
            LegalizationRow(
                numero_factura="INV-1",
                nit_proveedor="900123456",
                razon_social="AWS",
                detalle_gasto="TC 1111 GASTO AWS",
                articulo_contable="5135950002",
                centro_costo="100-Demo",
                moneda="COP",
                valor_base_cops=50000.0,
                iva=0.0,
                valor_total_compra_cop=50000.0,
                documento_soporte="SI",
            )
        ],
        new_provider_nits=[],
        output_filename="out.xlsx",
        output_path="/tmp/out.xlsx",
    )
    report = build_pipeline_report(result)
    assert report["proveedores_pendientes_historico"] == []
    assert report["status"] == "success"


def test_pipeline_report_no_pendientes_when_nit_in_new_nits_but_articulo_filled():
    """Caso TC 4444: proveedores resueltos por razón social tienen articulo_contable
    lleno en Excel aunque su NIT de factura aparezca en new_provider_nits.
    No debe generarse la sección de pendientes ni el warning al operador."""
    result = PipelineResult(
        extract=ExtractData(
            card="4444",
            period_month="MAYO",
            period_year=2026,
            transactions=[],
            total_cop=601749.0,
            source_filename="mov.xlsx",
        ),
        card_meta=CardMetadata("4444", "Demo User D", "100-Demo"),
        matches=[
            MatchResult(
                transaction=Transaction(
                    card="4444",
                    tx_date=date(2026, 5, 20),
                    description="MERCADOPAGO COLOMBIA",
                    currency="COP",
                    amount_cop=601749.0,
                    row_index=2,
                ),
                invoice=None,
                status="OK",
                documento_soporte="NO",
            )
        ],
        legalization_rows=[
            LegalizationRow(
                numero_factura="AL171043721",
                nit_proveedor="9009999999",
                razon_social="CENCOSUD COLOMBIA S.A.",
                detalle_gasto="TC 4444 COMPRA SUPERMERCADO",
                # Artículo ya resuelto vía razón social desde el Sheet
                articulo_contable="5195200001 - GASTOS DE REPRESENTACION",
                centro_costo="100-Demo",
                moneda="COP",
                valor_base_cops=601749.0,
                iva=0.0,
                valor_total_compra_cop=601749.0,
                documento_soporte="NO",
            )
        ],
        # Pipeline lo incluyó en new_nits porque el NIT de factura no era clave en el dict
        new_provider_nits=["9009999999"],
        output_filename="out.xlsx",
        output_path="/tmp/out.xlsx",
    )
    report = build_pipeline_report(result)
    assert report["proveedores_pendientes_historico"] == []
    assert report["articulo_contable_vacio"] == []
    assert not any("historico_proveedores" in w for w in report["warnings"])
    assert report["status"] == "success"


def test_pipeline_report_ok_and_gmf_is_success():
    """Verifica pipeline report ok and gmf is success."""
    gmf_txs = [
        Transaction(
            card="1111",
            tx_date=date(2026, 5, 11),
            description="4X1000 PERSONA JURIDICA",
            currency="COP",
            amount_cop=225.99,
            row_index=2,
            is_gmf=True,
        ),
        Transaction(
            card="1111",
            tx_date=date(2026, 5, 27),
            description="4X1000 PERSONA JURIDICA",
            currency="COP",
            amount_cop=14.67,
            row_index=3,
            is_gmf=True,
        ),
        Transaction(
            card="1111",
            tx_date=date(2026, 5, 31),
            description="4X1000 PERSONA JURIDICA",
            currency="COP",
            amount_cop=294.47,
            row_index=4,
            is_gmf=True,
        ),
    ]
    ok_tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 9),
        description="WEBAPP* DOMAIN#FAC-700001",
        currency="COP",
        amount_cop=56000.0,
        row_index=5,
    )
    matches = [
        MatchResult(transaction=tx, invoice=None, status="GMF", documento_soporte="SI")
        for tx in gmf_txs
    ]
    matches.append(
        MatchResult(
            transaction=ok_tx,
            invoice=None,
            status="OK",
            documento_soporte="SI",
        )
    )
    result = PipelineResult(
        extract=ExtractData(
            card="1111",
            period_month="MAYO",
            period_year=2026,
            transactions=gmf_txs + [ok_tx],
            total_cop=57033.57,
            source_filename="mov.xlsx",
        ),
        matches=matches,
        legalization_rows=[
            LegalizationRow(
                numero_factura="FAC-700001",
                nit_proveedor="900123456",
                razon_social="PROVEEDOR WEB",
                detalle_gasto="TC 1111 GASTO PROVEEDOR WEB",
                articulo_contable="5135950002",
                centro_costo="100-Demo",
                moneda="USD",
                valor_base_cops=56000.0,
                iva=0.0,
                valor_total_compra_cop=56000.0,
                documento_soporte="SI",
            ),
            LegalizationRow(
                numero_factura="",
                nit_proveedor="",
                razon_social="",
                detalle_gasto="TC 1111 GMF",
                articulo_contable="5135950002",
                centro_costo="100-Demo",
                moneda="COP",
                valor_base_cops=535.13,
                iva=0.0,
                valor_total_compra_cop=535.13,
                documento_soporte="SI",
            ),
        ],
        output_filename="out.xlsx",
        output_path="/tmp/out.xlsx",
    )
    report = build_pipeline_report(result)
    assert report["status"] == "success"
    assert report["transaction_count"] == 4
    assert report["matched_count"] == 1
    assert report["gmf_count"] == 3
    assert report["sin_factura_count"] == 0
    assert report["unmatched_count"] == 0
    assert report["movimientos_sin_soporte"] == []
    assert len(report["movimientos_gmf"]) == 3
    assert "GMF" in report["summary"]
    assert "consolidados" in report["summary"]


def test_pipeline_report_partial_when_ok_needs_review():
    """Verifica pipeline report partial when ok needs review."""
    ok_tx = Transaction(
        card="4444",
        tx_date=date(2026, 3, 31),
        description="TRANSPORTE APP",
        currency="COP",
        amount_cop=52508.0,
        row_index=2,
    )
    invoice = InvoiceData(
        source_filename="uber_793.pdf",
        numero_factura="793",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=52508.0,
        fecha_factura=date(2026, 5, 20),
        consolidado=True,
        legible=True,
    )
    match = MatchResult(
        transaction=ok_tx,
        invoice=invoice,
        status="OK",
        documento_soporte="SI",
        needs_review=True,
        match_kind="consolidated_review",
    )
    result = PipelineResult(
        extract=ExtractData(
            card="4444",
            period_month="MAYO",
            period_year=2026,
            transactions=[ok_tx],
            total_cop=52508.0,
            source_filename="mov.xlsx",
        ),
        matches=[match],
        legalization_rows=[
            LegalizationRow(
                numero_factura="RECIBO DE CAJA 793",
                nit_proveedor="9003333333",
                razon_social="TRANSPORTE APP SAS",
                detalle_gasto="TC 4444 SERVICIO DE TRANSPORTE APP",
                articulo_contable="5135950002",
                centro_costo="100-Demo",
                moneda="COP",
                valor_base_cops=52508.0,
                iva=0.0,
                valor_total_compra_cop=52508.0,
                documento_soporte="NO",
                needs_review=True,
            )
        ],
        output_filename="out.xlsx",
        output_path="/tmp/out.xlsx",
    )
    report = build_pipeline_report(result)
    assert report["status"] == "partial"
    assert report["matched_count"] == 1
    assert report["sin_factura_count"] == 0


def test_pipeline_report_facturas_peru_sin_ruc():
    """Verifica pipeline report facturas peru sin ruc."""
    result = PipelineResult(
        extract=ExtractData(
            card="5555",
            period_month="MAYO",
            period_year=2026,
            transactions=[],
            total_cop=50000.0,
            source_filename="mov.xlsx",
        ),
        card_meta=CardMetadata("5555", "Demo User B", "100-Demo"),
        matches=[],
        legalization_rows=[],
        facturas_peru_sin_ruc=[
            {
                "source_filename": "RESTAURANTE DEMO -F001.jpeg",
                "razon_social": "RESTAURANTE DEMO S.A.S",
                "accion": "Revisar boleta y completar RUC del emisor en nit_proveedor",
            }
        ],
        output_filename="out.xlsx",
        output_path="/tmp/out.xlsx",
    )
    report = build_pipeline_report(result)
    assert len(report["facturas_peru_sin_ruc"]) == 1
    entry = report["facturas_peru_sin_ruc"][0]
    assert entry["source_filename"] == "RESTAURANTE DEMO -F001.jpeg"
    assert entry["razon_social"] == "RESTAURANTE DEMO S.A.S"
    assert any("sin RUC" in w for w in report["warnings"])
