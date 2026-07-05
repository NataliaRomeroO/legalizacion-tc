"""Tests de mapeo MatchResult → LegalizationRow: IVA, GMF, histórico, moneda extranjera."""

from datetime import date
from dataclasses import replace

import pytest

from legalizacion_tc.metadata_mapper import (
    GMF_NIT,
    _extract_matches_base_plus_iva,
    _find_history,
    _historico_detalle_is_generic,
    _normalize_razon_social,
    build_legalization_rows,
)
from legalizacion_tc.models import CardMetadata, InvoiceData, MatchResult, ProviderHistory, Transaction


def test_excel_cols_use_preliminar_cop(card_meta, sample_invoice_usd, sample_transaction, settings):
    """Verifica excel cols use preliminar cop."""
    match = MatchResult(
        transaction=sample_transaction,
        invoice=sample_invoice_usd,
        status="OK",
        documento_soporte="SI",
    )
    rows, new_nits = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 1
    row = rows[0]
    assert row.valor_base_cops == 400000.0
    assert row.valor_total_compra_cop == 400000.0
    assert row.valor_base_usd == 100.0
    assert row.iva == 0.0
    assert row.documento_soporte == "SI"
    assert row.detalle_gasto == "TC 1111 GASTO PROVEEDOR CLOUD SAS"


def test_detalle_from_invoice_takes_priority(card_meta, sample_transaction, settings):
    """Verifica detalle from invoice takes priority."""
    invoice = InvoiceData(
        source_filename="uber.pdf",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=25000.0,
        fecha_factura=date(2026, 5, 7),
        detalle_gasto="TC 4444 SERVICIO DE TRANSPORTE APP 7 DE MAYO",
        legible=True,
    )
    historico = {
        "9003333333": ProviderHistory(
            nit="9003333333",
            razon_social="TRANSPORTE APP SAS",
            detalle_gasto="TC 4444 SERVICIO DE TRANSPORTE APP",
        )
    }
    match = MatchResult(
        transaction=sample_transaction,
        invoice=invoice,
        status="OK",
        documento_soporte="SI",
    )
    rows, _ = build_legalization_rows([match], card_meta, historico, settings)
    assert rows[0].detalle_gasto == "TC 4444 SERVICIO DE TRANSPORTE APP 7 DE MAYO"


def test_detalle_falls_back_to_generic_historico(card_meta, sample_transaction, settings):
    """Verifica detalle falls back to generic historico."""
    invoice = InvoiceData(
        source_filename="uber.pdf",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=25000.0,
        legible=True,
    )
    historico = {
        "9003333333": ProviderHistory(
            nit="9003333333",
            razon_social="TRANSPORTE APP SAS",
            detalle_gasto="TC 1111 SERVICIO DE TRANSPORTE APP",
        )
    }
    match = MatchResult(
        transaction=sample_transaction,
        invoice=invoice,
        status="OK",
        documento_soporte="SI",
    )
    rows, _ = build_legalization_rows([match], card_meta, historico, settings)
    assert rows[0].detalle_gasto == "TC 1111 SERVICIO DE TRANSPORTE APP"


def test_detalle_rejects_specific_historico_with_date(card_meta, sample_transaction, settings):
    """Verifica detalle rejects specific historico with date."""
    invoice = InvoiceData(
        source_filename="uber.pdf",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_total_documento=25000.0,
        legible=True,
    )
    historico = {
        "9003333333": ProviderHistory(
            nit="9003333333",
            razon_social="TRANSPORTE APP SAS",
            detalle_gasto="TC 4444 SERVICIO DE TRANSPORTE APP 7 DE MAYO",
        )
    }
    match = MatchResult(
        transaction=sample_transaction,
        invoice=invoice,
        status="OK",
        documento_soporte="SI",
    )
    rows, _ = build_legalization_rows([match], card_meta, historico, settings)
    assert rows[0].detalle_gasto == "TC 1111 GASTO TRANSPORTE APP SAS"


def test_detalle_generic_when_no_invoice_detalle_and_no_historico(
    card_meta, sample_transaction, settings
):
    """Verifica detalle generic when no invoice detalle and no historico."""
    invoice = InvoiceData(
        source_filename="new_vendor.pdf",
        nit_proveedor="9001111111",
        razon_social="PROVEEDOR NUEVO SAS",
        moneda="COP",
        valor_total_documento=50000.0,
        legible=True,
    )
    match = MatchResult(
        transaction=sample_transaction,
        invoice=invoice,
        status="OK",
        documento_soporte="SI",
    )
    rows, new_nits = build_legalization_rows([match], card_meta, {}, settings)
    assert rows[0].detalle_gasto == "TC 1111 GASTO PROVEEDOR NUEVO SAS"
    assert "9001111111" in new_nits


def test_historico_detalle_is_generic():
    """Verifica historico detalle is generic."""
    assert _historico_detalle_is_generic("TC 4444 SERVICIO DE TRANSPORTE APP")
    assert _historico_detalle_is_generic("TC 4444 COMPRA MERCADO")
    assert not _historico_detalle_is_generic("TC 4444 SERVICIO DE TRANSPORTE APP 7 DE MAYO")
    assert not _historico_detalle_is_generic(
        "TC 4444_ COMPRA DE VUELO MARIANA RAMOS Y DEMO USER D 26 MAYO"
    )
    assert not _historico_detalle_is_generic("TC 4444 Compra mercado medellin 26 mayo")


def test_normalize_razon_social_ignores_commas_and_periods():
    """Verifica normalize razon social ignores commas and periods."""
    assert _normalize_razon_social("PROVEEDOR IA, PBC") == _normalize_razon_social("PROVEEDOR IA PBC")
    assert _normalize_razon_social("PROVEEDOR MAYORISTA S.A.S.") == _normalize_razon_social(
        "PROVEEDOR MAYORISTA SAS"
    )


def test_find_history_by_razon_social_without_nit():
    """Verifica find history by razon social without nit."""
    historico = {
        "511111111111-99": ProviderHistory(
            nit="511111111111-99",
            razon_social="PROVEEDOR IA PBC",
            detalle_gasto="TC 1111 SERVICIO APLICACIONES",
            articulo_contable="5135950002 - SERVICIOS APLICACIONES",
        )
    }
    history = _find_history("", "PROVEEDOR IA, PBC", historico)
    assert history is not None
    assert history.nit == "511111111111-99"


def test_build_row_fills_nit_from_historico_by_razon_social(card_meta, settings):
    """Verifica build row fills nit from historico by razon social."""
    invoice = InvoiceData(
        source_filename="proveedor_ia.pdf",
        nit_proveedor=None,
        razon_social="PROVEEDOR IA, PBC",
        moneda="USD",
        valor_total_documento=20.0,
        fecha_factura=date(2026, 5, 28),
        legible=True,
    )
    tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 28),
        description="APP IA SUBSCRIPTION",
        currency="COP",
        amount_cop=75000.0,
        row_index=2,
    )
    historico = {
        "511111111111-99": ProviderHistory(
            nit="511111111111-99",
            razon_social="PROVEEDOR IA PBC",
            detalle_gasto="TC 1111 SERVICIO APLICACIONES",
            articulo_contable="5135950002 - SERVICIOS APLICACIONES",
        )
    }
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, new_nits = build_legalization_rows([match], card_meta, historico, settings)
    assert rows[0].nit_proveedor == "511111111111-99"
    assert rows[0].articulo_contable == "5135950002 - SERVICIOS APLICACIONES"
    assert new_nits == []


def test_gmf_movements_consolidated_into_single_row(card_meta, sample_invoice_usd, settings):
    """Verifica gmf movements consolidated into single row."""
    gmf_tx_1 = Transaction(
        card="1111",
        tx_date=date(2026, 5, 10),
        description="4X1000 PERSONA JURIDICA",
        currency="COP",
        amount_cop=1200.0,
        row_index=2,
        is_gmf=True,
    )
    gmf_tx_2 = Transaction(
        card="1111",
        tx_date=date(2026, 5, 20),
        description="4X1000 PERSONA JURIDICA",
        currency="COP",
        amount_cop=800.0,
        row_index=3,
        is_gmf=True,
    )
    regular_match = MatchResult(
        transaction=Transaction(
            card="1111",
            tx_date=date(2026, 5, 10),
            description="SERVICIO CLOUD DEMO",
            currency="COP",
            amount_cop=400000.0,
            row_index=4,
        ),
        invoice=sample_invoice_usd,
        status="OK",
        documento_soporte="SI",
    )
    matches = [
        MatchResult(
            transaction=gmf_tx_1,
            invoice=None,
            status="GMF",
            documento_soporte="SI",
        ),
        MatchResult(
            transaction=gmf_tx_2,
            invoice=None,
            status="GMF",
            documento_soporte="SI",
        ),
        regular_match,
    ]
    rows, _ = build_legalization_rows(matches, card_meta, {}, settings)
    assert len(rows) == 2
    gmf_row = rows[0]
    assert gmf_row.nit_proveedor == GMF_NIT
    assert gmf_row.valor_base_cops == 2000.0
    assert gmf_row.valor_total_compra_cop == 2000.0
    assert gmf_row.detalle_gasto == "TC 1111 GMF "
    assert gmf_row.documento_soporte == "NO"
    assert rows[1].nit_proveedor == "900123456"


def test_gmf_detalle_ignores_historico(settings):
    """Verifica gmf detalle ignores historico."""
    card_meta = CardMetadata("2222", "Demo User B", "100-Demo")
    gmf_tx = Transaction(
        card="2222",
        tx_date=date(2026, 5, 10),
        description="4X1000 PERSONA JURIDICA",
        currency="COP",
        amount_cop=1500.0,
        row_index=2,
        is_gmf=True,
    )
    historico = {
        GMF_NIT: ProviderHistory(
            nit=GMF_NIT,
            razon_social="BANCOLOMBIA",
            detalle_gasto="TC 4444 OTRO TEXTO",
            articulo_contable="5115950001 - GMF IMPUESTOS",
        )
    }
    matches = [
        MatchResult(
            transaction=gmf_tx,
            invoice=None,
            status="GMF",
            documento_soporte="SI",
        )
    ]
    rows, _ = build_legalization_rows(matches, card_meta, historico, settings)
    assert len(rows) == 1
    assert rows[0].detalle_gasto == "TC 2222 GMF "
    assert rows[0].articulo_contable == historico[GMF_NIT].articulo_contable


def test_documento_soporte_cop_is_no(card_meta, settings):
    """Verifica documento soporte cop is no."""
    invoice = InvoiceData(
        source_filename="factura_cop.pdf",
        nit_proveedor="900123456",
        razon_social="PROVEEDOR SAS",
        moneda="COP",
        valor_total_documento=50000.0,
        fecha_factura=date(2026, 5, 15),
        legible=True,
    )
    tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 15),
        description="PROVEEDOR SAS",
        currency="COP",
        amount_cop=50000.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert rows[0].documento_soporte == "NO"


def test_el_social_cop_full_charge(card_meta, settings):
    """Cargo > parte gravada (propina embebida) → split gravada + exenta."""
    invoice = InvoiceData(
        source_filename="EL SOCIAL MEDELLIN S.A.S - PROV-16650.pdf",
        numero_factura="PROV-16650",
        nit_proveedor="900123456",
        razon_social="EL SOCIAL MEDELLIN S.A.S",
        moneda="COP",
        valor_base=1879537.04,
        iva=150362.97,
        valor_total_documento=2217854.0,
        fecha_factura=date(2026, 5, 15),
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 15),
        description="EL SOCIAL MEDELLIN",
        currency="COP",
        amount_cop=2217854.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 2
    gravada, exenta = rows
    assert gravada.valor_base_cops == 791384.0
    assert gravada.iva == 150362.97
    assert gravada.valor_total_compra_cop == pytest.approx(941746.97)
    assert exenta.valor_base_cops == pytest.approx(1276107.03)
    assert exenta.iva == 0.0
    assert exenta.valor_total_compra_cop == pytest.approx(1276107.03)
    for row in rows:
        if row.iva and row.iva > 0:
            assert row.valor_base_cops + row.iva == pytest.approx(row.valor_total_compra_cop)
    assert sum(r.valor_total_compra_cop for r in rows) == pytest.approx(tx.amount_cop)


def test_cop_discriminated_charge(card_meta, settings):
    """Extracto = base+iva con ítems gravados y exentos → 2 filas COP."""
    invoice = InvoiceData(
        source_filename="factura_cop.pdf",
        nit_proveedor="900123456",
        razon_social="PROVEEDOR SAS",
        moneda="COP",
        valor_base=1879537.04,
        iva=150362.96,
        valor_total_documento=2029900.0,
        fecha_factura=date(2026, 5, 15),
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 15),
        description="PROVEEDOR SAS",
        currency="COP",
        amount_cop=2029900.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 2
    gravada, exenta = rows
    assert gravada.valor_base_cops == 791384.0
    assert gravada.iva == 150362.96
    assert gravada.valor_total_compra_cop == pytest.approx(941746.96)
    assert exenta.valor_base_cops == pytest.approx(1088153.04)
    assert exenta.iva == 0.0
    assert exenta.valor_total_compra_cop == pytest.approx(1088153.04)
    assert gravada.numero_factura == exenta.numero_factura


def test_cop_homogeneous_iva_single_row(card_meta, settings):
    """Extracto = base+iva y base×19% ≈ iva → una sola fila."""
    invoice = InvoiceData(
        source_filename="factura_cop_homog.pdf",
        nit_proveedor="900123456",
        razon_social="PROVEEDOR SAS",
        moneda="COP",
        valor_base=791384.0,
        iva=150362.96,
        valor_total_documento=941746.96,
        fecha_factura=date(2026, 5, 15),
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 15),
        description="PROVEEDOR SAS",
        currency="COP",
        amount_cop=941746.96,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 1
    row = rows[0]
    assert row.valor_base_cops == 791384.0
    assert row.iva == 150362.96
    assert row.valor_total_compra_cop == pytest.approx(941746.96)


def test_proveedor_mayorista_mixed_iva_split(card_meta, settings):
    """Verifica proveedor mayorista mixed iva split."""
    invoice = InvoiceData(
        source_filename="PROVEEDOR MAYORISTA - COFE2710171.pdf",
        numero_factura="COFE2710171",
        nit_proveedor="9006666666",
        razon_social="PROVEEDOR MAYORISTA S.A.S.",
        moneda="COP",
        valor_base=198272.0,
        iva=32827.0,
        valor_total_documento=231099.0,
        fecha_factura=date(2026, 4, 14),
        detalle_gasto="TC 4444 COMPRA MERCADO PROVEEDOR MAYORISTA 14 DE ABRIL",
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 4, 14),
        description="PROVEEDOR MAYORISTA",
        currency="COP",
        amount_cop=231099.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 2
    gravada, exenta = rows
    assert gravada.valor_base_cops == 172774.0
    assert gravada.iva == 32827.0
    assert gravada.valor_total_compra_cop == pytest.approx(205601.0)
    assert exenta.valor_base_cops == pytest.approx(25498.0)
    assert exenta.iva == 0.0
    assert exenta.valor_total_compra_cop == pytest.approx(25498.0)
    assert gravada.valor_total_compra_cop + exenta.valor_total_compra_cop == pytest.approx(
        231099.0
    )


def test_cop_mixed_iva_with_other_taxes_split(card_meta, settings):
    """IVA mixto + otros_impuestos (INC/ICUI): cargo = base+iva+otros → 2 filas."""
    invoice = InvoiceData(
        source_filename="SUPERMERCADO - FV123.pdf",
        numero_factura="FV123",
        nit_proveedor="900123456",
        razon_social="SUPERMERCADO SAS",
        moneda="COP",
        valor_base=129416.0,
        iva=8184.0,
        otros_impuestos=23470.0,
        valor_total_documento=161070.0,
        fecha_factura=date(2026, 6, 8),
        detalle_gasto="TC 4444 COMPRA MERCADO 8 DE JUNIO",
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 6, 8),
        description="SUPERMERCADO",
        currency="COP",
        amount_cop=161070.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 2
    gravada, exenta = rows
    assert gravada.valor_base_cops == 43074.0
    assert gravada.iva == 8184.0
    assert gravada.valor_total_compra_cop == pytest.approx(51258.0)
    assert exenta.valor_base_cops == pytest.approx(109812.0)
    assert exenta.iva == 0.0
    assert exenta.valor_total_compra_cop == pytest.approx(109812.0)
    assert gravada.valor_total_compra_cop + exenta.valor_total_compra_cop == pytest.approx(
        161070.0
    )


def test_proveedor_mayorista_split_ignores_amount_tolerance_pct(card_meta, settings):
    """IVA ~3.5% bajo base×19%: split aunque AMOUNT_TOLERANCE_PCT sea 5%."""
    settings = replace(settings, amount_tolerance_pct=0.05)
    invoice = InvoiceData(
        source_filename="PROVEEDOR MAYORISTA - COFE999.pdf",
        numero_factura="COFE999",
        nit_proveedor="9006666666",
        razon_social="PROVEEDOR MAYORISTA S.A.S.",
        moneda="COP",
        valor_base=2327035.0,
        iva=426861.0,
        valor_total_documento=2753900.0,
        fecha_factura=date(2026, 4, 14),
        detalle_gasto="TC 4444 COMPRA MERCADO PROVEEDOR MAYORISTA 14 DE ABRIL",
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 4, 14),
        description="PROVEEDOR MAYORISTA",
        currency="COP",
        amount_cop=2753900.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 2
    gravada, exenta = rows
    assert gravada.valor_base_cops == 2246637.0
    assert gravada.iva == 426861.0
    assert gravada.valor_total_compra_cop == pytest.approx(2673498.0)
    assert exenta.valor_base_cops == pytest.approx(80402.0)
    assert exenta.iva == 0.0
    assert exenta.valor_total_compra_cop == pytest.approx(80402.0)
    for row in rows:
        if row.iva and row.iva > 0:
            assert row.valor_base_cops + row.iva == pytest.approx(row.valor_total_compra_cop)
    assert sum(r.valor_total_compra_cop for r in rows) == pytest.approx(tx.amount_cop)


def test_sin_desglose_splits_when_charge_has_tip(card_meta, settings):
    """sin_desglose_iva=True pero cargo > base+iva (propina) → sí desglosa/split."""
    invoice = InvoiceData(
        source_filename="local_propina.pdf",
        numero_factura="FE-200",
        nit_proveedor="900111222",
        razon_social="LOCAL PROVEEDOR SAS",
        moneda="COP",
        valor_base=31428.56,
        iva=5971.44,
        valor_total_documento=37400.0,
        fecha_factura=date(2026, 5, 12),
        sin_desglose_iva=True,
        legible=True,
    )
    tx = Transaction(
        card="2222",
        tx_date=date(2026, 5, 12),
        description="LOCAL PROVEEDOR",
        currency="COP",
        amount_cop=40543.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="NO")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 2
    gravada, exenta = rows
    assert gravada.valor_base_cops == pytest.approx(31428.56)
    assert gravada.iva == pytest.approx(5971.44)
    assert gravada.valor_total_compra_cop == pytest.approx(37400.0)
    assert exenta.valor_base_cops == pytest.approx(3143.0)
    assert exenta.iva == 0.0
    assert exenta.valor_total_compra_cop == pytest.approx(3143.0)
    for row in rows:
        if row.iva and row.iva > 0:
            assert row.valor_base_cops + row.iva == pytest.approx(row.valor_total_compra_cop)
    assert sum(r.valor_total_compra_cop for r in rows) == pytest.approx(tx.amount_cop)


def test_latam_otros_impuestos_as_iva_homogeneous(card_meta, settings):
    """iva=0 pero otros_impuestos es IVA efectivo homogéneo → una fila con IVA."""
    invoice = InvoiceData(
        source_filename="LATAM - TKT1.pdf",
        numero_factura="TKT1",
        nit_proveedor="900999888",
        razon_social="LATAM AIRLINES",
        moneda="COP",
        valor_base=54978.0,
        iva=0.0,
        otros_impuestos=10450.0,
        valor_total_documento=65428.0,
        fecha_factura=date(2026, 5, 10),
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 10),
        description="LATAM",
        currency="COP",
        amount_cop=65428.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="NO")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 1
    row = rows[0]
    assert row.valor_base_cops == 54978.0
    assert row.iva == 10450.0
    assert row.valor_total_compra_cop == pytest.approx(65428.0)
    assert row.valor_base_cops + row.iva == pytest.approx(row.valor_total_compra_cop)


def test_latam_otros_impuestos_as_iva_mixed(card_meta, settings):
    """iva=0, otros_impuestos como IVA mixto → 2 filas."""
    invoice = InvoiceData(
        source_filename="LATAM - TKT2.pdf",
        numero_factura="TKT2",
        nit_proveedor="900999888",
        razon_social="LATAM AIRLINES",
        moneda="COP",
        valor_base=366560.0,
        iva=0.0,
        otros_impuestos=67840.0,
        valor_total_documento=434400.0,
        fecha_factura=date(2026, 5, 10),
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 10),
        description="LATAM",
        currency="COP",
        amount_cop=434400.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="NO")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 2
    gravada, exenta = rows
    assert gravada.valor_base_cops == 357053.0
    assert gravada.iva == 67840.0
    assert gravada.valor_total_compra_cop == pytest.approx(424893.0)
    assert exenta.valor_base_cops == pytest.approx(9507.0)
    assert exenta.iva == 0.0
    assert exenta.valor_total_compra_cop == pytest.approx(9507.0)
    for row in rows:
        if row.iva and row.iva > 0:
            assert row.valor_base_cops + row.iva == pytest.approx(row.valor_total_compra_cop)
    assert sum(r.valor_total_compra_cop for r in rows) == pytest.approx(tx.amount_cop)


def test_restaurant_multi_factura_no_iva_split(card_meta, settings):
    """Restaurante COP multi_factura: dos filas sin desglose IVA."""
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
    tx = Transaction(
        card="2222",
        tx_date=date(2026, 5, 12),
        description="RESTAURANTE CADENA",
        currency="COP",
        amount_cop=217500.0,
        row_index=2,
    )
    match = MatchResult(
        transaction=tx,
        invoice=factura_a,
        status="OK",
        documento_soporte="NO",
        match_kind="multi_factura",
        component_invoices=[factura_a, factura_b],
    )
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 2
    by_numero = {row.numero_factura: row for row in rows}
    assert by_numero["FE-9821"].valor_base_cops == 169050.0
    assert by_numero["FE-9821"].iva == 0.0
    assert by_numero["FE-9821"].valor_total_compra_cop == 169050.0
    assert by_numero["FE-9822"].valor_base_cops == 48450.0
    assert by_numero["FE-9822"].iva == 0.0
    assert by_numero["FE-9822"].valor_total_compra_cop == 48450.0
    assert (
        by_numero["FE-9821"].valor_total_compra_cop
        + by_numero["FE-9822"].valor_total_compra_cop
        == tx.amount_cop
    )


def test_restaurant_explicit_flag(card_meta, settings):
    """Verifica restaurant explicit flag."""
    invoice = InvoiceData(
        source_filename="local_comidas.pdf",
        numero_factura="FE-100",
        nit_proveedor="900111222",
        razon_social="LOCAL COMIDAS SAS",
        moneda="COP",
        valor_base=100000.0,
        iva=8000.0,
        valor_total_documento=108000.0,
        fecha_factura=date(2026, 5, 12),
        sin_desglose_iva=True,
        legible=True,
    )
    tx = Transaction(
        card="2222",
        tx_date=date(2026, 5, 12),
        description="LOCAL COMIDAS",
        currency="COP",
        amount_cop=108000.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="NO")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 1
    assert rows[0].valor_base_cops == 108000.0
    assert rows[0].iva == 0.0


def test_restaurant_keyword_from_bank(card_meta, settings):
    """Verifica restaurant keyword from bank."""
    invoice = InvoiceData(
        source_filename="restaurante_flor.pdf",
        numero_factura="INV-501",
        nit_proveedor="900222333",
        razon_social="RESTAURANTE FLOR SAS",
        nombre_comercial="FLOR",
        moneda="COP",
        valor_base=100000.0,
        iva=8000.0,
        valor_total_documento=108000.0,
        fecha_factura=date(2026, 5, 12),
        detalle_gasto="TC 2222 ALMUERZO RESTAURANTE FLOR 12 DE MAYO",
        legible=True,
    )
    tx = Transaction(
        card="2222",
        tx_date=date(2026, 5, 12),
        description="RESTAURANTE FLOR",
        currency="COP",
        amount_cop=108000.0,
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="NO")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 1
    assert rows[0].iva == 0.0
    assert rows[0].valor_base_cops == 108000.0


def test_usd_with_iva_split(card_meta, settings):
    """USD: sin IVA; monto USD del extracto; COPS y total = preliminar."""
    invoice = InvoiceData(
        source_filename="saas_usd.pdf",
        nit_proveedor="900123456",
        razon_social="SAAS INC",
        moneda="USD",
        valor_base=100.0,
        iva=19.0,
        valor_total_documento=119.0,
        fecha_factura=date(2026, 5, 10),
        legible=True,
    )
    tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 10),
        description="SAAS INC",
        currency="COP",
        amount_cop=500000.0,
        amount_original=119.0,
        original_currency="USD",
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    row = rows[0]
    assert row.moneda == "USD"
    assert row.valor_base_usd == 119.0
    assert row.valor_base_clp is None
    assert row.valor_base_sol is None
    assert row.iva == 0.0
    assert row.valor_base_cops == 500000.0
    assert row.valor_total_compra_cop == 500000.0
    assert row.documento_soporte == "SI"


def test_clp_invoice_columns(card_meta, settings):
    """Verifica clp invoice columns."""
    invoice = InvoiceData(
        source_filename="latam_clp.pdf",
        nit_proveedor="900123456",
        razon_social="LATAM",
        moneda="CLP",
        valor_total_documento=85000.0,
        fecha_factura=date(2026, 5, 10),
        legible=True,
    )
    tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 10),
        description="LATAM",
        currency="COP",
        amount_cop=380000.0,
        amount_original=85000.0,
        original_currency="CLP",
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    row = rows[0]
    assert row.moneda == "CLP"
    assert row.valor_base_usd is None
    assert row.valor_base_clp == 85000.0
    assert row.valor_base_sol is None
    assert row.iva == 0.0
    assert row.valor_base_cops == 380000.0
    assert row.valor_total_compra_cop == 380000.0


def test_foreign_invoice_with_mixed_iva_fields_stays_single_row(card_meta, settings):
    """Moneda extranjera: aunque base/IVA no cuadren al 19% COP, una sola fila sin desglose."""
    invoice = InvoiceData(
        source_filename="proveedor_extranjero.pdf",
        numero_factura="EXT-1001",
        nit_proveedor="20123456789",
        razon_social="PROVEEDOR EXTRANJERO S.A.C.",
        moneda="SOL",
        valor_base=50.0,
        iva=9.0,
        otros_impuestos=5.0,
        valor_total_documento=64.0,
        fecha_factura=date(2026, 6, 2),
        detalle_gasto="TC 4444 GASTO PROVEEDOR EXTRANJERO 2 DE JUNIO",
        sin_desglose_iva=True,
        legible=True,
        pais_emisor="PE",
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 6, 2),
        description="COMERCIO EXTRANJERO",
        currency="COP",
        amount_cop=70000.0,
        amount_original=64.0,
        original_currency="SOL",
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 1
    row = rows[0]
    assert row.moneda == "SOL"
    assert row.valor_base_sol == 64.0
    assert row.iva == 0.0
    assert row.valor_base_cops == 70000.0
    assert row.valor_total_compra_cop == 70000.0


def test_usd_non_homogeneous_iva_stays_single_row(card_meta, settings):
    """Verifica usd non homogeneous iva stays single row."""
    invoice = InvoiceData(
        source_filename="vendor_usd.pdf",
        numero_factura="US-42",
        nit_proveedor="US123456789",
        razon_social="VENDOR LLC",
        moneda="USD",
        valor_base=80.0,
        iva=12.0,
        valor_total_documento=92.0,
        fecha_factura=date(2026, 5, 15),
        legible=True,
    )
    tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 15),
        description="VENDOR LLC",
        currency="COP",
        amount_cop=400000.0,
        amount_original=92.0,
        original_currency="USD",
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    assert len(rows) == 1
    assert rows[0].iva == 0.0
    assert rows[0].valor_base_usd == 92.0


def test_sol_invoice_columns(card_meta, settings):
    """Verifica sol invoice columns."""
    invoice = InvoiceData(
        source_filename="saas_sol.pdf",
        nit_proveedor="900123456",
        razon_social="SAAS PERU",
        moneda="SOL",
        valor_total_documento=45.0,
        fecha_factura=date(2026, 5, 10),
        legible=True,
    )
    tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 10),
        description="SAAS PERU",
        currency="COP",
        amount_cop=48000.0,
        amount_original=45.0,
        original_currency="SOL",
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    row = rows[0]
    assert row.moneda == "SOL"
    assert row.valor_base_usd is None
    assert row.valor_base_clp is None
    assert row.valor_base_sol == 45.0
    assert row.iva == 0.0
    assert row.valor_base_cops == 48000.0


def test_usd_total_no_iva_column(card_meta, settings):
    """USD con extracto ≠ base+iva → IVA vacío, USD = cargo original del extracto."""
    invoice = InvoiceData(
        source_filename="saas_usd.pdf",
        nit_proveedor="900123456",
        razon_social="SAAS INC",
        moneda="USD",
        valor_base=100.0,
        iva=19.0,
        valor_total_documento=119.0,
        fecha_factura=date(2026, 5, 10),
        legible=True,
    )
    tx = Transaction(
        card="1111",
        tx_date=date(2026, 5, 10),
        description="SAAS INC",
        currency="COP",
        amount_cop=520000.0,
        amount_original=125.0,
        original_currency="USD",
        row_index=2,
    )
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="SI")
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    row = rows[0]
    assert row.valor_base_usd == 125.0
    assert row.iva == 0.0
    assert row.valor_base_cops == 520000.0


def _transport_recibo_801() -> InvoiceData:
    """Helper de prueba: transport recibo 801."""
    return InvoiceData(
        source_filename="recibo_caja_transporte_801.pdf",
        numero_factura="801",
        nit_proveedor="9003333333",
        razon_social="TRANSPORTE APP SAS",
        moneda="COP",
        valor_base=54245.0,
        valor_total_documento=54245.0,
        fecha_factura=date(2026, 5, 25),
        detalle_gasto="TC 4444 SERVICIO DE TRANSPORTE APP",
        tipo_documento="recibo_caja_menor",
        consolidado=True,
        legible=True,
    )


def test_consolidated_recibo_single_legalization_row(card_meta, settings):
    """Verifica consolidated recibo single legalization row."""
    invoice = _transport_recibo_801()
    matches = [
        MatchResult(
            transaction=Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=46646.0,
                row_index=2,
            ),
            invoice=invoice,
            status="OK",
            documento_soporte="SI",
        ),
        MatchResult(
            transaction=Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=7599.0,
                row_index=3,
            ),
            invoice=invoice,
            status="OK",
            documento_soporte="SI",
        ),
    ]
    rows, _ = build_legalization_rows(matches, card_meta, {}, settings)
    assert len(rows) == 1
    assert rows[0].numero_factura == "RECIBO DE CAJA 801"
    assert rows[0].valor_base_cops == 54245.0
    assert rows[0].valor_total_compra_cop == 54245.0
    assert rows[0].nit_proveedor == "9003333333"


def test_consolidated_recibo_review_row_highlighted(card_meta, settings):
    """Verifica consolidated recibo review row highlighted."""
    invoice = _transport_recibo_801()
    matches = [
        MatchResult(
            transaction=Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=54245.0,
                row_index=2,
            ),
            invoice=invoice,
            status="OK",
            documento_soporte="SI",
            match_kind="consolidated_review",
            needs_review=True,
        ),
    ]
    rows, _ = build_legalization_rows(matches, card_meta, {}, settings)
    assert len(rows) == 1
    assert rows[0].needs_review is True


def test_provider_date_review_row_highlighted(card_meta, settings):
    """Verifica provider date review row highlighted."""
    invoice = InvoiceData(
        source_filename="restaurante.pdf",
        numero_factura="F-100",
        razon_social="TAKAMI S.A.",
        nombre_comercial="OSAKI ARTISAN",
        moneda="COP",
        valor_total_documento=373120.0,
        fecha_factura=date(2026, 5, 18),
        legible=True,
    )
    matches = [
        MatchResult(
            transaction=Transaction(
                card="2222",
                tx_date=date(2026, 6, 18),
                description="OSAKI ARTISAN",
                currency="COP",
                amount_cop=373120.0,
                row_index=2,
            ),
            invoice=invoice,
            status="OK",
            documento_soporte="SI",
            match_kind="provider_date_review",
            needs_review=True,
        ),
    ]
    rows, _ = build_legalization_rows(matches, card_meta, {}, settings)
    assert len(rows) == 1
    assert rows[0].needs_review is True
    assert rows[0].numero_factura == "F-100"


def test_cabify_single_recibo_legalization_row(card_meta, settings):
    """Verifica cabify single recibo legalization row."""
    invoice = InvoiceData(
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
    matches = [
        MatchResult(
            transaction=Transaction(
                card="3333",
                tx_date=date(2026, 4, 30),
                description="MERCADOPAGO TRANSPORTE*VIAJE",
                currency="COP",
                amount_cop=69781.0,
                row_index=2,
            ),
            invoice=invoice,
            status="OK",
            documento_soporte="SI",
        ),
    ]
    rows, _ = build_legalization_rows(matches, card_meta, {}, settings)
    assert len(rows) == 1
    assert rows[0].numero_factura == "RECIBO DE CAJA 802"
    assert rows[0].valor_total_compra_cop == 69781.0


def test_consolidated_and_regular_rows_separate(
    card_meta, sample_invoice_usd, settings
):
    """Verifica consolidated and regular rows separate."""
    invoice = _transport_recibo_801()
    uber_matches = [
        MatchResult(
            transaction=Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=46646.0,
                row_index=2,
            ),
            invoice=invoice,
            status="OK",
            documento_soporte="SI",
        ),
        MatchResult(
            transaction=Transaction(
                card="4444",
                tx_date=date(2026, 5, 8),
                description="TRANSPORTE APP",
                currency="COP",
                amount_cop=7599.0,
                row_index=3,
            ),
            invoice=invoice,
            status="OK",
            documento_soporte="SI",
        ),
    ]
    aws_match = MatchResult(
        transaction=Transaction(
            card="1111",
            tx_date=date(2026, 5, 10),
            description="SERVICIO CLOUD DEMO",
            currency="COP",
            amount_cop=400000.0,
            row_index=4,
        ),
        invoice=sample_invoice_usd,
        status="OK",
        documento_soporte="SI",
    )
    rows, _ = build_legalization_rows(
        uber_matches + [aws_match], card_meta, {}, settings
    )
    assert len(rows) == 2
    assert rows[0].numero_factura == "RECIBO DE CAJA 801"
    assert rows[0].valor_total_compra_cop == 54245.0
    assert rows[1].numero_factura == "INV-123"
    assert rows[1].valor_total_compra_cop == 400000.0


def test_unmatched_movement_included_with_no_soporte(card_meta, settings):
    """Verifica unmatched movement included with no soporte."""
    unmatched = MatchResult(
        transaction=Transaction(
            card="1111",
            tx_date=date(2026, 5, 12),
            description="RESTAURANTE SIN FACTURA",
            currency="COP",
            amount_cop=85000.0,
            row_index=5,
        ),
        invoice=None,
        status="UNMATCHED",
        documento_soporte="NO",
        failure_reason="Factura no encontrada",
    )
    rows, new_nits = build_legalization_rows([unmatched], card_meta, {}, settings)
    assert len(rows) == 1
    row = rows[0]
    assert row.documento_soporte == ""
    assert row.nit_proveedor == ""
    assert row.numero_factura == ""
    assert row.valor_base_cops == 85000.0
    assert row.valor_total_compra_cop == 85000.0
    assert "RESTAURANTE SIN FACTURA" in row.detalle_gasto
    assert row.needs_review is True
    assert new_nits == []


def test_unmatched_with_suggested_invoice_fills_row_without_new_nit(
    card_meta, settings
):
    """Verifica unmatched with suggested invoice fills row without new nit."""
    suggested = InvoiceData(
        source_filename="RESTAURANTE DEMO -F001.jpeg",
        numero_factura="B050-DEMO001",
        nit_proveedor="20987654321",
        razon_social="RESTAURANTE DEMO S.A.S",
        moneda="SOL",
        valor_total_documento=129.0,
        fecha_factura=date(2026, 5, 24),
        legible=True,
    )
    unmatched = MatchResult(
        transaction=Transaction(
            card="5555",
            tx_date=date(2026, 5, 24),
            description="RESTAURANTE DEMO",
            currency="COP",
            amount_cop=180000.0,
            amount_original=141.9,
            original_currency="SOL",
            row_index=2,
        ),
        invoice=None,
        status="UNMATCHED",
        documento_soporte="NO",
        suggested_invoice=suggested,
    )
    rows, new_nits = build_legalization_rows([unmatched], card_meta, {}, settings)
    assert len(rows) == 1
    row = rows[0]
    assert row.numero_factura == "B050-DEMO001"
    assert row.nit_proveedor == "20987654321"
    assert row.razon_social == "RESTAURANTE DEMO S.A.S"
    assert row.needs_review is True
    assert row.documento_soporte == "SI"
    assert new_nits == []


def test_galaxi_suggested_row_fills_culto_sapori(card_meta, settings):
    """Verifica galaxi suggested row fills cafe beta."""
    suggested = InvoiceData(
        source_filename="CAFE BETA S.A.S - CBB29786.pdf",
        numero_factura="CBB29786",
        nit_proveedor="9011212121",
        razon_social="CAFE BETA S.A.S",
        moneda="COP",
        valor_total_documento=75279.63,
        fecha_factura=date(2026, 5, 8),
        legible=True,
    )
    unmatched = MatchResult(
        transaction=Transaction(
            card="5555",
            tx_date=date(2026, 5, 8),
            description="INVERSIONES ALPHA COL",
            currency="COP",
            amount_cop=75280.0,
            row_index=2,
        ),
        invoice=None,
        status="UNMATCHED",
        documento_soporte="NO",
        suggested_invoice=suggested,
    )
    rows, new_nits = build_legalization_rows([unmatched], card_meta, {}, settings)
    assert len(rows) == 1
    row = rows[0]
    assert row.numero_factura == "CBB29786"
    assert row.nit_proveedor == "9011212121"
    assert row.razon_social == "CAFE BETA S.A.S"
    assert row.needs_review is True
    assert new_nits == []


def test_ambiguous_movement_included_with_no_soporte(card_meta, settings):
    """Verifica ambiguous movement included with no soporte."""
    ambiguous = MatchResult(
        transaction=Transaction(
            card="1111",
            tx_date=date(2026, 5, 14),
            description="PROVEEDOR AMBIGUO",
            currency="COP",
            amount_cop=120000.0,
            row_index=6,
        ),
        invoice=None,
        status="AMBIGUOUS",
        documento_soporte="NO",
        failure_reason="Ambigüedad: múltiples candidatos",
    )
    rows, _ = build_legalization_rows([ambiguous], card_meta, {}, settings)
    assert len(rows) == 1
    assert rows[0].documento_soporte == ""


def test_mixed_ok_and_unmatched_rows(card_meta, sample_invoice_usd, settings):
    """Verifica mixed ok and unmatched rows."""
    ok_match = MatchResult(
        transaction=Transaction(
            card="1111",
            tx_date=date(2026, 5, 10),
            description="SERVICIO CLOUD DEMO",
            currency="COP",
            amount_cop=400000.0,
            row_index=2,
        ),
        invoice=sample_invoice_usd,
        status="OK",
        documento_soporte="SI",
    )
    unmatched = MatchResult(
        transaction=Transaction(
            card="1111",
            tx_date=date(2026, 5, 12),
            description="GASTO SIN SOPORTE",
            currency="COP",
            amount_cop=50000.0,
            row_index=3,
        ),
        invoice=None,
        status="UNMATCHED",
        documento_soporte="NO",
        failure_reason="Fuera de ventana de fecha",
    )
    rows, _ = build_legalization_rows([ok_match, unmatched], card_meta, {}, settings)
    assert len(rows) == 2
    assert rows[0].documento_soporte == "SI"
    assert rows[1].documento_soporte == ""


def test_compound_tip_emits_two_legalization_rows(card_meta, settings):
    """Verifica compound tip emits two legalization rows."""
    factura = InvoiceData(
        source_filename="RESTAURANTE ALFA S.A.S -TPV 00201.pdf",
        numero_factura="TPV00201",
        nit_proveedor="9004444449",
        razon_social="RESTAURANTE ALFA S.A.S",
        moneda="COP",
        valor_base=509256.0,
        iva=41646.0,
        valor_total_documento=550902.0,
        fecha_factura=date(2026, 5, 8),
        legible=True,
    )
    recibo = InvoiceData(
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
    tx = Transaction(
        card="2222",
        tx_date=date(2026, 5, 8),
        description="REST ALFA SUCURSAL",
        currency="COP",
        amount_cop=601828.0,
        row_index=2,
    )
    match = MatchResult(
        transaction=tx,
        invoice=factura,
        secondary_invoice=recibo,
        status="OK",
        documento_soporte="SI",
        match_kind="compound",
    )
    rows, _ = build_legalization_rows([match], card_meta, {}, settings)
    # Factura con IVA mixto → 2 filas; recibo de propina → 1 fila sin IVA.
    assert len(rows) == 3
    gravada, exenta, propina = rows
    assert gravada.numero_factura == "TPV00201"
    assert gravada.valor_base_cops == 219189.0
    assert gravada.iva == 41646.0
    assert gravada.valor_total_compra_cop == pytest.approx(260835.0)
    assert exenta.numero_factura == "TPV00201"
    assert exenta.valor_base_cops == pytest.approx(290067.0)
    assert exenta.iva == 0.0
    assert exenta.valor_total_compra_cop == pytest.approx(290067.0)
    assert propina.numero_factura == "RECIBO DE CAJA 803"
    assert propina.valor_total_compra_cop == 50926.0
    assert propina.iva == 0.0
    assert propina.articulo_contable == settings.articulo_propina
    assert gravada.documento_soporte == "NO"
    assert propina.documento_soporte == "NO"
    for row in rows:
        if row.iva and row.iva > 0:
            assert row.valor_base_cops + row.iva == pytest.approx(row.valor_total_compra_cop)
    assert sum(r.valor_total_compra_cop for r in rows) == pytest.approx(tx.amount_cop)


def test_propina_articulo_overrides_historico(card_meta, settings):
    """Verifica propina articulo overrides historico."""
    historico = {
        "9004444449": ProviderHistory(
            nit="9004444449",
            razon_social="RESTAURANTE ALFA S.A.S",
            articulo_contable="5195200005 - GASTOS DE REPRESENTACION",
        )
    }
    recibo = InvoiceData(
        source_filename="recibo_propina.pdf",
        numero_factura="803",
        nit_proveedor="9004444449",
        razon_social="RESTAURANTE ALFA S.A.S",
        moneda="COP",
        valor_total_documento=50926.0,
        fecha_factura=date(2026, 5, 28),
        tipo_documento="recibo_caja_menor",
        es_propina=True,
        legible=True,
    )
    tx = Transaction(
        card="2222",
        tx_date=date(2026, 5, 8),
        description="REST ALFA SUCURSAL",
        currency="COP",
        amount_cop=50926.0,
        row_index=2,
    )
    match = MatchResult(
        transaction=tx, invoice=recibo, status="OK", documento_soporte="SI"
    )
    rows, _ = build_legalization_rows([match], card_meta, historico, settings)
    assert rows[0].articulo_contable == settings.articulo_propina
    assert rows[0].articulo_contable != historico["9004444449"].articulo_contable


def test_compound_tip_factura_uses_historico_articulo(card_meta, settings):
    """Verifica compound tip factura uses historico articulo."""
    historico = {
        "9004444449": ProviderHistory(
            nit="9004444449",
            razon_social="RESTAURANTE ALFA S.A.S",
            articulo_contable="5195200005 - GASTOS DE REPRESENTACION",
        )
    }
    factura = InvoiceData(
        source_filename="tpv.pdf",
        numero_factura="TPV00201",
        nit_proveedor="9004444449",
        razon_social="RESTAURANTE ALFA S.A.S",
        moneda="COP",
        valor_base=509256.0,
        iva=41646.0,
        valor_total_documento=550902.0,
        fecha_factura=date(2026, 5, 8),
        legible=True,
    )
    recibo = InvoiceData(
        source_filename="recibo_propina.pdf",
        numero_factura="803",
        nit_proveedor="9004444449",
        razon_social="RESTAURANTE ALFA S.A.S",
        moneda="COP",
        valor_total_documento=50926.0,
        fecha_factura=date(2026, 5, 28),
        tipo_documento="recibo_caja_menor",
        es_propina=True,
        legible=True,
    )
    tx = Transaction(
        card="2222",
        tx_date=date(2026, 5, 8),
        description="REST ALFA SUCURSAL",
        currency="COP",
        amount_cop=601828.0,
        row_index=2,
    )
    match = MatchResult(
        transaction=tx,
        invoice=factura,
        secondary_invoice=recibo,
        status="OK",
        documento_soporte="SI",
        match_kind="compound",
    )
    rows, _ = build_legalization_rows([match], card_meta, historico, settings)
    assert len(rows) == 3
    assert rows[0].articulo_contable == "5195200005 - GASTOS DE REPRESENTACION"
    assert rows[1].articulo_contable == "5195200005 - GASTOS DE REPRESENTACION"
    assert rows[2].articulo_contable == settings.articulo_propina


def test_no_new_nit_when_matched_by_razon_social_with_different_nit(card_meta, settings):
    """Proveedor en histórico con NIT_A; factura llega con NIT_B distinto.
    _find_history lo resuelve por razón social → no debe marcarse como NIT nuevo."""
    invoice = InvoiceData(
        source_filename="cencosud.pdf",
        nit_proveedor="9009999999",
        razon_social="CENCOSUD COLOMBIA S.A.",
        moneda="COP",
        valor_total_documento=601749.0,
        fecha_factura=date(2026, 5, 20),
        legible=True,
    )
    tx = Transaction(
        card="4444",
        tx_date=date(2026, 5, 20),
        description="MERCADOPAGO COLOMBIA",
        currency="COP",
        amount_cop=601749.0,
        row_index=3,
    )
    # En el Sheet está registrado con la misma razón social pero clave distinta
    historico = {
        "NIT-DISTINTO": ProviderHistory(
            nit="NIT-DISTINTO",
            razon_social="CENCOSUD COLOMBIA S.A.",
            detalle_gasto="TC 4444 COMPRA SUPERMERCADO",
            articulo_contable="5195200001 - GASTOS DE REPRESENTACION",
        )
    }
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="NO")
    rows, new_nits = build_legalization_rows([match], card_meta, historico, settings)
    # El artículo contable debe estar lleno (resuelto por razón social)
    assert rows[0].articulo_contable == "5195200001 - GASTOS DE REPRESENTACION"
    # El NIT de la factura NO debe aparecer en new_nits
    assert "9009999999" not in new_nits
    assert new_nits == []


def test_build_row_matches_historico_nit_without_verification_digit(card_meta, settings):
    """Verifica build row matches historico nit without verification digit."""
    invoice = InvoiceData(
        source_filename="PROVEEDOR HOTEL SAS - ELEC1442.pdf",
        nit_proveedor="900111111-0",
        razon_social="PROVEEDOR HOTEL SAS",
        moneda="COP",
        valor_total_documento=500000.0,
        fecha_factura=date(2026, 5, 20),
        legible=True,
    )
    tx = Transaction(
        card="3333",
        tx_date=date(2026, 5, 20),
        description="PROVEEDOR HOTEL",
        currency="COP",
        amount_cop=500000.0,
        row_index=2,
    )
    historico = {
        "900111111": ProviderHistory(
            nit="900111111",
            razon_social="PROVEEDOR HOTEL SAS",
            detalle_gasto="TC 3333 ALOJAMIENTO",
            articulo_contable="5195200001 - GASTOS DE REPRESENTACION",
        )
    }
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="NO")
    rows, new_nits = build_legalization_rows([match], card_meta, historico, settings)
    assert rows[0].nit_proveedor == "900111111"
    assert rows[0].articulo_contable == "5195200001 - GASTOS DE REPRESENTACION"
    assert new_nits == []


def test_build_row_matches_historico_nit_with_verification_digit(card_meta, settings):
    """Verifica build row matches historico nit with verification digit."""
    invoice = InvoiceData(
        source_filename="BO LEGACY -  FE - 26968.pdf",
        nit_proveedor="900222222",
        razon_social="B.O LEGACY S.A.S.",
        moneda="COP",
        valor_total_documento=300000.0,
        fecha_factura=date(2026, 5, 18),
        legible=True,
    )
    tx = Transaction(
        card="3333",
        tx_date=date(2026, 5, 18),
        description="BO LEGACY",
        currency="COP",
        amount_cop=300000.0,
        row_index=2,
    )
    historico = {
        "900222222-0": ProviderHistory(
            nit="900222222-0",
            razon_social="B.O LEGACY S.A.S.",
            detalle_gasto="TC 3333 EVENTO",
            articulo_contable="5195200005 - GASTOS DE REPRESENTACION",
        )
    }
    match = MatchResult(transaction=tx, invoice=invoice, status="OK", documento_soporte="NO")
    rows, new_nits = build_legalization_rows([match], card_meta, historico, settings)
    assert rows[0].nit_proveedor == "900222222-0"
    assert rows[0].articulo_contable == "5195200005 - GASTOS DE REPRESENTACION"
    assert new_nits == []


def test_extract_matches_base_plus_iva_sol_uses_wider_tolerance(settings):
    """Verifica extract matches base plus iva sol uses wider tolerance."""
    invoice = InvoiceData(
        source_filename="restaurant_sol.pdf",
        razon_social="RESTAURANTE LIMA",
        moneda="SOL",
        valor_base=100.0,
        iva=18.0,
        valor_total_documento=118.0,
        fecha_factura=date(2026, 5, 24),
        legible=True,
    )
    tx = Transaction(
        card="5555",
        tx_date=date(2026, 5, 24),
        description="RESTAURANTE LIMA",
        currency="COP",
        amount_cop=50000.0,
        amount_original=120.0,
        original_currency="SOL",
        row_index=2,
    )
    assert _extract_matches_base_plus_iva(settings, tx, invoice) is True
    assert _extract_matches_base_plus_iva(
        replace(settings, amount_tolerance_pct_sol=0.01), tx, invoice
    ) is False
