#!/usr/bin/env bash
# ============================================================
#  Flujo - one-click setup & run for macOS / Linux
# ============================================================
set -e
cd "$(dirname "$0")"

echo ""
echo "==== Flujo - Sales, Order Processing & Dispatch ===="
echo ""

# 1. Virtual environment
if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi
source venv/bin/activate

# 2. Dependencies
echo "Installing dependencies..."
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# 3. Configuration lives in config/settings.py — no .env required.

# 4. Ensure the database exists (creates it if missing)
echo "Checking database..."
python ensure_db.py || { echo ">> Could not prepare the database. Fix the issue above and run again."; exit 1; }

# 5. Migrate
echo "Applying database migrations..."
python manage.py migrate

# 6. Seed once
if [ ! -f .seeded ]; then
  echo "Loading demo data..."
  python manage.py seed_demo
  echo done > .seeded
fi

# 7. Run
echo ""
echo "============================================================"
echo "  Flujo is starting. Open http://127.0.0.1:8000 in your browser."
echo "  Demo login: admin / flujo123   (press CTRL+C to stop)"
echo "============================================================"
echo ""
python manage.py runserver
