# OOTP DB Explorer

A web-based admin console for exploring the MySQL database export from **OOTP27** (Out of the Park Baseball 27).

Browse every table, paginate through rows, search within a table, follow foreign-key links, and see related records — all from a clean Bootstrap UI.

---

## Features

- **Table browser** — lists every table in the database with column/FK counts
- **Row viewer** — paginated, searchable view of any table
- **FK badges** — columns that are primary keys (PK) or foreign keys (FK) are labelled
- **FK navigation** — click a foreign-key value to jump to the referenced record
- **Record detail** — full field list plus all related records from other tables that reference this record
- **Responsive sidebar** — quick navigation to any table

---

## Requirements

- Python 3.10+
- A running MySQL server with the OOTP27 database imported

---

## Setup

```bash
# 1. Clone the repository
git clone https://github.com/timothyf/ootp-db-explorer.git
cd ootp-db-explorer

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure the database connection
cp .env.example .env
# Edit .env and fill in your MySQL credentials:
#   DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
```

## Running

```bash
python app.py
```

Then open your browser at **http://localhost:5000**.

For production use, run with a WSGI server:

```bash
pip install gunicorn
gunicorn app:app -b 0.0.0.0:5000
```

---

## Configuration (`.env`)

| Variable          | Default     | Description                        |
|-------------------|-------------|------------------------------------|
| `DB_HOST`         | `localhost` | MySQL host                         |
| `DB_PORT`         | `3306`      | MySQL port                         |
| `DB_USER`         | `root`      | MySQL username                     |
| `DB_PASSWORD`     | *(empty)*   | MySQL password                     |
| `DB_NAME`         | `ootp_db`   | Database name                      |
| `FLASK_SECRET_KEY`| *(random)*  | Flask session secret — change this |
| `FLASK_DEBUG`     | `false`     | Enable Flask debug mode            |

---

## Project Structure

```
ootp-db-explorer/
├── app.py              # Flask application (routes, DB helpers)
├── config.py           # Configuration from environment variables
├── requirements.txt    # Python dependencies
├── .env.example        # Example environment file
├── static/
│   └── style.css       # Custom CSS
└── templates/
    ├── base.html       # Base layout (navbar + sidebar)
    ├── index.html      # Home — table list
    ├── table.html      # Table browser (paginated + search)
    ├── record.html     # Record detail + related records
    └── error.html      # DB connection error page
```

