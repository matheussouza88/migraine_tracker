import logging
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
logger = logging.getLogger("migraine_tracker.database")


def ensure_utc(dt):
    """Normalize datetime to UTC-aware datetime.

    If dt is naive (e.g. from SQLite), attach timezone.utc.
    If dt is aware (e.g. from PostgreSQL), convert to UTC.
    If dt is None, return None.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class MigraineEpisode(db.Model):
    __tablename__ = "migraine_episodes"

    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    end_time = db.Column(db.DateTime(timezone=True), nullable=True, index=True)
    duration_seconds = db.Column(db.Integer, nullable=True)
    severity = db.Column(db.String(50), nullable=True, default="moderate")
    notes = db.Column(db.String(255), nullable=True)

    def to_dict(self):
        st = ensure_utc(self.start_time)
        et = ensure_utc(self.end_time)
        return {
            "id": self.id,
            "start_time": st.isoformat() if st else None,
            "end_time": et.isoformat() if et else None,
            "duration_seconds": self.duration_seconds,
            "severity": self.severity,
            "notes": self.notes,
            "is_active": self.end_time is None,
        }


class MedicationLog(db.Model):
    __tablename__ = "medication_logs"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    medication_type = db.Column(db.String(64), nullable=False)
    dosage = db.Column(db.String(64), nullable=True)
    notes = db.Column(db.String(255), nullable=True)

    def to_dict(self):
        ts = ensure_utc(self.timestamp)
        return {
            "id": self.id,
            "timestamp": ts.isoformat() if ts else None,
            "medication_type": self.medication_type,
            "dosage": self.dosage,
            "notes": self.notes,
        }


def init_app(app):
    db.init_app(app)
    with app.app_context():
        logger.info("Synchronizing database schema tables...")
        db.create_all()
        logger.info("Database schema synchronized successfully.")
