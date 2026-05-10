from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Header, HTTPException, status

from ..store.repos import SessionsRepo
from .settings import get_settings


ROLE_RANK = {"viewer": 1, "engineer": 2, "lead": 3}


@dataclass(frozen=True)
class Principal:
    token: str
    role: str

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)

    def at_least(self, required: str) -> bool:
        return self.rank >= ROLE_RANK.get(required, 99)


def resolve_principal(authorization: str | None) -> Principal | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return resolve_principal_from_token(token.strip())


def resolve_principal_from_token(token: str | None) -> Principal | None:
    if not token:
        return None
    role = get_settings().access.role_for(token.strip())
    if role is None:
        return None
    return Principal(token=token.strip(), role=role)


def resolve_principal_from_cookie(session_token: str | None) -> Principal | None:
    if not session_token:
        return None
    session = SessionsRepo.get_active(session_token, touch=True)
    if session is None:
        return None
    return Principal(token=str(session["principal_token"]), role=str(session["principal_role"]))


def session_cookie_name() -> str:
    return get_settings().api.session_cookie_name


def clear_session_cookie_kwargs() -> dict[str, object]:
    settings = get_settings()
    return {
        "key": settings.api.session_cookie_name,
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": settings.api.session_cookie_secure,
    }


def set_session_cookie_kwargs(session_id: str) -> dict[str, object]:
    if not session_id:
        raise ValueError("cannot set session cookie for an empty session id")
    settings = get_settings()
    return {
        "key": settings.api.session_cookie_name,
        "value": session_id,
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": settings.api.session_cookie_secure,
        "max_age": settings.api.session_ttl_s,
    }


def require_role(required: str) -> Callable[[str | None], Principal]:
    """FastAPI dependency factory enforcing a minimum role."""

    def dependency(authorization: str | None = Header(default=None)) -> Principal:
        principal = resolve_principal(authorization)
        if principal is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer token missing or invalid.",
                headers={"WWW-Authenticate": 'Bearer realm="qos_buddy"'},
            )
        if not principal.at_least(required):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{principal.role}' cannot perform this action (need '{required}').",
            )
        return principal

    return dependency


def optional_principal(authorization: str | None = Header(default=None)) -> Principal | None:
    """FastAPI dependency returning the principal if present, else None."""
    return resolve_principal(authorization)
