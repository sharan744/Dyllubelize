@echo off
REM ============================================================
REM  Flujo - one-click setup & run for Windows
REM ============================================================
setlocal

echo.
echo ==== Flujo - Sales, Order Processing ^& Dispatch ====
echo.

REM 1. Create virtual environment if missing
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM 2. Activate it
call venv\Scripts\activate.bat

REM 3. Install dependencies
echo Installing dependencies...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt

REM 4. Configuration lives in config\settings.py — no .env required.

REM 5. Ensure the database exists (creates it if missing)
echo Checking database...
python ensure_db.py
if errorlevel 1 (
    echo.
    echo  Could not prepare the database. Fix the issue above and run again.
    echo.
    pause
    exit /b
)

REM 6. Migrate database
echo Applying database migrations...
python manage.py migrate

REM 7. Load demo data on first run only
if not exist .seeded (
    echo Loading demo data...
    python manage.py seed_demo
    echo done > .seeded
)

REM 8. Run the server
echo.
echo ============================================================
echo   Flujo is starting. Open http://127.0.0.1:8000 in your browser.
echo   Demo login: admin / flujo123   (press CTRL+C to stop)
echo ============================================================
echo.
python manage.py runserver

endlocal
