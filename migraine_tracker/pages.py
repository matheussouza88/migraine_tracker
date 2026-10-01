import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func, select

from migraine_tracker.database import MedicationLog, MigraineCheckup, db

bp = Blueprint("pages", __name__)
logger = logging.getLogger("migraine_tracker.activity")

VALID_SEVERITIES = {"mild", "moderate", "severe"}


@bp.route("/health")
def health():
    """Healthcheck endpoint for Consul and monitoring probes."""
    return jsonify({"status": "healthy", "service": "migraine_tracker"}), 200


@bp.route("/")
def home():
    migraines = db.session.scalars(
        select(MigraineCheckup).order_by(MigraineCheckup.timestamp.desc()).limit(30)
    ).all()

    medications = db.session.scalars(
        select(MedicationLog).order_by(MedicationLog.timestamp.desc()).limit(30)
    ).all()

    total_migraines = db.session.scalar(select(func.count(MigraineCheckup.id))) or 0
    total_meds = db.session.scalar(select(func.count(MedicationLog.id))) or 0

    last_migraine = migraines[0] if migraines else None
    last_medication = medications[0] if medications else None

    logger.info(
        "Home page accessed: total_migraines=%d, total_meds=%d",
        total_migraines,
        total_meds,
    )

    return render_template(
        "pages/home.html",
        migraines=migraines,
        medications=medications,
        total_migraines=total_migraines,
        total_medications=total_meds,
        last_migraine=last_migraine,
        last_medication=last_medication,
    )


@bp.route("/api/status", methods=["GET"])
def get_status():
    last_migraine = db.session.scalars(
        select(MigraineCheckup).order_by(MigraineCheckup.timestamp.desc()).limit(1)
    ).first()

    last_med = db.session.scalars(
        select(MedicationLog).order_by(MedicationLog.timestamp.desc()).limit(1)
    ).first()

    total_migraines = db.session.scalar(select(func.count(MigraineCheckup.id))) or 0
    total_meds = db.session.scalar(select(func.count(MedicationLog.id))) or 0

    now_utc = datetime.now(timezone.utc)
    return jsonify(
        {
            "last_migraine": (last_migraine.to_dict() if last_migraine else None),
            "last_medication": last_med.to_dict() if last_med else None,
            "total_migraines": total_migraines,
            "total_medications": total_meds,
            "server_time": now_utc.isoformat(),
        }
    )


@bp.route("/api/migraine", methods=["POST"])
def log_migraine():
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    payload = request.get_json(silent=True) or {}
    raw_severity = (payload.get("severity") or "moderate").strip().lower()

    if raw_severity not in VALID_SEVERITIES:
        return (
            jsonify(
                {
                    "error": (
                        "Invalid severity level. "
                        "Must be 'mild', 'moderate', or 'severe'."
                    )
                }
            ),
            400,
        )

    notes = payload.get("notes")

    checkup = MigraineCheckup(
        timestamp=datetime.now(timezone.utc),
        severity=raw_severity,
        notes=notes,
    )
    db.session.add(checkup)
    db.session.commit()

    logger.info(
        "Migraine checkup #%d LOGGED at %s (severity=%s, client: %s)",
        checkup.id,
        checkup.timestamp.isoformat(),
        raw_severity,
        client_ip,
    )

    return (
        jsonify(
            {
                "message": "Migraine checkup recorded successfully!",
                "checkup": checkup.to_dict(),
            }
        ),
        201,
    )


@bp.route("/api/migraine/<int:migraine_id>", methods=["PATCH", "PUT"])
def update_migraine(migraine_id):
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    entry = db.session.get(MigraineCheckup, migraine_id)
    if not entry:
        logger.warning(
            "Update rejected: Migraine entry #%d not found (client: %s)",
            migraine_id,
            client_ip,
        )
        return jsonify({"error": "Migraine checkup entry not found."}), 404

    payload = request.get_json(silent=True) or {}
    if "severity" in payload:
        raw_severity = (payload.get("severity") or "").strip().lower()
        if raw_severity not in VALID_SEVERITIES:
            return (
                jsonify(
                    {
                        "error": (
                            "Invalid severity level. "
                            "Must be 'mild', 'moderate', or 'severe'."
                        )
                    }
                ),
                400,
            )
        entry.severity = raw_severity

    if "notes" in payload:
        entry.notes = payload.get("notes")

    db.session.commit()
    logger.info(
        "Migraine checkup #%d UPDATED: severity=%s (client: %s)",
        migraine_id,
        entry.severity,
        client_ip,
    )

    return (
        jsonify(
            {
                "message": "Migraine severity updated successfully!",
                "checkup": entry.to_dict(),
            }
        ),
        200,
    )


@bp.route("/api/medication", methods=["POST"])
def log_medication():
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    data = request.get_json(silent=True) or {}
    med_type = (data.get("medication_type") or "").strip()

    valid_types = {
        "painkiller": "Painkiller",
        "sumatriptan": "Sumatriptan",
    }

    normalized_type = valid_types.get(med_type.lower())
    if not normalized_type:
        return (
            jsonify(
                {
                    "error": (
                        "Invalid medication type. "
                        "Must be 'painkiller' or 'sumatriptan'."
                    )
                }
            ),
            400,
        )

    log_entry = MedicationLog(
        timestamp=datetime.now(timezone.utc),
        medication_type=normalized_type,
        dosage=data.get("dosage"),
        notes=data.get("notes"),
    )
    db.session.add(log_entry)
    db.session.commit()

    logger.info(
        "Medication %s logged at %s (id=%d, client: %s)",
        normalized_type,
        log_entry.timestamp.isoformat(),
        log_entry.id,
        client_ip,
    )

    return (
        jsonify(
            {
                "message": f"{normalized_type} intake recorded successfully!",
                "entry": log_entry.to_dict(),
            }
        ),
        201,
    )


@bp.route("/api/history", methods=["GET"])
def get_history():
    migraines = db.session.scalars(
        select(MigraineCheckup).order_by(MigraineCheckup.timestamp.desc()).limit(100)
    ).all()
    medications = db.session.scalars(
        select(MedicationLog).order_by(MedicationLog.timestamp.desc()).limit(100)
    ).all()

    return jsonify(
        {
            "migraines": [m.to_dict() for m in migraines],
            "medications": [m.to_dict() for m in medications],
        }
    )


@bp.route("/api/history/migraine/<int:migraine_id>", methods=["DELETE"])
def delete_migraine(migraine_id):
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    entry = db.session.get(MigraineCheckup, migraine_id)
    if not entry:
        logger.warning(
            "Delete rejected: Migraine entry #%d not found (client: %s)",
            migraine_id,
            client_ip,
        )
        return jsonify({"error": "Migraine checkup entry not found."}), 404

    db.session.delete(entry)
    db.session.commit()
    logger.info("Migraine checkup #%d DELETED (client: %s)", migraine_id, client_ip)
    return (
        jsonify(
            {
                "message": "Migraine checkup deleted successfully.",
                "id": migraine_id,
            }
        ),
        200,
    )


@bp.route("/api/history/medication/<int:med_id>", methods=["DELETE"])
def delete_medication(med_id):
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    med = db.session.get(MedicationLog, med_id)
    if not med:
        logger.warning(
            "Delete rejected: Medication entry #%d not found (client: %s)",
            med_id,
            client_ip,
        )
        return jsonify({"error": "Medication entry not found."}), 404

    db.session.delete(med)
    db.session.commit()
    logger.info("Medication log #%d DELETED (client: %s)", med_id, client_ip)
    return (
        jsonify(
            {
                "message": "Medication entry deleted successfully.",
                "id": med_id,
            }
        ),
        200,
    )
