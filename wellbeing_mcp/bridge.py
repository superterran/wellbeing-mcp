"""
wellbeing-bridge — HTTP server that receives Apple Health data
from the Health Auto Export iOS app and writes it to the vault.

Runs persistently as a systemd user service on port 8765.
The iPhone app POSTs health data to http://10.0.0.226:8765/health

Raw payloads are stored in SQLite (apple_health_raw) for reference.
Parsed metrics are written directly to markdown daily notes via daily.py.
"""

import logging
from datetime import date, datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from . import db
from . import daily

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("wellbeing-bridge")

app = FastAPI(title="wellbeing-bridge", docs_url=None, redoc_url=None)

db.init_db()


def _parse_health_payload(payload: dict) -> dict:
    """
    Parse a Health Auto Export webhook payload and extract key metrics.
    Returns a dict with what was ingested.
    """
    ingested = {}

    # Weight (Body Mass)
    metrics = payload.get("data", {}).get("metrics", [])
    for metric in metrics:
        name = metric.get("name", "").lower()
        datapoints = metric.get("data", [])

        if name in ("body_mass", "weight_body_mass") and datapoints:
            for point in datapoints:
                qty = point.get("qty")
                date_str = point.get("date", "")
                unit = metric.get("units", "").lower()
                if qty and date_str:
                    try:
                        d = datetime.fromisoformat(date_str[:10]).date()
                        # Health Auto Export reports in kg by default; convert if needed
                        weight_lbs = float(qty)
                        if "kg" in unit or "kilogram" in unit:
                            weight_lbs = round(float(qty) * 2.20462, 1)
                        daily.log_weight(weight_lbs, d=d)
                        ingested["weight_lbs"] = weight_lbs
                        ingested["weight_date"] = str(d)
                    except (ValueError, TypeError):
                        logger.warning(f"Could not parse weight entry: {point}")

    # Workouts
    workouts = payload.get("data", {}).get("workouts", [])
    for workout in workouts:
        workout_type = workout.get("workoutActivityType", "").replace("HKWorkoutActivityType", "").lower()
        duration_sec = workout.get("duration")
        start_str = workout.get("startDate", "")
        try:
            d = datetime.fromisoformat(start_str[:10]).date() if start_str else date.today()
        except (ValueError, TypeError):
            d = date.today()
        duration_min = int(duration_sec / 60) if duration_sec else None
        if workout_type:
            daily.log_workout_to_daily(workout_type, duration_min, d=d)
            ingested.setdefault("workouts", []).append({
                "type": workout_type,
                "duration_min": duration_min,
                "date": str(d),
            })

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
    profile = db.get_profile()
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
