"""Tests del motor de conciliación (``reconciliation_engine``).

Cubre: OK/UNMATCHED/AMBIGUOUS/GMF, FX Frankfurter, recibos consolidados Transporte app,
propina compound, multi_factura, SOL 12 % vs COP 2 %, provider_date_review,
sugerencias near-miss y reserva de facturas sugeridas entre UNMATCHED.
"""

from datetime import date
from dataclasses import replace
from unittest.mock import patch

import pytest

from legalizacion_tc.models import ExtractData, InvoiceData, Transaction
from legalizacion_tc.reconciliation_engine import (
    _provider_concept_score,
    _transaction_matches_invoice_provider,
    reconcile,
)
from legalizacion_tc.validation_notes import validation_flag


@pytest.fixture
def consolidated_settings(settings):
    """Fixture o helper: consolidated settings."""
    return replace(
        settings,
        consolidated_receipt_max_days_after=30,
        consolidated_receipt_review_max_months=3,
    )


def test_match_ok_with_mock_fx(settings, sample_invoice_usd, sample_transaction):
    """Verifica match ok with mock fx."""
    extract = ExtractData(
        card="1111",
        period_month="MAYO",
        period_year=2026,
        transactions=[sample_transaction],
        total_cop=400000.0,
        source_filename="mov.xlsx",
    )
    with patch(
        "legalizacion_tc.reconciliation_engine.convert_to_cop",
        return_value=400000.0,
    ):
        matches = reconcile(settings, extract, [sample_invoice_usd])
    assert len(matches) == 1
    assert matches[0].status == "OK"
    assert matches[0].documento_soporte == "SI"


def test_match_original_currency_amount(settings):
    """Verifica match original currency amount."""
    extract = ExtractData(
        card="1111",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="1111",
                tx_date=date(2026, 5, 28),
                description="APP IA SUBSCRIPTION VR MONEDA ORIG 20.0 US",
                currency="USD",
                amount_cop=75000.0,
                row_index=2,
                amount_original=20.0,
                original_currency="USD",
            )
        ],
        total_cop=75000.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="proveedor_ia-FAC-900001.pdf",
        numero_factura="FAC-900001",
        razon_social="PROVEEDOR IA, PBC",
        moneda="USD",
        valor_total_documento=20.0,
        fecha_factura=date(2026, 5, 28),
        detalle_gasto="TC 1111 APP IA SUBSCRIPTION",
        legible=True,
    )
    matches = reconcile(settings, extract, [invoice])
    assert matches[0].status == "OK"


def test_match_ia_via_frankfurter(settings):
    """Sin VR MONEDA ORIG en concepto: concilia vía conversión USD→COP (Frankfurter v2)."""
    extract = ExtractData(
        card="1111",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="1111",
                tx_date=date(2026, 5, 28),
                description="APP IA SUBSCRIPTION",
                currency="COP",
                amount_cop=75000.0,
                row_index=2,
            )
        ],
        total_cop=75000.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="proveedor_ia-FAC-900001.pdf",
        numero_factura="FAC-900001",
        razon_social="PROVEEDOR IA, PBC",
        moneda="USD",
        valor_total_documento=20.0,
        fecha_factura=date(2026, 5, 28),
        detalle_gasto="TC 1111 APP IA SUBSCRIPTION",
        legible=True,
    )
    with patch(
        "legalizacion_tc.reconciliation_engine.convert_to_cop",
        return_value=75000.0,
    ):
        matches = reconcile(settings, extract, [invoice])
    assert matches[0].status == "OK"
    assert matches[0].invoice is invoice


def test_match_web_by_domain_id(settings):
    """Verifica match web provider by domain id."""
    extract = ExtractData(
        card="1111",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="1111",
                tx_date=date(2026, 5, 9),
                description="WEBAPP* DOMAIN#FAC-700001",
                currency="COP",
                amount_cop=56000.0,
                row_index=2,
            )
        ],
        total_cop=56000.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="PROVEEDOR WEB - FAC-700001.pdf",
        numero_factura="FAC-700001",
        razon_social="PROVEEDOR WEB INC",
        moneda="USD",
        valor_total_documento=15.0,
        fecha_factura=date(2026, 5, 9),
        legible=True,
    )
    matches = reconcile(settings, extract, [invoice])
    assert matches[0].status == "OK"
    assert matches[0].invoice is not None


def test_unmatched_when_no_invoice(settings):
    """Verifica unmatched when no invoice."""
    extract = ExtractData(
        card="1111",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="1111",
                tx_date=date(2026, 5, 20),
                description="UNKNOWN",
                currency="COP",
                amount_cop=999.0,
                row_index=2,
            )
        ],
        total_cop=999.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [])
    assert matches[0].documento_soporte == "NO"


def test_consolidated_recibo_matches_multiple_uber_rides(settings):
    """Verifica consolidated recibo matches multiple transport app rides."""
    extract = ExtractData(
        card="4444",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=46646.0,
                row_index=2,
            ),
            Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=7599.0,
                row_index=3,
            ),
        ],
        total_cop=54245.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="recibo_caja_transporte_801.pdf",
        numero_factura="801",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=54245.0,
        fecha_factura=date(2026, 5, 25),
        tipo_documento="recibo_caja_menor",
        consolidado=True,
        legible=True,
    )
    matches = reconcile(settings, extract, [invoice])
    assert len(matches) == 2
    assert all(m.status == "OK" for m in matches)
    assert all(m.documento_soporte == "SI" for m in matches)
    assert all(m.invoice is invoice for m in matches)


def _transport_recibo_810() -> InvoiceData:
    """Helper de prueba: transport recibo 810."""
    return InvoiceData(
        source_filename="TRANSPORTE - RECIBO DE CAJA 810.pdf",
        numero_factura="810",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=62080.47,
        fecha_factura=date(2026, 5, 25),
        tipo_documento="recibo_caja_menor",
        consolidado=True,
        legible=True,
    )


def _transport_recibo_814() -> InvoiceData:
    """Helper de prueba: transport recibo 814."""
    return InvoiceData(
        source_filename="TRANSPORTE - RECIBO DE CAJA 814.pdf",
        numero_factura="814",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=142307.93,
        fecha_factura=date(2026, 6, 5),
        tipo_documento="recibo_caja_menor",
        consolidado=True,
        legible=True,
    )


def _transport_recibo_815() -> InvoiceData:
    """Helper de prueba: transport recibo 815."""
    return InvoiceData(
        source_filename="TRANSPORTE - RECIBO DE CAJA 815.pdf",
        numero_factura="815",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=94095.72,
        fecha_factura=date(2026, 6, 5),
        tipo_documento="recibo_caja_menor",
        consolidado=True,
        legible=True,
    )


def test_consolidated_transport_815_with_mixed_day_pool(settings):
    """Verifica consolidated transport 815 with mixed day pool."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 27),
                description="TRANSPORTE *VIAJE",
                currency="COP",
                amount_cop=37953.0,
                row_index=2,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 27),
                description="TRANSPORTE *VIAJE",
                currency="COP",
                amount_cop=12941.0,
                row_index=3,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 27),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=34691.0,
                row_index=4,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 27),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=8511.0,
                row_index=5,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 27),
                description="IZI*PASTELERIA EPSILON SA",
                currency="COP",
                amount_cop=841708.0,
                row_index=6,
            ),
        ],
        total_cop=925794.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_transport_recibo_815()])
    by_description = {match.transaction.description: match for match in matches}
    uber_matches = [
        match
        for match in matches
        if match.transaction.description != "IZI*PASTELERIA EPSILON SA"
    ]
    assert len(uber_matches) == 4
    assert all(m.status == "OK" for m in uber_matches)
    assert all(m.invoice.numero_factura == "815" for m in uber_matches)
    assert by_description["IZI*PASTELERIA EPSILON SA"].status == "UNMATCHED"


def test_consolidated_transport_810_multi_concept_same_day(settings):
    """Verifica consolidated transport 810 multi concept same day."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 25),
                description="TRANSPORTE *VIAJE",
                currency="COP",
                amount_cop=33772.65,
                row_index=2,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 25),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=28307.82,
                row_index=3,
            ),
        ],
        total_cop=62080.47,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_transport_recibo_810()])
    assert len(matches) == 2
    assert all(m.status == "OK" for m in matches)
    assert all(m.invoice.numero_factura == "810" for m in matches)


def test_consolidated_transport_814_four_concepts_same_day(settings):
    """Verifica consolidated transport 814 four concepts same day."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="TRANSPORTE *VIAJE",
                currency="COP",
                amount_cop=67423.66,
                row_index=2,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=40127.95,
                row_index=3,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=19564.09,
                row_index=4,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="DLC*TRANSPORTE VIAJE",
                currency="COP",
                amount_cop=15192.23,
                row_index=5,
            ),
        ],
        total_cop=142307.93,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_transport_recibo_814()])
    assert len(matches) == 4
    assert all(m.status == "OK" for m in matches)
    assert all(m.invoice.numero_factura == "814" for m in matches)


def test_consolidated_transport_810_and_814_together(settings):
    """Verifica consolidated transport 810 and 814 together."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 25),
                description="TRANSPORTE *VIAJE",
                currency="COP",
                amount_cop=33772.65,
                row_index=2,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 25),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=28307.82,
                row_index=3,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="TRANSPORTE *VIAJE",
                currency="COP",
                amount_cop=67423.66,
                row_index=4,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=40127.95,
                row_index=5,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=19564.09,
                row_index=6,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="DLC*TRANSPORTE VIAJE",
                currency="COP",
                amount_cop=15192.23,
                row_index=7,
            ),
        ],
        total_cop=204388.4,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_transport_recibo_810(), _transport_recibo_814()])
    assert len(matches) == 6
    assert all(m.status == "OK" for m in matches)
    nums = {m.invoice.numero_factura for m in matches}
    assert nums == {"810", "814"}


def test_consolidated_subset_ambiguous_two_equal_sums(settings):
    """Dos cargos distintos con el mismo monto: recibo = uno solo → ambiguo, no concilia."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 25),
                description="TRANSPORTE *VIAJE",
                currency="COP",
                amount_cop=50000.0,
                row_index=2,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 25),
                description="DLC*TRANSPORTE APP",
                currency="COP",
                amount_cop=50000.0,
                row_index=3,
            ),
        ],
        total_cop=100000.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="recibo.pdf",
        numero_factura="999",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 5, 25),
        consolidado=True,
        legible=True,
    )
    matches = reconcile(settings, extract, [invoice])
    assert all(m.status == "UNMATCHED" for m in matches)


def test_consolidated_skipped_in_phase_one(settings):
    """Consolidated invoices match in phase 3, not phase 1."""
    extract = ExtractData(
        card="4444",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=54245.0,
                row_index=2,
            ),
        ],
        total_cop=54245.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="recibo.pdf",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=54245.0,
        fecha_factura=date(2026, 5, 25),
        consolidado=True,
        legible=True,
    )
    matches = reconcile(settings, extract, [invoice])
    assert matches[0].status == "OK"
    assert matches[0].invoice is invoice


def _proveedor_mayorista_invoice() -> InvoiceData:
    """Helper de prueba: proveedor mayorista invoice."""
    return InvoiceData(
        source_filename="PROVEEDOR MAYORISTA - COFE3533414.pdf",
        numero_factura="COFE3533414",
        nit_proveedor="9006666666",
        razon_social="PROVEEDOR MAYORISTA S.A.S.",
        moneda="COP",
        valor_total_documento=214001.0,
        fecha_factura=date(2026, 5, 19),
        legible=True,
    )


def _rest_eta_invoice() -> InvoiceData:
    """Helper de prueba: rest eta invoice."""
    return InvoiceData(
        source_filename="REST-ETA- 106F-141640.pdf",
        numero_factura="106F-141640",
        nit_proveedor="9008888888",
        razon_social="RESTAURANTE ETA S.A.S",
        moneda="COP",
        valor_total_documento=208358.0,
        fecha_factura=date(2026, 5, 21),
        legible=True,
    )


def test_proveedor_mayorista_tiebreak_by_concept(settings):
    """Verifica proveedor mayorista tiebreak by concept."""
    settings_wide = replace(settings, amount_tolerance_pct=0.05)
    extract = ExtractData(
        card="4444",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="4444",
                tx_date=date(2026, 5, 19),
                description="PROVEEDOR MAYORISTA",
                currency="COP",
                amount_cop=214000.0,
                row_index=2,
            )
        ],
        total_cop=214000.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(
        settings_wide,
        extract,
        [_proveedor_mayorista_invoice(), _rest_eta_invoice()],
    )
    assert matches[0].status == "OK"
    assert matches[0].invoice is not None
    assert matches[0].invoice.numero_factura == "COFE3533414"


def test_proveedor_mayorista_concept_with_space():
    """Verifica proveedor mayorista concept with space."""
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 19),
        description="PROVEEDOR MAYORISTA COLOMBIA",
        currency="COP",
        amount_cop=214000.0,
        row_index=2,
    )
    score = _provider_concept_score(tx, _proveedor_mayorista_invoice())
    assert score >= 10


def test_compensar_matches_keyword_not_first_word():
    """Verifica compensar matches keyword not first word."""
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 6),
        description="COMPENSAR",
        currency="COP",
        amount_cop=202500.0,
        row_index=2,
    )
    invoice = InvoiceData(
        source_filename="COMPENSAR- AM93-240.pdf",
        nit_proveedor="8600111111",
        razon_social="CAJA DE COMPENSACION FAMILIAR COMPENSAR",
        moneda="COP",
        valor_total_documento=202500.0,
        fecha_factura=date(2026, 5, 6),
        legible=True,
    )
    assert _transaction_matches_invoice_provider(tx, invoice)


def test_el_social_matches_social_not_el():
    """Verifica el social matches social not el."""
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 21),
        description="EL SOCIAL MEDELLIN",
        currency="COP",
        amount_cop=2217854.0,
        row_index=2,
    )
    invoice = InvoiceData(
        source_filename="EL SOCIAL MEDELLIN S.A.S - PROV-16650.pdf",
        razon_social="EL SOCIAL MEDELLIN S.A.S",
        moneda="COP",
        valor_total_documento=2217854.0,
        fecha_factura=date(2026, 5, 21),
        legible=True,
    )
    assert _transaction_matches_invoice_provider(tx, invoice)


def test_starbucks_no_false_match_estrella(settings):
    """Verifica starbucks no false match estrella."""
    settings_wide = replace(settings, amount_tolerance_pct=0.05)
    extract = ExtractData(
        card="4444",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="4444",
                tx_date=date(2026, 5, 21),
                description="STARBUCKS",
                currency="COP",
                amount_cop=47500.0,
                row_index=2,
            )
        ],
        total_cop=47500.0,
        source_filename="mov.xlsx",
    )
    starbucks = InvoiceData(
        source_filename="STARBUCKS - MOFE-841323.pdf",
        razon_social="ESTRELLA ANDINA S.A.S",
        moneda="COP",
        valor_total_documento=47500.0,
        fecha_factura=date(2026, 5, 21),
        legible=True,
    )
    farmatodo = InvoiceData(
        source_filename="FARMATODO - 667685.pdf",
        razon_social="FARMATODO COLOMBIA S.A.",
        moneda="COP",
        valor_total_documento=47500.0,
        fecha_factura=date(2026, 5, 21),
        legible=True,
    )
    assert _provider_concept_score(extract.transactions[0], starbucks) == 0
    matches = reconcile(settings_wide, extract, [starbucks, farmatodo])
    assert matches[0].status == "AMBIGUOUS"


def test_ambiguous_when_no_provider_in_concept(settings):
    """Verifica ambiguous when no provider in concept."""
    settings_wide = replace(settings, amount_tolerance_pct=0.05)
    extract = ExtractData(
        card="4444",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="4444",
                tx_date=date(2026, 5, 21),
                description="COMPRA GENERICA",
                currency="COP",
                amount_cop=50000.0,
                row_index=2,
            )
        ],
        total_cop=50000.0,
        source_filename="mov.xlsx",
    )
    inv_a = InvoiceData(
        source_filename="a.pdf",
        razon_social="PROVEEDOR A SAS",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 5, 21),
        legible=True,
    )
    inv_b = InvoiceData(
        source_filename="b.pdf",
        razon_social="PROVEEDOR B SAS",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 5, 21),
        legible=True,
    )
    matches = reconcile(settings_wide, extract, [inv_a, inv_b])
    assert matches[0].status == "AMBIGUOUS"


def test_tiebreak_amount_same_provider(settings):
    """Verifica tiebreak amount same provider."""
    settings_wide = replace(settings, amount_tolerance_pct=0.05)
    extract = ExtractData(
        card="4444",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=50000.0,
                row_index=2,
            )
        ],
        total_cop=50000.0,
        source_filename="mov.xlsx",
    )
    exact = InvoiceData(
        source_filename="uber_exact.pdf",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 5, 8),
        legible=True,
    )
    close = InvoiceData(
        source_filename="uber_close.pdf",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=48000.0,
        fecha_factura=date(2026, 5, 8),
        legible=True,
    )
    matches = reconcile(settings_wide, extract, [close, exact])
    assert matches[0].status == "OK"
    assert matches[0].invoice is exact


def _cabify_recibo_802() -> InvoiceData:
    """Helper de prueba: cabify recibo 802."""
    return InvoiceData(
        source_filename="TRANSPORTE-B - RECIBO DE CAJA 802.pdf",
        numero_factura="802",
        nit_proveedor="20123456789",
        razon_social="TRANSPORTE PERU S.A.C",
        moneda="COP",
        valor_total_documento=69781.0,
        fecha_factura=date(2026, 5, 26),
        tipo_documento="recibo_caja_menor",
        consolidado=True,
        legible=True,
    )


def test_consolidated_recibo_single_cabify_ride(settings):
    """Verifica consolidated recibo single cabify ride."""
    extract = ExtractData(
        card="3333",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 4, 30),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=69781.0,
                row_index=2,
            )
        ],
        total_cop=69781.0,
        source_filename="mov.xlsx",
    )
    invoice = _cabify_recibo_802()
    matches = reconcile(settings, extract, [invoice])
    assert len(matches) == 1
    assert matches[0].status == "OK"
    assert matches[0].invoice is invoice


def test_consolidated_recibo_rejects_date_before_charge(settings):
    """Verifica consolidated recibo rejects date before charge."""
    extract = ExtractData(
        card="3333",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 5, 26),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=69781.0,
                row_index=2,
            )
        ],
        total_cop=69781.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="cabify_early.pdf",
        razon_social="TRANSPORTE PERU S.A.C",
        moneda="COP",
        valor_total_documento=69781.0,
        fecha_factura=date(2026, 5, 20),
        consolidado=True,
        legible=True,
    )
    matches = reconcile(settings, extract, [invoice])
    assert matches[0].status == "UNMATCHED"


def test_consolidated_recibo_matches_outside_30_days_with_review(consolidated_settings):
    """Verifica consolidated recibo matches outside 30 days with review."""
    extract = ExtractData(
        card="3333",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 4, 30),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=69781.0,
                row_index=2,
            )
        ],
        total_cop=69781.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="cabify_late.pdf",
        razon_social="TRANSPORTE PERU S.A.C",
        moneda="COP",
        valor_total_documento=69781.0,
        fecha_factura=date(2026, 6, 1),
        consolidado=True,
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [invoice])
    assert matches[0].status == "OK"
    assert matches[0].needs_review is True
    assert matches[0].match_kind == "consolidated_review"
    assert "REVISAR" in matches[0].observacion


def test_consolidated_recibo_rejects_more_than_review_max_months(consolidated_settings):
    """Verifica consolidated recibo rejects more than review max months."""
    extract = ExtractData(
        card="3333",
        period_month="ENERO",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 1, 15),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=69781.0,
                row_index=2,
            )
        ],
        total_cop=69781.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="cabify_too_late.pdf",
        razon_social="TRANSPORTE PERU S.A.C",
        moneda="COP",
        valor_total_documento=69781.0,
        fecha_factura=date(2026, 5, 20),
        consolidado=True,
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [invoice])
    assert matches[0].status == "UNMATCHED"


def test_consolidated_recibo_matches_consecutive_year_with_review(consolidated_settings):
    """Verifica consolidated recibo matches consecutive year with review."""
    extract = ExtractData(
        card="3333",
        period_month="DICIEMBRE",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 12, 15),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=69781.0,
                row_index=2,
            )
        ],
        total_cop=69781.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="cabify_next_year.pdf",
        razon_social="TRANSPORTE PERU S.A.C",
        moneda="COP",
        valor_total_documento=69781.0,
        fecha_factura=date(2027, 1, 10),
        consolidado=True,
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [invoice])
    assert matches[0].status == "OK"
    assert matches[0].needs_review is True
    assert matches[0].match_kind == "consolidated_review"


def test_consolidated_recibo_rejects_non_consecutive_year(consolidated_settings):
    """Verifica consolidated recibo rejects non consecutive year."""
    extract = ExtractData(
        card="3333",
        period_month="DICIEMBRE",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 12, 15),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=69781.0,
                row_index=2,
            )
        ],
        total_cop=69781.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="cabify_skip_year.pdf",
        razon_social="TRANSPORTE PERU S.A.C",
        moneda="COP",
        valor_total_documento=69781.0,
        fecha_factura=date(2028, 1, 10),
        consolidado=True,
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [invoice])
    assert matches[0].status == "UNMATCHED"


def test_consolidated_recibo_in_window_has_no_review_flag(consolidated_settings):
    """Verifica consolidated recibo in window has no review flag."""
    extract = ExtractData(
        card="3333",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 4, 30),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=69781.0,
                row_index=2,
            )
        ],
        total_cop=69781.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="cabify_in_window.pdf",
        razon_social="TRANSPORTE PERU S.A.C",
        moneda="COP",
        valor_total_documento=69781.0,
        fecha_factura=date(2026, 5, 20),
        consolidado=True,
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [invoice])
    assert matches[0].status == "OK"
    assert matches[0].needs_review is False
    assert matches[0].match_kind == "consolidated"


def test_consolidated_recibo_single_rejects_amount_mismatch(settings):
    """Verifica consolidated recibo single rejects amount mismatch."""
    extract = ExtractData(
        card="3333",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 4, 30),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=75000.0,
                row_index=2,
            )
        ],
        total_cop=75000.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_cabify_recibo_802()])
    assert matches[0].status == "UNMATCHED"


def _masa_factura() -> InvoiceData:
    """Helper de prueba: masa factura."""
    return InvoiceData(
        source_filename="RESTAURANTE ALFA S.A.S -TPV 00201.pdf",
        numero_factura="TPV00201",
        nit_proveedor="9004444449",
        razon_social="RESTAURANTE ALFA S.A.S",
        moneda="COP",
        valor_base=509256.0,
        iva=41646.0,
        valor_total_documento=550902.0,
        fecha_factura=date(2026, 5, 8),
        tipo_documento="factura",
        legible=True,
    )


def _masa_recibo_propina() -> InvoiceData:
    """Helper de prueba: masa recibo propina."""
    return InvoiceData(
        source_filename="RESTAURANTE ALFA S.A.S - RECIBO DE CAJA 803.pdf",
        numero_factura="803",
        nit_proveedor="9004444449",
        razon_social="RESTAURANTE ALFA S.A.S",
        moneda="COP",
        valor_total_documento=50926.0,
        fecha_factura=date(2026, 5, 28),
        tipo_documento="recibo_caja_menor",
        es_propina=True,
        detalle_gasto="TC 2222 PROPINA RESTAURANTE ALFA AV 19 8 DE MAYO",
        legible=True,
    )


def _papa_johns_factura() -> InvoiceData:
    """Helper de prueba: papa johns factura."""
    return InvoiceData(
        source_filename="PJ COLSAS - O9PC -349.pdf",
        numero_factura="09PC-349",
        nit_proveedor="9003288341",
        razon_social="PJ COLSAS S.A.S",
        moneda="COP",
        valor_base=156133.0,
        iva=29667.0,
        valor_total_documento=185800.0,
        fecha_factura=date(2026, 5, 13),
        detalle_gasto="TC 2222 ALMUERZO RESTAURANTE BETA VIA DELIVERY APP 13 DE MAYO",
        legible=True,
    )


def _papa_johns_recibo_propina() -> InvoiceData:
    """Helper de prueba: papa johns recibo propina."""
    return InvoiceData(
        source_filename="PJ COLSAS - RECIBO DE CAJA 804.pdf",
        numero_factura="804",
        nit_proveedor="9003288341",
        razon_social="PJ COLSAS",
        moneda="COP",
        valor_total_documento=10300.0,
        fecha_factura=date(2026, 5, 28),
        tipo_documento="recibo_caja_menor",
        es_propina=True,
        detalle_gasto="TC 2222 PROPINA RESTAURANTE BETA VIA DELIVERY APP 13 DE MAYO",
        legible=True,
    )


def _dlili_factura() -> InvoiceData:
    """Helper de prueba: dlili factura."""
    return InvoiceData(
        source_filename="D_LILI PASTELERIA SAS -P89574533.pdf",
        numero_factura="PS574533",
        nit_proveedor="9005555555",
        razon_social="D'LILI PASTELERIA SAS",
        moneda="COP",
        valor_base=53703.0,
        iva=4296.0,
        valor_total_documento=57999.0,
        fecha_factura=date(2026, 5, 13),
        detalle_gasto="TC 2222 PASTELERIA RESTAURANTE GAMMA VIA DELIVERY APP 13 DE MAYO",
        legible=True,
    )


def _dlili_recibo_propina() -> InvoiceData:
    """Helper de prueba: dlili recibo propina."""
    return InvoiceData(
        source_filename="RECIBO DE CAJA 805 - D_LILI PASTELERIA SAS.json",
        numero_factura="805",
        nit_proveedor="9005555555",
        razon_social="D'LILI PASTELERIA SAS",
        moneda="COP",
        valor_total_documento=6301.0,
        fecha_factura=date(2026, 5, 28),
        tipo_documento="recibo_caja_menor",
        es_propina=True,
        detalle_gasto="TC 2222 PROPINA RESTAURANTE GAMMA VIA DELIVERY APP 13 DE MAYO",
        legible=True,
    )


def test_compound_tip_masa(settings):
    """Verifica compound tip rest alpha."""
    extract = ExtractData(
        card="2222",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 5, 8),
                description="REST ALFA SUCURSAL",
                currency="COP",
                amount_cop=601828.0,
                row_index=2,
            )
        ],
        total_cop=601828.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_masa_factura(), _masa_recibo_propina()])
    assert matches[0].status == "OK"
    assert matches[0].match_kind == "compound"
    assert matches[0].invoice is not None
    assert matches[0].secondary_invoice is not None
    assert matches[0].invoice.numero_factura == "TPV00201"
    assert matches[0].secondary_invoice.numero_factura == "803"


def test_compound_tip_rappi_same_day(settings):
    """Verifica compound tip rappi same day."""
    extract = ExtractData(
        card="2222",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 5, 13),
                description="DELIVERY APP*DL",
                currency="COP",
                amount_cop=196100.0,
                row_index=2,
            ),
            Transaction(
                card="2222",
                tx_date=date(2026, 5, 13),
                description="DELIVERY APP*DL",
                currency="COP",
                amount_cop=64300.0,
                row_index=3,
            ),
        ],
        total_cop=260400.0,
        source_filename="mov.xlsx",
    )
    invoices = [
        _papa_johns_factura(),
        _papa_johns_recibo_propina(),
        _dlili_factura(),
        _dlili_recibo_propina(),
    ]
    matches = reconcile(settings, extract, invoices)
    assert all(m.status == "OK" for m in matches)
    assert all(m.match_kind == "compound" for m in matches)
    assert {m.invoice.numero_factura for m in matches} == {"09PC-349", "PS574533"}


def test_compound_without_recibo_stays_unmatched(settings):
    """Verifica compound without recibo stays unmatched."""
    extract = ExtractData(
        card="2222",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 5, 8),
                description="REST ALFA SUCURSAL",
                currency="COP",
                amount_cop=601828.0,
                row_index=2,
            )
        ],
        total_cop=601828.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_masa_factura()])
    assert matches[0].status == "UNMATCHED"


def _rest_alpha_factura_cache_nits() -> InvoiceData:
    """Helper de prueba: masa factura cache nits."""
    return InvoiceData(
        source_filename="RESTAURANTE ALFA S.A.S -TPV 00201.pdf",
        numero_factura="TPV00201",
        nit_proveedor="900444444-9",
        razon_social="RESTAURANTE ALFA S.A.S",
        moneda="COP",
        valor_base=509256.0,
        iva=41646.0,
        valor_total_documento=550902.0,
        fecha_factura=date(2026, 5, 8),
        tipo_documento="factura",
        detalle_gasto="TC 3333 ALMUERZO EN RESTAURANTE ALFA AV 19 8 DE MAYO",
        legible=True,
    )


def _rest_alpha_recibo_propina_cache_nits() -> InvoiceData:
    """Helper de prueba: masa recibo propina cache nits."""
    return InvoiceData(
        source_filename="RESTAURANTE ALFA S.A.S - RECIBO DE CAJA 803.pdf",
        numero_factura="803",
        nit_proveedor="9004444449",
        razon_social="RESTAURANTE ALFA S.A.S",
        moneda="COP",
        valor_total_documento=50926.0,
        fecha_factura=date(2026, 5, 28),
        tipo_documento="recibo_caja_menor",
        es_propina=True,
        detalle_gasto="TC 3333 PROPINA RESTAURANTE ALFA AV 19 8 DE MAYO",
        legible=True,
    )


def _rest_gamma_factura_cache_nits() -> InvoiceData:
    """Helper de prueba: dlili factura cache nits."""
    return InvoiceData(
        source_filename="D_LILI PASTELERIA SAS -P89574533.pdf",
        numero_factura="PS9574533",
        nit_proveedor="900555555-5",
        razon_social="D'LILI PASTELERIA SAS",
        moneda="COP",
        valor_base=53703.0,
        iva=4296.0,
        valor_total_documento=57999.0,
        fecha_factura=date(2026, 5, 13),
        detalle_gasto="TC 3333 COMPRA PASTELERIA D'LILI 13 DE MAYO",
        legible=True,
    )


def _rest_gamma_recibo_propina_cache_nits() -> InvoiceData:
    """Helper de prueba: dlili recibo propina cache nits."""
    return InvoiceData(
        source_filename="RECIBO DE CAJA 805 - D_LILI PASTELERIA SAS.json",
        numero_factura="805",
        nit_proveedor="9005555555",
        razon_social="D'LILI PASTELERIA SAS",
        moneda="COP",
        valor_total_documento=6301.0,
        fecha_factura=date(2026, 5, 28),
        tipo_documento="recibo_caja_menor",
        es_propina=True,
        detalle_gasto="TC 3333 PROPINA D'LILI PASTELERIA 13 DE MAYO",
        legible=True,
    )


def test_compound_tip_rest_alpha_nit_dash_mismatch(settings):
    """Verifica compound tip rest alpha nit dash mismatch."""
    extract = ExtractData(
        card="2222",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 5, 8),
                description="REST ALFA SUCURSAL",
                currency="COP",
                amount_cop=601828.0,
                row_index=2,
            )
        ],
        total_cop=601828.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(
        settings,
        extract,
        [_rest_alpha_factura_cache_nits(), _rest_alpha_recibo_propina_cache_nits()],
    )
    assert matches[0].status == "OK"
    assert matches[0].match_kind == "compound"
    assert matches[0].invoice.numero_factura == "TPV00201"
    assert matches[0].secondary_invoice.numero_factura == "803"


def test_compound_tip_rest_gamma_delivery_nit_and_concept(settings):
    """Verifica compound tip rest gamma rappi nit and concept."""
    extract = ExtractData(
        card="2222",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 5, 13),
                description="DELIVERY APP*DL",
                currency="COP",
                amount_cop=64300.0,
                row_index=2,
            )
        ],
        total_cop=64300.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(
        settings,
        extract,
        [_rest_gamma_factura_cache_nits(), _rest_gamma_recibo_propina_cache_nits()],
    )
    assert matches[0].status == "OK"
    assert matches[0].match_kind == "compound"
    assert matches[0].invoice.numero_factura == "PS9574533"
    assert matches[0].secondary_invoice.numero_factura == "805"


def _rest_demo_invoice() -> InvoiceData:
    """Helper de prueba: sushi bar invoice."""
    return InvoiceData(
        source_filename="RESTAURANTE DEMO -F001.jpeg",
        numero_factura="B050-DEMO001",
        nit_proveedor=None,
        razon_social="RESTAURANTE DEMO S.A.S",
        moneda="SOL",
        valor_base=104.45,
        iva=13.38,
        valor_total_documento=129.0,
        fecha_factura=date(2026, 5, 24),
        detalle_gasto="TC 5555 GASTO REST DEMO 24 DE MAYO",
        legible=True,
    )


def test_sol_match_with_terminal_tip_tolerance(settings):
    """Verifica sol match with terminal tip tolerance."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 24),
                description="RESTAURANTE DEMO",
                currency="COP",
                amount_cop=155091.88,
                amount_original=141.9,
                original_currency="SOL",
                row_index=2,
            )
        ],
        total_cop=155091.88,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_rest_demo_invoice()])
    assert matches[0].status == "OK"
    assert matches[0].invoice.razon_social == "RESTAURANTE DEMO S.A.S"


def test_sol_cop_only_uses_sol_tolerance(settings):
    """Verifica sol cop only uses sol tolerance."""
    settings = replace(
        settings, amount_tolerance_pct=0.02, amount_tolerance_pct_sol=0.12
    )
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 24),
                description="RESTAURANTE DEMO",
                currency="COP",
                amount_cop=155091.88,
                row_index=2,
            )
        ],
        total_cop=155091.88,
        source_filename="mov.xlsx",
    )
    with patch(
        "legalizacion_tc.reconciliation_engine.convert_to_cop",
        return_value=141900.0,
    ):
        matches = reconcile(settings, extract, [_rest_demo_invoice()])
    assert matches[0].status == "OK"


def test_sol_cop_only_fails_beyond_sol_tolerance(settings):
    """Verifica sol cop only fails beyond sol tolerance."""
    settings = replace(
        settings, amount_tolerance_pct=0.02, amount_tolerance_pct_sol=0.12
    )
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 24),
                description="RESTAURANTE DEMO",
                currency="COP",
                amount_cop=155091.88,
                row_index=2,
            )
        ],
        total_cop=155091.88,
        source_filename="mov.xlsx",
    )
    with patch(
        "legalizacion_tc.reconciliation_engine.convert_to_cop",
        return_value=120000.0,
    ):
        matches = reconcile(settings, extract, [_rest_demo_invoice()])
    assert matches[0].status == "UNMATCHED"


def test_sol_still_fails_beyond_sol_tolerance(settings):
    """Verifica sol still fails beyond sol tolerance."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 24),
                description="RESTAURANTE DEMO",
                currency="COP",
                amount_cop=180000.0,
                amount_original=150.0,
                original_currency="SOL",
                row_index=2,
            )
        ],
        total_cop=180000.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_rest_demo_invoice()])
    assert matches[0].status == "UNMATCHED"


def test_sol_beyond_tolerance_sets_suggested_invoice(settings):
    """Verifica sol beyond tolerance sets suggested invoice."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 24),
                description="RESTAURANTE DEMO",
                currency="COP",
                amount_cop=180000.0,
                amount_original=150.0,
                original_currency="SOL",
                row_index=2,
            )
        ],
        total_cop=180000.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_rest_demo_invoice()])
    assert matches[0].status == "UNMATCHED"
    assert matches[0].suggested_invoice is not None
    assert matches[0].suggested_invoice.numero_factura == "B050-DEMO001"


def test_cop_unchanged_at_two_percent(settings):
    """Verifica cop unchanged at two percent."""
    settings = replace(
        settings, amount_tolerance_pct=0.02, amount_tolerance_pct_sol=0.12
    )
    invoice = InvoiceData(
        source_filename="factura_cop.pdf",
        numero_factura="FAC-001",
        nit_proveedor="900123456",
        razon_social="PROVEEDOR TEST",
        moneda="COP",
        valor_total_documento=100000.0,
        fecha_factura=date(2026, 5, 10),
        legible=True,
    )
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 10),
                description="MERCADOPAGO LIMA",
                currency="COP",
                amount_cop=105000.0,
                row_index=2,
            )
        ],
        total_cop=105000.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [invoice])
    assert matches[0].status == "UNMATCHED"
    assert matches[0].failure_reason == "Diferencia de monto"


def _proveedor_peru_delta_invoice() -> InvoiceData:
    """Helper de prueba: proveedor peru delta invoice."""
    return InvoiceData(
        source_filename="PROVEEDOR PERU SAC - B006-00089635.pdf",
        numero_factura="B006-00089635",
        nit_proveedor="20111111111",
        razon_social="PROVEEDOR PERU SAC",
        nombre_comercial="CAFE DELTA",
        moneda="SOL",
        valor_base=622.98,
        iva=65.41,
        valor_total_documento=732.0,
        fecha_factura=date(2026, 5, 26),
        detalle_gasto="TC 5555 GASTO CAFE DELTA 26 DE MAYO",
        legible=True,
        pais_emisor="PE",
    )


def _rest_epsilon_invoice() -> InvoiceData:
    """Helper de prueba: rest epsilon invoice."""
    return InvoiceData(
        source_filename="PASTELERIA EPSILON - B003-00090833.pdf",
        numero_factura="B003-00090833",
        nit_proveedor="20222222222",
        razon_social="PASTELERIA EPSILON S.A.C.",
        moneda="SOL",
        valor_base=558.72,
        iva=100.58,
        valor_total_documento=774.0,
        fecha_factura=date(2026, 5, 27),
        detalle_gasto="TC 5555 GASTO PASTELERIA EPSILON 27 DE MAYO",
        legible=True,
        pais_emisor="PE",
    )


def test_provider_concept_score_uses_nombre_comercial():
    """Verifica provider concept score uses nombre comercial."""
    tx = Transaction(
        card="5555",
        tx_date=date(2026, 5, 26),
        description="CAFE DELTA",
        currency="COP",
        amount_cop=879838.0,
        amount_original=805.0,
        original_currency="SOL",
        row_index=2,
    )
    invoice = _proveedor_peru_delta_invoice()
    assert _provider_concept_score(tx, invoice) >= 4
    assert _provider_concept_score(tx, _rest_epsilon_invoice()) == 0


def test_rest_delta_matches_proveedor_peru_over_epsilon(settings):
    """Verifica rest delta matches proveedor peru over rest epsilon."""
    settings = replace(settings, amount_tolerance_pct_sol=0.12)
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="CAFE DELTA",
                currency="COP",
                amount_cop=879838.0,
                amount_original=805.0,
                original_currency="SOL",
                row_index=2,
            )
        ],
        total_cop=879838.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(
        settings,
        extract,
        [_proveedor_peru_delta_invoice(), _rest_epsilon_invoice()],
    )
    assert matches[0].status == "OK"
    assert matches[0].invoice.numero_factura == "B006-00089635"
    assert matches[0].invoice.razon_social == "PROVEEDOR PERU SAC"


def test_rest_osaka_does_not_score_delta_invoice():
    """Verifica rest osaka does not score amore invoice."""
    tx = Transaction(
        card="5555",
        tx_date=date(2026, 5, 26),
        description="REST ZETA",
        currency="COP",
        amount_cop=755254.0,
        amount_original=690.0,
        original_currency="SOL",
        row_index=3,
    )
    assert _provider_concept_score(tx, _proveedor_peru_delta_invoice()) == 0


def test_delta_wins_proveedor_peru_when_osaka_also_candidate(settings):
    """Verifica amore wins restoinvestment when osaka also candidate."""
    settings = replace(settings, amount_tolerance_pct_sol=0.12)
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="REST ZETA",
                currency="COP",
                amount_cop=755254.0,
                amount_original=690.0,
                original_currency="SOL",
                row_index=2,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 26),
                description="CAFE DELTA",
                currency="COP",
                amount_cop=879838.0,
                amount_original=805.0,
                original_currency="SOL",
                row_index=3,
            ),
        ],
        total_cop=1635092.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(
        settings,
        extract,
        [_proveedor_peru_delta_invoice(), _rest_epsilon_invoice()],
    )
    by_description = {match.transaction.description: match for match in matches}
    assert by_description["CAFE DELTA"].status == "OK"
    assert by_description["CAFE DELTA"].invoice.numero_factura == "B006-00089635"
    assert by_description["REST ZETA"].status == "UNMATCHED"
    assert by_description["REST ZETA"].suggested_invoice is None


def test_suggested_invoice_not_duplicated(settings):
    """Verifica suggested invoice not duplicated."""
    sushi = _rest_demo_invoice()
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 24),
                description="RESTAURANTE DEMO",
                currency="COP",
                amount_cop=180000.0,
                amount_original=150.0,
                original_currency="SOL",
                row_index=2,
            ),
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 24),
                description="REST DEMO",
                currency="COP",
                amount_cop=185000.0,
                amount_original=155.0,
                original_currency="SOL",
                row_index=3,
            ),
        ],
        total_cop=365000.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [sushi])
    suggested = [
        match.suggested_invoice
        for match in matches
        if match.suggested_invoice is not None
    ]
    assert len(suggested) == 1
    assert suggested[0].numero_factura == "B050-DEMO001"


def _cafe_beta_invoice() -> InvoiceData:
    """Helper de prueba: cafe beta invoice."""
    return InvoiceData(
        source_filename="CAFE BETA S.A.S - CBB29786.pdf",
        numero_factura="CBB29786",
        nit_proveedor="9011212121",
        razon_social="CAFE BETA S.A.S",
        moneda="COP",
        valor_base=63796.29,
        iva=5103.71,
        valor_total_documento=75279.63,
        fecha_factura=date(2026, 5, 8),
        detalle_gasto="TC 5555 GASTO CAFE BETA 8 DE MAYO",
        legible=True,
        pais_emisor="CO",
    )


def test_alpha_cafe_beta_amount_date_suggested_not_ok(settings):
    """Verifica galaxi cafe beta amount date suggested not ok."""
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 8),
                description="INVERSIONES ALPHA COL",
                currency="COP",
                amount_cop=75280.0,
                row_index=2,
            )
        ],
        total_cop=75280.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [_cafe_beta_invoice()])
    assert matches[0].status == "UNMATCHED"
    assert matches[0].invoice is None
    assert matches[0].suggested_invoice is not None
    assert matches[0].suggested_invoice.numero_factura == "CBB29786"
    assert "Coincidencia monto/fecha" in matches[0].observacion
    assert validation_flag(matches[0]) == "REVISAR"


def test_amount_date_suggestion_ambiguous_two_same_amount(settings):
    """Verifica amount date suggestion ambiguous two same amount."""
    inv_a = InvoiceData(
        source_filename="a.pdf",
        numero_factura="A-1",
        razon_social="PROVEEDOR A SAS",
        moneda="COP",
        valor_total_documento=75280.0,
        fecha_factura=date(2026, 5, 8),
        legible=True,
    )
    inv_b = InvoiceData(
        source_filename="b.pdf",
        numero_factura="B-1",
        razon_social="PROVEEDOR B SAS",
        moneda="COP",
        valor_total_documento=75280.0,
        fecha_factura=date(2026, 5, 8),
        legible=True,
    )
    extract = ExtractData(
        card="5555",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="5555",
                tx_date=date(2026, 5, 8),
                description="COMPRA GENERICA",
                currency="COP",
                amount_cop=75280.0,
                row_index=2,
            )
        ],
        total_cop=75280.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [inv_a, inv_b])
    assert matches[0].status == "AMBIGUOUS"
    assert matches[0].suggested_invoice is None


def _archies_multi_factura_invoices() -> tuple[InvoiceData, InvoiceData]:
    """Helper de prueba: archies multi factura invoices."""
    factura_a = InvoiceData(
        source_filename="REST-CADENA - FE-9821.pdf",
        numero_factura="FE-9821",
        nit_proveedor="8600123456",
        razon_social="RESTAURANTE CADENA S.A.S",
        nombre_comercial="REST-CADENA",
        moneda="COP",
        valor_base=142016.81,
        iva=27033.19,
        valor_total_documento=169050.0,
        fecha_factura=date(2026, 5, 12),
        detalle_gasto="TC 2222 GASTO DE REPRESENTACIÓN ALMUERZO RESTAURANTE CADENA 12 DE MAYO",
        sin_desglose_iva=True,
        legible=True,
    )
    factura_b = InvoiceData(
        source_filename="REST-CADENA - FE-9822.pdf",
        numero_factura="FE-9822",
        nit_proveedor="8600123456",
        razon_social="RESTAURANTE CADENA S.A.S",
        nombre_comercial="REST-CADENA",
        moneda="COP",
        valor_base=40714.29,
        iva=7735.71,
        valor_total_documento=48450.0,
        fecha_factura=date(2026, 5, 12),
        detalle_gasto="TC 2222 GASTO DE REPRESENTACIÓN ALMUERZO RESTAURANTE CADENA 12 DE MAYO",
        sin_desglose_iva=True,
        legible=True,
    )
    return factura_a, factura_b


def test_multi_factura_two_invoices_one_tx(settings):
    """Verifica multi factura two invoices one tx."""
    factura_a, factura_b = _archies_multi_factura_invoices()
    extract = ExtractData(
        card="2222",
        period_month="MAYO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 5, 12),
                description="RESTAURANTE CADENA",
                currency="COP",
                amount_cop=217500.0,
                row_index=2,
            )
        ],
        total_cop=217500.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [factura_a, factura_b])
    assert len(matches) == 1
    assert matches[0].status == "OK"
    assert matches[0].match_kind == "multi_factura"
    assert {inv.numero_factura for inv in matches[0].component_invoices} == {
        "FE-9821",
        "FE-9822",
    }


def test_multi_factura_ambiguous_subset_stays_unmatched(settings):
    """Verifica multi factura ambiguous subset stays unmatched."""
    inv_a = InvoiceData(
        source_filename="a.pdf",
        numero_factura="A-1",
        nit_proveedor="900111222",
        razon_social="RESTAURANTE X SAS",
        nombre_comercial="REST X",
        moneda="COP",
        valor_total_documento=40000.0,
        fecha_factura=date(2026, 6, 19),
        legible=True,
    )
    inv_b = InvoiceData(
        source_filename="b.pdf",
        numero_factura="B-1",
        nit_proveedor="900111222",
        razon_social="RESTAURANTE X SAS",
        nombre_comercial="REST X",
        moneda="COP",
        valor_total_documento=60000.0,
        fecha_factura=date(2026, 6, 19),
        legible=True,
    )
    inv_c = InvoiceData(
        source_filename="c.pdf",
        numero_factura="C-1",
        nit_proveedor="900111222",
        razon_social="RESTAURANTE X SAS",
        nombre_comercial="REST X",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 6, 19),
        legible=True,
    )
    inv_d = InvoiceData(
        source_filename="d.pdf",
        numero_factura="D-1",
        nit_proveedor="900111222",
        razon_social="RESTAURANTE X SAS",
        nombre_comercial="REST X",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 6, 19),
        legible=True,
    )
    extract = ExtractData(
        card="3333",
        period_month="JUNIO",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 6, 19),
                description="RESTAURANTE X",
                currency="COP",
                amount_cop=100000.0,
                row_index=2,
            )
        ],
        total_cop=100000.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [inv_a, inv_b, inv_c, inv_d])
    assert matches[0].status == "UNMATCHED"
    assert matches[0].match_kind == "simple"


def test_multi_factura_skipped_when_single_invoice_matches_phase_one(settings):
    """Verifica multi factura skipped when single invoice matches phase one."""
    invoice = InvoiceData(
        source_filename="solo.pdf",
        numero_factura="S-1",
        nit_proveedor="900111222",
        razon_social="RESTAURANTE X SAS",
        nombre_comercial="REST X",
        moneda="COP",
        valor_total_documento=100000.0,
        fecha_factura=date(2026, 6, 19),
        legible=True,
    )
    extra = InvoiceData(
        source_filename="extra.pdf",
        numero_factura="E-1",
        nit_proveedor="900111222",
        razon_social="RESTAURANTE X SAS",
        nombre_comercial="REST X",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 6, 19),
        legible=True,
    )
    extract = ExtractData(
        card="3333",
        period_month="JUNIO",
        period_year=2026,
        transactions=[
            Transaction(
                card="3333",
                tx_date=date(2026, 6, 19),
                description="RESTAURANTE X",
                currency="COP",
                amount_cop=100000.0,
                row_index=2,
            )
        ],
        total_cop=100000.0,
        source_filename="mov.xlsx",
    )
    matches = reconcile(settings, extract, [invoice, extra])
    assert matches[0].status == "OK"
    assert matches[0].match_kind == "simple"
    assert matches[0].invoice.numero_factura == "S-1"


def test_provider_date_review_matches_nombre_comercial_outside_window(
    consolidated_settings,
):
    """Verifica provider date review matches nombre comercial outside window."""
    extract = ExtractData(
        card="2222",
        period_month="JUNIO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 6, 18),
                description="OSAKI ARTISAN",
                currency="COP",
                amount_cop=373120.0,
                row_index=2,
            )
        ],
        total_cop=373120.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="restaurante.pdf",
        numero_factura="F-100",
        razon_social="TAKAMI S.A.",
        nombre_comercial="OSAKI ARTISAN",
        moneda="COP",
        valor_total_documento=373120.0,
        fecha_factura=date(2026, 5, 18),
        sin_desglose_iva=True,
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [invoice])
    assert matches[0].status == "OK"
    assert matches[0].needs_review is True
    assert matches[0].match_kind == "provider_date_review"
    assert validation_flag(matches[0]) == "REVISAR"
    assert "REVISAR" in matches[0].observacion
    assert "31 días" in matches[0].observacion


def test_provider_date_review_rejects_beyond_max_months(consolidated_settings):
    """Verifica provider date review rejects beyond max months."""
    extract = ExtractData(
        card="2222",
        period_month="JUNIO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 6, 18),
                description="CAFE CENTRAL",
                currency="COP",
                amount_cop=50000.0,
                row_index=2,
            )
        ],
        total_cop=50000.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="cafe.pdf",
        numero_factura="C-1",
        razon_social="CAFE CENTRAL SAS",
        nombre_comercial="CAFE CENTRAL",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 2, 1),
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [invoice])
    assert matches[0].status == "UNMATCHED"


def test_provider_date_review_ambiguous_stays_unmatched(consolidated_settings):
    """Verifica provider date review ambiguous stays unmatched."""
    extract = ExtractData(
        card="2222",
        period_month="JUNIO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 6, 18),
                description="CAFE CENTRAL",
                currency="COP",
                amount_cop=50000.0,
                row_index=2,
            )
        ],
        total_cop=50000.0,
        source_filename="mov.xlsx",
    )
    inv_a = InvoiceData(
        source_filename="cafe_a.pdf",
        numero_factura="C-1",
        razon_social="CAFE CENTRAL SAS",
        nombre_comercial="CAFE CENTRAL",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 5, 18),
        legible=True,
    )
    inv_b = InvoiceData(
        source_filename="cafe_b.pdf",
        numero_factura="C-2",
        razon_social="CAFE CENTRAL SAS",
        nombre_comercial="CAFE CENTRAL",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 5, 18),
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [inv_a, inv_b])
    assert matches[0].status == "UNMATCHED"


def test_provider_date_review_requires_razon_or_nombre_comercial(
    consolidated_settings,
):
    """Verifica provider date review requires razon or nombre comercial."""
    extract = ExtractData(
        card="2222",
        period_month="JUNIO",
        period_year=2026,
        transactions=[
            Transaction(
                card="2222",
                tx_date=date(2026, 6, 18),
                description="CAFE CENTRAL",
                currency="COP",
                amount_cop=50000.0,
                row_index=2,
            )
        ],
        total_cop=50000.0,
        source_filename="mov.xlsx",
    )
    invoice = InvoiceData(
        source_filename="cafe.pdf",
        numero_factura="C-1",
        razon_social="PROVEEDOR DISTINTO SAS",
        nombre_comercial="OTRO NOMBRE",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 5, 18),
        detalle_gasto="TC 2222 GASTO CAFE CENTRAL 18 DE MAYO",
        legible=True,
    )
    matches = reconcile(consolidated_settings, extract, [invoice])
    assert matches[0].status == "UNMATCHED"
