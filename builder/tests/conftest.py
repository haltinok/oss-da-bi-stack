import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
for p in (REPO, REPO / "dashboards"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
