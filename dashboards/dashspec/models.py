"""The models a stack serves, from models.yml (PLAN-models.md): which Cube model folder and dashboards folder each one has. The first is the default model."""
import os
import pathlib
import re
from dataclasses import dataclass

import yaml

REPO = pathlib.Path(__file__).resolve().parents[2]
ID = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


@dataclass(frozen=True)
class Model:
    id: str
    label: str
    dir: pathlib.Path            # the Cube model folder
    dashboards: pathlib.Path     # the folder of the model's dashboard YAML
    cube: str                    # the compose service of its Cube

    @property
    def build(self) -> pathlib.Path:
        """Where `dashspec build` writes the compiled dashboards (committed: nginx serves them as they are)."""
        return self.dashboards / "build"

    @property
    def config_file(self) -> pathlib.Path:
        return self.dir.parent / "model.config.yml"


def load(path=None, base=None) -> list[Model]:
    """Every model of models.yml (`path`, else $MODELS_FILE, else the repo's); folders are relative to `base` (the file's own folder). Raises ValueError on a file that cannot be used."""
    file = pathlib.Path(path or os.environ.get("MODELS_FILE") or REPO / "models.yml")
    base = pathlib.Path(base) if base else file.parent
    raw = (yaml.safe_load(file.read_text(encoding="utf-8")) or {}).get("models")
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{file}: `models` must be a list with at least one model")
    out, seen = [], set()
    for i, m in enumerate(raw, 1):
        if not isinstance(m, dict) or not all(isinstance(m.get(k), str) and m[k] for k in ("id", "label", "dir", "dashboards", "cube")):
            raise ValueError(f"{file}: model {i} needs id, label, dir, dashboards and cube")
        if not ID.fullmatch(m["id"]) or m["id"] in seen:
            raise ValueError(f"{file}: model {i}: the id '{m['id']}' must be lower-case letters, digits, - and _ and used once")
        seen.add(m["id"])
        out.append(Model(m["id"], m["label"], base / m["dir"], base / m["dashboards"], m["cube"]))
    return out


def get(model_id: str | None, path=None) -> Model | None:
    """The model with this id; the default one for None or an empty id; None when there is no such model."""
    models = load(path)
    return models[0] if not model_id else next((m for m in models if m.id == model_id), None)


def default(path=None) -> Model:
    return load(path)[0]


def known(path=None) -> str:
    return ", ".join(m.id for m in load(path))
