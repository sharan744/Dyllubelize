# Flujo — Sales, Order Processing & Dispatch Management

An internal web platform that tracks the **complete order flow** in one place:

> Catalogue → Customer → Order → Team Lead confirmation → Processing →
> Ready for Dispatch → Dispatch List → Delivery → Proof of Delivery → Completed

Built with **Django 5 + PostgreSQL** and a modern **HTML / CSS / vanilla JavaScript
(ES modules)** front-end. It runs entirely on a **local machine** — no cloud or
external server required.

---

## 1. What's inside

| Module | Covers |
|--------|--------|
| **Catalogue** | Categories & products, images, SKU, unit, price, stock, active/inactive |
| **Customers** | Search existing, add new, view previous orders |
| **Orders** | Product picker, quantities, line & order discounts, remarks, draft/submit |
| **Team Lead** | Review queue, confirm / return for correction, remarks |
| **Processing** | Start processing → mark ready for dispatch |
| **Dispatch** | Combine multiple orders into one vehicle, assign driver, printable A4 delivery note |
| **Delivery** | Confirm delivery, capture receiver, signature, remarks, POD file upload |
| **Tracking** | Central dashboard with counts, pipeline, filters by status / customer / salesperson / date |
| **Users & Roles** | Admin, Sales, Team Lead, Processing, Dispatch, Delivery (role-based access) |

Every order has a unique **Order ID** (e.g. `ORD-26-0001`) and every dispatch a
unique **Dispatch ID** (`DSP-26-0001`), with a full status history.

---

## 2. Requirements

- **Python 3.11+** — https://www.python.org/downloads/ (on Windows, tick *“Add Python to PATH”*)
- **PostgreSQL 14+** — https://www.postgresql.org/download/

---

## 3. Setup (step by step)

### 3.1 Create the database
The run scripts (`run.bat` / `run.sh`) **create the database automatically** on first
launch, so you normally don't need to do anything here — just make sure PostgreSQL is
installed and running, and that your password is set in `.env` (step 3.2).

If you prefer to create it yourself, open **pgAdmin** or the **SQL Shell (psql)** that
ships with PostgreSQL and run:

```sql
CREATE DATABASE sopd_db;
```

> If you ever see `FATAL: database "sopd_db" does not exist`, it just means the database
> hasn't been created yet — run `psql -U postgres -c "CREATE DATABASE sopd_db;"` (or use
> the run script, which does it for you).

(The default `postgres` user is fine. Note the password you set during PostgreSQL install.)

### 3.2 Configure the app
Copy `.env.example` to `.env` and edit the database password:

```
DB_NAME=sopd_db
DB_USER=postgres
DB_PASSWORD=YOUR_POSTGRES_PASSWORD
DB_HOST=127.0.0.1
DB_PORT=5432
```

### 3.3 Install & run

**Windows** — double-click **`run.bat`** (or run it in a terminal).
**macOS / Linux** — run `bash run.sh`.

The script creates a virtual environment, installs dependencies, applies the
database migrations, loads demo data and starts the server.

When you see `Starting development server at http://127.0.0.1:8000/`, open that
address in your browser.

---

## 4. Manual commands (if you prefer)

```bash
python -m venv venv
# Windows:  venv\Scripts\activate
# mac/linux: source venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # optional demo data
python manage.py createsuperuser    # your own admin login
python manage.py runserver
```

---

## 5. Demo logins

After `seed_demo`, these accounts exist (password: **`flujo123`**):

| Username | Role | Sees |
|----------|------|------|
| `admin` | Admin | Everything + `/admin/` |
| `sales` | Sales Person | Catalogue, customers, create orders |
| `teamlead` | Team Lead | Review queue, confirm/return |
| `processing` | Processing | Confirmed → ready for dispatch |
| `dispatch` | Dispatch | Create dispatch lists, print delivery notes |
| `delivery` | Delivery | Confirm deliveries, upload POD |

> ⚠️ Before going live, delete the demo users (or run `seed_demo --reset` is only
> for demos), create real users in **Users**, and change the `admin` password.

---

## 6. Company details on printed documents

Log in as **admin → Admin & Settings → Site settings** (or `/admin/`) to set your
company name, address, phone, e-mail and RFC. These appear on every printed
delivery note. Currency defaults to Mexican Peso (MXN, `$`).

---

## 7. Printing delivery notes

Open any dispatch → **Delivery Document** → **Print / Save as PDF**. The layout is
A4-optimised; in the browser's print dialog choose *“Save as PDF”* to keep a file,
or send it straight to a printer. It includes a customer acknowledgement /
signature section.

---

## 8. Project structure

```
flujo/
├── config/          Django project settings & URLs
├── accounts/        Custom user + roles, login, user management
├── catalogue/       Categories & products
├── orders/          Customers, orders, order items, status history
├── dispatchapp/     Dispatch lists + printable delivery note
├── delivery/        Delivery confirmation & POD
├── core/            Dashboard, site settings, shared permissions
├── templates/       All HTML templates
├── static/          CSS (design system + print) and JavaScript
├── media/           Uploaded product images & POD files
├── requirements.txt
├── run.bat / run.sh Setup & run helpers
└── .env.example     Configuration template
```

---

## 9. Going to production (later)

This build is configured for easy local use. Before deploying for real:

- set `DEBUG=False` and a strong `SECRET_KEY` in `.env`
- set `ALLOWED_HOSTS` to the machine's name/IP
- run `python manage.py collectstatic` and serve behind a real web server
  (e.g. Waitress/Gunicorn + Nginx)
- take regular PostgreSQL backups
