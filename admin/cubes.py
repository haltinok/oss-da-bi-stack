"""The cubes of the Cube model (names, descriptions, how many members): what a dataset is made of. Read once from the model files the image carries."""
from __future__ import annotations

import os

_cache: list[dict] | None = None


def cubes() -> list[dict]:
    global _cache
    if _cache is None:
        try:
            from dashspec import catalog as cat
            c = cat.from_model(os.environ.get("ADMIN_MODEL_DIR", "/app/cube-model"))
            _cache = [{"name": n, "description": v.get("description", ""), "measures": len(v["measures"]), "dimensions": len(v["dimensions"]),
                       "fields": [{"name": m, "kind": "measure"} for m in sorted(v["measures"])] + [{"name": d, "kind": "dimension"} for d in sorted(v["dimensions"])]} for n, v in sorted(c.cubes.items())]
        except (ImportError, SystemExit, OSError):
            _cache = []
    return _cache
