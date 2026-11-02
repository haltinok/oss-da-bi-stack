import os
import pathlib
import sys

os.environ.setdefault("KEYCLOAK_ISSUER", "http://kc/realms/spike")
os.environ.setdefault("KEYCLOAK_JWKS_URL", "http://kc/certs")
os.environ.setdefault("ADMIN_CLIENT_SECRET", "x")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
