# Commonplace Careers

A Flask and SQLite job portal for people looking for work and teams hiring. Job seekers can search and filter listings, apply, and track application status. Employers can publish and manage listings and review applicants. Administrators can manage user access and remove listings.

## Features

- Seeker and employer registration, sign-in, and sign-out with hashed passwords
- Role-protected seeker, employer, and administrator workspaces
- Job search by keywords, location, category, and company
- Employer job creation, editing, removal, and applicant review
- Seeker applications with an optional resume URL and status tracking
- Admin user access controls and listing moderation
- CSRF protection on form submissions
- SQLite database initialized automatically with sample listings
- Responsive Bootstrap-based interface with custom styling

## Requirements

- Python 3.10 or newer
- pip

## Run locally

From the project directory, create and activate a virtual environment:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000. The SQLite database is created at `instance/job_portal.sqlite3` on the first run. The app seeds sample roles automatically when that database has no listings.

For a development admin account, set credentials before the first run (or before restarting an existing database):

```powershell
$env:ADMIN_EMAIL = "admin@example.com"
$env:ADMIN_PASSWORD = "choose-a-long-password"
python app.py
```

The admin can then sign in at `/login`. Admin accounts are not available through public registration. Set `$env:SECRET_KEY` to a private random value; the built-in key is for local development only.

## Tests

Run the workflow tests with:

```powershell
python -m unittest discover -s tests -v
```

The tests use a temporary SQLite database and do not alter the local demo data.

## Deployment

Set a unique `SECRET_KEY`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD` in the hosting provider's environment settings. Install dependencies with `pip install -r requirements.txt`, then start with `gunicorn app:app` on Linux hosts. Use persistent storage for the `instance/` directory so SQLite data survives redeployments. For a multi-instance deployment, configure PostgreSQL and a shared session store instead of local SQLite.

## Project layout

```text
app.py                 Flask routes, auth, database setup
templates/             Jinja pages
static/                CSS and small browser interactions
tests/test_app.py      Workflow tests
requirements.txt       Python dependencies
instance/              Local SQLite database (generated)
```