# AGENTS.md — Operador Claude Code (Legalización TC)

Este repositorio automatiza la legalización mensual de tarjetas de crédito corporativas.
**Claude Code** actúa como operador: tú ejecutas scripts Python y lees facturas en sesión.

## Reglas absolutas

1. Ejecutar pasos **en orden**; no saltar validaciones.
2. **No inventar** NIT, montos, fechas ni números de factura.
3. **No incluir montos COP** en JSON de facturas (vienen del preliminar).
4. **No loguear** credenciales ni PAN completo de tarjeta.
5. Cálculos de montos y FX: solo scripts Python (Frankfurter), nunca estimaciones manuales.
6. **Drive y Sheets:** acceder **solo** ejecutando scripts Python (`extract_invoices_template.py`, `run_pipeline`). **Prohibido** buscar, navegar o listar archivos en Drive desde el chat.
7. **Mac — Python:** ejecutar scripts **siempre** con `.venv/bin/python` (ruta explícita al venv). No usar `python` suelto en macOS.

## Acceso a Google Drive y Sheets

Los scripts usan la **cuenta de servicio** definida en `.env`:

- `GOOGLE_APPLICATION_CREDENTIALS` → ruta al JSON de la SA
- `SERVICE_ACCOUNT_EMAIL` → email de la SA (o el campo `client_email` del JSON)

Compartir cada carpeta de tarjeta y el Sheet de control con **ese** email (Editor).

| Acción | Cómo hacerlo | Autenticación |
|--------|--------------|---------------|
| Listar / descargar facturas y preliminar | `.venv/bin/python scripts/extract_invoices_template.py --folder-id "..."` | Cuenta de servicio (`.env`) |
| Ejecutar legalización y subir Excel | `.venv/bin/python -m legalizacion_tc.run_pipeline --folder-id "..." --skip-invoice-extraction` | Cuenta de servicio (`.env`) |
| Leer tarjetas e histórico | Automático dentro de `run_pipeline` (modo Drive) | Cuenta de servicio (`.env`) |
| “Buscar en Drive” desde el chat | **No hacer** | No aplica |

## Estructura de carpetas Drive

| Layout | Contenido | Comportamiento |
|--------|-----------|----------------|
| **Carpeta padre (mes)** | Subcarpetas `1111 - DEMO USER A`, `2222 - ...` | Procesa **todas** las subcarpetas |
| **Carpeta de una TC** | Preliminar `Mov TC*.xlsx` **o** extracto PDF `{tarjeta}_{MES}{año}.pdf` + facturas | Procesa **solo esa** tarjeta |

## Origen de movimientos

| Opción | Archivo | Ejemplo |
|--------|---------|---------|
| **1 — Preliminar Excel** | `Mov TC*.xlsx` | `Mov TC 1111 Corte Mayo.xlsx` |
| **2 — Extracto PDF Bancolombia** | `{tarjeta}_{MES}{año}.pdf` | `1111_MAY2026.pdf` |

**Prioridad:** si hay PDF y Excel, se usa el **PDF**.

**Prompt — todas las tarjetas:**

```
Legaliza todas las tarjetas del mes.
Carpeta Drive: https://drive.google.com/drive/folders/PARENT_ID
Sigue AGENTS.md paso a paso.
```

**Prompt — una tarjeta:**

```
Legaliza la tarjeta 1111.
Carpeta Drive: https://drive.google.com/drive/folders/SUBFOLDER_ID
Sigue AGENTS.md paso a paso.
```

## Flujo por tarjeta

### Paso 1 — Preparar entorno

**macOS:**

```bash
cd <repo-root>
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
cp .env.example .env
```

**Windows:**

```powershell
cd <repo-root>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
copy .env.example .env
```

### Paso 2 — Descargar archivos

```bash
.venv/bin/python scripts/extract_invoices_template.py --folder-id "URL_O_ID_DRIVE" --init-templates
```

### Paso 3 — Extraer facturas (Claude Code en sesión)

Seguir [`docs/PROMPT-FACTURAS.md`](docs/PROMPT-FACTURAS.md). Guardar JSON en `.cache/cards/{tarjeta}/invoices/`.

### Paso 4 — Ejecutar pipeline

```bash
.venv/bin/python -m legalizacion_tc.run_pipeline --folder-id "URL_O_ID_DRIVE" --skip-invoice-extraction
```

**Modo prueba local:**

```bash
.venv/bin/python -m legalizacion_tc.run_pipeline --local-folder "tests/fixtures/demo_card" --skip-invoice-extraction
```

### Paso 5 — Notificar al operador

Interpretar el JSON de stdout: `status`, `summary`, `legalization_file_link`, movimientos sin soporte, etc.

## Sheet de control

- ID en `.env` (`CONTROL_SHEET_ID`)
- Pestaña `Tarjetas`: tarjeta → solicitante, centro_costo
- Pestaña `historico_proveedores`: NIT → detalle, artículo contable

## Tarjeta de ejemplo (demo)

| Tarjeta | Solicitante | Centro de costo |
|---------|-------------|-----------------|
| 1111 | Demo User A | 100-Demo |

En producción, las tarjetas se cargan desde el Sheet de control.

## Documentación adicional

- [`docs/PROMPT-FACTURAS.md`](docs/PROMPT-FACTURAS.md) — extracción de facturas
