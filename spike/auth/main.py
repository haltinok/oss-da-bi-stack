"""Minimal auth service. Phase 0: health + config sanity only.

Phase 5 adds: validate the Keycloak token, look up the user's territories,
mint a short-lived Cube JWT {user_id, role, territories}.
"""
import os

from fastapi import FastAPI

app = FastAPI(title="spike-auth")

# Fail at startup, not at first request, if the shared secret is missing.
_ = os.environ["CUBEJS_API_SECRET"]


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
