# Prompt para extracción de facturas (Claude Code)

Usa este prompt al crear cada JSON en `.cache/cards/{tarjeta}/invoices/{nombre_sin_extension}.json` (no usar la ruta legacy `.cache/invoices/`).

**Un PDF → un JSON.** Si el banco registra un solo cargo pero hay varios PDFs del mismo proveedor/fecha, extrae **cada PDF por separado**; Python concilia la suma en el paso `multi_factura` y genera **una fila Excel por factura**. Ver [Varias facturas, un solo cargo](#varias-facturas-un-solo-cargo-en-el-preliminar).

Conoce el número de tarjeta del contexto de la sesión (ej. "Legaliza tarjeta 1234").

---

## Prompt

```
Analiza el documento de factura adjunto y devuelve ÚNICAMENTE un JSON válido con esta estructura:

{
  "source_filename": "<nombre exacto del archivo>",
  "numero_factura": "<string o null>",
  "nit_proveedor": "<string o null>",
  "razon_social": "<string o null>",
  "nombre_comercial": "<string o null — nombre del local en terminal/boleta si difiere de razón social>",
  "moneda": "COP|USD|SOL|CLP|null",
  "valor_base": <number o null>,
  "iva": <number, 0 si no se discrimina>,
  "otros_impuestos": <number, 0 si no hay INC/ICUI/IBUA u otros impuestos fuera del IVA>,
  "valor_total_documento": <number o null>,
  "fecha_factura": "YYYY-MM-DD o null",
  "detalle_gasto": "<string o null>",
  "tipo_documento": "factura|recibo_caja_menor|null",
  "consolidado": <true|false>,
  "sin_desglose_iva": <true|false>,
  "pais_emisor": "PE|CO|null",
  "legible": <true|false>
}

Reglas estrictas:
- Extrae SOLO datos visibles en el documento.
- valor_base, iva y valor_total_documento están en la moneda indicada en "moneda".
- **IVA mixto (ítems gravados al 19% y exentos en la misma factura):** `valor_base` = **suma de todas las bases** (gravada + exenta), NO solo la subtotal gravada. `iva` = **solo IVA discriminado al 19%** (no incluir INC, ICUI, IBUA ni otros impuestos). Si el PDF discrimina INC, ICUI, IBUA u otros impuestos aparte del IVA, anótalos en `otros_impuestos` (suma de esos montos; `0` si no aplican). Debe cumplirse `valor_base + iva + otros_impuestos = valor_total_documento` (y ese total debe coincidir con el cargo). Python divide en dos filas Excel: gravada (`round(iva/0.19)` + IVA) y exenta (resto del cargo sin IVA). Si pones solo la base gravada en `valor_base`, si sumas INC/ICUI en `iva`, o si omites `otros_impuestos` cuando el total incluye esos impuestos, el split falla.
- **Tiquetes aéreos — “Tasas y/o impuestos”:** si el desglose de pago muestra **Asiento / Tarifa / Pasaje** (monto A) y una línea aparte **Tasas y/o impuestos**, **Impuestos**, **YSA**, **Tasa aeroportuaria** u otra tasa sumada (monto B), con **Total pagado = A + B**: `valor_base` = **A** (nunca el total pagado), `otros_impuestos` = **B** (aunque no diga “IVA”), `iva` = solo si el PDF etiqueta explícitamente **IVA** / **IVA 19%** (si no, `0`), `valor_total_documento` = total pagado. **Prohibido** `valor_base = valor_total_documento` con `iva = 0` y `otros_impuestos = 0` cuando el documento discrimina tasas/impuestos aparte. Ver ejemplo más abajo.
- **Restaurante (comida en local):** `sin_desglose_iva: true` cuando el gasto es almuerzo, cena o gasto de representación en restaurante. Sigue extrayendo `valor_base`, `iva` y `valor_total_documento` del PDF; Python pone **una fila** en Excel con COPS = cargo del preliminar e IVA vacío. Incluye en `detalle_gasto` palabras como `RESTAURANTE`, `ALMUERZO` o `CENA` (o las del concepto bancario) para que Python también detecte el caso si el flag falta.
- NO incluyas valor_cop, valor_total_cop ni valor_total.
- NO extraigas centro de costo ni artículo contable.
- Recibo de caja menor (consolida varios cargos de tarjeta en un solo documento):
  - tipo_documento="recibo_caja_menor" y consolidado=true
  - numero_factura = número del recibo tal como aparece en el documento (ej. "801"); Python lo muestra en Excel como "RECIBO DE CAJA 801"
  - valor_total_documento = total del recibo (suma de los movimientos que cubre)
  - fecha_factura = fecha del recibo (puede ser posterior a los viajes/compras)
- **Varias facturas PDF, un solo cargo en el preliminar:** si el mismo consumo (mismo proveedor, misma fecha) generó 2+ facturas pero el banco muestra **un movimiento** = suma de esas facturas, genera **un JSON por PDF** con el `valor_total_documento` **de esa factura** (no el total del cargo). Python concilia en paso `multi_factura` y el Excel tendrá una fila por factura. Ver sección [Varias facturas, un solo cargo](#varias-facturas-un-solo-cargo-en-el-preliminar).
- Pago mixto (factura con varios medios de pago: efectivo, transferencia, tarjeta):
  - valor_total_documento y valor_base = SOLO el monto pagado con tarjeta/tarjetas
  - NO uses "Total a pagar", "Total bruto" ni el valor de un ítem si solo parte se pagó con TC
  - Python compara valor_total_documento contra el cargo del extracto bancario (±tolerancia)
  - Si hay duda, el monto del JSON debe coincidir con el movimiento Mov TC correspondiente
- detalle_gasto: describe el gasto en MAYÚSCULAS con formato preferido
  "TC {tarjeta} {DESCRIPCIÓN} {DÍA} DE {MES}".
  - Usa el número de tarjeta de la sesión (ej. el de la carpeta Drive).
  - Infiere la descripción del ítem o servicio visible (almuerzo, transporte, compra mercado, vuelo, etc.).
  - **Incluye palabras del concepto bancario** cuando las conozcas del preliminar (ej. cargo `RESTAURANTE LA MESA` → usar `RESTAURANTE LA MESA` o `GASTO DE REPRESENTACIÓN ALMUERZO RESTAURANTE LA MESA`, no solo `ALMUERZO LA MESA`). Python compara concepto del extracto con `detalle_gasto`, `nombre_comercial` y razón social.
  - Usa fecha_factura para la parte de fecha cuando aplique.
  - Si no puedes inferir con confianza: detalle_gasto=null (Python aplicará fallback).
  - NO inventes nombres de personas, ciudades ni eventos que no aparezcan en el documento.
- Si el documento es ilegible o falta información crítica: legible=false y campos en null.
- NO inventes datos.
- **Documentos Perú:** ver sección [Documentos Perú (RUC)](#documentos-perú-ruc) más abajo.
```

---

## Documentos Perú (RUC)

**Cuándo es Perú** (cualquiera de estas señales en el documento):
- Moneda **SOL** / S/ / soles
- Referencias **SUNAT**, **IGV**, **RUC**, comprobante electrónico peruano
- Emisor con domicilio en Perú (Lima, San Isidro, etc.)

**Reglas de extracción:**
- `nit_proveedor` = **RUC del emisor** (11 dígitos, solo números; sin guiones). En Perú no se usa NIT colombiano.
- Buscar etiquetas junto al emisor: `RUC:`, `N° RUC`, `R.U.C.`
- **No** confundir con el RUC/NIT del cliente (empresa receptora del gasto); extraer el del **proveedor emisor**
- `pais_emisor`: `"PE"` cuando el documento es claramente peruano; `"CO"` si es colombiano; `null` si no es evidente
- Si el RUC no es legible: `nit_proveedor: null` y `legible: false` (no inventar)

**Ejemplo — boleta Perú (montos y emisor ilustrativos):**

```json
{
  "source_filename": "RESTAURANTE NIKKEI - B001-00012345.jpeg",
  "numero_factura": "B001-00012345",
  "nit_proveedor": "20123456789",
  "razon_social": "RESTAURANTE NIKKEI EJEMPLO S.A.C.",
  "moneda": "SOL",
  "pais_emisor": "PE",
  "valor_base": 80.0,
  "iva": 14.4,
  "valor_total_documento": 94.4,
  "fecha_factura": "2026-05-24",
  "detalle_gasto": "TC 1234 GASTO RESTAURANTE NIKKEI 24 DE MAYO",
  "tipo_documento": "factura",
  "consolidado": false,
  "legible": true
}
```

---

## Ejemplos de detalle_gasto

Los números de tarjeta y comercios son ilustrativos; usa la tarjeta de la sesión y el proveedor del documento.

| Tipo de factura | detalle_gasto |
|-----------------|---------------|
| Restaurante 6 mayo, tarjeta 1234 | `TC 1234 GASTO ALMUERZO 6 DE MAYO` |
| Transporte app 7 mayo, tarjeta 1234 | `TC 1234 SERVICIO DE TRANSPORTE 7 DE MAYO` |
| Supermercado 13 mayo, tarjeta 1234 | `TC 1234 COMPRA MERCADO 13 DE MAYO` |
| SaaS USD, tarjeta 5678 | `TC 5678 SERVICIO APLICACIONES` |

---

## Ejemplo válido (factura USD)

```json
{
  "source_filename": "CLOUD SERVICES - INV-1001.pdf",
  "numero_factura": "INV-1001",
  "nit_proveedor": "900111222",
  "razon_social": "CLOUD SERVICES EXAMPLE INC",
  "moneda": "USD",
  "valor_base": 50.0,
  "iva": 0.0,
  "valor_total_documento": 50.0,
  "fecha_factura": "2026-05-10",
  "detalle_gasto": "TC 5678 SERVICIO APLICACIONES",
  "legible": true
}
```

## Ejemplo válido (factura COP)

```json
{
  "source_filename": "APP TRANSPORTE - RC-100.pdf",
  "numero_factura": "RC-100",
  "nit_proveedor": "900222333",
  "razon_social": "APP TRANSPORTE EJEMPLO SAS",
  "moneda": "COP",
  "valor_base": 18000.0,
  "iva": 0.0,
  "valor_total_documento": 18000.0,
  "fecha_factura": "2026-05-07",
  "detalle_gasto": "TC 1234 SERVICIO DE TRANSPORTE 7 DE MAYO",
  "legible": true
}
```

## IVA mixto gravado y exento (factura COP)

Cuando el documento discrimina IVA sobre **parte** de los ítems y otros ítems son exentos (típico en supermercados, tiquetes aéreos con tasas exentas, etc.):

| Campo | Qué extraer |
|-------|-------------|
| `valor_base` | **Base gravada + base exenta** (subtotal antes de IVA, todos los ítems) |
| `iva` | **Solo IVA al 19%** discriminado en el documento. No incluir INC, ICUI, IBUA ni otros impuestos |
| `otros_impuestos` | Suma de INC, ICUI, IBUA y demás impuestos **fuera del IVA 19%**. `0` si no hay |
| `valor_total_documento` | Total a pagar con tarjeta |

**Validación antes de guardar:** `valor_total_documento` debe coincidir con el cargo del preliminar y cumplir `valor_base + iva + otros_impuestos = valor_total_documento`. Si no hay otros impuestos, `otros_impuestos = 0` y `valor_base + iva` debe igualar el total. Si solo anotas la base gravada, `valor_base × 19%` cuadrará con el IVA pero faltará la parte exenta y Python no podrá generar las dos filas.

**Ejemplo — supermercado sin otros impuestos (IVA mixto clásico):**

| Concepto en factura | Monto |
|---------------------|-------|
| Base gravada (19%) | 80,000 |
| IVA | 15,200 |
| Base exenta | 10,000 |
| **valor_base (suma)** | **90,000** |
| **Total** | **105,200** |

```json
{
  "source_filename": "MERCADO DEL VALLE - FV-9001.pdf",
  "numero_factura": "FV-9001",
  "nit_proveedor": "900333444",
  "razon_social": "MERCADO DEL VALLE EJEMPLO S.A.S.",
  "moneda": "COP",
  "valor_base": 90000.0,
  "iva": 15200.0,
  "valor_total_documento": 105200.0,
  "fecha_factura": "2026-04-14",
  "detalle_gasto": "TC 1234 COMPRA MERCADO 14 DE ABRIL",
  "tipo_documento": "factura",
  "consolidado": false,
  "legible": true
}
```

**Ejemplo — supermercado con INC/ICUI u otros impuestos:**

| Concepto en factura | Monto |
|---------------------|-------|
| Subtotal ítems | 50,000 |
| IVA 19% | 5,700 |
| INC 8% | 2,000 |
| ICUI 20% | 4,000 |
| **valor_base (subtotal)** | **50,000** |
| **otros_impuestos (INC + ICUI)** | **6,000** |
| **Total a pagar** | **61,700** |

`iva` = solo IVA 19%. INC, ICUI e impuestos similares van en `otros_impuestos`, no en `iva`. Python genera dos filas: gravada (`round(iva/0.19)` + IVA) y exenta (resto del cargo).

```json
{
  "source_filename": "MERCADO CENTRAL - FV-200.pdf",
  "numero_factura": "FV-200",
  "nit_proveedor": "900444555",
  "razon_social": "MERCADO CENTRAL EJEMPLO SAS",
  "moneda": "COP",
  "valor_base": 50000.0,
  "iva": 5700.0,
  "otros_impuestos": 6000.0,
  "valor_total_documento": 61700.0,
  "fecha_factura": "2026-06-08",
  "detalle_gasto": "TC 1234 COMPRA MERCADO 8 DE JUNIO",
  "tipo_documento": "factura",
  "consolidado": false,
  "legible": true
}
```

**Incorrecto — sumar INC/ICUI en `iva` o omitir `otros_impuestos`:**

```json
{
  "valor_base": 50000.0,
  "iva": 11700.0,
  "otros_impuestos": 0.0,
  "valor_total_documento": 61700.0
}
```

Aquí `iva` mezcla IVA con INC/ICUI, o falta `otros_impuestos`; Python no puede calcular la base gravada y el Excel sale con desglose erróneo en una sola fila.

**Ejemplo — tiquete aéreo con “Tasas y/o impuestos”:**

Layout típico en el desglose de pago (montos ilustrativos):

| Concepto en el documento | Monto |
|--------------------------|-------|
| Asiento / Tarifa / Pasaje | 100,000 |
| Tasas y/o impuestos (ej. nota YSA) | 19,000 |
| **Total pagado** | **119,000** |

| Campo | Valor |
|-------|-------|
| `valor_base` | **100,000** (asiento/tarifa; **no** el total) |
| `iva` | **0** (el PDF no dice “IVA”; dice tasas/impuestos/YSA) |
| `otros_impuestos` | **19,000** (la línea de tasas/impuestos) |
| `valor_total_documento` | **119,000** |

`nit_proveedor` y `razon_social` = emisor fiscal del documento (razón social del grupo aéreo si el PDF muestra ese NIT, no solo una marca comercial u operador regional).

```json
{
  "source_filename": "AEROLINEA ANDINA - TK-1000ABCD.pdf",
  "numero_factura": "TK-1000ABCD",
  "nit_proveedor": "900555666",
  "razon_social": "AEROLINEA ANDINA EJEMPLO SA",
  "nombre_comercial": "AEROLINEA ANDINA",
  "moneda": "COP",
  "valor_base": 100000.0,
  "iva": 0.0,
  "otros_impuestos": 19000.0,
  "valor_total_documento": 119000.0,
  "fecha_factura": "2026-05-15",
  "detalle_gasto": "TC 1234 ASIENTO VUELO AEROLINEA ANDINA 15 DE MAYO",
  "tipo_documento": "factura",
  "consolidado": false,
  "legible": true
}
```

Python usa `otros_impuestos` cuando `iva = 0` y genera el desglose en Excel (fila gravada + fila exenta si aplica).

**Incorrecto — meter el total pagado en `valor_base` e ignorar tasas/impuestos:**

```json
{
  "valor_base": 119000.0,
  "iva": 0.0,
  "otros_impuestos": 0.0,
  "valor_total_documento": 119000.0
}
```

Aquí se perdió la línea “Tasas y/o impuestos”; Python no tiene impuesto que desglosar y el Excel queda en **una sola fila sin IVA**.

Si el PDF **sí** etiqueta **IVA** o **IVA 19%** aparte de la tarifa, pon ese monto en `iva` (no en `otros_impuestos`) y suma en `valor_base` tarifa + cualquier ítem exento que no sea impuesto.

## Varias facturas, un solo cargo en el preliminar

Cuando el restaurante/comercio emite **más de una factura** el mismo día pero la tarjeta registra **un solo cargo** (suma de todas), extrae **un JSON por PDF** con el total **individual** de cada documento. Python concilia en el paso `multi_factura` (mismo NIT, misma fecha, suma ≈ cargo) y genera **una fila Excel por factura**.

**Cuándo aplicar:**

| Señal | Acción |
|-------|--------|
| 2+ PDFs del mismo NIT y misma `fecha_factura` | Un JSON por PDF con su `valor_total_documento` individual |
| Un solo movimiento bancario ≈ suma de facturas | Python concilia en paso `multi_factura` |
| Varios movimientos bancarios (uno por factura) | Un JSON por PDF (flujo normal, fase 1) |

**Incorrecto — JSON fusionado con números concatenados:**

```json
{
  "numero_factura": "FE-1001, FE-1002",
  "valor_total_documento": 100000.0
}
```

Eso generaba una sola fila Excel con ambos números. Usar JSONs separados.

**Ejemplo — restaurante, dos facturas, un cargo (montos ilustrativos):**

| Documento | Total |
|-----------|-------|
| FE-1001 | 80,000 |
| FE-1002 | 20,000 |
| **Cargo preliminar** `RESTAURANTE LA MESA` | **100,000** |

`RESTAURANTE LA MESA - FE-1001.json`:

```json
{
  "source_filename": "RESTAURANTE LA MESA - FE-1001.pdf",
  "numero_factura": "FE-1001",
  "nit_proveedor": "900666777",
  "razon_social": "RESTAURANTE LA MESA EJEMPLO S.A.S",
  "nombre_comercial": "LA MESA",
  "moneda": "COP",
  "valor_base": 67226.89,
  "iva": 12773.11,
  "valor_total_documento": 80000.0,
  "fecha_factura": "2026-05-12",
  "detalle_gasto": "TC 1234 GASTO DE REPRESENTACIÓN ALMUERZO RESTAURANTE LA MESA 12 DE MAYO",
  "tipo_documento": "factura",
  "consolidado": false,
  "sin_desglose_iva": true,
  "legible": true
}
```

`RESTAURANTE LA MESA - FE-1002.json`:

```json
{
  "source_filename": "RESTAURANTE LA MESA - FE-1002.pdf",
  "numero_factura": "FE-1002",
  "nit_proveedor": "900666777",
  "razon_social": "RESTAURANTE LA MESA EJEMPLO S.A.S",
  "nombre_comercial": "LA MESA",
  "moneda": "COP",
  "valor_base": 16806.72,
  "iva": 3193.28,
  "valor_total_documento": 20000.0,
  "fecha_factura": "2026-05-12",
  "detalle_gasto": "TC 1234 GASTO DE REPRESENTACIÓN ALMUERZO RESTAURANTE LA MESA 12 DE MAYO",
  "tipo_documento": "factura",
  "consolidado": false,
  "sin_desglose_iva": true,
  "legible": true
}
```

Python concilia la suma (80.000 + 20.000 = 100.000) contra el cargo único y genera **dos filas** en Excel.

## Ejemplo recibo de caja menor (consolidado)

Un recibo puede cubrir **varios movimientos** del extracto con la misma descripción y fecha.
Python concilia si la suma de esos movimientos coincide con el total del recibo.

```json
{
  "source_filename": "APP TRANSPORTE - RECIBO DE CAJA 100.pdf",
  "numero_factura": "100",
  "nit_proveedor": "900222333",
  "razon_social": "APP TRANSPORTE EJEMPLO SAS",
  "moneda": "COP",
  "valor_base": 35000.0,
  "iva": 0.0,
  "valor_total_documento": 35000.0,
  "fecha_factura": "2026-05-25",
  "detalle_gasto": "TC 1234 SERVICIO DE TRANSPORTE",
  "tipo_documento": "recibo_caja_menor",
  "consolidado": true,
  "legible": true
}
```

## Recibo de caja por propina (cargo compuesto)

Cuando el **cargo del extracto** incluye factura + propina en documentos separados, el recibo de propina debe marcarse así:

- `tipo_documento`: `"recibo_caja_menor"`
- `consolidado`: **false** (no agrupa varios movimientos del extracto)
- `es_propina`: **true**
- `valor_total_documento`: monto de la propina únicamente
- `detalle_gasto`: incluir "PROPINA" y referencia al gasto (fecha/comercio)

Python concilia si `factura + recibo ≈ cargo` (±2%), mismo NIT, fecha del recibo hasta 30 días después del cargo. En Excel salen **dos filas** (factura + recibo).

```json
{
  "source_filename": "CAFETERIA EL HORNO - RECIBO DE CAJA 50.pdf",
  "numero_factura": "50",
  "nit_proveedor": "900777888",
  "razon_social": "CAFETERIA EL HORNO EJEMPLO SAS",
  "moneda": "COP",
  "valor_base": 8000.0,
  "iva": 0.0,
  "valor_total_documento": 8000.0,
  "fecha_factura": "2026-05-28",
  "detalle_gasto": "TC 1234 PROPINA CAFETERIA EL HORNO 8 DE MAYO",
  "tipo_documento": "recibo_caja_menor",
  "consolidado": false,
  "es_propina": true,
  "legible": true
}
```

## Pago mixto (solo porción con tarjeta)

Cuando la factura muestra **varios medios de pago**, el JSON debe reflejar únicamente lo cargado a la tarjeta corporativa, no el total de la factura.

| En la factura | ¿Usar en JSON? |
|---------------|----------------|
| Total a pagar / Total bruto | No |
| Valor de un ítem (si solo parte se pagó con TC) | No |
| Línea "Tarjeta", "Tarjetas", "TC", etc. | **Sí** → `valor_total_documento` |
| Efectivo / transferencia (otro medio) | No |

**Ejemplo — club deportivo, pago mixto (montos ilustrativos):**

| Concepto en PDF | Monto |
|-----------------|-------|
| Total a pagar | 500,000 |
| Transferencia / efectivo | 300,000 |
| **Tarjetas** | **200,000** ← usar este |
| Cargo extracto `CLUB DEPORTIVO EJEMPLO` | 200,000 |

```json
{
  "source_filename": "CLUB DEPORTIVO - BOL-300.pdf",
  "numero_factura": "BOL-300",
  "nit_proveedor": "900888999",
  "razon_social": "CLUB DEPORTIVO EJEMPLO S.A.S",
  "moneda": "COP",
  "valor_base": 200000.0,
  "iva": 0.0,
  "valor_total_documento": 200000.0,
  "fecha_factura": "2026-05-12",
  "detalle_gasto": "TC 1234 BEBIDAS CELEBRACION COLABORADORES 12 DE MAYO",
  "tipo_documento": "factura",
  "consolidado": false,
  "legible": true
}
```

## Ejemplo ilegible

```json
{
  "source_filename": "scan_borroso.jpg",
  "numero_factura": null,
  "nit_proveedor": null,
  "razon_social": null,
  "moneda": null,
  "valor_base": null,
  "iva": 0.0,
  "valor_total_documento": null,
  "fecha_factura": null,
  "detalle_gasto": null,
  "legible": false
}
```

## Conciliación (Python, no Claude)

- El cargo en COP del banco viene del **preliminar** (columna E).
- Python convierte `valor_total_documento` a COP vía Frankfurter v2 (`/v2/rate/{moneda}/COP`) y compara ±2% y ±3 días. **Facturas SOL** usan tolerancia ampliada (`AMOUNT_TOLERANCE_PCT_SOL`, default 12%) aunque el preliminar solo traiga el cargo en COP (propinas en terminal Perú); si el concepto incluye `VR MONEDA ORIG … SOL`, Python compara también en soles directamente. USD/CLP/COP siguen en 2%.
- Excel columnas COPS y total compra = COP del preliminar, no de la factura.
- **Facturas COP:** Python muestra el desglose (`valor_base` + `iva`) en Excel **solo si** el cargo ≈ `valor_base + iva` (±tolerancia), o si `otros_impuestos > 0` y el cargo ≈ `valor_base + iva + otros_impuestos`. En ambos casos `iva` debe ser **solo IVA al 19%**; INC/ICUI/IBUA van en `otros_impuestos`. Por eso `valor_base` debe ser la **suma gravada + exenta** (subtotal ítems), no solo la gravada.
  - **Restaurante:** si `sin_desglose_iva: true` o si `detalle_gasto`/concepto bancario contiene keywords de restaurante (`RESTAURANT_NO_IVA_KEYWORDS` en `.env`, default: RESTAURANTE, ALMUERZO, CENA, COMIDA, GASTO DE REPRESENTACION), **una fila**: COPS = cargo del preliminar, IVA vacío (aunque el PDF discrimine IVA al 8%).
  - Si además `valor_base × 19% ≈ iva` (`IVA_RATE_COP`), **una fila**: COPS = `valor_base`, IVA = `iva`, Total compra = cargo.
  - Si el cargo ≈ base+iva pero `valor_base × 19%` no cuadra con el IVA (ítems gravados y exentos), **dos filas**: gravada con `round(iva / IVA_RATE_COP)` + IVA; exenta con el resto de la base sin IVA.
  - Si el cargo ≈ `base + iva + otros_impuestos` con `otros_impuestos > 0` (INC/ICUI, etc.), **dos filas** con la misma lógica de split; la fila exenta incluye bases exentas más esos otros impuestos.
  - Si el extracto es el **total** con propina/recargos incluidos (cargo > base+iva), Python parte en dos filas: gravada (`base` + `iva` = total de esa fila) y exenta (resto del cargo sin IVA), salvo restaurante (`sin_desglose_iva` / keywords).
- **Facturas USD / CLP / SOL:** columna G = moneda; monto en columna H (USD), I (CLP) o J (SOL) según `moneda` del JSON (prioridad: `amount_original` del preliminar si coincide moneda → `valor_total_documento` → `valor_base`); **sin IVA**; COPS y total compra = cargo COP del preliminar.
- Si `detalle_gasto` es null, Python usa histórico genérico del proveedor o texto `TC {tarjeta} GASTO {razón social}`.
- Recibos con `consolidado=true`: Python agrupa movimientos UNMATCHED del **mismo día** que **identifiquen al proveedor** (pueden tener **distintos conceptos** en el extracto, ej. `APP*TRIP`, `DLC*RIDES`) buscando el subconjunto cuya suma ≈ total del recibo (hasta `CONSOLIDATED_MAX_GROUP_SIZE`, default 6), o **un solo movimiento** si su monto ≈ total; cargos de otros comercios el mismo día no entran al pool del recibo. Si hay más de un subconjunto válido, no concilia automáticamente. **Fecha del recibo (fase automática):** mismo año calendario que el cargo y hasta 30 días después (`CONSOLIDATED_RECEIPT_MAX_DAYS_AFTER`). **Fecha fuera de ventana (fase revisión):** si concepto y monto coinciden pero el recibo cae después de esos 30 días, Python concilia con fila amarilla y `Validación = REVISAR` en el preliminar; el recibo debe ser ≥ al cargo, con gap máximo de 3 meses (`CONSOLIDATED_RECEIPT_REVIEW_MAX_MONTHS`); si cambia el año, deben ser años consecutivos. En el **Excel de legalización** esos movimientos aparecen como **una sola fila** con el total del recibo (no una fila por cada viaje/cargo del extracto). La columna Nº factura muestra **RECIBO DE CAJA {número}** (ej. `RECIBO DE CAJA 100`).
- Recibos con `es_propina=true`: Python concilia **un movimiento** cuyo monto = factura + recibo (mismo NIT). En Excel salen **dos filas** (factura con base/IVA; recibo de propina sin IVA). La fila de propina recibe el artículo contable de `ARTICULO_PROPINA` en `.env`.
- **Varias facturas, un cargo:** Python concilia **1 movimiento ↔ 1 JSON**. Si hay varios PDFs pero un solo cargo bancario, el operador debe fusionar en un JSON (suma de montos, números de factura concatenados); ver sección [Varias facturas, un solo cargo](#varias-facturas-un-solo-cargo-en-el-preliminar). Python **no** suma varios JSON contra un movimiento.
- **Desempate por concepto:** si varias facturas coinciden en monto y fecha (±tolerancia), Python compara el **concepto del movimiento** del preliminar con tokens significativos de la razón social, **`nombre_comercial`**, **`detalle_gasto`** y el NIT del proveedor; gana la factura con mayor coincidencia. Si persiste empate, elige monto y fecha más cercanos. **Una factura solo se asigna a un movimiento:** si varios cargos compiten por la misma factura, gana el de mayor coincidencia de concepto y monto/fecha más cercanos; los tokens del extracto deben coincidir exactamente (evita falsos positivos tipo `REST` vs `RESTAURANTE`). Incluir en `detalle_gasto` palabras del concepto bancario (ej. `RESTAURANTE`) mejora la conciliación cuando `nombre_comercial` es corto (ej. `LA MESA`).
- Pago mixto: si `valor_total_documento` es el total de la factura y no la porción tarjeta, la conciliación fallará (`Validación` = NO en el preliminar; revisar columna **Observaciones**).
- **Documento Soporte (Excel):** indica factura internacional — `SI` si `moneda` ≠ COP, `NO` si COP, vacío si el movimiento no concilió.
- **Histórico de proveedores:** Python **lee** la pestaña `historico_proveedores` del Sheet de control; **no la escribe**. La búsqueda es por NIT (normalizando guión y dígito de verificación antes de comparar, p. ej. `901964712-0` ↔ `901964712`) y, en su defecto, por razón social. El reporte incluye `proveedores_pendientes_historico` **únicamente** cuando un NIT conciliado no pudo resolverse de ninguna forma y la fila del Excel quedó sin artículo contable; si el Excel tiene el artículo lleno, el proveedor ya estaba en el Sheet (pudo haberse resuelto por razón social) y la sección no aparece.
- **Filas amarillas con factura sugerida:** movimientos `UNMATCHED`/`AMBIGUOUS` con candidato claro muestran Nº factura, NIT y razón social sugeridos en el Excel de legalización (montos según factura), pero la fila sigue amarilla y **no** cuenta como conciliado en el reporte ni agrega NIT a `new_provider_nits`. Si **monto y fecha** coinciden pero el concepto del banco difiere de la razón social (ej. nombre legal en terminal vs comercial en factura), Python sugiere la factura en amarillo sin marcar `OK`.
