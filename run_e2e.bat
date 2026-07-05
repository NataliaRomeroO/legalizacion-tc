@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe python -m venv .venv
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
.venv\Scripts\python.exe -m pip install -q -e .

set "FOLDER_ARG="
if not "%~1"=="" (
    set "FOLDER_ARG=--folder %~1"
)

echo.
echo === E2E Legalizacion TC ===
if defined FOLDER_ARG (
    echo Carpeta: %~1
) else (
    echo Carpeta: auto-detectada en el repo
)
echo.

.venv\Scripts\python.exe scripts\run_full_e2e.py %FOLDER_ARG%
if errorlevel 1 (
    echo.
    echo E2E fallo. Ver e2e_results.json
    exit /b 1
)

.venv\Scripts\python.exe scripts\dump_xlsx_json.py %FOLDER_ARG%
.venv\Scripts\python.exe scripts\run_e2e_1111.py %FOLDER_ARG%
echo DONE > e2e_done.flag
echo.
echo E2E completado. Ver e2e_results.json y xlsx_dump.json
