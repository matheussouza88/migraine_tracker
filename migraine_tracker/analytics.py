from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from migraine_tracker.database import MedicationLog, MigraineCheckup, ensure_utc

TIME_PERIODS = [
    ("early_morning", "Early Morning (05-09h)", 5, 9),
    ("morning", "Morning (09-12h)", 9, 12),
    ("afternoon", "Afternoon (12-17h)", 12, 17),
    ("evening", "Evening (17-22h)", 17, 22),
    ("night", "Night (22-05h)", None, None),
]

DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def classify_time_of_day(hour: int) -> str:
    if 5 <= hour < 9:
        return "Early Morning (05-09h)"
    elif 9 <= hour < 12:
        return "Morning (09-12h)"
    elif 12 <= hour < 17:
        return "Afternoon (12-17h)"
    elif 17 <= hour < 22:
        return "Evening (17-22h)"
    else:
        return "Night (22-05h)"


def calculate_analytics(
    migraines: List[MigraineCheckup],
    medications: List[MedicationLog],
    now_utc: datetime = None,
) -> Dict[str, Any]:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    else:
        now_utc = ensure_utc(now_utc)

    total_migraines = len(migraines)
    total_meds = len(medications)

    # Sort migraines chronologically (oldest to newest)
    sorted_migraines = sorted(
        migraines,
        key=lambda m: ensure_utc(m.timestamp)
        or datetime.min.replace(tzinfo=timezone.utc),
    )

    # Severity distribution
    sev_counter = Counter((m.severity or "moderate").strip().lower() for m in migraines)
    severity_counts = {
        "mild": sev_counter.get("mild", 0),
        "moderate": sev_counter.get("moderate", 0),
        "severe": sev_counter.get("severe", 0),
    }

    # Medication distribution
    med_counter = Counter((m.medication_type or "").strip() for m in medications)
    medication_counts = {
        "Painkiller": med_counter.get("Painkiller", 0),
        "Sumatriptan": med_counter.get("Sumatriptan", 0),
    }

    # Time of Day distribution
    tod_counter = Counter(
        classify_time_of_day(ensure_utc(m.timestamp).hour) for m in migraines
    )
    time_of_day_breakdown = [
        {
            "key": key,
            "label": label,
            "count": tod_counter.get(label, 0),
            "percentage": (
                round((tod_counter.get(label, 0) / total_migraines) * 100)
                if total_migraines > 0
                else 0
            ),
        }
        for key, label, _, _ in TIME_PERIODS
    ]

    most_common_tod = (
        max(time_of_day_breakdown, key=lambda x: x["count"])["label"]
        if total_migraines > 0
        else "N/A"
    )

    # Day of week distribution
    dow_counter = Counter(
        DAYS_OF_WEEK[ensure_utc(m.timestamp).weekday()] for m in migraines
    )
    day_of_week_breakdown = [
        {"day": d, "count": dow_counter.get(d, 0)} for d in DAYS_OF_WEEK
    ]

    # Date intervals & metrics
    first_dt = ensure_utc(sorted_migraines[0].timestamp) if sorted_migraines else None
    last_dt = ensure_utc(sorted_migraines[-1].timestamp) if sorted_migraines else None

    days_since_last = None
    if last_dt:
        days_since_last = max(0, (now_utc - last_dt).days)

    # Intervals between consecutive episodes
    intervals = []
    longest_streak_days = 0
    if len(sorted_migraines) > 1:
        for i in range(1, len(sorted_migraines)):
            prev_ts = ensure_utc(sorted_migraines[i - 1].timestamp)
            curr_ts = ensure_utc(sorted_migraines[i].timestamp)
            diff_days = (curr_ts - prev_ts).days
            intervals.append(diff_days)
            if diff_days > longest_streak_days:
                longest_streak_days = diff_days

    avg_interval_days = round(sum(intervals) / len(intervals), 1) if intervals else None

    # Monthly aggregation combining migraines and medications
    monthly_data: Dict[str, Dict[str, Any]] = {}

    for m in migraines:
        dt = ensure_utc(m.timestamp)
        key = dt.strftime("%Y-%m")
        label = dt.strftime("%b %Y")
        if key not in monthly_data:
            monthly_data[key] = {
                "month": key,
                "label": label,
                "migraines": 0,
                "medications": 0,
            }
        monthly_data[key]["migraines"] += 1

    for med in medications:
        dt = ensure_utc(med.timestamp)
        key = dt.strftime("%Y-%m")
        label = dt.strftime("%b %Y")
        if key not in monthly_data:
            monthly_data[key] = {
                "month": key,
                "label": label,
                "migraines": 0,
                "medications": 0,
            }
        monthly_data[key]["medications"] += 1

    sorted_months = sorted(monthly_data.values(), key=lambda x: x["month"])

    # Calculate average migraines per active month
    num_active_months = len(monthly_data)
    avg_per_month = (
        round(total_migraines / num_active_months, 1) if num_active_months > 0 else 0.0
    )

    meds_per_migraine = (
        round(total_meds / total_migraines, 1) if total_migraines > 0 else 0.0
    )

    most_common_severity = (
        max(severity_counts.items(), key=lambda x: x[1])[0].capitalize()
        if total_migraines > 0
        else "N/A"
    )

    # Max count in monthly trend for relative scaling
    max_monthly_count = (
        max(
            [max(m["migraines"], m["medications"]) for m in sorted_months],
            default=1,
        )
        if sorted_months
        else 1
    )

    return {
        "summary": {
            "total_migraines": total_migraines,
            "total_medications": total_meds,
            "days_since_last": days_since_last,
            "avg_per_month": avg_per_month,
            "meds_per_migraine": meds_per_migraine,
            "most_common_severity": most_common_severity,
            "most_common_time_of_day": most_common_tod,
            "longest_streak_days": longest_streak_days,
            "avg_interval_days": avg_interval_days,
            "first_migraine_date": first_dt.isoformat() if first_dt else None,
            "last_migraine_date": last_dt.isoformat() if last_dt else None,
        },
        "severity_counts": severity_counts,
        "medication_counts": medication_counts,
        "time_of_day_breakdown": time_of_day_breakdown,
        "day_of_week_breakdown": day_of_week_breakdown,
        "monthly_trend": sorted_months,
        "max_monthly_count": max_monthly_count,
    }
