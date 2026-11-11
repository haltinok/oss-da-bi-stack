"""The cubes of every model the console serves (names, descriptions, how many members, and which model): what a dataset is made of. Read once from the model files (models.yml narrowed by $MODELS; ADMIN_MODEL_DIR names one model's folder instead, an older single-model setup). Cube names differ between models, so a dataset is a set of cube names whichever model they come from."""
from __future__ import annotations

import os

_cache: list[dict] | None = None


def _read(folder: str, model: str) -> list[dict]:
    from dashspec import catalog as cat
    c = cat.from_model(folder)
    return [{"name": n, "model": model, "description": v.get("description", ""), "measures": len(v["measures"]), "dimensions": len(v["dimensions"]),
             "fields": [{"name": m, "kind": "measure"} for m in sorted(v["measures"])] + [{"name": d, "kind": "dimension"} for d in sorted(v["dimensions"])]} for n, v in sorted(c.cubes.items())]


def cubes() -> list[dict]:
    global _cache
    if _cache is None:
        try:
            if os.environ.get("ADMIN_MODEL_DIR"):
                _cache = _read(os.environ["ADMIN_MODEL_DIR"], "")
            else:
                from dashspec import models
                try:
                    _cache = [c for m in models.served() for c in _read(str(m.dir), m.id)]
                except OSError:                                                       # no models.yml (an image run without its mount): the one model the image carries
                    _cache = _read("/app/cube-model", "")
        except (ImportError, SystemExit, OSError):
            _cache = []
    return _cache
