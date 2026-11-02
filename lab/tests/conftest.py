import os
import pathlib
import sys

os.environ.setdefault("KEYCLOAK_ISSUER", "http://kc/realms/spike")
os.environ.setdefault("KEYCLOAK_JWKS_URL", "http://kc/certs")
ROOT = pathlib.Path(__file__).resolve().parents[2]
os.environ.setdefault("LAB_MODEL_DIR", str(ROOT / "cube" / "model"))
sys.path.insert(0, str(ROOT / "dashboards"))                    # dashspec, for the schema browser
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
