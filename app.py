from __future__ import annotations

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)

import os
import sqlite3
import json
import secrets

from datetime import timedelta, datetime
from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)

from timetable_generator import generate_timetable


# ============================================================
# SMARTCLASS FLASK APPLICATION
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DATABASE = os.path.join(
    BASE_DIR,
    "database",
    "smartclass.db"
)

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SMARTCLASS_SECRET_KEY",
    "smartclass_dev_secret_change_me",
)

app.permanent_session_lifetime = timedelta(
    days=30
)


# ============================================================
# DATABASE HELPERS
# ============================================================

def db_connection():
    os.makedirs(
        os.path.dirname(DATABASE),
        exist_ok=True
    )

    connection = sqlite3.connect(
        DATABASE
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():

    connection = db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            reset_token TEXT,
            reset_expires TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_timetables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT,
            class_name TEXT,
            academic_year TEXT,
            semester TEXT,
            working_days TEXT,
            periods_per_day INTEGER DEFAULT 0,
            timetable TEXT,
            class_details TEXT,
            settings_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS generated_timetables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_key TEXT,
            project_name TEXT,
            timetable TEXT,
            class_details TEXT,
            subjects TEXT,
            settings_json TEXT,
            teacher_availability TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS teacher_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_key TEXT NOT NULL,
            project_name TEXT NOT NULL,
            availability TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(owner_key, project_name)
        )
        """
    )

    # ========================================================
    # DATABASE UPGRADES
    # ========================================================

    cursor.execute(
        "PRAGMA table_info(saved_timetables)"
    )

    columns = {
        row["name"]
        for row in cursor.fetchall()
    }

    upgrades = {

        "project_name":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN project_name TEXT",

        "class_name":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN class_name TEXT",

        "academic_year":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN academic_year TEXT",

        "semester":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN semester TEXT",

        "working_days":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN working_days TEXT",

        "periods_per_day":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN periods_per_day INTEGER DEFAULT 0",

        "timetable":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN timetable TEXT",

        "class_details":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN class_details TEXT",

        "settings_json":
            "ALTER TABLE saved_timetables "
            "ADD COLUMN settings_json TEXT",
    }

    for column, sql in upgrades.items():

        if column not in columns:
            cursor.execute(sql)

    connection.commit()
    connection.close()


init_database()


# ============================================================
# SESSION / AUTH
# ============================================================

@app.before_request
def make_session_permanent():

    session.permanent = True

    public_endpoints = {
        "login",
        "register",
        "forgot_password",
        "reset_password",
        "static",
    }

    if (
        request.endpoint not in public_endpoints
        and "user_id" not in session
    ):
        return redirect(
            url_for("login")
        )


# ============================================================
# COMMON HELPERS
# ============================================================

def availability_owner_key():
    return str(
        session.get(
            "user_id",
            "guest"
        )
    )


def save_teacher_availability_to_db(data):

    project = session.get(
        "project",
        {}
    )

    project_name = str(
        project.get(
            "project_name",
            ""
        )
    ).strip()

    if not project_name:
        return

    connection = db_connection()

    connection.execute(
        """
        INSERT INTO teacher_availability
        (
            owner_key,
            project_name,
            availability,
            updated_at
        )
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)

        ON CONFLICT(owner_key, project_name)
        DO UPDATE SET
            availability = excluded.availability,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            availability_owner_key(),
            project_name,
            json.dumps(data),
        ),
    )

    connection.commit()
    connection.close()


def load_teacher_availability_from_db():

    project = session.get(
        "project",
        {}
    )

    project_name = str(
        project.get(
            "project_name",
            ""
        )
    ).strip()

    if not project_name:
        return {}

    connection = db_connection()

    row = connection.execute(
        """
        SELECT availability
        FROM teacher_availability
        WHERE owner_key = ?
        AND project_name = ?
        """,
        (
            availability_owner_key(),
            project_name,
        ),
    ).fetchone()

    connection.close()

    if not row:
        return {}

    try:

        value = json.loads(
            row["availability"]
        )

        return (
            value
            if isinstance(value, dict)
            else {}
        )

    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):

        return {}


def delete_saved_teacher_availability():

    project = session.get(
        "project",
        {}
    )

    project_name = str(
        project.get(
            "project_name",
            ""
        )
    ).strip()

    if not project_name:
        return

    connection = db_connection()

    connection.execute(
        """
        DELETE FROM teacher_availability
        WHERE owner_key = ?
        AND project_name = ?
        """,
        (
            availability_owner_key(),
            project_name,
        ),
    )

    connection.commit()
    connection.close()


def clear_generated_timetable():

    session.pop(
        "current_timetable_id",
        None
    )

    session.pop(
        "timetable",
        None
    )

    session.modified = True


def class_list_from_session():

    details = session.get(
        "class_details",
        {}
    )

    classes = details.get(
        "classes"
    )

    if isinstance(classes, list) and classes:
        return classes

    old_name = str(
        details.get(
            "class_name",
            ""
        )
    ).strip()

    old_divisions = details.get(
        "divisions",
        []
    )

    if old_name:

        converted = [{
            "class_name": old_name,
            "divisions": (
                old_divisions
                or ["A"]
            ),
        }]

        session["class_details"] = (
            build_class_details(
                converted
            )
        )

        return converted

    return []


def build_class_details(classes):

    all_divisions = []
    division_ids = []

    for class_data in classes:

        class_name = class_data[
            "class_name"
        ]

        for division in class_data[
            "divisions"
        ]:

            division_id = (
                f"{class_name}-{division}"
            )

            all_divisions.append({
                "class_name": class_name,
                "division": division,
                "id": division_id,
            })

            division_ids.append(
                division_id
            )

    return {
        "classes": classes,

        "all_divisions":
            all_divisions,

        "divisions":
            division_ids,

        "class_name":
            (
                classes[0]["class_name"]
                if len(classes) == 1
                else ""
            ),

        "division_names":
            division_ids,
    }


def unique_teachers(subjects):

    teachers = []
    seen = set()

    for subject in subjects or []:

        teacher = str(
            subject.get(
                "teacher_name",
                ""
            )
        ).strip()

        key = teacher.casefold()

        if (
            teacher
            and key not in seen
        ):

            seen.add(key)
            teachers.append(teacher)

    return teachers


def unique_subjects_for_class(
    subjects,
    class_name
):

    return [
        subject
        for subject in subjects
        if subject.get(
            "class_name"
        ) == class_name
    ]


def load_current_timetable():

    timetable_id = session.get(
        "current_timetable_id"
    )

    if not timetable_id:
        return []

    connection = db_connection()

    row = connection.execute(
        """
        SELECT timetable
        FROM generated_timetables
        WHERE id = ?
        """,
        (
            timetable_id,
        ),
    ).fetchone()

    connection.close()

    if not row:
        return []

    try:

        return json.loads(
            row["timetable"]
            or "[]"
        )

    except (
        json.JSONDecodeError,
        TypeError,
    ):

        return []


def project_summary(
    project,
    classes,
    subjects,
    settings
):

    project = dict(
        project or {}
    )

    project["classes_count"] = len(
        classes
    )

    project["divisions_count"] = sum(
        len(
            c.get(
                "divisions",
                []
            )
        )
        for c in classes
    )

    project["subjects_count"] = len(
        subjects
    )

    project["working_days_count"] = len(
        settings.get(
            "working_days",
            []
        )
    )

    project["periods_per_day"] = (
        settings.get(
            "periods_per_day",
            0
        )
    )

    return project


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    if "user_id" not in session:
        return redirect(
            url_for("login")
        )

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if "user_id" in session:
        return redirect(
            url_for("dashboard")
        )

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        connection = db_connection()

        user = connection.execute(
            """
            SELECT *
            FROM users
            WHERE email = ?
            """,
            (
                email,
            ),
        ).fetchone()

        connection.close()

        if (
            user
            and check_password_hash(
                user["password_hash"],
                password,
            )
        ):

            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]

            flash(
                "Welcome back! ✨",
                "success"
            )

            return redirect(
                url_for("dashboard")
            )

        flash(
            "Incorrect email or password.",
            "error"
        )

    return render_template(
        "login.html"
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if (
            not name
            or not email
            or len(password) < 8
        ):

            flash(
                "Enter your name, a valid email "
                "and a password of at least 8 characters.",
                "error",
            )

            return redirect(
                url_for("register")
            )

        try:

            connection = db_connection()

            connection.execute(
                """
                INSERT INTO users
                (
                    name,
                    email,
                    password_hash
                )
                VALUES (?, ?, ?)
                """,
                (
                    name,
                    email,
                    generate_password_hash(
                        password
                    ),
                ),
            )

            connection.commit()
            connection.close()

            flash(
                "Account created. You can now log in. 🎉",
                "success",
            )

            return redirect(
                url_for("login")
            )

        except sqlite3.IntegrityError:

            flash(
                "An account with that email already exists.",
                "error",
            )

    return render_template(
        "register.html"
    )


# ============================================================
# FORGOT PASSWORD
# ============================================================

@app.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
def forgot_password():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        token = secrets.token_urlsafe(
            32
        )

        expires = (
            datetime.utcnow().timestamp()
            + 900
        )

        connection = db_connection()

        row = connection.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (
                email,
            ),
        ).fetchone()

        if row:

            connection.execute(
                """
                UPDATE users
                SET reset_token = ?,
                    reset_expires = ?
                WHERE id = ?
                """,
                (
                    token,
                    str(expires),
                    row["id"],
                ),
            )

            connection.commit()

        connection.close()

        if row:

            flash(
                "Reset request created. "
                "Demo reset token: "
                + token,
                "success",
            )

        else:

            flash(
                "If that email is registered, "
                "a reset request has been created.",
                "success",
            )

        return redirect(
            url_for(
                "reset_password",
                token=token
                if row
                else ""
            )
        )

    return render_template(
        "forgot_password.html"
    )


# ============================================================
# RESET PASSWORD
# ============================================================

@app.route(
    "/reset-password",
    methods=["GET", "POST"]
)
def reset_password():

    token = request.args.get(
        "token",
        ""
    )

    if request.method == "POST":

        token = request.form.get(
            "token",
            ""
        ).strip()

        password = request.form.get(
            "password",
            ""
        )

        if len(password) < 8:

            flash(
                "Password must be at least 8 characters.",
                "error",
            )

            return render_template(
                "reset_password.html",
                token=token,
            )

        connection = db_connection()

        row = connection.execute(
            """
            SELECT *
            FROM users
            WHERE reset_token = ?
            """,
            (
                token,
            ),
        ).fetchone()

        valid = False

        if row:

            try:

                valid = (
                    float(
                        row["reset_expires"]
                    )
                    >= datetime.utcnow().timestamp()
                )

            except (
                ValueError,
                TypeError,
            ):

                valid = False

        if not valid:

            connection.close()

            flash(
                "The reset token is invalid or expired.",
                "error",
            )

            return render_template(
                "reset_password.html",
                token=token,
            )

        connection.execute(
            """
            UPDATE users
            SET password_hash = ?,
                reset_token = NULL,
                reset_expires = NULL
            WHERE id = ?
            """,
            (
                generate_password_hash(
                    password
                ),
                row["id"],
            ),
        )

        connection.commit()
        connection.close()

        flash(
            "Password changed successfully. "
            "You can now log in.",
            "success",
        )

        return redirect(
            url_for("login")
        )

    return render_template(
        "reset_password.html",
        token=token,
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    project = session.get(
        "project",
        {}
    )

    classes = class_list_from_session()

    subjects = session.get(
        "subjects",
        []
    )

    settings_data = session.get(
        "settings",
        {}
    )

    project = project_summary(
        project,
        classes,
        subjects,
        settings_data,
    )

    connection = db_connection()

    saved_rows = connection.execute(
        """
        SELECT
            id,
            project_name,
            class_name,
            academic_year,
            semester,
            periods_per_day,
            created_at
        FROM saved_timetables
        ORDER BY id DESC
        LIMIT 5
        """
    ).fetchall()

    connection.close()

    saved = [
        dict(row)
        for row in saved_rows
    ]

    return render_template(
        "dashboard.html",
        project=project,
        classes=classes,
        class_details_count=len(
            [
                d
                for c in classes
                for d in c.get(
                    "divisions",
                    []
                )
            ]
        ),
        saved=saved,
    )


# ============================================================
# CREATE PROJECT
# ============================================================

@app.route(
    "/create-project",
    methods=["GET", "POST"]
)
def create_project():

    if request.method == "POST":

        project_name = request.form.get(
            "project_name",
            ""
        ).strip()

        academic_year = request.form.get(
            "academic_year",
            ""
        ).strip()

        semester = request.form.get(
            "semester",
            ""
        ).strip()

        if not project_name:

            flash(
                "Please enter a project name.",
                "error",
            )

            return redirect(
                url_for("create_project")
            )

        session["project"] = {
            "project_name":
                project_name,

            "academic_year":
                academic_year,

            "semester":
                semester,
        }

        # New project starts clean.
        delete_saved_teacher_availability()

        for key in (
            "class_details",
            "subjects",
            "teacher_availability",
            "division_availability",
            "settings",
            "current_timetable_id",
            "timetable",
        ):

            session.pop(
                key,
                None
            )

        session.modified = True

        return redirect(
            url_for("class_details")
        )

    return render_template(
        "create_project.html"
    )


# ============================================================
# CLASS DETAILS
# ============================================================

@app.route(
    "/class-details",
    methods=["GET", "POST"]
)
def class_details():

    if "project" not in session:

        return redirect(
            url_for("create_project")
        )

    if request.method == "POST":

        class_names = request.form.getlist(
            "class_name[]"
        )

        classes = []

        for index, raw_name in enumerate(
            class_names
        ):

            class_name = raw_name.strip()

            if not class_name:
                continue

            raw_divisions = (
                request.form.getlist(
                    f"division_{index}[]"
                )
            )

            if (
                not raw_divisions
                and index == 0
            ):

                raw_divisions = (
                    request.form.getlist(
                        "division[]"
                    )
                )

            divisions = []
            seen = set()

            for raw_division in (
                raw_divisions
            ):

                division = (
                    raw_division.strip()
                )

                key = (
                    division.casefold()
                )

                if (
                    division
                    and key not in seen
                ):

                    seen.add(key)
                    divisions.append(
                        division
                    )

            if not divisions:

                flash(
                    f"Please add at least one "
                    f"division for {class_name}.",
                    "error",
                )

                return redirect(
                    url_for("class_details")
                )

            classes.append({
                "class_name":
                    class_name,

                "divisions":
                    divisions,
            })

        if not classes:

            flash(
                "Please add at least one class / course.",
                "error",
            )

            return redirect(
                url_for("class_details")
            )

        # No duplicate class names.
        seen_classes = set()

        for class_data in classes:

            key = (
                class_data[
                    "class_name"
                ].casefold()
            )

            if key in seen_classes:

                flash(
                    "Each class / course name "
                    "must be unique.",
                    "error",
                )

                return redirect(
                    url_for("class_details")
                )

            seen_classes.add(key)

        session["class_details"] = (
            build_class_details(
                classes
            )
        )

        # Class changes invalidate class-specific
        # subject data and availability.
        for key in (
            "subjects",
            "teacher_availability",
            "division_availability",
        ):

            session.pop(
                key,
                None
            )

        clear_generated_timetable()

        session.modified = True

        return redirect(
            url_for("subjects")
        )

    classes = class_list_from_session()

    return render_template(
        "class_details.html",
        classes=classes,
        class_details=session.get(
            "class_details",
            {}
        ),
    )


# ============================================================
# SUBJECTS
# ============================================================

@app.route(
    "/subjects",
    methods=["GET", "POST"]
)
def subjects():

    if "project" not in session:

        return redirect(
            url_for("create_project")
        )

    classes = class_list_from_session()

    if not classes:

        return redirect(
            url_for("class_details")
        )

    if request.method == "POST":

        subject_names = request.form.getlist(
            "subject_name[]"
        )

        teacher_names = request.form.getlist(
            "teacher_name[]"
        )

        theory_counts = request.form.getlist(
            "theory_count[]"
        )

        practical_counts = request.form.getlist(
            "practical_count[]"
        )

        subject_classes = request.form.getlist(
            "class_name[]"
        )

        valid_classes = {
            c["class_name"]
            for c in classes
        }

        subjects_data = []

        for index, raw_subject in enumerate(
            subject_names
        ):

            subject_name = (
                raw_subject.strip()
            )

            if not subject_name:
                continue

            teacher_name = (
                teacher_names[index].strip()
                if index < len(teacher_names)
                else ""
            )

            class_name = (
                subject_classes[index].strip()
                if index < len(subject_classes)
                else ""
            )

            theory_value = (
                theory_counts[index]
                if index < len(theory_counts)
                else "0"
            )

            practical_value = (
                practical_counts[index]
                if index < len(practical_counts)
                else "0"
            )

            try:

                theory = max(
                    0,
                    int(theory_value or 0)
                )

            except (
                ValueError,
                TypeError,
            ):

                theory = 0

            try:

                practical = max(
                    0,
                    int(practical_value or 0)
                )

            except (
                ValueError,
                TypeError,
            ):

                practical = 0

            if class_name not in valid_classes:

                flash(
                    f"Invalid class selected "
                    f"for {subject_name}.",
                    "error",
                )

                return redirect(
                    url_for("subjects")
                )

            if not teacher_name:

                flash(
                    f"Please enter a teacher "
                    f"for {subject_name}.",
                    "error",
                )

                return redirect(
                    url_for("subjects")
                )

            if (
                theory == 0
                and practical == 0
            ):

                flash(
                    f"Enter at least one theory "
                    f"or practical lecture "
                    f"for {subject_name}.",
                    "error",
                )

                return redirect(
                    url_for("subjects")
                )

            subjects_data.append({
                "subject_name":
                    subject_name,

                "teacher_name":
                    teacher_name,

                "theory":
                    theory,

                "practical":
                    practical,

                "class_name":
                    class_name,
            })

        if not subjects_data:

            flash(
                "Please add at least one subject.",
                "error",
            )

            return redirect(
                url_for("subjects")
            )

        # ====================================================
        # SAVE SUBJECTS
        # ====================================================

        session["subjects"] = (
            subjects_data
        )

        # ====================================================
        # IMPORTANT:
        #
        # DO NOT DELETE TEACHER AVAILABILITY HERE.
        #
        # Previously saved teacher availability must stay
        # available when returning to Teacher Availability.
        # ====================================================

        # Division availability is currently unused.
        session.pop(
            "division_availability",
            None
        )

        # Subject changes invalidate old timetable.
        clear_generated_timetable()

        session.modified = True

        return redirect(
            url_for("availability")
        )

    saved_subjects = session.get(
        "subjects",
        []
    )

    return render_template(
        "subjects.html",
        classes=classes,
        subjects=saved_subjects,
    )


# ============================================================
# TEACHER AVAILABILITY
# ============================================================

@app.route(
    "/availability",
    methods=["GET", "POST"]
)
def availability():

    if "project" not in session:

        return redirect(
            url_for("create_project")
        )

    classes = class_list_from_session()

    subjects = session.get(
        "subjects",
        []
    )

    if not classes:

        return redirect(
            url_for("class_details")
        )

    if not subjects:

        return redirect(
            url_for("subjects")
        )

    teachers = unique_teachers(
        subjects
    )

    # ========================================================
    # LOAD PREVIOUSLY SAVED AVAILABILITY
    # ========================================================

    saved = session.get(
        "teacher_availability",
        {}
    )

    if not isinstance(saved, dict):

        saved = {}

    # If session doesn't have it,
    # load it from database.
    if not saved:

        saved = (
            load_teacher_availability_from_db()
        )

        if saved:

            session[
                "teacher_availability"
            ] = saved

            session.modified = True

    # ========================================================
    # SAVE AVAILABILITY
    # ========================================================

    if request.method == "POST":

        teacher_availability = {}

        for teacher_index, teacher in enumerate(
            teachers
        ):

            start = request.form.get(
                f"teacher_start_{teacher_index}",
                "",
            ).strip()

            end = request.form.get(
                f"teacher_end_{teacher_index}",
                "",
            ).strip()

            # Both blank = unrestricted.
            if not start and not end:

                teacher_availability[
                    teacher
                ] = {
                    "start": "",
                    "end": "",
                }

                continue

            # Only one field entered.
            if not start or not end:

                flash(
                    f"Please enter both start "
                    f"and end time for {teacher}, "
                    f"or leave both blank.",
                    "error",
                )

                return redirect(
                    url_for("availability")
                )

            # End must be later.
            if start >= end:

                flash(
                    f"End time must be later "
                    f"than start time for {teacher}.",
                    "error",
                )

                return redirect(
                    url_for("availability")
                )

            teacher_availability[
                teacher
            ] = {
                "start": start,
                "end": end,
            }

        # Save in session.
        session[
            "teacher_availability"
        ] = teacher_availability

        # Currently unused.
        session[
            "division_availability"
        ] = {}

        # Save permanently in database.
        save_teacher_availability_to_db(
            teacher_availability
        )

        # Old timetable becomes invalid.
        clear_generated_timetable()

        session.modified = True

        return redirect(
            url_for("settings")
        )

    # ========================================================
    # PREPARE DATA FOR FORM
    # ========================================================

    form_availability = {}

    for teacher in teachers:

        value = saved.get(
            teacher,
            {}
        )

        # New format.
        if (
            isinstance(value, dict)
            and (
                "start" in value
                or "end" in value
            )
        ):

            form_availability[
                teacher
            ] = {
                "start":
                    value.get(
                        "start",
                        ""
                    ),

                "end":
                    value.get(
                        "end",
                        ""
                    ),
            }

        # Old day-wise format.
        elif isinstance(value, dict):

            first_range = {
                "start": "",
                "end": "",
            }

            for day_data in value.values():

                if isinstance(
                    day_data,
                    dict
                ):

                    start = day_data.get(
                        "start",
                        ""
                    )

                    end = day_data.get(
                        "end",
                        ""
                    )

                    if start or end:

                        first_range = {
                            "start": start,
                            "end": end,
                        }

                        break

            form_availability[
                teacher
            ] = first_range

        else:

            form_availability[
                teacher
            ] = {
                "start": "",
                "end": "",
            }

    return render_template(
        "availability.html",
        teachers=teachers,
        teacher_availability=form_availability,
    )


# ============================================================
# SETTINGS
# ============================================================

@app.route(
    "/settings",
    methods=["GET", "POST"]
)
def settings():

    if "project" not in session:

        return redirect(
            url_for("create_project")
        )

    if not class_list_from_session():

        return redirect(
            url_for("class_details")
        )

    if not session.get("subjects"):

        return redirect(
            url_for("subjects")
        )

    if request.method == "POST":

        working_days = request.form.getlist(
            "days"
        )

        if not working_days:

            working_days = request.form.getlist(
                "working_days[]"
            )

        periods_value = request.form.get(
            "periods_per_day",
            "0"
        ).strip()

        start_time = request.form.get(
            "start_time",
            ""
        ).strip()

        end_time = request.form.get(
            "end_time",
            ""
        ).strip()

        # Optional break between periods. Stored with the project settings.
        break_after_period = request.form.get("break_after_period", "4").strip()
        break_start = request.form.get("break_start", "14:20").strip()
        break_end = request.form.get("break_end", "14:50").strip()

        # Optional custom time for every period.
        # Stored as {"1": {"start": "09:30", "end": "10:30"}, ...}
        period_times = {}
        for p in range(1, 13):
            p_start = request.form.get(
                f"period_{p}_start",
                ""
            ).strip()
            p_end = request.form.get(
                f"period_{p}_end",
                ""
            ).strip()
            if p_start or p_end:
                period_times[str(p)] = {
                    "start": p_start,
                    "end": p_end,
                }

        try:

            periods_per_day = int(
                periods_value
            )

        except (
            ValueError,
            TypeError,
        ):

            periods_per_day = 0

        if not working_days:

            flash(
                "Please select at least one working day.",
                "error",
            )

            return redirect(
                url_for("settings")
            )

        if (
            periods_per_day < 1
            or periods_per_day > 12
        ):

            flash(
                "Periods per day must be between 1 and 12.",
                "error",
            )

            return redirect(
                url_for("settings")
            )

        if (
            not start_time
            or not end_time
        ):

            flash(
                "Please select both start and end time.",
                "error",
            )

            return redirect(
                url_for("settings")
            )

        if start_time >= end_time:

            flash(
                "End time must be later than start time.",
                "error",
            )

            return redirect(
                url_for("settings")
            )

        # Validate custom period timings when they are supplied.
        def _mins(value):
            try:
                h, m = value.split(":", 1)
                return int(h) * 60 + int(m)
            except (ValueError, AttributeError):
                return None

        for p in range(1, periods_per_day + 1):
            item = period_times.get(str(p))
            if not item or not item.get("start") or not item.get("end"):
                flash(
                    f"Please enter start and end time for Period {p}.",
                    "error",
                )
                return redirect(url_for("settings"))

            a = _mins(item["start"])
            b = _mins(item["end"])
            if a is None or b is None or a >= b:
                flash(
                    f"Period {p} end time must be later than its start time.",
                    "error",
                )
                return redirect(url_for("settings"))

        try:
            break_after_period = int(break_after_period)
        except (ValueError, TypeError):
            break_after_period = 4

        if not 1 <= break_after_period < periods_per_day:
            flash("Break must be placed after a period, before the final period.", "error")
            return redirect(url_for("settings"))

        break_start_minutes = _mins(break_start)
        break_end_minutes = _mins(break_end)
        if break_start_minutes is None or break_end_minutes is None or break_start_minutes >= break_end_minutes:
            flash("Please enter a valid break start and end time.", "error")
            return redirect(url_for("settings"))

        # Periods must be in chronological order. Gaps are allowed.
        for p in range(2, periods_per_day + 1):
            previous = period_times[str(p - 1)]
            current = period_times[str(p)]
            if _mins(current["start"]) < _mins(previous["end"]):
                flash(
                    f"Period {p} cannot start before Period {p - 1} ends.",
                    "error",
                )
                return redirect(url_for("settings"))

        session["settings"] = {
            "working_days":
                working_days,

            "periods_per_day":
                periods_per_day,

            "start_time":
                start_time,

            "end_time":
                end_time,

            "period_times":
                period_times,

            "break_after_period": break_after_period,
            "break_start": break_start,
            "break_end": break_end,
        }

        clear_generated_timetable()

        session.modified = True

        return redirect(
            url_for("generate")
        )

    saved_settings = session.get(
        "settings",
        {}
    )

    return render_template(
        "settings.html",
        settings=saved_settings,

        selected_days=saved_settings.get(
            "working_days",
            [
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
            ],
        ),

        periods_per_day=saved_settings.get(
            "periods_per_day",
            6
        ),

        start_time=saved_settings.get(
            "start_time",
            "09:30"
        ),

        end_time=saved_settings.get(
            "end_time",
            "16:30"
        ),

        period_times=saved_settings.get(
            "period_times",
            {}
        ),
        break_after_period=saved_settings.get("break_after_period", 4),
        break_start=saved_settings.get("break_start", "14:20"),
        break_end=saved_settings.get("break_end", "14:50"),
    )


# ============================================================
# GENERATE
# ============================================================

@app.route(
    "/generate",
    methods=["GET", "POST"]
)
def generate():

    if "project" not in session:

        return redirect(
            url_for("create_project")
        )

    classes = class_list_from_session()

    subjects = session.get(
        "subjects",
        []
    )

    settings_data = session.get(
        "settings",
        {}
    )

    if not classes:

        return redirect(
            url_for("class_details")
        )

    if not subjects:

        return redirect(
            url_for("subjects")
        )

    if not settings_data:

        return redirect(
            url_for("settings")
        )

    divisions = [
        item["id"]
        for item in session[
            "class_details"
        ].get(
            "all_divisions",
            []
        )
    ]

    if request.method == "POST":

        try:

            generated = generate_timetable(

                subjects=subjects,

                divisions=divisions,

                working_days=settings_data[
                    "working_days"
                ],

                periods_per_day=settings_data[
                    "periods_per_day"
                ],

                teacher_availability=session.get(
                    "teacher_availability",
                    {}
                ),

                division_availability=session.get(
                    "division_availability",
                    {}
                ),

                start_time=settings_data.get(
                    "start_time",
                    "09:30"
                ),

                end_time=settings_data.get(
                    "end_time",
                    "16:30"
                ),

                period_times=settings_data.get(
                    "period_times",
                    {}
                ),

                classes=classes,
                combined_rules=session.get("combine_subjects", {}),
            )

            timetable_list = []

            for division_id in divisions:

                class_name = ""
                division_name = division_id

                for item in session[
                    "class_details"
                ].get(
                    "all_divisions",
                    []
                ):

                    if item["id"] == division_id:

                        class_name = item[
                            "class_name"
                        ]

                        division_name = item[
                            "division"
                        ]

                        break

                for day in settings_data[
                    "working_days"
                ]:

                    day_data = generated.get(
                        division_id,
                        {}
                    ).get(
                        day,
                        {}
                    )

                    for period in range(
                        1,
                        settings_data[
                            "periods_per_day"
                        ] + 1,
                    ):

                        lecture = day_data.get(
                            period
                        )

                        if not lecture:

                            lecture = {
                                "subject":
                                    "Free",

                                "teacher":
                                    "",

                                "type":
                                    "FREE",
                            }

                        timetable_list.append({

                            "division":
                                division_id,

                            "division_name":
                                division_name,

                            "class_name":
                                lecture.get(
                                    "class_name",
                                    class_name
                                ),

                            "day":
                                day,

                            "period":
                                period,

                            "subject_name":
                                lecture.get(
                                    "subject",
                                    "Free"
                                ),

                            "teacher_name":
                                lecture.get(
                                    "teacher",
                                    ""
                                ),

                            "lecture_type":
                                lecture.get(
                                    "type",
                                    "FREE"
                                ),
                        })

            connection = db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                INSERT INTO generated_timetables
                (
                    owner_key,
                    project_name,
                    timetable,
                    class_details,
                    subjects,
                    settings_json,
                    teacher_availability
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(
                        session.get(
                            "user_id",
                            ""
                        )
                    ),

                    session[
                        "project"
                    ].get(
                        "project_name",
                        ""
                    ),

                    json.dumps(
                        timetable_list
                    ),

                    json.dumps(
                        session.get(
                            "class_details",
                            {}
                        )
                    ),

                    json.dumps(
                        subjects
                    ),

                    json.dumps(
                        settings_data
                    ),

                    json.dumps(
                        session.get(
                            "teacher_availability",
                            {}
                        )
                    ),
                ),
            )

            generated_id = cursor.lastrowid

            connection.commit()
            connection.close()

            session[
                "current_timetable_id"
            ] = generated_id

            session.modified = True

            return redirect(
                url_for("result")
            )

        except Exception as exc:

            print(
                "\nSMARTCLASS GENERATION ERROR:\n",
                repr(exc),
                "\n",
            )

            flash(
                f"Timetable generation error: {exc}",
                "error",
            )

            return redirect(
                url_for("generate")
            )

    return render_template(
        "generate.html",

        project=session.get(
            "project",
            {}
        ),

        class_details=session.get(
            "class_details",
            {}
        ),

        classes=classes,

        subjects=subjects,

        settings=settings_data,

        divisions=divisions,

        working_days=settings_data.get(
            "working_days",
            []
        ),

        periods_per_day=settings_data.get(
            "periods_per_day",
            6
        ),

        start_time=settings_data.get(
            "start_time",
            "09:30"
        ),

        end_time=settings_data.get(
            "end_time",
            "16:30"
        ),

        teacher_availability=session.get(
            "teacher_availability",
            {}
        ),
    )


# ============================================================
# RESULT
# ============================================================

@app.route("/result")
def result():

    if "project" not in session:

        return redirect(
            url_for("create_project")
        )

    timetable_data = (
        load_current_timetable()
    )

    return render_template(
        "result.html",

        project=session.get(
            "project",
            {}
        ),

        class_details=session.get(
            "class_details",
            {}
        ),

        classes=class_list_from_session(),

        subjects=session.get(
            "subjects",
            []
        ),

        settings=session.get(
            "settings",
            {}
        ),

        timetable=timetable_data,

        saved_timetable=False,
    )


# ============================================================
# TIMETABLE
# ============================================================

@app.route("/timetable")
def timetable():

    return redirect(
        url_for("result")
    )


# ============================================================
# SAVE TIMETABLE
# ============================================================

@app.route(
    "/save-timetable",
    methods=["POST"]
)
def save_timetable():

    timetable_data = (
        load_current_timetable()
    )

    project = session.get(
        "project",
        {}
    )

    class_details = session.get(
        "class_details",
        {}
    )

    settings_data = session.get(
        "settings",
        {}
    )

    if not timetable_data:

        flash(
            "No timetable available to save.",
            "error",
        )

        return redirect(
            url_for("result")
        )

    classes = class_details.get(
        "classes",
        []
    )

    class_names = ", ".join(
        c.get(
            "class_name",
            ""
        )
        for c in classes
        if c.get("class_name")
    )

    connection = db_connection()

    connection.execute(
        """
        INSERT INTO saved_timetables
        (
            project_name,
            class_name,
            academic_year,
            semester,
            working_days,
            periods_per_day,
            timetable,
            class_details,
            settings_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project.get(
                "project_name",
                ""
            ),

            class_names,

            project.get(
                "academic_year",
                ""
            ),

            project.get(
                "semester",
                ""
            ),

            json.dumps(
                settings_data.get(
                    "working_days",
                    []
                )
            ),

            int(
                settings_data.get(
                    "periods_per_day",
                    0
                )
            ),

            json.dumps(
                timetable_data
            ),

            json.dumps(
                class_details
            ),

            json.dumps(
                settings_data
            ),
        ),
    )

    connection.commit()
    connection.close()

    flash(
        "Timetable saved successfully! 🎉",
        "success",
    )

    return redirect(
        url_for("saved_timetables")
    )


# ============================================================
# SAVED TIMETABLES
# ============================================================

@app.route("/saved-timetables")
def saved_timetables():

    connection = db_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM saved_timetables
        ORDER BY id DESC
        """
    ).fetchall()

    connection.close()

    saved = []

    for row in rows:

        item = dict(row)

        try:

            item["working_days"] = ", ".join(
                json.loads(
                    item.get(
                        "working_days"
                    )
                    or "[]"
                )
            )

        except (
            json.JSONDecodeError,
            TypeError,
        ):

            pass

        saved.append(item)

    return render_template(
        "saved_timetables.html",
        saved_timetables=saved,
    )


# ============================================================
# VIEW SAVED TIMETABLE
# ============================================================

@app.route(
    "/saved-timetable/<int:timetable_id>"
)
def view_saved_timetable(
    timetable_id
):

    connection = db_connection()

    saved = connection.execute(
        """
        SELECT *
        FROM saved_timetables
        WHERE id = ?
        """,
        (
            timetable_id,
        ),
    ).fetchone()

    connection.close()

    if not saved:

        flash(
            "Saved timetable not found.",
            "error",
        )

        return redirect(
            url_for("saved_timetables")
        )

    try:

        timetable_data = json.loads(
            saved["timetable"]
            or "[]"
        )

    except (
        json.JSONDecodeError,
        TypeError,
    ):

        timetable_data = []

    try:

        class_details = json.loads(
            saved["class_details"]
            or "{}"
        )

    except (
        json.JSONDecodeError,
        TypeError,
    ):

        class_details = {}

    try:

        settings_data = json.loads(
            saved["settings_json"]
            or "{}"
        )

    except (
        json.JSONDecodeError,
        TypeError,
    ):

        settings_data = {}

    # Backward compatibility.
    if not class_details:

        divisions = sorted({
            item.get(
                "division",
                ""
            )
            for item in timetable_data
            if item.get("division")
        })

        class_details = {

            "classes": [{
                "class_name":
                    saved["class_name"]
                    or "",

                "divisions":
                    divisions,
            }],

            "all_divisions": [],

            "divisions":
                divisions,

            "class_name":
                saved["class_name"]
                or "",
        }

    if not settings_data:

        try:

            days = json.loads(
                saved["working_days"]
                or "[]"
            )

        except (
            json.JSONDecodeError,
            TypeError,
        ):

            days = []

        settings_data = {

            "working_days":
                days,

            "periods_per_day":
                saved[
                    "periods_per_day"
                ]
                or 0,
        }

    project = {

        "project_name":
            saved["project_name"]
            or "Saved Timetable",

        "academic_year":
            saved["academic_year"]
            or "",

        "semester":
            saved["semester"]
            or "",
    }

    return render_template(
        "result.html",

        project=project,

        class_details=class_details,

        classes=class_details.get(
            "classes",
            []
        ),

        subjects=[],

        settings=settings_data,

        timetable=timetable_data,

        saved_timetable=True,
    )


# ============================================================
# DELETE SAVED TIMETABLE
# ============================================================

@app.route(
    "/delete-saved-timetable/<int:timetable_id>"
)
def delete_saved_timetable(
    timetable_id
):

    connection = db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        DELETE FROM saved_timetables
        WHERE id = ?
        """,
        (
            timetable_id,
        ),
    )

    deleted = cursor.rowcount

    connection.commit()
    connection.close()

    if deleted:

        flash(
            "Saved timetable deleted successfully.",
            "success",
        )

    else:

        flash(
            "Saved timetable not found.",
            "error",
        )

    return redirect(
        url_for("saved_timetables")
    )


# ============================================================
# RESET CURRENT PROJECT
# ============================================================

@app.route("/reset")
def reset():

    keep_keys = {
        "user_id",
        "user_name",
        "user_email",
        "_permanent",
    }

    for key in list(
        session.keys()
    ):

        if key not in keep_keys:

            session.pop(
                key,
                None
            )

    session.modified = True

    return redirect(
        url_for("dashboard")
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True,
    )