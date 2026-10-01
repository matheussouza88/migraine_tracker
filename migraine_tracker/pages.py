import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func, select

from migraine_tracker.database import (
    MedicationLog,
    MigraineEpisode,
    db,
    ensure_utc,
)

bp = Blueprint("pages", __name__)
logger = logging.getLogger("migraine_tracker.activity")


def _get_active_episode():
    return db.session.scalars(
        select(MigraineEpisode)
        .where(MigraineEpisode.end_time.is_(None))
        .order_by(MigraineEpisode.start_time.desc())
        .limit(1)
    ).first()


@bp.route("/health")
def health():
    """Healthcheck endpoint for Consul and monitoring probes."""
    return jsonify({"status": "healthy", "service": "migraine_tracker"}), 200


@bp.route("/")
def home():
    active_episode = _get_active_episode()
    history = db.session.scalars(
        select(MigraineEpisode)
        .where(MigraineEpisode.end_time.isnot(None))
        .order_by(MigraineEpisode.start_time.desc())
        .limit(30)
    ).all()

    medications = db.session.scalars(
        select(MedicationLog).order_by(MedicationLog.timestamp.desc()).limit(30)
    ).all()

    stats_stmt = select(
        func.count(MigraineEpisode.id),
        func.coalesce(func.sum(MigraineEpisode.duration_seconds), 0),
        func.coalesce(func.avg(MigraineEpisode.duration_seconds), 0),
    ).where(MigraineEpisode.end_time.isnot(None))

    total_episodes, total_seconds, avg_seconds = db.session.execute(stats_stmt).one()

    total_meds = db.session.scalar(select(func.count(MedicationLog.id))) or 0

    logger.info(
        "Home page accessed: active_episode=%s, total_history=%d, total_meds=%d",
        bool(active_episode),
        total_episodes,
        total_meds,
    )

    return render_template(
        "pages/home.html",
        active_episode=active_episode,
        history=history,
        medications=medications,
        total_episodes=total_episodes,
        avg_seconds=int(avg_seconds),
        total_medications=total_meds,
    )


@bp.route("/api/status", methods=["GET"])
def get_status():
    active_episode = _get_active_episode()
    now_utc = datetime.now(timezone.utc)
    if active_episode:
        start_time = ensure_utc(active_episode.start_time)
        elapsed = int((now_utc - start_time).total_seconds())
        logger.debug(
            "Status queried: is_active=True, episode_id=%d, elapsed=%ds",
            active_episode.id,
            elapsed,
        )
        return jsonify(
            {
                "is_active": True,
                "episode": active_episode.to_dict(),
                "elapsed_seconds": max(0, elapsed),
                "server_time": now_utc.isoformat(),
            }
        )

    logger.debug("Status queried: is_active=False")
    return jsonify(
        {
            "is_active": False,
            "episode": None,
            "elapsed_seconds": 0,
            "server_time": now_utc.isoformat(),
        }
    )


@bp.route("/api/start", methods=["POST"])
def start_episode():
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    active_episode = _get_active_episode()
    if active_episode:
        logger.warning(
            "Episode start ignored: Episode #%d is already in progress "
            "(started at %s, client: %s)",
            active_episode.id,
            active_episode.start_time.isoformat(),
            client_ip,
        )
        return (
            jsonify(
                {
                    "message": "Migraine episode already in progress.",
                    "episode": active_episode.to_dict(),
                }
            ),
            200,
        )

    payload = request.get_json(silent=True) or {}
    severity = payload.get("severity", "moderate")
    notes = payload.get("notes")

    new_episode = MigraineEpisode(
        start_time=datetime.now(timezone.utc),
        severity=severity,
        notes=notes,
    )
    db.session.add(new_episode)
    db.session.commit()
    logger.info(
        "Migraine episode #%d STARTED at %s (client: %s)",
        new_episode.id,
        new_episode.start_time.isoformat(),
        client_ip,
    )
    return (
        jsonify(
            {
                "message": "Migraine episode started!",
                "episode": new_episode.to_dict(),
            }
        ),
        201,
    )


@bp.route("/api/finish", methods=["POST"])
def finish_episode():
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    active_episode = _get_active_episode()
    if not active_episode:
        logger.warning(
            "Episode finish rejected: No active episode in progress (client: %s)",
            client_ip,
        )
        return jsonify({"error": "No active migraine episode to finish."}), 400

    now_utc = datetime.now(timezone.utc)
    active_episode.end_time = now_utc
    start_time = ensure_utc(active_episode.start_time)
    duration = int((now_utc - start_time).total_seconds())
    active_episode.duration_seconds = max(0, duration)

    payload = request.get_json(silent=True) or {}
    if "notes" in payload:
        active_episode.notes = payload["notes"]
    if "severity" in payload:
        active_episode.severity = payload["severity"]

    db.session.commit()

    logger.info(
        "Migraine episode #%d FINISHED: duration=%ds (%s -> %s, client: %s)",
        active_episode.id,
        active_episode.duration_seconds,
        active_episode.start_time.isoformat(),
        active_episode.end_time.isoformat(),
        client_ip,
    )
    return (
        jsonify(
            {
                "message": "Migraine episode ended successfully!",
                "episode": active_episode.to_dict(),
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
    episodes = db.session.scalars(
        select(MigraineEpisode)
        .where(MigraineEpisode.end_time.isnot(None))
        .order_by(MigraineEpisode.start_time.desc())
        .limit(100)
    ).all()
    medications = db.session.scalars(
        select(MedicationLog).order_by(MedicationLog.timestamp.desc()).limit(100)
    ).all()

    return jsonify(
        {
            "episodes": [e.to_dict() for e in episodes],
            "medications": [m.to_dict() for m in medications],
        }
    )


@bp.route("/api/history/episode/<int:episode_id>", methods=["DELETE"])
def delete_episode(episode_id):
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "-")
    episode = db.session.get(MigraineEpisode, episode_id)
    if not episode:
        logger.warning(
            "Delete rejected: Episode #%d not found (client: %s)",
            episode_id,
            client_ip,
        )
        return jsonify({"error": "Episode not found."}), 404

    db.session.delete(episode)
    db.session.commit()
    logger.info("Migraine episode #%d DELETED (client: %s)", episode_id, client_ip)
    return jsonify({"message": "Episode deleted successfully.", "id": episode_id}), 200


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
        jsonify({"message": "Medication entry deleted successfully.", "id": med_id}),
        200,
    )
