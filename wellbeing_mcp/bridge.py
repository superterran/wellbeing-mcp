"""
wellbeing-bridge — HTTP server that receives Apple Health data
from the Health Auto Export iOS app and writes it to the vault.

Runs persistently as a systemd user service on port 8765.
The iPhone app POSTs health data to http://10.0.0.226:8765/health

Raw payloads are stored in SQLite (apple_health_raw) for reference.
Parsed metrics are written directly to markdown daily notes via daily.py.
"""

import logging
import os
from datetime import date, datetime

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import daily, db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("wellbeing-bridge")

# Shared secret for the public webhook. When set (it is, in the closet deploy),
# every POST to /health must present ?token=<value> or an X-Webhook-Token header.
# Left empty for LAN-only / local dev, where the endpoint stays unauthenticated.
BRIDGE_TOKEN = os.environ.get("WELLBEING_BRIDGE_TOKEN", "")

app = FastAPI(title="wellbeing-bridge", docs_url=None, redoc_url=None)

db.init_db()


def _date_from_str(date_str: str) -> date:
    try:
        return datetime.fromisoformat(date_str[:10]).date()
    except (ValueError, TypeError):
        return date.today()


def _latest_by_date(datapoints: list) -> dict[date, float]:
    """Reduce a list of {date, qty} points to one value per calendar day (last wins)."""
    by_day: dict[date, float] = {}
    for point in datapoints:
        qty = point.get("qty")
        date_str = point.get("date", "")
        if qty is not None and date_str:
            d = _date_from_str(date_str)
            by_day[d] = float(qty)
    return by_day


def _extract_sleep_hours(point: dict) -> float | None:
    """Pull total asleep hours from a Health Auto Export sleep_analysis point.

    HAE's sleep shape has drifted across versions; try the aggregate fields
    first, fall back to summing stages, then to a bare qty.
    """
    for key in ("totalSleep", "asleep"):
        v = point.get(key)
        if v is not None:
            return float(v)
    stage_vals = [float(point[k]) for k in ("core", "deep", "rem") if point.get(k) is not None]
    if stage_vals:
        return round(sum(stage_vals), 2)
    qty = point.get("qty")
    return float(qty) if qty is not None else None


def _parse_health_payload(payload: dict) -> dict:
    """
    Parse a Health Auto Export webhook payload and write metrics to daily notes.
    Returns a summary dict of what was ingested.
    """
    ingested: dict = {}

    # Collect all metric data keyed by metric name
    metrics = payload.get("data", {}).get("metrics", [])
    metric_map: dict[str, tuple[list, str]] = {}
    for metric in metrics:
        name = metric.get("name", "").lower()
        metric_map[name] = (metric.get("data", []), metric.get("units", "").lower())

    # --- Weight (Body Mass) ---
    for weight_key in ("body_mass", "weight_body_mass"):
        if weight_key in metric_map:
            datapoints, unit = metric_map[weight_key]
            by_day = _latest_by_date(datapoints)
            for d, qty in by_day.items():
                weight_lbs = qty
                if "kg" in unit or "kilogram" in unit:
                    weight_lbs = round(qty * 2.20462, 1)
                try:
                    daily.log_weight(weight_lbs, d=d)
                    ingested.setdefault("weight", []).append({"date": str(d), "lbs": weight_lbs})
                except Exception:
                    logger.exception(f"Failed to log weight for {d}")

    # --- Per-day Apple Health metrics ---
    # For each metric, collect one representative value per day and write together
    # to avoid creating/saving the daily note once per metric.
    metric_fields = {
        "resting_heart_rate": "resting_heart_rate",
        "heart_rate_variability": "hrv",
        "step_count": "steps",
        "active_energy": "active_calories",
        "vo2_max": "vo2_max",
        "blood_oxygen_saturation": "blood_oxygen",
        "cardio_recovery": "cardio_recovery",
    }

    # Build a per-day dict of {field: value}
    day_metrics: dict[date, dict] = {}
    for metric_name, field in metric_fields.items():
        if metric_name not in metric_map:
            continue
        datapoints, _ = metric_map[metric_name]
        by_day = _latest_by_date(datapoints)
        for d, qty in by_day.items():
            day_metrics.setdefault(d, {})[field] = qty

    # --- Sleep (Health Auto Export "sleep_analysis") ---
    if "sleep_analysis" in metric_map:
        datapoints, _ = metric_map["sleep_analysis"]
        sleep_by_day: dict[date, float] = {}
        for point in datapoints:
            hours = _extract_sleep_hours(point)
            date_str = point.get("date") or point.get("sleepEnd") or ""
            if hours is not None and date_str:
                d = _date_from_str(date_str)
                sleep_by_day[d] = round(hours, 2)
        for d, hours in sleep_by_day.items():
            day_metrics.setdefault(d, {})["sleep_hours"] = hours

    for d, fields in day_metrics.items():
        # Convert step_count and active_energy to int
        if "steps" in fields:
            fields["steps"] = int(fields["steps"])
        if "active_calories" in fields:
            fields["active_calories"] = int(fields["active_calories"])
        try:
            daily.log_apple_health_metrics(d=d, **fields)
            ingested.setdefault("health_metrics", []).append({"date": str(d), **fields})
        except Exception:
            logger.exception(f"Failed to log health metrics for {d}")

    # --- Workouts ---
    workouts = payload.get("data", {}).get("workouts", [])
    for workout in workouts:
        workout_type = (
            workout.get("workoutActivityType", "")
            .replace("HKWorkoutActivityType", "")
            .lower()
            .strip()
        )
        duration_sec = workout.get("duration")
        start_str = workout.get("startDate", "")
        d = _date_from_str(start_str) if start_str else date.today()
        duration_min = int(float(duration_sec) / 60) if duration_sec else None
        if workout_type:
            try:
                daily.log_workout_to_daily(workout_type, duration_min, d=d)
                ingested.setdefault("workouts", []).append(
                    {
                        "type": workout_type,
                        "duration_min": duration_min,
                        "date": str(d),
                    }
                )
            except Exception:
                logger.exception(f"Failed to log workout for {d}")

    return ingested


@app.post("/health")
async def receive_health_data(request: Request):
    """
    Endpoint for Health Auto Export webhook.
    Receives Apple Health metrics and writes them to daily notes.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if BRIDGE_TOKEN:
        supplied = request.query_params.get("token") or request.headers.get(
            "x-webhook-token", ""
        )
        if supplied != BRIDGE_TOKEN:
            raise HTTPException(status_code=401, detail="Unauthorized")

    logger.info("Received Health Auto Export payload")

    # Always store raw payload for reference
    db.store_apple_health_raw(payload)

    try:
        ingested = _parse_health_payload(payload)
        logger.info(f"Ingested: {ingested}")
        return JSONResponse({"status": "ok", "ingested": ingested})
    except Exception as e:
        logger.exception("Error ingesting Apple Health data")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def status():
    """Health check — returns latest weight and last workout."""
    return {
        "status": "ok",
        "latest_weight": daily.get_latest_weight(),
        "last_workout": daily.get_last_workout_info(),
        "calories_today": daily.get_calories_today(),
    }


@app.get("/snapshot")
async def snapshot():
    """Return the current wellbeing snapshot as plain text."""
    profile = db.get_profile()
    return {"snapshot": daily.build_current_snapshot(profile)}


if __name__ == "__main__":
    uvicorn.run(
        "wellbeing_mcp.bridge:app",
        host="0.0.0.0",
        port=8765,
        log_level="info",
    )
