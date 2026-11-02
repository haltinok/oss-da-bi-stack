"""A small client for the parts of Keycloak's admin REST API the console uses.

It signs in as the `admin-console` client (client-credentials, a service account that holds only the realm-management roles it needs), keeps the token until just before it
expires, and turns every Keycloak refusal into a KeycloakError with a message a person can read. Everything returns plain dicts, so the tests swap this class for a fake.
"""
from __future__ import annotations

import time

import httpx


class KeycloakError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Keycloak:
    def __init__(self, base: str, realm: str, client_id: str, client_secret: str, timeout: float = 10.0):
        self.base, self.realm = base.rstrip("/"), realm
        self.client_id, self.client_secret = client_id, client_secret
        self.http = httpx.Client(timeout=timeout)
        self._token, self._expires = "", 0.0

    # ---------------------------------------------------------------------------------------------------------------- plumbing
    def _bearer(self) -> str:
        if time.time() > self._expires - 20:
            r = self.http.post(f"{self.base}/realms/{self.realm}/protocol/openid-connect/token",
                               data={"grant_type": "client_credentials", "client_id": self.client_id, "client_secret": self.client_secret})
            if r.status_code != 200:
                raise KeycloakError(502, "the console cannot sign in to Keycloak (check ADMIN_CLIENT_SECRET)")
            body = r.json()
            self._token, self._expires = body["access_token"], time.time() + body.get("expires_in", 60)
        return self._token

    def _call(self, method: str, path: str, *, params=None, json=None, ok=(200, 201, 204)):
        try:
            r = self.http.request(method, f"{self.base}/admin/realms/{self.realm}{path}", params=params, json=json, headers={"Authorization": f"Bearer {self._bearer()}"})
        except httpx.HTTPError as exc:
            raise KeycloakError(502, f"Keycloak is not reachable: {exc}") from exc
        if r.status_code not in ok:
            try:
                body = r.json()
                msg = body.get("errorMessage") or body.get("error") or r.text
            except ValueError:
                msg = r.text
            raise KeycloakError(404 if r.status_code == 404 else 409 if r.status_code == 409 else 400 if r.status_code == 400 else 502, msg[:300] or f"Keycloak answered {r.status_code}")
        return r

    def _json(self, method: str, path: str, **kw):
        return self._call(method, path, **kw).json()

    # ---------------------------------------------------------------------------------------------------------------- users
    def users(self, search: str = "", enabled: bool | None = None, limit: int = 1000) -> list[dict]:
        params = {"max": limit, **({"search": search} if search else {}), **({"enabled": str(enabled).lower()} if enabled is not None else {})}
        return self._json("GET", "/users", params=params)

    def user(self, uid: str) -> dict:
        return self._json("GET", f"/users/{uid}")

    def create_user(self, rep: dict) -> str:
        r = self._call("POST", "/users", json=rep)
        return r.headers["Location"].rsplit("/", 1)[-1]

    def update_user(self, uid: str, rep: dict) -> None:
        self._call("PUT", f"/users/{uid}", json=rep)

    def delete_user(self, uid: str) -> None:
        self._call("DELETE", f"/users/{uid}")

    def logout(self, uid: str) -> None:
        self._call("POST", f"/users/{uid}/logout")

    def set_password(self, uid: str, password: str, temporary: bool) -> None:
        self._call("PUT", f"/users/{uid}/reset-password", json={"type": "password", "value": password, "temporary": temporary})

    def email_update_password(self, uid: str) -> None:
        self._call("PUT", f"/users/{uid}/execute-actions-email", json=["UPDATE_PASSWORD"])

    # ---------------------------------------------------------------------------------------------------------------- roles
    def role(self, name: str) -> dict:
        return self._json("GET", f"/roles/{name}")

    def role_members(self, name: str) -> list[dict]:
        return self._json("GET", f"/roles/{name}/users", params={"max": 1000})

    def add_role(self, uid: str, name: str) -> None:
        self._call("POST", f"/users/{uid}/role-mappings/realm", json=[self.role(name)])

    def remove_role(self, uid: str, name: str) -> None:
        self._call("DELETE", f"/users/{uid}/role-mappings/realm", json=[self.role(name)])

    # ---------------------------------------------------------------------------------------------------------------- groups
    def groups(self) -> list[dict]:
        return self._json("GET", "/groups", params={"max": 1000, "briefRepresentation": "true"})

    def group_members(self, gid: str) -> list[dict]:
        return self._json("GET", f"/groups/{gid}/members", params={"max": 1000})

    def create_group(self, name: str) -> str:
        r = self._call("POST", "/groups", json={"name": name})
        return r.headers["Location"].rsplit("/", 1)[-1]

    def rename_group(self, gid: str, name: str) -> None:
        self._call("PUT", f"/groups/{gid}", json={"name": name})

    def delete_group(self, gid: str) -> None:
        self._call("DELETE", f"/groups/{gid}")

    def add_to_group(self, uid: str, gid: str) -> None:
        self._call("PUT", f"/users/{uid}/groups/{gid}")

    def remove_from_group(self, uid: str, gid: str) -> None:
        self._call("DELETE", f"/users/{uid}/groups/{gid}")
