"""
Keycloak OIDC integration for the gateway.

Validates Bearer tokens against Keycloak's JWKS, extracts realm-roles, and
maps them onto the QOS-Buddy `Role` enum. Caches JWKS for 5 minutes.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from jose import jwt
from jose.exceptions import JWTError

from contracts.schemas import Role

log = logging.getLogger("qos.gateway.auth")

DEMO_MODE = os.getenv("GATEWAY_DEMO_MODE", "false").lower() in ("1", "true", "yes")
_DEMO_ROLE_MAP: dict[str, Role] = {
    "noc_viewer": Role.NOC_VIEWER,
    "noc_executive": Role.NOC_EXECUTIVE,
    "ai_engineer": Role.AI_ENGINEER,
    "site_admin": Role.SITE_ADMIN,
}


def demo_principal(token: str) -> Principal | None:
    """Return a synthetic Principal for demo tokens of the form `demo:<role>`.

    Only available when GATEWAY_DEMO_MODE=true. Returns None for non-demo tokens.
    """
    if not DEMO_MODE:
        return None
    if not token.startswith("demo:"):
        return None
    role_str = token[5:].strip().lower()
    role = _DEMO_ROLE_MAP.get(role_str, Role.NOC_VIEWER)
    return Principal(
        sub=f"demo-{role_str}",
        username=f"demo-{role_str}",
        email=None,
        role=role,
        raw_roles=(role.value,),
    )

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://keycloak:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "qos-buddy")
KEYCLOAK_AUDIENCE = os.getenv("KEYCLOAK_AUDIENCE", "qos-buddy-shell")
# Browser-facing issuer baked into tokens. The gateway must validate the
# token's `iss` claim against the URL the browser used to log in
# (e.g. http://localhost:8081/...), not the internal docker hostname.
KEYCLOAK_ISSUER = os.getenv(
    "KEYCLOAK_ISSUER",
    f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}",
)
# Internal URL used to fetch JWKS from inside the docker network.
KEYCLOAK_INTERNAL_URL = os.getenv("KEYCLOAK_INTERNAL_URL", KEYCLOAK_URL)
KEYCLOAK_JWKS_URL = (
    f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}"
    f"/protocol/openid-connect/certs"
)
JWKS_TTL_SECONDS = 300


@dataclass(frozen=True)
class Principal:
    sub: str
    username: str
    email: str | None
    role: Role
    raw_roles: tuple[str, ...]


class _JwksCache:
    def __init__(self) -> None:
        self._keys: list[dict[str, Any]] | None = None
        self._fetched_at: float = 0.0

    async def get(self, http: httpx.AsyncClient) -> list[dict[str, Any]]:
        now = time.time()
        if self._keys is not None and (now - self._fetched_at) < JWKS_TTL_SECONDS:
            return self._keys
        resp = await http.get(KEYCLOAK_JWKS_URL, timeout=5.0)
        resp.raise_for_status()
        self._keys = resp.json().get("keys", [])
        self._fetched_at = now
        log.info(
            "refreshed jwks keys=%d url=%s issuer=%s",
            len(self._keys),
            KEYCLOAK_JWKS_URL,
            KEYCLOAK_ISSUER,
        )
        return self._keys


_jwks = _JwksCache()


_ROLE_PRIORITY: tuple[Role, ...] = (
    Role.SITE_ADMIN,
    Role.AI_ENGINEER,
    Role.NOC_EXECUTIVE,
    Role.NOC_VIEWER,
)


def _select_role(realm_roles: list[str]) -> Role:
    available = {r.lower() for r in realm_roles}
    for role in _ROLE_PRIORITY:
        if role.value in available:
            return role
    return Role.NOC_VIEWER


async def verify_token(token: str, http: httpx.AsyncClient) -> Principal:
    """Validate a Keycloak access token and return the principal.

    Raises JWTError on any failure — caller maps to HTTP 401.
    """
    keys = await _jwks.get(http)
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise JWTError(f"malformed token header: {exc}") from exc

    kid = unverified_header.get("kid")
    key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        # forced refresh in case Keycloak rotated keys
        _jwks._fetched_at = 0.0  # noqa: SLF001
        keys = await _jwks.get(http)
        key = next((k for k in keys if k.get("kid") == kid), None)
    if key is None:
        raise JWTError("signing key not found in JWKS")

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[unverified_header.get("alg", "RS256")],
            audience=KEYCLOAK_AUDIENCE,
            issuer=KEYCLOAK_ISSUER,
            options={"verify_at_hash": False},
        )
    except JWTError as exc:
        raise JWTError(f"token rejected: {exc}") from exc

    realm_roles = list(claims.get("realm_access", {}).get("roles", []))
    role = _select_role(realm_roles)

    return Principal(
        sub=str(claims.get("sub", "")),
        username=str(claims.get("preferred_username", "")),
        email=claims.get("email"),
        role=role,
        raw_roles=tuple(realm_roles),
    )
