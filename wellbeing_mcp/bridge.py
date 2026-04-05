"""
wellbeing-bridge — HTTP server that receives Apple Health data
from the Health Auto Export iOS app and writes it to the local SQLite DB.

Runs persistently as a systemd user service on port 8765.
The iPhone app POSTs health data to http://10.0.0.226:8765/health
"""

import json
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
from . import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("wellbeing-bridge")

app = FastAPI(title="wellbeing-bridge", docs_url=None, redoc_url=None)

db.init_db()


@app.post("/health")
async def receive_health_data(request: Request):
    """
    Endpoint for Health Auto Export webhook.
    Receives Apple Health metrics and workouts, stores them in SQLite.
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    logger.info("Received Health Auto Export payload")

    try:
        ingested = db.ingest_apple_health(payload)
        logger.info(f"Ingested: {ingested}")
        return JSONResponse({"status": "ok", "ingested": ingested})
    except Exception as e:
        logger.exception("Error ingesting Apple Health data")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status")
async def status():
    """Health check — returns latest weight and last workout."""
    latest_weight = db.get_latest_weight()
    last_workout = db.get_last_workout()
    return {
        "status": "ok",
        "latest_weight": latest_weight,
        "last_workout": last_workout,
        "calories_today": db.get_calories_today(),
    }


@app.get("/snapshot")
async def snapshot():
    """Return the current wellbeing snapshot as plain text."""
    return {"snapshot": db.build_current_snapshot()}


if __name__ == "__main__":
    uvicorn.run(
        "wellbeing_mcp.bridge:app",
        host="0.0.0.0",
        port=8765,
        log_level="info",
    )
