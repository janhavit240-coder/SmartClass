import sqlite3
import os

# --------------------------------------------------
# DATABASE PATH
# --------------------------------------------------

DATABASE_FOLDER = "database"
DATABASE_FILE = os.path.join(
    DATABASE_FOLDER,
    "smartclass.db"
)


# --------------------------------------------------
# CREATE DATABASE FOLDER
# --------------------------------------------------

def create_database_folder():
    os.makedirs(DATABASE_FOLDER, exist_ok=True)


# --------------------------------------------------
# GET DATABASE CONNECTION
# --------------------------------------------------

def get_connection():

    create_database_folder()

    connection = sqlite3.connect(DATABASE_FILE)

    connection.row_factory = sqlite3.Row

    return connection


# --------------------------------------------------
# CREATE ALL TABLES
# --------------------------------------------------

def create_tables():

    connection = get_connection()

    cursor = connection.cursor()

    # ----------------------------------------------
    # PROJECTS
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_name TEXT NOT NULL,

            academic_year TEXT,

            semester TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
    """)

    # ----------------------------------------------
    # CLASSES
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS classes (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_id INTEGER,

            class_name TEXT NOT NULL,

            FOREIGN KEY (project_id)
            REFERENCES projects(id)

        )
    """)

    # ----------------------------------------------
    # DIVISIONS
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS divisions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            class_id INTEGER,

            division_name TEXT NOT NULL,

            FOREIGN KEY (class_id)
            REFERENCES classes(id)

        )
    """)

    # ----------------------------------------------
    # TEACHERS
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS teachers (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            teacher_name TEXT NOT NULL,

            email TEXT,

            availability TEXT

        )
    """)

    # ----------------------------------------------
    # SUBJECTS
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subjects (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            subject_name TEXT NOT NULL,

            teacher_id INTEGER,

            theory_lectures INTEGER DEFAULT 0,

            practical_lectures INTEGER DEFAULT 0,

            FOREIGN KEY (teacher_id)
            REFERENCES teachers(id)

        )
    """)

    # ----------------------------------------------
    # CLASSROOMS
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS classrooms (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            room_name TEXT NOT NULL,

            room_type TEXT DEFAULT 'Classroom',

            capacity INTEGER DEFAULT 0

        )
    """)

    # ----------------------------------------------
    # TIME SLOTS
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS time_slots (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            day TEXT NOT NULL,

            start_time TEXT NOT NULL,

            end_time TEXT NOT NULL,

            is_break INTEGER DEFAULT 0

        )
    """)

    # ----------------------------------------------
    # TIMETABLE
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS timetable (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_id INTEGER,

            class_id INTEGER,

            division_id INTEGER,

            subject_id INTEGER,

            teacher_id INTEGER,

            classroom_id INTEGER,

            day TEXT NOT NULL,

            start_time TEXT NOT NULL,

            end_time TEXT NOT NULL,

            lecture_type TEXT DEFAULT 'Theory',

            FOREIGN KEY (project_id)
            REFERENCES projects(id),

            FOREIGN KEY (class_id)
            REFERENCES classes(id),

            FOREIGN KEY (division_id)
            REFERENCES divisions(id),

            FOREIGN KEY (subject_id)
            REFERENCES subjects(id),

            FOREIGN KEY (teacher_id)
            REFERENCES teachers(id),

            FOREIGN KEY (classroom_id)
            REFERENCES classrooms(id)

        )
    """)

    # ----------------------------------------------
    # SETTINGS
    # ----------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            project_id INTEGER,

            working_days TEXT,

            periods_per_day INTEGER DEFAULT 0,

            start_time TEXT,

            end_time TEXT,

            FOREIGN KEY (project_id)
            REFERENCES projects(id)

        )
    """)

    connection.commit()

    connection.close()


# --------------------------------------------------
# INITIALIZE DATABASE
# --------------------------------------------------

if __name__ == "__main__":

    create_tables()

    print("----------------------------------------")
    print("SmartClass database created successfully!")
    print("----------------------------------------")