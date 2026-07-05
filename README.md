# Legalización TC — Python + Claude Code operador

Automatización de legalización de tarjetas de crédito corporativas.

- **Python:** extracto, conciliación (Frankfurter ±2%), Excel, Drive, Sheets.
- **Claude Code:** lee facturas en sesión → JSON; notifica al operador.

## Inicio rápido

**Windows (PowerShell):**

```powershell
cd <repo-root>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
copy .env.example .env
pytest
```

**macOS (zsh):**

```bash
cd <repo-root>
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
cp .env.example .env
.venv/bin/python -m pytest
```

## Demo local (sin Google Drive)

```bash
mkdir -p .cache/cards/1111/invoices
cp tests/fixtures/demo_card/invoices/aws.json .cache/cards/1111/invoices/

python -m legalizacion_tc.run_pipeline \
  --local-folder tests/fixtures/demo_card \
  --skip-invoice-extraction
```

## Uso con Google Drive

1. Crear cuenta de servicio GCP y compartir carpetas con su email (Editor).
2. Configurar `GOOGLE_APPLICATION_CREDENTIALS` y demás variables en `.env`.
3. Descargar facturas y crear JSON (Claude Code o manual):

```bash
python scripts/extract_invoices_template.py --folder-id "FOLDER_ID" --init-templates
```

4. Ejecutar pipeline:

```bash
python -m legalizacion_tc.run_pipeline --folder-id "FOLDER_ID" --skip-invoice-extraction
```

## Estructura

```
src/legalizacion_tc/   # Código del pipeline
scripts/               # Utilidades CLI
tests/                 # Tests + fixtures
docs/                  # PROMPT-FACTURAS.md, MODULOS.md
Plantilla Legalizacion TC Demo.xlsx  # Plantilla Excel demo (git)
AGENTS.md              # Contrato para el agente Claude Code
.cache/cards/{tarjeta}/invoices/  # JSON por factura (gitignored)
```

## Documentación

| Archivo | Para quién |
|---------|------------|
| [AGENTS.md](AGENTS.md) | Claude Code (operador automático) |
| [docs/PROMPT-FACTURAS.md](docs/PROMPT-FACTURAS.md) | Prompt extracción facturas |
| [docs/MODULOS.md](docs/MODULOS.md) | Mapa de módulos y flujo del pipeline |

## Variables de entorno

Ver [.env.example](.env.example). **No commitear** `.env` ni JSON de cuenta de servicio.

## Tests

```bash
pytest -v
python scripts/inspect_samples.py tests/fixtures/demo_card
```
