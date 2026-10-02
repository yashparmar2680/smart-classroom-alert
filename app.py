from flask import Flask, jsonify, render_template, request, session
import mysql.connector
import os
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = "smart-classroom-secret-key"


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 23126)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
        ssl_disabled=False
    )


# =========================
# HOME / LOGIN PAGE
# =========================

@app.route("/")
def home():
    return render_template("login.html")


# =========================
# LOGOUT
# =========================

@app.route("/logout")
def logout():

    session.clear()

    return jsonify({
        "success": True,
        "redirect": "/"
    })


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["POST"])
def login():

    data = request.get_json()

    if not data:
        return jsonify({
            "success": False,
            "message": "Invalid request"
        }), 400

    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({
            "success": False,
            "message": "Email and password are required"
        }), 400

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # =========================
    # CHECK STUDENT
    # =========================

    cursor.execute(
        """
        SELECT student_id, name, email
        FROM students
        WHERE email = %s AND password = %s
        """,
        (email, password)
    )

    student = cursor.fetchone()

    if student:

        session.clear()

        session["student_id"] = student["student_id"]
        session["student_name"] = student["name"]
        session["role"] = "student"

        cursor.close()
        db.close()

        return jsonify({
            "success": True,
            "redirect": "/student"
        })


    # =========================
    # CHECK ADMIN / FACULTY
    # =========================

    cursor.execute(
        """
        SELECT user_id, name, email, role
        FROM users
        WHERE email = %s AND password = %s
        """,
        (email, password)
    )

    user = cursor.fetchone()

    cursor.close()
    db.close()

    if user:

        session.clear()

        session["user_id"] = user["user_id"]
        session["user_name"] = user["name"]
        session["role"] = user["role"]

        return jsonify({
            "success": True,
            "redirect": "/admin"
        })


    return jsonify({
        "success": False,
        "message": "Invalid email or password"
    }), 401


# =========================
# CHANGE CLASSROOM
# =========================

@app.route("/change-room", methods=["POST"])
def change_room():

    if session.get("role") not in ["admin", "faculty"]:
        return jsonify({
            "message": "Access denied"
        }), 403

    data = request.get_json()

    class_id = data["class_id"]
    new_room = data["new_room"]

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT room, section, subject
        FROM classes
        WHERE class_id = %s
        """,
        (class_id,)
    )

    class_data = cursor.fetchone()

    if not class_data:

        cursor.close()
        db.close()

        return jsonify({
            "message": "Class not found"
        }), 404

    old_room = class_data["room"]
    section = class_data["section"]
    subject = class_data["subject"]

    # Update classroom
    cursor.execute(
        """
        UPDATE classes
        SET room = %s
        WHERE class_id = %s
        """,
        (new_room, class_id)
    )

    # Save change history
    cursor.execute(
        """
        INSERT INTO classroom_changes
        (class_id, old_room, new_room, reason)
        VALUES (%s, %s, %s, %s)
        """,
        (
            class_id,
            old_room,
            new_room,
            "Classroom changed by admin"
        )
    )

    change_id = cursor.lastrowid

    # Get students from same section
    cursor.execute(
        """
        SELECT student_id
        FROM students
        WHERE section = %s
        """,
        (section,)
    )

    students = cursor.fetchall()

    message = (
        f"{subject} classroom changed "
        f"from {old_room} to {new_room}."
    )

    # Create notifications
    for student in students:

        cursor.execute(
            """
            INSERT INTO notifications
            (student_id, change_id, message)
            VALUES (%s, %s, %s)
            """,
            (
                student["student_id"],
                change_id,
                message
            )
        )

    db.commit()

    cursor.close()
    db.close()

    return jsonify({
        "success": True,
        "message": f"Room changed from {old_room} to {new_room}"
    })


# =========================
# ADMIN PAGE
# =========================

@app.route("/admin")
def admin():

    if session.get("role") not in ["admin", "faculty"]:
        return jsonify({
            "message": "Access denied"
        }), 403

    return render_template("admin.html")


# =========================
# STUDENT PAGE
# =========================

@app.route("/student")
def student():

    if not session.get("student_id"):
        return jsonify({
            "message": "Please login as student"
        }), 401

    return render_template("student.html")


# =========================
# GET ALL CLASSES
# =========================

@app.route("/classes")
def get_classes():

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT * FROM classes")

    classes = cursor.fetchall()

    for class_data in classes:

        if class_data["class_time"]:
            class_data["class_time"] = str(
                class_data["class_time"]
            )

    cursor.close()
    db.close()

    return jsonify(classes)


# =========================
# NOTIFICATIONS
# =========================

@app.route("/notifications")
def get_notifications():

    student_id = session.get("student_id")

    if not student_id:
        return jsonify({
            "message": "Not logged in"
        }), 401

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            notification_id,
            message,
            created_at,
            is_read
        FROM notifications
        WHERE student_id = %s
        ORDER BY created_at DESC
        """,
        (student_id,)
    )

    notifications = cursor.fetchall()

    for notification in notifications:

        if notification["created_at"]:
            notification["created_at"] = str(
                notification["created_at"]
            )

    cursor.close()
    db.close()

    return jsonify(notifications)


# =========================
# MARK NOTIFICATION READ
# =========================

@app.route(
    "/notifications/<int:notification_id>/read",
    methods=["POST"]
)
def mark_notification_read(notification_id):

    student_id = session.get("student_id")

    if not student_id:
        return jsonify({
            "message": "Not logged in"
        }), 401

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute(
        """
        UPDATE notifications
        SET is_read = TRUE
        WHERE notification_id = %s
        AND student_id = %s
        """,
        (notification_id, student_id)
    )

    db.commit()

    cursor.close()
    db.close()

    return jsonify({
        "success": True
    })


# =========================
# RECENT ROOM CHANGES
# =========================

@app.route("/recent-changes")
def recent_changes():

    if session.get("role") not in ["admin", "faculty"]:
        return jsonify({
            "message": "Access denied"
        }), 403

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            cc.change_id,
            c.subject,
            c.section,
            cc.old_room,
            cc.new_room,
            cc.reason,
            cc.changed_at
        FROM classroom_changes cc
        JOIN classes c
            ON cc.class_id = c.class_id
        ORDER BY cc.changed_at DESC
        LIMIT 5
        """
    )

    changes = cursor.fetchall()

    for change in changes:

        if change["changed_at"]:
            change["changed_at"] = str(
                change["changed_at"]
            )

    cursor.close()
    db.close()

    return jsonify(changes)


# =========================
# RUN FLASK
# =========================

if __name__ == "__main__":
    app.run(debug=True)