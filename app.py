from flask import Flask, request, render_template, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import uuid
import json
from functools import wraps
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        """Allow the app to run when python-dotenv is not installed."""
        return False
from google import genai
from google.genai import types
from math import radians, sin, cos, sqrt, atan2
from datetime import datetime, timezone

# Load environment configuration from .env file
load_dotenv()


def utcnow_naive():
    """Return the current UTC time as a naive datetime for SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


app = Flask(__name__)

# Secret key & database configuration from environment
app.secret_key = os.getenv("SECRET_KEY", "civicConnect9690_default_dev_secret")

raw_db_uri = os.getenv("SQLALCHEMY_DATABASE_URI", "sqlite:///users.db")
if raw_db_uri.startswith("postgres://"):
    raw_db_uri = raw_db_uri.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = raw_db_uri
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Maximum upload payload size (16MB default)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "static/uploads")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Allowed image extensions for safe uploads
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}


def allowed_file(filename):
    """Check if the uploaded file has an allowed image extension."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


db = SQLAlchemy(app)

# Gemini AI Client configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

gemini_client = None
if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Warning: Could not initialize Gemini client: {e}")

DUPLICATE_RADIUS_KM = float(os.getenv("DUPLICATE_RADIUS_KM", 0.3))


# ==========================
# Authentication & Role Decorators
# ==========================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "logged_in" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("landing"))
        return f(*args, **kwargs)
    return decorated_function


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "logged_in" not in session:
                flash("Please log in to continue.", "warning")
                return redirect(url_for("landing"))
            if session.get("role") not in roles:
                flash("Unauthorized access for your account role.", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ==========================
# User Model
# ==========================

class User(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(100), unique=True, nullable=False)

    password = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(20), nullable=False)


class Fundraiser(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(150), nullable=False)

    description = db.Column(db.Text, nullable=False)

    target_amount = db.Column(db.Float, nullable=False)

    collected_amount = db.Column(
        db.Float,
        default=0.0
    )

    image = db.Column(
        db.String(200),
        nullable=True
    )

    campaign_type = db.Column(
        db.String(50),
        nullable=False
    )

    # NGO who created campaign

    ngo_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    # Optional citizen complaint reference

    complaint_id = db.Column(
        db.Integer,
        db.ForeignKey("complaint.id"),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow_naive
    )


class Donation(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    fundraiser_id = db.Column(
        db.Integer,
        db.ForeignKey("fundraiser.id"),
        nullable=False
    )

    donor_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    amount = db.Column(
        db.Float,
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow_naive
    )


class VolunteerDrive(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(150), nullable=False)

    description = db.Column(db.Text, nullable=False)

    meeting_point = db.Column(
        db.String(200),
        nullable=False
    )

    latitude = db.Column(
        db.Float,
        nullable=True
    )

    longitude = db.Column(
        db.Float,
        nullable=True
    )

    contact = db.Column(db.String(20))

    drive_date = db.Column(db.String(30))

    drive_time = db.Column(db.String(20))

    volunteers_needed = db.Column(db.Integer)

    instructions = db.Column(db.Text)

    status = db.Column(
        db.String(20),
        default="Open"
    )

    ngo_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id")
    )

# ==========================================
# Complaint SLA / Overdue Settings
# ==========================================

COMPLAINT_DEADLINES = {
    "Water Leakage": 2,
    "Sewage": 2,
    "Garbage": 3,
    "Illegal Dumping": 3,
    "Street Light": 5,
    "Pothole": 7,
    "Other": 7
}


class Complaint(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(150), nullable=False)

    description = db.Column(db.Text, nullable=False)

    category = db.Column(db.String(50), nullable=False)

    location = db.Column(db.String(255), nullable=False)

    latitude = db.Column(db.Float, nullable=False)

    longitude = db.Column(db.Float, nullable=False)

    image = db.Column(db.String(255))          # Before image

    status = db.Column(
        db.String(30),
        default="Pending"
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow_naive,
        nullable=True
    )

    citizen_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    # -------- New Fields --------

    assigned_to = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    assigned_role = db.Column(
        db.String(20),
        nullable=True
    )

    after_image = db.Column(
        db.String(255),
        nullable=True
    )

    completion_note = db.Column(
        db.Text,
        nullable=True
    )

    completed_at = db.Column(
        db.DateTime,
        nullable=True
    )

    verified = db.Column(
        db.Boolean,
        default=False
    )

    # -------- Duplicate-handling field --------

    priority = db.Column(
        db.Integer,
        default=1,
        nullable=False
    )

    # -------- Severity, Department & Feedback Fields --------

    severity = db.Column(
        db.String(20),
        default="Medium",
        nullable=False
    )

    department = db.Column(
        db.String(60),
        default="General",
        nullable=False
    )

    is_emergency = db.Column(
        db.Boolean,
        default=False,
        nullable=False
    )

    citizen_feedback = db.Column(
        db.String(20),
        nullable=True
    )

    citizen_rating = db.Column(
        db.Integer,
        nullable=True
    )

    citizen_feedback_note = db.Column(
        db.Text,
        nullable=True
    )

    @property
    def report_count(self):
        """Total number of citizens who reported this issue,
        including the original reporter."""
        return len(self.duplicate_reports) + 1

    @property
    def age_days(self):
        if not self.created_at:
            return 0
        return (utcnow_naive() - self.created_at).days

    @property
    def deadline_days(self):
        base_days = COMPLAINT_DEADLINES.get(self.category, 7)
        if self.severity == "Critical Hazard":
            return max(1, base_days // 3)
        elif self.severity == "High":
            return max(2, int(base_days * 0.6))
        return base_days

    @property
    def is_overdue(self):
        if self.status in ["Completed", "Verified"]:
            return False
        return self.age_days >= self.deadline_days

    @property
    def is_aging(self):
        if self.status in ["Completed", "Verified"]:
            return False
        return (
            self.age_days >= max(1, int(self.deadline_days * 0.75))
            and not self.is_overdue
        )

    @property
    def urgency_status(self):
        if self.status in ["Completed", "Verified"]:
            return "Resolved"
        if self.is_overdue:
            return "Overdue"
        if self.is_aging:
            return "Aging"
        return "Normal"


class DuplicateReport(db.Model):
    """Tracks which citizens confirmed an existing complaint as
    'their' issue, instead of filing a fresh duplicate. Each
    citizen can only bump a given complaint's priority once."""

    id = db.Column(db.Integer, primary_key=True)

    complaint_id = db.Column(
        db.Integer,
        db.ForeignKey("complaint.id"),
        nullable=False
    )

    citizen_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow_naive
    )

    complaint = db.relationship(
        "Complaint",
        backref="duplicate_reports"
    )

    citizen = db.relationship("User")


class Complaint_UniqueDuplicate(db.Model):
    """Placeholder retained intentionally unused - see
    UniqueConstraint below instead."""
    __abstract__ = True


# Prevent the same citizen from confirming the same complaint as
# a duplicate more than once at the database level too.
db.Index(
    "uq_duplicate_report_complaint_citizen",
    DuplicateReport.complaint_id,
    DuplicateReport.citizen_id,
    unique=True
)


class Announcement(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(150), nullable=False)

    message = db.Column(db.Text, nullable=False)

    category = db.Column(db.String(30), default="General")

    posted_by = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime,
        default=utcnow_naive
    )

    author = db.relationship("User")


class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), default="ticket_update")  # ticket_update, emergency, volunteer, donation, system
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    is_emergency = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    user = db.relationship("User", backref=db.backref("notifications", lazy=True, cascade="all, delete-orphan"))

    @property
    def time_ago(self):
        if not self.created_at:
            return "Just now"
        delta = utcnow_naive() - self.created_at
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "Just now"
        elif seconds < 3600:
            mins = seconds // 60
            return f"{mins}m ago"
        elif seconds < 86400:
            hours = seconds // 3600
            return f"{hours}h ago"
        else:
            days = seconds // 86400
            return f"{days}d ago"


class EmergencyAlert(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    severity = db.Column(db.String(50), default="Critical Hazard")  # Critical Hazard, Severe Weather, Flash Flood, Evacuation, Utility Failure
    helpline = db.Column(db.String(100), default="112 / 108 / 1800-CIVIC-ALERT")
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    resolved_at = db.Column(db.DateTime, nullable=True)

    creator = db.relationship("User")


def create_notification(user_id, title, message, category="ticket_update", link=None, is_emergency=False):
    """Safely dispatches an in-app notification to a user."""
    try:
        notif = Notification(
            user_id=user_id,
            title=title,
            message=message,
            category=category,
            link=link,
            is_emergency=is_emergency,
            created_at=utcnow_naive()
        )
        db.session.add(notif)
        db.session.commit()
        return notif
    except Exception as e:
        print(f"Notification error: {e}")
        db.session.rollback()
        return None


def broadcast_emergency_notification(title, message, helpline=None):
    """Broadcasts an urgent emergency notification to ALL registered users."""
    try:
        users = User.query.all()
        for u in users:
            notif = Notification(
                user_id=u.id,
                title=f"🚨 EMERGENCY ALERT: {title}",
                message=f"{message} (Helpline: {helpline or '112'})",
                category="emergency",
                link="/emergency/alerts",
                is_emergency=True,
                created_at=utcnow_naive()
            )
            db.session.add(notif)
        db.session.commit()
    except Exception as e:
        print(f"Emergency broadcast error: {e}")
        db.session.rollback()


def migrate_database_schema():
    """Safely add created_at, severity, department, and feedback columns to existing SQLite databases."""
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)

    if "complaint" not in inspector.get_table_names():
        return

    columns = [
        column["name"]
        for column in inspector.get_columns("complaint")
    ]

    if "created_at" not in columns:
        print("Adding created_at column to complaint table...")
        db.session.execute(
            text(
                "ALTER TABLE complaint "
                "ADD COLUMN created_at DATETIME"
            )
        )
        db.session.commit()

    if "severity" not in columns:
        print("Adding severity column to complaint table...")
        db.session.execute(
            text(
                "ALTER TABLE complaint "
                "ADD COLUMN severity VARCHAR(20) DEFAULT 'Medium'"
            )
        )
        db.session.commit()

    if "department" not in columns:
        print("Adding department column to complaint table...")
        db.session.execute(
            text(
                "ALTER TABLE complaint "
                "ADD COLUMN department VARCHAR(60) DEFAULT 'General'"
            )
        )
        db.session.commit()

    if "citizen_feedback" not in columns:
        print("Adding citizen_feedback column to complaint table...")
        db.session.execute(
            text(
                "ALTER TABLE complaint "
                "ADD COLUMN citizen_feedback VARCHAR(20)"
            )
        )
        db.session.commit()

    if "citizen_rating" not in columns:
        print("Adding citizen_rating column to complaint table...")
        db.session.execute(
            text(
                "ALTER TABLE complaint "
                "ADD COLUMN citizen_rating INTEGER"
            )
        )
        db.session.commit()

    if "citizen_feedback_note" not in columns:
        print("Adding citizen_feedback_note column to complaint table...")
        db.session.execute(
            text(
                "ALTER TABLE complaint "
                "ADD COLUMN citizen_feedback_note TEXT"
            )
        )
        db.session.commit()

    if "is_emergency" not in columns:
        print("Adding is_emergency column to complaint table...")
        db.session.execute(
            text(
                "ALTER TABLE complaint "
                "ADD COLUMN is_emergency BOOLEAN DEFAULT 0"
            )
        )
        db.session.commit()

    # Existing complaints did not have timestamps.
    # Give them the current timestamp so the new SLA system works.
    db.session.execute(
        text(
            "UPDATE complaint "
            "SET created_at = :now "
            "WHERE created_at IS NULL"
        ),
        {"now": utcnow_naive()}
    )
    db.session.commit()


def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in kilometers

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


# ==========================
# Landing
# ==========================

@app.route("/")
def landing():

    if "logged_in" in session:
        return redirect(url_for("dashboard"))

    return render_template("landing.html")


# ==========================
# Authentication
# ==========================

@app.route("/auth/<role>", methods=["GET", "POST"])
def auth(role):

    if role not in ["citizen", "ngo", "municipal"]:
        return "Invalid Role"
    if "logged_in" in session:
        return redirect(url_for("dashboard"))
    colors = {
        "citizen": "primary",
        "ngo": "success",
        "municipal": "dark"
    }

    titles = {
        "citizen": "Citizen",
        "ngo": "NGO",
        "municipal": "Municipal Authority"
    }

    message = ""
    category = ""

    if request.method == "POST":

        action = request.form.get("action")

        username = request.form.get("username")

        password = request.form.get("password")

        # ---------------- Register ----------------

        if action == "register":

            confirm = request.form.get("confirm_password")

            if password != confirm:

                message = "Passwords do not match."

                category = "danger"

            elif User.query.filter_by(username=username).first():

                message = "Username already exists."

                category = "danger"

            else:

                hashed = generate_password_hash(password)

                new_user = User(
                    username=username,
                    password=hashed,
                    role=role
                )

                db.session.add(new_user)

                db.session.commit()

                message = "Registration successful. Please login."

                category = "success"

        # ---------------- Login ----------------

        elif action == "login":

            user = User.query.filter_by(
                username=username,
                role=role
            ).first()
            if user and check_password_hash(user.password, password):

                session["logged_in"] = True
                session["user_id"] = user.id
                session["username"] = user.username
                session["role"] = user.role

                return redirect(url_for("dashboard"))

            else:

                message = "Invalid username or password."

                category = "danger"

    return render_template(
        "auth.html",
        role=titles[role],
        role_value=role,
        color=colors[role],
        message=message,
        category=category
    )


# ==========================
# Dashboard
# ==========================
@app.route("/dashboard")
def dashboard():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    role = session["role"]

    if role == "citizen":

        user_id = session["user_id"]

        pending = Complaint.query.filter_by(
            citizen_id=user_id,
            status="Pending"
        ).count()

        in_progress = Complaint.query.filter_by(
            citizen_id=user_id,
            status="In Progress"
        ).count()

        resolved = Complaint.query.filter_by(
            citizen_id=user_id,
            status="Completed"
        ).count()

        recent_complaints = Complaint.query.filter_by(
            citizen_id=user_id
        ).order_by(
            Complaint.id.desc()
        ).limit(5).all()

        announcements = Announcement.query.order_by(
            Announcement.id.desc()
        ).limit(5).all()

        return render_template(
            "citizen/dashboard.html",
            username=session["username"],
            pending=pending,
            in_progress=in_progress,
            resolved=resolved,
            recent_complaints=recent_complaints,
            announcements=announcements
        )

    elif session["role"] == "ngo":

        assigned_count = Complaint.query.filter_by(
            assigned_to=session["user_id"]
        ).count()

        completed_count = Complaint.query.filter_by(
            assigned_to=session["user_id"],
            status="Completed"
        ).count()

        active_drives = VolunteerDrive.query.filter_by(
            ngo_id=session["user_id"],
            status="Open"
        ).count()

        ngo_drive_ids = [
            d.id for d in VolunteerDrive.query.filter_by(
                ngo_id=session["user_id"]
            ).all()
        ]

        volunteers_joined = Volunteer.query.filter(
            Volunteer.drive_id.in_(ngo_drive_ids)
        ).count() if ngo_drive_ids else 0

        recent_issues = Complaint.query.filter_by(
            assigned_to=session["user_id"]
        ).order_by(
            Complaint.id.desc()
        ).limit(3).all()

        return render_template(
            "ngo/dashboard.html",
            username=session["username"],
            assigned_count=assigned_count,
            completed_count=completed_count,
            active_drives=active_drives,
            volunteers_joined=volunteers_joined,
            recent_issues=recent_issues
        )
    elif role == "municipal":

        total_complaints = Complaint.query.count()

        pending = Complaint.query.filter_by(status="Pending").count()

        in_progress = Complaint.query.filter_by(status="In Progress").count()

        completed = Complaint.query.filter_by(status="Completed").count()

        verified_count = Complaint.query.filter_by(verified=True).count()

        pending_verification = Complaint.query.filter_by(
            status="Completed",
            verified=False
        ).count()

        overdue_list = [
            complaint
            for complaint in Complaint.query.all()
            if complaint.is_overdue
        ]

        overdue_complaints = len(overdue_list)

        # Most urgent overdue issues first.
        overdue_alerts = sorted(
            overdue_list,
            key=lambda c: (
                -c.age_days,
                -c.priority,
                -c.report_count
            )
        )[:5]

        total_citizens = User.query.filter_by(role="citizen").count()

        total_ngos = User.query.filter_by(role="ngo").count()

        recent_complaints = Complaint.query.order_by(
            Complaint.id.desc()
        ).limit(5).all()

        recent_announcements = Announcement.query.order_by(
            Announcement.id.desc()
        ).limit(3).all()

        return render_template(
            "municipal/dashboard.html",
            username=session["username"],
            total_complaints=total_complaints,
            pending=pending,
            in_progress=in_progress,
            completed=completed,
            verified_count=verified_count,
            pending_verification=pending_verification,
            overdue_complaints=overdue_complaints,
            overdue_alerts=overdue_alerts,
            total_citizens=total_citizens,
            total_ngos=total_ngos,
            recent_complaints=recent_complaints,
            recent_announcements=recent_announcements
        )

    return redirect(url_for("landing"))


class Volunteer(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    drive_id = db.Column(
        db.Integer,
        db.ForeignKey("volunteer_drive.id"),
        nullable=False
    )

    citizen_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    joined_at = db.Column(
        db.DateTime,
        default=utcnow_naive
    )

    citizen = db.relationship("User")
    drive = db.relationship("VolunteerDrive")


@app.route("/view_volunteers/<int:drive_id>")
def view_volunteers(drive_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "ngo":
        return redirect(url_for("dashboard"))

    drive = VolunteerDrive.query.get_or_404(drive_id)

    if drive.ngo_id != session["user_id"]:
        return redirect(url_for("volunteer_drives"))

    volunteers = Volunteer.query.filter_by(
        drive_id=drive.id
    ).order_by(
        Volunteer.joined_at.desc()
    ).all()

    return render_template(
        "ngo/view_volunteers.html",
        drive=drive,
        volunteers=volunteers,
        username=session["username"]
    )


@app.route("/volunteer_drives")
def volunteer_drives():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "ngo":
        return redirect(url_for("dashboard"))

    drives = VolunteerDrive.query.filter_by(
        ngo_id=session["user_id"]
    ).order_by(
        VolunteerDrive.id.desc()
    ).all()

    total_volunteers = 0

    for drive in drives:
        drive.joined_count = Volunteer.query.filter_by(
            drive_id=drive.id
        ).count()

        total_volunteers += drive.joined_count

    return render_template(
        "ngo/volunteer_drives.html",
        username=session["username"],
        drives=drives,
        total_volunteers=total_volunteers
    )


@app.route("/drives")
def browse_drives():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "citizen":
        return redirect(url_for("dashboard"))

    drives = VolunteerDrive.query.filter_by(
        status="Open"
    ).order_by(
        VolunteerDrive.id.desc()
    ).all()

    for drive in drives:
        drive.joined_count = Volunteer.query.filter_by(
            drive_id=drive.id
        ).count()

    joined_drive_ids = [
        v.drive_id for v in Volunteer.query.filter_by(
            citizen_id=session["user_id"]
        ).all()
    ]

    return render_template(
        "citizen/drives.html",
        username=session["username"],
        drives=drives,
        joined_drive_ids=joined_drive_ids
    )


@app.route("/join_drive/<int:drive_id>")
def join_drive(drive_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "citizen":
        return redirect(url_for("dashboard"))

    drive = VolunteerDrive.query.get_or_404(drive_id)

    already_joined = Volunteer.query.filter_by(
        drive_id=drive.id,
        citizen_id=session["user_id"]
    ).first()

    joined_count = Volunteer.query.filter_by(
        drive_id=drive.id
    ).count()

    if (
        drive.status == "Open"
        and not already_joined
        and joined_count < drive.volunteers_needed
    ):

        volunteer = Volunteer(
            drive_id=drive.id,
            citizen_id=session["user_id"]
        )

        db.session.add(volunteer)
        db.session.commit()

        if drive.ngo_id:
            create_notification(
                user_id=drive.ngo_id,
                title="New Volunteer Joined!",
                message=f"Citizen '{session.get('username')}' registered for your drive '{drive.title}' ({joined_count + 1}/{drive.volunteers_needed} volunteers).",
                category="volunteer",
                link="/volunteer_drives"
            )
        create_notification(
            user_id=session["user_id"],
            title="Drive Registration Confirmed",
            message=f"You successfully registered for volunteer drive: '{drive.title}' at {drive.meeting_point}.",
            category="volunteer",
            link="/drives"
        )

    return redirect(url_for("browse_drives"))


@app.route("/close_drive/<int:drive_id>")
def close_drive(drive_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "ngo":
        return redirect(url_for("dashboard"))

    drive = VolunteerDrive.query.get_or_404(drive_id)

    if drive.ngo_id != session["user_id"]:
        return redirect(url_for("volunteer_drives"))

    drive.status = "Closed"

    db.session.commit()

    return redirect(url_for("volunteer_drives"))


@app.route("/create_drive", methods=["GET", "POST"])
def create_drive():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "ngo":
        return redirect(url_for("dashboard"))

    if request.method == "POST":

        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")

        # Make sure a location was selected
        if not latitude or not longitude:
            return render_template(
                "ngo/create_drive.html",
                username=session["username"],
                error="Please select a meeting point on the map."
            )

        drive = VolunteerDrive(

            title=request.form["title"],

            description=request.form["description"],

            meeting_point=request.form["meeting_point"],

            latitude=float(latitude),

            longitude=float(longitude),

            contact=request.form["contact"],

            drive_date=request.form["date"],

            drive_time=request.form["time"],

            volunteers_needed=int(
                request.form["needed"]
            ),

            instructions=request.form["instructions"],

            ngo_id=session["user_id"]

        )

        db.session.add(drive)

        db.session.commit()

        return redirect(
            url_for("volunteer_drives")
        )

    return render_template(
        "ngo/create_drive.html",
        username=session["username"]
    )

@app.route("/my_assigned")
def my_assigned():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    complaints = Complaint.query.filter_by(
        assigned_to=session["user_id"]
    ).order_by(
        Complaint.priority.desc(),
        Complaint.id.desc()
    ).all()

    return render_template(
        "ngo/my_assigned.html",
        complaints=complaints,
        username=session["username"]
    )


@app.route("/fundraisers")
def fundraisers():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    fundraisers = Fundraiser.query.order_by(
        Fundraiser.created_at.desc()
    ).all()

    if session.get("role") == "ngo":
        return render_template(
            "ngo/fundraisers.html",
            fundraisers=fundraisers
        )

    return render_template(
        "citizen/fundraisers.html",
        fundraisers=fundraisers,
        username=session.get("username")
    )


@app.route("/create_fundraiser", methods=["GET", "POST"])
def create_fundraiser():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    user = User.query.get(session["user_id"])

    if not user or user.role != "ngo":
        return redirect(url_for("dashboard"))

    complaints = Complaint.query.filter(
        Complaint.assigned_to == user.id,
        Complaint.assigned_role == "ngo"
    ).all()

    if request.method == "POST":

        title = request.form.get("title")

        description = request.form.get("description")

        campaign_type = request.form.get(
            "campaign_type"
        )

        target_amount = float(
            request.form.get("target_amount")
        )

        complaint_id = request.form.get(
            "complaint_id"
        )

        image = request.files.get("image")

        filename = None

        if image and image.filename:

            if not allowed_file(image.filename):
                flash("Invalid campaign image format. Please upload a PNG, JPG, JPEG, or WEBP file.", "danger")
                return redirect(url_for("create_fundraiser"))

            filename = secure_filename(
                str(uuid.uuid4()) + "_" + image.filename
            )

            image.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )
            )

        fundraiser = Fundraiser(

            title=title,

            description=description,

            target_amount=target_amount,

            collected_amount=0,

            image=filename,

            campaign_type=campaign_type,

            ngo_id=user.id,

            complaint_id=(
                int(complaint_id)
                if complaint_id
                else None
            )

        )

        db.session.add(fundraiser)

        db.session.commit()

        return redirect(
            url_for("fundraisers")
        )

    return render_template(
        "ngo/create_fundraiser.html",
        complaints=complaints
    )


@app.route("/fundraiser_details/<int:fundraiser_id>")
def fundraiser_details(fundraiser_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    fundraiser = Fundraiser.query.get_or_404(fundraiser_id)

    return render_template(
        "ngo/fundraiser_details.html",
        fundraiser=fundraiser,
        username=session.get("username")
    )

@app.route("/uncomplete_issue/<int:complaint_id>", methods=["POST"])
def uncomplete_issue(complaint_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session.get("role") != "municipal":
        return redirect(url_for("dashboard"))

    complaint = Complaint.query.get_or_404(complaint_id)

    if complaint.status != "Completed":
        flash(
            "This issue is not currently marked as completed.",
            "warning"
        )
        return redirect(url_for("municipal_complaints"))

    # Send the issue back to the assigned worker
    complaint.status = "In Progress"

    # Remove verification
    complaint.verified = False

    # Keep after_image and completion_note
    # for accountability/history.

    db.session.commit()

    flash(
        "Completion rejected. The issue has been returned to In Progress.",
        "warning"
    )

    return redirect(url_for("municipal_complaints"))

@app.route("/donate/<int:fundraiser_id>", methods=["POST"])
def donate(fundraiser_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    fundraiser = Fundraiser.query.get_or_404(fundraiser_id)

    try:
        amount = float(request.form.get("amount", 0))
    except (ValueError, TypeError):
        amount = 0

    if amount <= 0:
        return redirect(
            url_for(
                "fundraiser_details",
                fundraiser_id=fundraiser.id
            )
        )

    # Prevent donation beyond target
    remaining = (
        fundraiser.target_amount
        - fundraiser.collected_amount
    )

    if amount > remaining:
        amount = remaining

    if amount <= 0:
        return redirect(
            url_for(
                "fundraiser_details",
                fundraiser_id=fundraiser.id
            )
        )

    donation = Donation(
        fundraiser_id=fundraiser.id,
        donor_id=session["user_id"],
        amount=amount
    )

    db.session.add(donation)

    # Update collected amount
    fundraiser.collected_amount += amount

    db.session.commit()

    if fundraiser.ngo_id:
        create_notification(
            user_id=fundraiser.ngo_id,
            title="New Donation Received! 💖",
            message=f"{session.get('username')} donated ₹{amount:.0f} to your cause '{fundraiser.title}'.",
            category="donation",
            link=f"/fundraiser_details/{fundraiser.id}"
        )
    create_notification(
        user_id=session["user_id"],
        title="Donation Successful",
        message=f"Thank you for contributing ₹{amount:.0f} to '{fundraiser.title}'!",
        category="donation",
        link=f"/fundraiser_details/{fundraiser.id}"
    )

    return redirect(
        url_for(
            "fundraiser_details",
            fundraiser_id=fundraiser.id
        )
    )


# ==========================
# Report an issue
# ==========================

@app.route("/report", methods=["GET", "POST"])
@login_required
@role_required("citizen")
def report():

    if request.method == "POST":

        # If the citizen confirmed this matches an existing
        # complaint (via the duplicate-check modal), don't create
        # a new row - just log the confirmation and bump priority.
        duplicate_of = request.form.get("duplicate_of")

        if duplicate_of:
            return _register_duplicate(int(duplicate_of))

        file = request.files.get("image")

        filename = ""

        if file and file.filename != "":

            if not allowed_file(file.filename):
                flash("Invalid image type. Please upload a PNG, JPG, JPEG, or WEBP file.", "danger")
                return redirect(url_for("report"))

            filename = secure_filename(
                str(uuid.uuid4()) + "_" + file.filename
            )

            file.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )
            )

        severity = (request.form.get("severity") or "Medium").strip()
        if severity not in ["Low", "Medium", "High", "Critical Hazard"]:
            severity = "Medium"

        department = (request.form.get("department") or "General").strip()

        is_emergency_flag = request.form.get("is_emergency") == "1" or severity == "Critical Hazard"
        if is_emergency_flag:
            severity = "Critical Hazard"
            base_priority = 5
        else:
            # Severity-based priority boost
            base_priority = 3 if severity == "Critical Hazard" else (2 if severity == "High" else 1)

        complaint = Complaint(
            title=request.form["title"],
            description=request.form["description"],
            category=request.form["category"],
            location=request.form["location"],
            latitude=float(request.form.get("latitude") or 0),
            longitude=float(request.form.get("longitude") or 0),
            severity=severity,
            department=department,
            priority=base_priority,
            is_emergency=is_emergency_flag,
            image=filename,
            citizen_id=session["user_id"]
        )

        db.session.add(complaint)
        db.session.commit()

        # Notification dispatch
        if is_emergency_flag:
            create_notification(
                user_id=session["user_id"],
                title="🚨 Emergency SOS Registered",
                message=f"Emergency SOS ticket #{complaint.id} ('{complaint.title}') prioritized for immediate municipal dispatch.",
                category="emergency",
                link="/my_complaints",
                is_emergency=True
            )
            # Alert all municipal officers
            muni_officers = User.query.filter_by(role="municipal").all()
            for m in muni_officers:
                create_notification(
                    user_id=m.id,
                    title="🚨 CRITICAL SOS: Immediate Dispatch Required",
                    message=f"Citizen logged Emergency SOS ticket #{complaint.id}: '{complaint.title}' ({complaint.category}) at {complaint.location}.",
                    category="emergency",
                    link="/municipal/complaints",
                    is_emergency=True
                )
            flash("🚨 Emergency SOS ticket registered! Prioritized for immediate municipal response.", "danger")
        else:
            create_notification(
                user_id=session["user_id"],
                title="Issue Report Logged",
                message=f"Ticket #{complaint.id} ('{complaint.title}') registered and routed to {complaint.department}.",
                category="ticket_update",
                link="/my_complaints"
            )
            flash("Your civic issue has been successfully reported!", "success")
        return redirect(url_for("dashboard"))

    return render_template("citizen/report.html")


def _register_duplicate(complaint_id):
    """Shared logic for confirming a complaint as a duplicate.
    Used both by /report (modal flow) and /confirm_duplicate."""

    complaint = Complaint.query.get_or_404(complaint_id)

    user_id = session["user_id"]

    already_reported = DuplicateReport.query.filter_by(
        complaint_id=complaint.id,
        citizen_id=user_id
    ).first()

    # Don't let the original reporter, or a repeat reporter,
    # bump priority more than once.
    if not already_reported and complaint.citizen_id != user_id:

        db.session.add(DuplicateReport(
            complaint_id=complaint.id,
            citizen_id=user_id
        ))

        complaint.priority += 1

        db.session.commit()
        flash("Thank you! You endorsed this issue (+1). Its community priority was boosted.", "success")
    elif complaint.citizen_id == user_id:
        flash("You are already the original reporter of this issue.", "info")
    else:
        flash("You have already upvoted/endorsed this issue.", "warning")

    referrer = request.referrer
    if referrer and ("nearby" in referrer or "my_complaints" in referrer):
        return redirect(referrer)

    return redirect(url_for("dashboard"))


@app.route("/check_duplicates", methods=["POST"])
def check_duplicates():
    """Called via AJAX from the report form before final submit.
    Returns nearby, unresolved complaints of the same category so
    the citizen can confirm one instead of filing a new report."""

    if "logged_in" not in session:
        return {"success": False, "error": "Please login first."}, 401

    data = request.get_json(silent=True) or request.form

    try:
        lat = float(data.get("latitude"))
        lon = float(data.get("longitude"))
    except (TypeError, ValueError):
        return {"success": False, "error": "Invalid location."}, 400

    category = data.get("category")

    if not category:
        return {"success": True, "matches": []}

    candidates = Complaint.query.filter(
        Complaint.category == category,
        Complaint.status.in_(["Pending", "In Progress"])
    ).all()

    matches = []

    for c in candidates:

        distance = haversine(lat, lon, c.latitude, c.longitude)

        if distance <= DUPLICATE_RADIUS_KM:

            matches.append({
                "id": c.id,
                "title": c.title,
                "description": c.description,
                "status": c.status,
                "image": c.image,
                "severity": getattr(c, "severity", "Medium"),
                "department": getattr(c, "department", "General"),
                "distance_m": round(distance * 1000),
                "reporters": c.report_count
            })

    matches.sort(key=lambda m: m["distance_m"])

    return {"success": True, "matches": matches}


@app.route("/confirm_duplicate/<int:complaint_id>", methods=["POST"])
@login_required
@role_required("citizen")
def confirm_duplicate(complaint_id):
    """Standalone confirm endpoint - e.g. a 'Report this too'
    button on the nearby-issues page, outside the report-form
    flow."""
    return _register_duplicate(complaint_id)


@app.route("/analyze_issue", methods=["POST"])
def analyze_issue():

    if "logged_in" not in session:
        return {
            "success": False,
            "error": "Please login first."
        }, 401

    if session.get("role") != "citizen":
        return {
            "success": False,
            "error": "Only citizens can report issues."
        }, 403

    file = request.files.get("image")

    if not file or file.filename == "":
        return {
            "success": False,
            "error": "Please upload an image."
        }, 400

    if not allowed_file(file.filename):
        return {
            "success": False,
            "error": "Unsupported file format. Please upload JPG, PNG, or WEBP."
        }, 400

    if not gemini_client:
        return {
            "success": False,
            "error": "AI service is currently unavailable. Please fill the form manually."
        }, 503

    try:

        image_bytes = file.read()

        mime_type = file.mimetype or "image/jpeg"

        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=mime_type
        )

        prompt = """
You are an AI assistant for CivicConnect.

Analyze the uploaded image and identify the civic issue.

Return ONLY valid JSON in exactly this format:

{
    "title": "short issue title",
    "description": "clear description of the issue",
    "category": "one category",
    "severity": "Low" | "Medium" | "High" | "Critical Hazard",
    "department": "Roads & Transport" | "Water Supply & Sewerage" | "Solid Waste Management" | "Electrical & Lighting" | "Public Health" | "General",
    "urgency_rationale": "one concise sentence explaining why this severity applies"
}

IMPORTANT:
The category MUST be EXACTLY ONE of these values:

"Garbage"
"Pothole"
"Street Light"
"Water Leakage"
"Sewage"
"Illegal Dumping"
"Other"

Severity Criteria:
- "Critical Hazard": Imminent life/safety danger (exposed live electric wires, deep uncovered manhole on road/sidewalk, major structural collapse).
- "High": Major sanitation risk or traffic disruption (overflowing sewage flooding road, burst water pipe, huge vehicle-damaging crater).
- "Medium": Standard civic problem (flickering or out street light, typical pothole, regular overflowing trash bin).
- "Low": Minor inconvenience or cosmetic issue (small litter pile, faded marker).

Do not use any other category.
Do not return markdown fences.
Return JSON only.
"""
        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[
                image_part,
                prompt
            ]
        )

        result_text = response.text.strip()

        # Remove markdown fences if Gemini adds them
        if result_text.startswith("```"):
            result_text = result_text.replace("```json", "")
            result_text = result_text.replace("```", "")
            result_text = result_text.strip()

        result = json.loads(result_text)

        # Fallbacks for robustness
        if result.get("severity") not in ["Low", "Medium", "High", "Critical Hazard"]:
            result["severity"] = "Medium"
        if not result.get("department"):
            result["department"] = "General"

        return {
            "success": True,
            "data": result
        }

    except Exception as e:

        print("Gemini Error:", e)

        return {
            "success": False,
            "error": "Could not analyze the image. Please fill the form manually."
        }, 500


# ==========================
# My Complaints
# ==========================

@app.route("/my_complaints")
def my_complaints():

    # User must be logged in
    if "logged_in" not in session:
        return redirect(url_for("landing"))

    # Only citizens can access this page
    if session.get("role") != "citizen":
        return redirect(url_for("dashboard"))

    # Current logged in user's ID
    user_id = session["user_id"]

    # Fetch ONLY this user's complaints
    complaints = Complaint.query.filter_by(
        citizen_id=user_id
    ).order_by(Complaint.id.desc()).all()

    # Statistics
    pending = Complaint.query.filter_by(
        citizen_id=user_id,
        status="Pending"
    ).count()

    in_progress = Complaint.query.filter_by(
        citizen_id=user_id,
        status="In Progress"
    ).count()

    resolved = Complaint.query.filter_by(
        citizen_id=user_id,
        status="Completed"
    ).count()

    return render_template(
        "citizen/my_complaints.html",
        username=session["username"],
        complaints=complaints,
        pending=pending,
        in_progress=in_progress,
        resolved=resolved
    )


# ==========================
# Profile
# ==========================

@app.route("/profile", methods=["GET", "POST"])
def profile():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    user = User.query.get(session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("landing"))

    message = ""
    category = ""

    if request.method == "POST":

        username = request.form.get("username", "").strip()

        current_password = request.form.get(
            "current_password",
            ""
        )

        new_password = request.form.get(
            "new_password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        # =================================
        # USERNAME
        # =================================

        if not username:

            message = "Username cannot be empty."
            category = "danger"

        else:

            existing_user = User.query.filter(
                User.username == username,
                User.id != user.id
            ).first()

            if existing_user:

                message = "Username already exists."
                category = "danger"

            else:

                # Update username

                user.username = username

                # =================================
                # PASSWORD CHANGE
                # =================================

                if new_password or confirm_password:

                    # Current password is REQUIRED

                    if not current_password:

                        message = (
                            "Enter your current password "
                            "to change your password."
                        )

                        category = "danger"

                    # Verify current password

                    elif not check_password_hash(
                        user.password,
                        current_password
                    ):

                        message = "Current password is incorrect."
                        category = "danger"

                    # Check new passwords

                    elif new_password != confirm_password:

                        message = "New passwords do not match."
                        category = "danger"

                    # Minimum password length

                    elif len(new_password) < 6:

                        message = (
                            "New password must contain "
                            "at least 6 characters."
                        )

                        category = "danger"

                    # Everything is valid

                    else:

                        user.password = generate_password_hash(
                            new_password
                        )

                        message = (
                            "Profile and password updated successfully."
                        )

                        category = "success"

                else:

                    message = "Profile updated successfully."
                    category = "success"

                # =================================
                # SAVE
                # =================================

                if category == "success":

                    db.session.commit()

                    session["username"] = user.username

    return render_template(
        "citizen/profile.html",
        username=user.username,
        role=user.role,
        message=message,
        category=category
    )


@app.route("/complete_issue/<int:complaint_id>", methods=["GET", "POST"])
@login_required
def complete_issue(complaint_id):

    complaint = Complaint.query.get_or_404(complaint_id)

    if complaint.assigned_to != session["user_id"]:
        flash("You are not assigned to resolve this issue.", "danger")
        return redirect(url_for("nearby"))

    if request.method == "POST":

        file = request.files.get("after_image")

        filename = ""

        if file and file.filename:

            if not allowed_file(file.filename):
                flash("Invalid image format for completion proof. Please upload PNG, JPG, JPEG, or WEBP.", "danger")
                return redirect(url_for("complete_issue", complaint_id=complaint_id))

            filename = secure_filename(
                str(uuid.uuid4()) + "_" + file.filename
            )

            file.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )
            )

        complaint.after_image = filename

        complaint.completion_note = request.form.get("completion_note", "")

        complaint.completed_at = utcnow_naive()

        complaint.status = "Completed"

        db.session.commit()

        create_notification(
            user_id=complaint.citizen_id,
            title="Work Completed: Review Proof",
            message=f"Resolution proof was uploaded for ticket '{complaint.title}'. Please inspect the before/after photos and confirm your satisfaction.",
            category="ticket_update",
            link="/my_complaints"
        )

        flash("Issue marked as Completed! Uploaded proof submitted for municipal verification.", "success")
        return redirect(url_for("nearby"))

    return render_template(
        "complete_issue.html",
        complaint=complaint,
        username=session["username"]
    )


# =========================================================
# Citizen Resolution Verification & Feedback / Reopen Flow
# =========================================================

@app.route("/citizen_confirm_resolution/<int:complaint_id>", methods=["POST"])
@login_required
@role_required("citizen")
def citizen_confirm_resolution(complaint_id):
    complaint = Complaint.query.get_or_404(complaint_id)
    if complaint.citizen_id != session["user_id"]:
        flash("Only the citizen who reported this issue can confirm its resolution.", "danger")
        return redirect(url_for("my_complaints"))

    rating = request.form.get("rating", type=int)
    note = (request.form.get("feedback_note") or "").strip()

    complaint.citizen_feedback = "Satisfied"
    complaint.citizen_rating = min(5, max(1, rating)) if rating else 5
    complaint.citizen_feedback_note = note
    complaint.verified = True
    db.session.commit()

    if complaint.assigned_to:
        create_notification(
            user_id=complaint.assigned_to,
            title="Resolution Approved! ⭐",
            message=f"Citizen confirmed resolution for '{complaint.title}' with {complaint.citizen_rating}★ rating.",
            category="ticket_update",
            link="/dashboard"
        )

    flash("Thank you for confirming! Your feedback was logged and this issue is now officially closed.", "success")
    return redirect(url_for("my_complaints"))


@app.route("/citizen_reopen_complaint/<int:complaint_id>", methods=["POST"])
@login_required
@role_required("citizen")
def citizen_reopen_complaint(complaint_id):
    complaint = Complaint.query.get_or_404(complaint_id)
    if complaint.citizen_id != session["user_id"]:
        flash("Only the citizen who reported this issue can dispute or reopen it.", "danger")
        return redirect(url_for("my_complaints"))

    reopen_reason = (request.form.get("reopen_reason") or "").strip()
    if not reopen_reason:
        flash("Please provide a brief reason why the problem is still unresolved.", "warning")
        return redirect(url_for("my_complaints"))

    complaint.status = "In Progress"
    complaint.verified = False
    complaint.citizen_feedback = "Unsatisfied"
    complaint.citizen_feedback_note = reopen_reason
    complaint.priority += 2  # Escalate priority due to failed inspection
    db.session.commit()

    if complaint.assigned_to:
        create_notification(
            user_id=complaint.assigned_to,
            title="Ticket Reopened & Escalated ⚠️",
            message=f"Citizen disputed resolution for '{complaint.title}' (+2 Priority). Reason: {reopen_reason}",
            category="ticket_update",
            link="/dashboard"
        )

    flash("Issue reopened and escalated (+2 Priority) for prompt re-inspection.", "warning")
    return redirect(url_for("my_complaints"))


# =========================================================
# NGO Impact Analytics & Statistics
# =========================================================

@app.route("/ngo/statistics")
@login_required
@role_required("ngo")
def ngo_statistics():
    user_id = session["user_id"]
    username = session["username"]

    # Drives by this NGO
    drives = VolunteerDrive.query.filter_by(ngo_id=user_id).all()
    total_drives = len(drives)
    drive_ids = [d.id for d in drives]
    total_volunteers = Volunteer.query.filter(Volunteer.drive_id.in_(drive_ids)).count() if drive_ids else 0

    # Resolved issues assigned to this NGO
    resolved_complaints = Complaint.query.filter(
        Complaint.assigned_to == user_id,
        Complaint.assigned_role == "ngo",
        Complaint.status.in_(["Completed", "Verified"])
    ).all()
    total_resolved = len(resolved_complaints)

    # Category breakdown of resolved complaints
    category_counts_dict = {}
    for c in resolved_complaints:
        category_counts_dict[c.category] = category_counts_dict.get(c.category, 0) + 1

    category_labels = list(category_counts_dict.keys())
    category_counts = [category_counts_dict[k] for k in category_labels]

    # Fundraisers by this NGO
    fundraisers = Fundraiser.query.filter_by(ngo_id=user_id).all()
    total_funds = sum(f.collected_amount for f in fundraisers)
    fundraiser_titles = [f.title[:20] for f in fundraisers[:5]]
    fundraiser_collected = [f.collected_amount for f in fundraisers[:5]]
    fundraiser_targets = [f.target_amount for f in fundraisers[:5]]

    return render_template(
        "ngo/statistics.html",
        username=username,
        total_drives=total_drives,
        total_volunteers=total_volunteers,
        total_resolved=total_resolved,
        total_funds=total_funds,
        category_labels=category_labels,
        category_counts=category_counts,
        fundraiser_titles=fundraiser_titles,
        fundraiser_collected=fundraiser_collected,
        fundraiser_targets=fundraiser_targets
    )


@app.route("/nearby", methods=["GET", "POST"])
def nearby():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    complaints = []

    sort_by = request.args.get("sort", "priority")

    if request.method == "POST":

        user_lat = float(request.form["latitude"])
        user_lon = float(request.form["longitude"])

        all_complaints = Complaint.query.filter(
            Complaint.status != "Verified"
        ).all()

        for complaint in all_complaints:

            distance = haversine(
                user_lat,
                user_lon,
                complaint.latitude,
                complaint.longitude
            )

            if distance <= 20:

                complaint.distance = round(distance, 2)

                complaints.append(complaint)

        # ==========================
        # SORTING
        # ==========================

        if sort_by == "distance":
            # Nearest first
            complaints.sort(key=lambda x: x.distance)

        elif sort_by == "priority":
            # Highest priority first
            complaints.sort(
                key=lambda x: (-x.priority, x.distance)
            )

        elif sort_by == "reports":
            # Most reported first
            complaints.sort(
                key=lambda x: (-x.report_count, x.distance)
            )

        elif sort_by == "newest":
            # Newest complaint first
            complaints.sort(
                key=lambda x: x.id,
                reverse=True
            )

        elif sort_by == "oldest":
            # Oldest complaint first
            complaints.sort(
                key=lambda x: x.id
            )

        elif sort_by == "category_az":
            complaints.sort(
                key=lambda x: x.category.lower()
            )

        elif sort_by == "category_za":
            complaints.sort(
                key=lambda x: x.category.lower(),
                reverse=True
            )

        elif sort_by == "status":
            status_order = {
                "Pending": 1,
                "In Progress": 2,
                "Completed": 3
            }

            complaints.sort(
                key=lambda x: status_order.get(x.status, 99)
            )

    return render_template(
        "nearby.html",
        complaints=complaints,
        username=session["username"],
        role=session["role"],
        sort_by=sort_by
    )

@app.route("/take_issue/<int:complaint_id>")
def take_issue(complaint_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    complaint = Complaint.query.get_or_404(complaint_id)

    # Only pending complaints can be taken
    if complaint.status != "Pending":
        return redirect(url_for("nearby"))

    complaint.status = "In Progress"

    complaint.assigned_to = session["user_id"]

    complaint.assigned_role = session["role"]

    db.session.commit()

    create_notification(
        user_id=complaint.citizen_id,
        title="Ticket Claimed by Partner NGO",
        message=f"NGO '{session.get('username')}' has claimed your ticket '{complaint.title}' and marked it In Progress.",
        category="ticket_update",
        link="/my_complaints"
    )

    return redirect(url_for("nearby"))


# ==========================
# Municipal
# ==========================


# ==========================
# Civic Heat Map
# ==========================

# ==========================
# Municipal Overdue Alerts
# ==========================

@app.route("/municipal/alerts")
def municipal_alerts():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "municipal":
        return redirect(url_for("dashboard"))

    overdue_alerts = [
        complaint
        for complaint in Complaint.query.all()
        if complaint.is_overdue
    ]

    overdue_alerts.sort(
        key=lambda c: (
            -c.age_days,
            -c.priority,
            -c.report_count
        )
    )

    return render_template(
        "municipal/alerts.html",
        username=session["username"],
        overdue_alerts=overdue_alerts
    )


@app.route("/municipal/heatmap")
def municipal_heatmap():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "municipal":
        return redirect(url_for("dashboard"))

    # Show all issues that are not officially verified.
    complaints = Complaint.query.filter(
        Complaint.status != "Verified"
    ).all()

    heatmap_data = []

    for complaint in complaints:

        # Priority is the main heat intensity.
        # Additional citizen reports slightly increase intensity.
        intensity = complaint.priority + (
            min(max(complaint.report_count - 1, 0), 5) * 0.5
        )

        heatmap_data.append({
            "id": complaint.id,
            "title": complaint.title,
            "category": complaint.category,
            "status": complaint.status,
            "latitude": complaint.latitude,
            "longitude": complaint.longitude,
            "priority": complaint.priority,
            "reports": complaint.report_count,
            "intensity": min(intensity, 10),
            "overdue": complaint.is_overdue,
            "aging": complaint.is_aging
        })

    categories = sorted(
        {
            complaint.category
            for complaint in complaints
            if complaint.category
        }
    )

    return render_template(
        "municipal/heatmap.html",
        username=session["username"],
        heatmap_data=heatmap_data,
        categories=categories
    )


@app.route("/municipal/complaints")
def municipal_complaints():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "municipal":
        return redirect(url_for("dashboard"))

    status_filter = request.args.get("status", "All")
    category_filter = request.args.get("category", "All")
    urgency_filter = request.args.get("urgency", "All")

    query = Complaint.query

    if status_filter != "All":
        query = query.filter_by(status=status_filter)

    if category_filter != "All":
        query = query.filter_by(category=category_filter)

    complaints = query.all()

    # Overdue first, then aging, then priority, then newest.
    complaints.sort(
        key=lambda c: (
            not c.is_overdue,
            not c.is_aging,
            -c.priority,
            -c.id
        )
    )

    if urgency_filter == "Overdue":
        complaints = [c for c in complaints if c.is_overdue]

    elif urgency_filter == "Aging":
        complaints = [c for c in complaints if c.is_aging]

    categories = [
        row[0]
        for row in db.session.query(
            Complaint.category
        ).distinct().all()
    ]

    ngos = User.query.filter_by(role="ngo").all()

    return render_template(
        "municipal/complaints.html",
        username=session["username"],
        complaints=complaints,
        categories=categories,
        ngos=ngos,
        status_filter=status_filter,
        category_filter=category_filter,
        urgency_filter=urgency_filter
    )


@app.route("/municipal/assign/<int:complaint_id>", methods=["POST"])
def assign_complaint(complaint_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "municipal":
        return redirect(url_for("dashboard"))

    complaint = Complaint.query.get_or_404(complaint_id)

    ngo_id = request.form.get("ngo_id")

    if complaint.status == "Pending" and ngo_id:

        ngo_user = User.query.filter_by(id=ngo_id, role="ngo").first()
        if ngo_user:
            complaint.assigned_to = ngo_user.id
            complaint.assigned_role = "ngo"
            complaint.status = "In Progress"
            db.session.commit()

            create_notification(
                user_id=complaint.citizen_id,
                title="Assigned to Partner NGO",
                message=f"Municipal Authority assigned ticket '{complaint.title}' to partner NGO '{ngo_user.username}'.",
                category="ticket_update",
                link="/my_complaints"
            )
            create_notification(
                user_id=ngo_user.id,
                title="New Issue Assigned to Your NGO",
                message=f"Municipal Authority assigned you ticket '{complaint.title}' ({complaint.category}, {complaint.severity}).",
                category="ticket_update",
                link="/my_assigned"
            )

    return redirect(url_for("municipal_complaints"))



# ==========================
# AI Resolution Proof Analysis
# ==========================

@app.route("/ai_verify_completion/<int:complaint_id>")
def ai_verify_completion(complaint_id):

    if "logged_in" not in session:
        return {
            "success": False,
            "error": "Please login first."
        }, 401

    if session.get("role") != "municipal":
        return {
            "success": False,
            "error": "Municipal access only."
        }, 403

    complaint = Complaint.query.get_or_404(complaint_id)

    if complaint.status != "Completed":
        return {
            "success": False,
            "error": "AI proof analysis is available after the issue is marked completed."
        }, 400

    if not complaint.after_image:
        return {
            "success": False,
            "error": "No completion proof image was uploaded."
        }, 400

    after_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        complaint.after_image
    )

    if not os.path.exists(after_path):
        return {
            "success": False,
            "error": "Completion proof image could not be found."
        }, 404

    try:

        with open(after_path, "rb") as f:
            after_bytes = f.read()

        after_mime = (
            "image/jpeg"
            if complaint.after_image.lower().endswith((".jpg", ".jpeg"))
            else "image/png"
        )

        contents = []

        # Before image, when available.
        if complaint.image:

            before_path = os.path.join(
                app.config["UPLOAD_FOLDER"],
                complaint.image
            )

            if os.path.exists(before_path):

                with open(before_path, "rb") as f:
                    before_bytes = f.read()

                before_mime = (
                    "image/jpeg"
                    if complaint.image.lower().endswith((".jpg", ".jpeg"))
                    else "image/png"
                )

                contents.append(
                    types.Part.from_bytes(
                        data=before_bytes,
                        mime_type=before_mime
                    )
                )

        contents.append(
            types.Part.from_bytes(
                data=after_bytes,
                mime_type=after_mime
            )
        )

        prompt = f"""
You are an AI quality-check assistant for CivicConnect.

A civic complaint was reported as:

Title: {complaint.title}
Category: {complaint.category}
Description: {complaint.description}

The assigned worker has submitted a completion note:

{complaint.completion_note or "No completion note provided."}

The images supplied are:
1. Before image, if available.
2. After/completion image.

Compare the images when both are available and determine whether the
visible civic problem appears resolved.

Return ONLY valid JSON:

{{
    "resolved": true,
    "confidence": 0,
    "summary": "short explanation",
    "remaining_issue": "what still appears unresolved, or None",
    "recommendation": "Verify" 
}}

Rules:
- confidence must be an integer from 0 to 100.
- Analyze only what is visible.
- Do not invent facts.
- If the images do not clearly prove resolution, use resolved=false
  or a lower confidence and recommend manual review.
- AI is only an assistant; the municipal officer makes the final decision.
"""

        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=contents + [prompt]
        )

        result_text = response.text.strip()

        if result_text.startswith("```"):
            result_text = result_text.replace("```json", "")
            result_text = result_text.replace("```", "")
            result_text = result_text.strip()

        result = json.loads(result_text)

        result["confidence"] = max(
            0,
            min(
                100,
                int(result.get("confidence", 0))
            )
        )

        return {
            "success": True,
            "data": result
        }

    except Exception as e:

        print("Completion Proof AI Error:", e)

        return {
            "success": False,
            "error": "AI could not analyze the completion proof. Please review it manually."
        }, 500


@app.route("/verify_issue/<int:complaint_id>")
def verify_issue(complaint_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "municipal":
        return redirect(url_for("dashboard"))

    complaint = Complaint.query.get_or_404(complaint_id)

    return render_template(
        "municipal/verify_issue.html",
        complaint=complaint,
        username=session["username"]
    )


@app.route("/verify_issue/<int:complaint_id>/confirm")
def verify_issue_confirm(complaint_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "municipal":
        return redirect(url_for("dashboard"))

    complaint = Complaint.query.get_or_404(complaint_id)

    if complaint.status == "Completed":
        complaint.verified = True
        db.session.commit()

    return redirect(url_for("municipal_complaints"))



# ==========================
# AI Announcement Assistant
# ==========================

@app.route("/ai_generate_announcement", methods=["POST"])
def ai_generate_announcement():

    if "logged_in" not in session:
        return {"success": False, "error": "Please login first."}, 401

    if session.get("role") != "municipal":
        return {"success": False, "error": "Municipal access only."}, 403

    data = request.get_json(silent=True) or request.form

    topic = (data.get("topic") or "").strip()
    category = (data.get("category") or "General").strip()
    audience = (data.get("audience") or "citizens").strip()
    location = (data.get("location") or "the local area").strip()
    urgency = (data.get("urgency") or "normal").strip()

    if not topic:
        return {
            "success": False,
            "error": "Enter the announcement topic first."
        }, 400

    prompt = f"""
You are the official CivicConnect municipal communication assistant.

Create a clear, factual public announcement for citizens.

Topic:
{topic}

Category:
{category}

Audience:
{audience}

Location:
{location}

Urgency:
{urgency}

Return ONLY valid JSON:
{{
    "title": "short public announcement title",
    "message": "professional announcement message"
}}

Rules:
- Do not invent dates, numbers, deadlines, services, phone numbers,
  government departments, or facts that were not supplied.
- Keep the title under 100 characters.
- Keep the message concise and easy for citizens to understand.
- Clearly state what citizens should know or do.
- Use a calm official tone.
- Do not use markdown.
"""

    try:

        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[prompt]
        )

        result_text = response.text.strip()

        if result_text.startswith("```"):
            result_text = result_text.replace("```json", "")
            result_text = result_text.replace("```", "")
            result_text = result_text.strip()

        result = json.loads(result_text)

        if not result.get("title") or not result.get("message"):
            raise ValueError("Incomplete AI response.")

        return {
            "success": True,
            "data": {
                "title": result["title"],
                "message": result["message"]
            }
        }

    except Exception as e:

        print("Announcement AI Error:", e)

        return {
            "success": False,
            "error": "AI could not draft the announcement. Please write it manually."
        }, 500


@app.route("/announcements", methods=["GET", "POST"])
def announcements():

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if request.method == "POST":

        if session["role"] != "municipal":
            return redirect(url_for("dashboard"))

        announcement = Announcement(
            title=request.form["title"],
            message=request.form["message"],
            category=request.form.get("category") or "General",
            posted_by=session["user_id"]
        )

        db.session.add(announcement)
        db.session.commit()

        return redirect(url_for("announcements"))

    all_announcements = Announcement.query.order_by(
        Announcement.id.desc()
    ).all()

    if session["role"] == "municipal":
        return render_template(
            "municipal/announcements.html",
            username=session["username"],
            announcements=all_announcements
        )

    return redirect(url_for("dashboard"))


@app.route("/delete_announcement/<int:announcement_id>")
def delete_announcement(announcement_id):

    if "logged_in" not in session:
        return redirect(url_for("landing"))

    if session["role"] != "municipal":
        return redirect(url_for("dashboard"))

    announcement = Announcement.query.get_or_404(announcement_id)

    if announcement.posted_by == session["user_id"]:
        db.session.delete(announcement)
        db.session.commit()

    return redirect(url_for("announcements"))


# =========================================================
# Real-Time In-App Notification Center & APIs
# =========================================================

@app.route("/api/notifications", methods=["GET"])
def api_get_notifications():
    if "logged_in" not in session:
        return jsonify({"logged_in": False, "unread_count": 0, "notifications": []})

    user_id = session["user_id"]
    unread_count = Notification.query.filter_by(user_id=user_id, is_read=False).count()
    recent = Notification.query.filter_by(user_id=user_id).order_by(
        Notification.created_at.desc()
    ).limit(15).all()

    data = []
    for n in recent:
        data.append({
            "id": n.id,
            "title": n.title,
            "message": n.message,
            "category": n.category,
            "link": n.link or "#",
            "is_read": n.is_read,
            "is_emergency": n.is_emergency,
            "time_ago": n.time_ago,
            "created_at": n.created_at.strftime("%b %d, %H:%M") if n.created_at else "Recently"
        })

    return jsonify({
        "logged_in": True,
        "unread_count": unread_count,
        "notifications": data
    })


@app.route("/api/notifications/mark_read/<int:notif_id>", methods=["POST"])
def api_mark_notification_read(notif_id):
    if "logged_in" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    notif = Notification.query.filter_by(id=notif_id, user_id=session["user_id"]).first()
    if notif:
        notif.is_read = True
        db.session.commit()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Notification not found"}), 404


@app.route("/api/notifications/mark_all_read", methods=["POST"])
def api_mark_all_notifications_read():
    if "logged_in" not in session:
        return jsonify({"success": False, "error": "Not logged in"}), 401

    Notification.query.filter_by(user_id=session["user_id"], is_read=False).update(
        {"is_read": True}
    )
    db.session.commit()
    return jsonify({"success": True})


@app.route("/notifications")
@login_required
def notifications_view():
    user_id = session["user_id"]
    all_notifs = Notification.query.filter_by(user_id=user_id).order_by(
        Notification.created_at.desc()
    ).all()
    unread_count = sum(1 for n in all_notifs if not n.is_read)
    emergency_count = sum(1 for n in all_notifs if n.is_emergency)

    return render_template(
        "notifications.html",
        notifications=all_notifs,
        unread_count=unread_count,
        emergency_count=emergency_count,
        username=session["username"],
        role=session["role"]
    )


# =========================================================
# Emergency Alert Broadcast & SOS APIs
# =========================================================

@app.route("/emergency/alerts")
@app.route("/emergency")
def emergency_alerts():
    active_alert = EmergencyAlert.query.filter_by(active=True).order_by(
        EmergencyAlert.created_at.desc()
    ).first()
    past_alerts = EmergencyAlert.query.filter_by(active=False).order_by(
        EmergencyAlert.created_at.desc()
    ).limit(10).all()
    return render_template(
        "emergency_alerts.html",
        active_alert=active_alert,
        past_alerts=past_alerts,
        logged_in="logged_in" in session,
        username=session.get("username"),
        role=session.get("role")
    )


@app.route("/api/emergency/active", methods=["GET"])
def api_active_emergency():
    """Returns the current active municipal emergency alert if any."""
    alert = EmergencyAlert.query.filter_by(active=True).order_by(
        EmergencyAlert.created_at.desc()
    ).first()

    if not alert:
        return jsonify({"active": False})

    return jsonify({
        "active": True,
        "id": alert.id,
        "title": alert.title,
        "message": alert.message,
        "severity": alert.severity,
        "helpline": alert.helpline,
        "created_at": alert.created_at.strftime("%b %d, %H:%M") if alert.created_at else "Active"
    })


@app.route("/municipal/emergency", methods=["GET", "POST"])
@login_required
@role_required("municipal")
def municipal_emergency():
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        message = (request.form.get("message") or "").strip()
        severity = request.form.get("severity") or "Critical Hazard"
        helpline = (request.form.get("helpline") or "112 / 108 / 1800-CIVIC-ALERT").strip()

        if not title or not message:
            flash("Please specify both title and detailed instructions for the Emergency Broadcast.", "warning")
            return redirect(url_for("municipal_emergency"))

        # Deactivate previous active emergency
        EmergencyAlert.query.filter_by(active=True).update({
            "active": False,
            "resolved_at": utcnow_naive()
        })

        new_alert = EmergencyAlert(
            title=title,
            message=message,
            severity=severity,
            helpline=helpline,
            active=True,
            created_by=session["user_id"],
            created_at=utcnow_naive()
        )
        db.session.add(new_alert)
        db.session.commit()

        # Broadcast urgent alert to all citizens and NGOs
        broadcast_emergency_notification(title=title, message=message, helpline=helpline)

        flash("🚨 EMERGENCY BROADCAST ACTIVATED! Marquee sirens and push alerts dispatched site-wide.", "danger")
        return redirect(url_for("municipal_emergency"))

    active_alert = EmergencyAlert.query.filter_by(active=True).order_by(
        EmergencyAlert.created_at.desc()
    ).first()

    past_alerts = EmergencyAlert.query.filter_by(active=False).order_by(
        EmergencyAlert.created_at.desc()
    ).limit(10).all()

    # Emergency SOS complaints filed by citizens
    sos_complaints = Complaint.query.filter_by(is_emergency=True).order_by(
        Complaint.id.desc()
    ).all()

    return render_template(
        "municipal/emergency.html",
        active_alert=active_alert,
        past_alerts=past_alerts,
        sos_complaints=sos_complaints,
        username=session["username"]
    )


@app.route("/municipal/emergency/deactivate/<int:alert_id>", methods=["POST"])
@login_required
@role_required("municipal")
def municipal_emergency_deactivate(alert_id):
    alert = EmergencyAlert.query.get_or_404(alert_id)
    alert.active = False
    alert.resolved_at = utcnow_naive()
    db.session.commit()

    # Broadcast All-Clear Notification to all users
    users = User.query.all()
    for u in users:
        create_notification(
            user_id=u.id,
            title="🟢 All-Clear: Emergency Alert Lifted",
            message=f"Municipal Authority has deactivated the emergency alert: '{alert.title}'. Safe conditions restored.",
            category="emergency",
            link="/notifications",
            is_emergency=False
        )

    flash("Emergency broadcast deactivated. 'All-Clear' notice sent to all users.", "success")
    return redirect(url_for("municipal_emergency"))


# ==========================
# Short Routes
# ==========================
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/citizen")
def citizen():
    return redirect(url_for("auth", role="citizen"))


@app.route("/ngo")
def ngo():
    return redirect(url_for("auth", role="ngo"))


@app.route("/municipal")
def municipal():
    return redirect(url_for("auth", role="municipal"))


@app.route("/api/db-status")
def api_db_status():
    """Healthcheck endpoint to verify database connectivity and engine type."""
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({
            "status": "connected",
            "engine": db.engine.name,
            "database": "postgresql" if db.engine.name == "postgresql" else "sqlite"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500


with app.app_context():
    try:
        db.session.execute(text("SELECT 1"))
        engine_type = db.engine.name.upper()
        print("==================================================")
        print(f"[OK] SQL DATABASE CONNECTED SUCCESSFULLY!")
        print(f"     Database Engine: {engine_type}")
        print("==================================================")
    except Exception as e:
        print("==================================================")
        print(f"[ERROR] DATABASE CONNECTION FAILED: {e}")
        print("==================================================")

    db.create_all()
    migrate_database_schema()


if __name__ == "__main__":
    app.run(debug=True)