import os
import secrets
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('seeker', 'employer', 'admin')),
    company TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    category TEXT NOT NULL,
    employment_type TEXT NOT NULL,
    salary TEXT,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    cover_letter TEXT NOT NULL,
    resume_url TEXT,
    status TEXT NOT NULL DEFAULT 'Received'
        CHECK (status IN ('Received', 'In review', 'Interview', 'Declined')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, user_id)
);
"""

SAMPLE_JOBS = [
    (
        "Senior Product Designer",
        "Northstar Labs",
        "New York, NY · Hybrid",
        "Design",
        "Full-time",
        "$145k – $180k",
        "Shape the next generation of tools for independent businesses. You will partner with product and engineering to take thoughtful ideas from first sketch through launch.\n\nWe value clear thinking, useful details, and a healthy respect for the people on the other side of the screen. You will help set the direction for our design system and make complex workflows feel simple.",
    ),
    (
        "Backend Engineer, Platform",
        "Fieldwork",
        "Remote · US time zones",
        "Engineering",
        "Full-time",
        "$160k – $205k",
        "Build dependable infrastructure for a product used by teams around the world. Our platform group owns service foundations, developer tooling, and the systems that keep customer data safe.\n\nYou bring strong Python experience, a practical approach to distributed systems, and the curiosity to improve how a growing engineering team works.",
    ),
    (
        "People Operations Partner",
        "Common Thread",
        "Chicago, IL · Hybrid",
        "People & HR",
        "Full-time",
        "$95k – $120k",
        "Help a people-first company build the practices that let good work happen. You will partner with managers on employee experience, thoughtful hiring, and the everyday systems behind a healthy team.\n\nThe ideal partner combines excellent judgment with a bias for clear, human communication.",
    ),
    (
        "Growth Marketing Associate",
        "Brightside Energy",
        "Austin, TX · On-site",
        "Marketing",
        "Full-time",
        "$72k – $88k",
        "Make clean energy easier to choose. Work with a small, ambitious team to run experiments across paid, lifecycle, and content channels, then turn what you learn into the next round of better campaigns.\n\nBring sharp writing, analytical instincts, and a willingness to get close to the details.",
    ),
    (
        "Finance & Business Analyst",
        "Morrow Health",
        "Remote · US",
        "Finance",
        "Full-time",
        "$105k – $132k",
        "Turn thoughtful analysis into decisions that improve access to care. You will build operating models, help teams understand performance, and make financial information useful to people across the company.\n\nAdvanced spreadsheet skills and a collaborative working style are essential.",
    ),
    (
        "Customer Support Specialist",
        "Fieldwork",
        "Denver, CO · Hybrid",
        "Customer Success",
        "Full-time",
        "$58k – $72k",
        "Be the calm, capable voice customers remember. You will help people solve real problems, spot patterns in incoming feedback, and work closely with product to make the experience better for everyone.",
    ),
]


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "local-development-key-change-me"),
        DATABASE=os.path.join(app.instance_path, "job_portal.sqlite3"),
        ADMIN_EMAIL=os.environ.get("ADMIN_EMAIL", ""),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    with app.app_context():
        init_db()
        bootstrap_admin()

    @app.before_request
    def load_user_and_check_csrf():
        user_id = session.get("user_id")
        g.user = None
        if user_id is not None:
            g.user = get_db().execute(
                "SELECT * FROM users WHERE id = ? AND active = 1", (user_id,)
            ).fetchone()
            if g.user is None:
                session.clear()
        if request.method == "POST":
            submitted = request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not expected or not secrets.compare_digest(submitted, expected):
                abort(400, description="The form expired. Please reload and try again.")

    @app.teardown_appcontext
    def close_db(exception=None):
        database = g.pop("db", None)
        if database is not None:
            database.close()

    @app.context_processor
    def inject_template_values():
        return {"csrf_token": get_csrf_token}

    @app.get("/")
    def index():
        search = request.args.get("q", "").strip()
        location = request.args.get("location", "").strip()
        category = request.args.get("category", "").strip()
        company = request.args.get("company", "").strip()
        clauses = []
        values = []
        if search:
            clauses.append("(j.title LIKE ? OR j.description LIKE ? OR j.company LIKE ?)")
            values.extend([f"%{search}%"] * 3)
        if location:
            clauses.append("j.location LIKE ?")
            values.append(f"%{location}%")
        if category:
            clauses.append("j.category = ?")
            values.append(category)
        if company:
            clauses.append("j.company LIKE ?")
            values.append(f"%{company}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        jobs = get_db().execute(
            f"""SELECT j.*, COUNT(a.id) AS applicant_count
                FROM jobs j LEFT JOIN applications a ON a.job_id = j.id
                {where} GROUP BY j.id ORDER BY j.created_at DESC, j.id DESC""",
            values,
        ).fetchall()
        categories = get_db().execute(
            "SELECT DISTINCT category FROM jobs ORDER BY category"
        ).fetchall()
        return render_template(
            "index.html",
            jobs=jobs,
            categories=categories,
            filters={"q": search, "location": location, "category": category, "company": company},
        )

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            role = request.form.get("role", "seeker")
            company = request.form.get("company", "").strip()
            error = None
            if not name or len(name) > 100:
                error = "Enter your name (up to 100 characters)."
            elif "@" not in email or len(email) > 254:
                error = "Enter a valid email address."
            elif len(password) < 8:
                error = "Your password must be at least 8 characters."
            elif role not in ("seeker", "employer"):
                error = "Choose a valid account type."
            elif role == "employer" and not company:
                error = "Enter your company name."
            if error:
                flash(error, "error")
            else:
                try:
                    cursor = get_db().execute(
                        "INSERT INTO users (name, email, password_hash, role, company) VALUES (?, ?, ?, ?, ?)",
                        (name, email, generate_password_hash(password), role, company or None),
                    )
                    get_db().commit()
                    session.clear()
                    session["user_id"] = cursor.lastrowid
                    flash("Your account is ready. Welcome to Commonplace.", "success")
                    return redirect(url_for("index"))
                except sqlite3.IntegrityError:
                    get_db().rollback()
                    flash("An account with that email already exists.", "error")
        return render_template("auth.html", mode="register")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute(
                "SELECT * FROM users WHERE email = ? AND active = 1", (email,)
            ).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("That email and password combination was not recognized.", "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                flash(f"Welcome back, {user['name'].split()[0]}.", "success")
                return redirect(url_for("dashboard"))
        return render_template("auth.html", mode="login")

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("index"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        if g.user["role"] == "employer":
            return redirect(url_for("employer_dashboard"))
        if g.user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        applications = get_db().execute(
            """SELECT a.*, j.title, j.company, j.location FROM applications a
               JOIN jobs j ON j.id = a.job_id WHERE a.user_id = ?
               ORDER BY a.created_at DESC""",
            (g.user["id"],),
        ).fetchall()
        return render_template("seeker_dashboard.html", applications=applications)

    @app.get("/jobs/<int:job_id>")
    def job_detail(job_id):
        job = get_db().execute(
            "SELECT * FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
        if job is None:
            abort(404)
        applied = False
        if g.user and g.user["role"] == "seeker":
            applied = get_db().execute(
                "SELECT 1 FROM applications WHERE job_id = ? AND user_id = ?",
                (job_id, g.user["id"]),
            ).fetchone() is not None
        return render_template("job_detail.html", job=job, applied=applied)

    @app.post("/jobs/<int:job_id>/apply")
    @login_required
    @role_required("seeker")
    def apply(job_id):
        job = get_db().execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            abort(404)
        cover_letter = request.form.get("cover_letter", "").strip()
        resume_url = request.form.get("resume_url", "").strip()
        if not cover_letter or len(cover_letter) > 5000:
            flash("Add a short cover letter (up to 5,000 characters) to apply.", "error")
        elif resume_url and not resume_url.startswith(("https://", "http://")):
            flash("Resume links must start with http:// or https://.", "error")
        else:
            try:
                get_db().execute(
                    "INSERT INTO applications (job_id, user_id, cover_letter, resume_url) VALUES (?, ?, ?, ?)",
                    (job_id, g.user["id"], cover_letter, resume_url or None),
                )
                get_db().commit()
                flash("Application sent. You can follow its progress from your dashboard.", "success")
                return redirect(url_for("job_detail", job_id=job_id))
            except sqlite3.IntegrityError:
                get_db().rollback()
                flash("You have already applied for this role.", "error")
        return redirect(url_for("job_detail", job_id=job_id) + "#apply")

    @app.get("/employer")
    @login_required
    @role_required("employer")
    def employer_dashboard():
        jobs = get_db().execute(
            """SELECT j.*, COUNT(a.id) AS applicant_count FROM jobs j
               LEFT JOIN applications a ON a.job_id = j.id
               WHERE j.employer_id = ? GROUP BY j.id ORDER BY j.created_at DESC""",
            (g.user["id"],),
        ).fetchall()
        return render_template("employer_dashboard.html", jobs=jobs)

    @app.route("/employer/jobs/new", methods=["GET", "POST"])
    @login_required
    @role_required("employer")
    def create_job():
        if request.method == "POST":
            data, error = validate_job_form()
            if error:
                flash(error, "error")
            else:
                get_db().execute(
                    """INSERT INTO jobs
                       (employer_id, title, company, location, category, employment_type, salary, description)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (g.user["id"], data["title"], g.user["company"], data["location"], data["category"],
                     data["employment_type"], data["salary"], data["description"]),
                )
                get_db().commit()
                flash("Your job listing is live.", "success")
                return redirect(url_for("employer_dashboard"))
        return render_template("job_form.html", mode="create", job=None)

    @app.route("/employer/jobs/<int:job_id>/edit", methods=["GET", "POST"])
    @login_required
    @role_required("employer")
    def edit_job(job_id):
        job = owned_job_or_404(job_id)
        if request.method == "POST":
            data, error = validate_job_form()
            if error:
                flash(error, "error")
            else:
                get_db().execute(
                    """UPDATE jobs SET title = ?, location = ?, category = ?, employment_type = ?,
                       salary = ?, description = ? WHERE id = ? AND employer_id = ?""",
                    (data["title"], data["location"], data["category"], data["employment_type"],
                     data["salary"], data["description"], job_id, g.user["id"]),
                )
                get_db().commit()
                flash("Listing updated.", "success")
                return redirect(url_for("employer_dashboard"))
        return render_template("job_form.html", mode="edit", job=job)

    @app.post("/employer/jobs/<int:job_id>/delete")
    @login_required
    @role_required("employer")
    def delete_job(job_id):
        owned_job_or_404(job_id)
        get_db().execute(
            "DELETE FROM jobs WHERE id = ? AND employer_id = ?", (job_id, g.user["id"])
        )
        get_db().commit()
        flash("Listing removed.", "success")
        return redirect(url_for("employer_dashboard"))

    @app.get("/employer/jobs/<int:job_id>/applications")
    @login_required
    @role_required("employer")
    def view_applications(job_id):
        job = owned_job_or_404(job_id)
        applications = get_db().execute(
            """SELECT a.*, u.name, u.email FROM applications a
               JOIN users u ON u.id = a.user_id WHERE a.job_id = ?
               ORDER BY a.created_at DESC""",
            (job_id,),
        ).fetchall()
        return render_template("applications.html", job=job, applications=applications)

    @app.post("/employer/applications/<int:application_id>/status")
    @login_required
    @role_required("employer")
    def update_application_status(application_id):
        status = request.form.get("status", "")
        if status not in ("Received", "In review", "Interview", "Declined"):
            abort(400)
        result = get_db().execute(
            """UPDATE applications SET status = ? WHERE id = ? AND job_id IN
               (SELECT id FROM jobs WHERE employer_id = ?)""",
            (status, application_id, g.user["id"]),
        )
        get_db().commit()
        if result.rowcount == 0:
            abort(404)
        flash("Application status updated.", "success")
        return redirect(request.referrer or url_for("employer_dashboard"))

    @app.get("/admin")
    @login_required
    @role_required("admin")
    def admin_dashboard():
        users = get_db().execute(
            "SELECT id, name, email, role, company, active, created_at FROM users ORDER BY created_at DESC"
        ).fetchall()
        jobs = get_db().execute(
            """SELECT j.*, u.name AS employer_name, COUNT(a.id) AS applicant_count
               FROM jobs j LEFT JOIN users u ON u.id = j.employer_id
               LEFT JOIN applications a ON a.job_id = j.id GROUP BY j.id
               ORDER BY j.created_at DESC"""
        ).fetchall()
        return render_template("admin_dashboard.html", users=users, jobs=jobs)

    @app.post("/admin/users/<int:user_id>/toggle")
    @login_required
    @role_required("admin")
    def toggle_user(user_id):
        if user_id == g.user["id"]:
            flash("You cannot deactivate your own admin account.", "error")
            return redirect(url_for("admin_dashboard"))
        target = get_db().execute("SELECT id, active FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            abort(404)
        get_db().execute("UPDATE users SET active = ? WHERE id = ?", (0 if target["active"] else 1, user_id))
        get_db().commit()
        flash("User access updated.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.post("/admin/jobs/<int:job_id>/delete")
    @login_required
    @role_required("admin")
    def admin_delete_job(job_id):
        result = get_db().execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        get_db().commit()
        if result.rowcount == 0:
            abort(404)
        flash("Job and associated applications removed.", "success")
        return redirect(url_for("admin_dashboard"))

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, message="We couldn't find that page."), 404

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("error.html", code=403, message="You don't have access to this page."), 403

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", code=400, message=getattr(error, "description", "That request could not be processed.")), 400

    return app


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def current_app_config_database():
    return current_app.config["DATABASE"]


def init_db():
    db = sqlite3.connect(current_app_config_database())
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    count = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    if count == 0:
        db.executemany(
            """INSERT INTO jobs (title, company, location, category, employment_type, salary, description)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            SAMPLE_JOBS,
        )
    db.commit()
    db.close()


def bootstrap_admin():
    email = current_app.config.get("ADMIN_EMAIL", "").strip().lower()
    password = current_app.config.get("ADMIN_PASSWORD", "")
    if not email or not password:
        return
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing is None:
        db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'admin')",
            ("Portal administrator", email, generate_password_hash(password)),
        )
        db.commit()


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Sign in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(role):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user["role"] != role:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorate


def validate_job_form():
    data = {
        "title": request.form.get("title", "").strip(),
        "location": request.form.get("location", "").strip(),
        "category": request.form.get("category", "").strip(),
        "employment_type": request.form.get("employment_type", "").strip(),
        "salary": request.form.get("salary", "").strip(),
        "description": request.form.get("description", "").strip(),
    }
    if any(not data[key] for key in ("title", "location", "category", "employment_type", "description")):
        return data, "Complete all required fields before publishing."
    if len(data["title"]) > 120 or len(data["location"]) > 120 or len(data["description"]) > 10000:
        return data, "One or more fields exceed the allowed length."
    if data["employment_type"] not in ("Full-time", "Part-time", "Contract", "Internship", "Temporary"):
        return data, "Choose a valid employment type."
    if len(data["salary"]) > 80:
        return data, "Salary details must be 80 characters or fewer."
    return data, None


def owned_job_or_404(job_id):
    job = get_db().execute(
        "SELECT * FROM jobs WHERE id = ? AND employer_id = ?", (job_id, g.user["id"])
    ).fetchone()
    if job is None:
        abort(404)
    return job


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")