"""JWT authentication. Validates issuer, audience, expiry, and tenant claim."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import HTTPException, Request, status

from gateway.settings import Settings


@dataclass(frozen=True)
class Principal:
    tenant_id: str
    subject: str
    scopes: frozenset[str]


def authenticate(request: Request, settings: Settings) -> Principal:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")

    token = auth.split(" ", 1)[1].strip()
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from exc

    tenant_id = claims.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing tenant_id claim"
        )

    return Principal(
        tenant_id=str(tenant_id),
        subject=str(claims.get("sub", "anonymous")),
        scopes=frozenset(claims.get("scopes", [])),
    )
