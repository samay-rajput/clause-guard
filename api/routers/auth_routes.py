"""Login / refresh / logout. Access token in the JSON body (frontend memory
only); refresh token in an httpOnly cookie scoped to this router's path."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from .. import authcore, settings
from ..limits import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE_KW = dict(httponly=True, samesite="strict", path="/api/auth")


@router.post("/login")
@limiter.limit("5/minute")
def login(request: Request, response: Response,
          creds: OAuth2PasswordRequestForm = Depends()):
    user = authcore.verify_login(creds.username, creds.password)
    if not user:
        raise HTTPException(401, "Wrong username or password")
    response.set_cookie(authcore.REFRESH_COOKIE,
                        authcore.issue_refresh_token(user["username"]),
                        max_age=settings.REFRESH_TOKEN_DAYS * 86400, **_COOKIE_KW)
    return {"access_token": authcore.make_access_token(user),
            "token_type": "bearer", "user": user,
            "expires_minutes": settings.ACCESS_TOKEN_MINUTES}


@router.post("/refresh")
@limiter.limit("30/minute")
def refresh(request: Request, response: Response):
    token = request.cookies.get(authcore.REFRESH_COOKIE)
    rotated = authcore.rotate_refresh_token(token) if token else None
    if not rotated:
        response.delete_cookie(authcore.REFRESH_COOKIE, path="/api/auth")
        raise HTTPException(401, "Session expired — log in again")
    user, new_refresh = rotated
    response.set_cookie(authcore.REFRESH_COOKIE, new_refresh,
                        max_age=settings.REFRESH_TOKEN_DAYS * 86400, **_COOKIE_KW)
    return {"access_token": authcore.make_access_token(user),
            "token_type": "bearer", "user": user,
            "expires_minutes": settings.ACCESS_TOKEN_MINUTES}


@router.post("/logout")
def logout(request: Request, response: Response):
    if token := request.cookies.get(authcore.REFRESH_COOKIE):
        authcore.revoke_refresh_token(token)
    response.delete_cookie(authcore.REFRESH_COOKIE, path="/api/auth")
    return {"ok": True}
