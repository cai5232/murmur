"""Authenticated deployment entry point for the native Murmur API."""
import base64
import hmac
import json
import os
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

import api
from engine import DATA, _atomic_write
from examples.unanswered_signals import outreach_after, user_active_since

app = api.app
engine = api.engine
engine.unanswered_signals = {
    "outreach_after": outreach_after,
    "user_active_since": user_active_since,
}


@app.middleware("http")
async def authenticate(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    supplied = request.headers.get("authorization", "")
    token = os.environ.get("MURMUR_INTERNAL_TOKEN", "")
    allowed = bool(token) and hmac.compare_digest(supplied, "Bearer " + token)
    if supplied.startswith("Basic "):
        try:
            credentials = base64.b64decode(supplied[6:], validate=True).decode()
            user = os.environ.get("MURMUR_DASHBOARD_USER", "")
            password = os.environ.get("MURMUR_DASHBOARD_PASSWORD", "")
            allowed = bool(user and password) and hmac.compare_digest(credentials, user + ":" + password)
        except (ValueError, UnicodeError):
            allowed = False
    if not allowed:
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="Murmur"'})
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok", "engine": "murmur", "character": engine.character,
            "version": "native-aria-v1", "dimensions": list(engine.dims)}


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/docs")


class Signal(BaseModel):
    ts: float | None = Field(default=None, ge=0, allow_inf_nan=False)


def signal_time(signal):
    now = time.time()
    ts = signal.ts if signal.ts is not None else now
    if ts > now + 5:
        raise HTTPException(400, "activity timestamp must not be in the future")
    return ts


@app.post("/emotion/presence")
def presence(signal: Signal):
    ts = signal_time(signal)
    path = DATA / "presence.json"
    with engine.lock:
        old = json.loads(path.read_text()).get("last_active_ts", 0) if path.exists() else 0
        _atomic_write(path, json.dumps({"last_active_ts": max(old, ts)}))
    return {"ok": True}


@app.post("/emotion/outreach")
def outreach(signal: Signal):
    from datetime import datetime, timezone
    ts = signal_time(signal)
    with engine.lock:
        with (DATA / "outreach_log.jsonl").open("a") as handle:
            handle.write(json.dumps({"ts": datetime.fromtimestamp(ts, timezone.utc).isoformat()}) + "\n")
    return {"ok": True}
