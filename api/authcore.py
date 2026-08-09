"""Authentication core: Argon2 password hashing (pwdlib), PyJWT access tokens,
rotating opaque refresh tokens stored hashed in SQLite (stdlib sqlite3 — no ORM
for two tables). FastAPI dependencies at the bottom."""
import datetime as dt
import hashlib
import os
import secrets
import sqlite3
import threading

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from pwdlib import PasswordHash

from . import settings

_pwd = PasswordHash.recommended()          # argon2id
_db_lock = threading.Lock()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

REFRESH_COOKIE = "cg_refresh"


def _db() -> sqlite3.Connection:
    settings.USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(settings.USERS_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS users(
        username TEXT PRIMARY KEY, pw_hash TEXT NOT NULL, role TEXT NOT NULL,
        created TEXT NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS refresh_tokens(
        token_sha TEXT PRIMARY KEY, username TEXT NOT NULL,
        expires TEXT NOT NULL)""")
    return con


def seed_users() -> None:
    """Create the demo accounts on first boot. Passwords come from env vars;
    a generated one is printed exactly once so it is never stored in code."""
    with _db_lock, _db() as con:
        for name, spec in settings.SEED_USERS.items():
            if con.execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone():
                continue
            pw = os.environ.get(spec["pw_env"])
            if not pw:
                pw = secrets.token_urlsafe(9)
                print(f"[auth] seeded user '{name}' (role {spec['role']}) "
                      f"password: {pw}  — set {spec['pw_env']} to control this",
                      flush=True)
            con.execute("INSERT INTO users VALUES(?,?,?,?)",
                        (name, _pwd.hash(pw), spec["role"],
                         dt.datetime.now(dt.timezone.utc).isoformat()))


def verify_login(username: str, password: str):
    with _db_lock, _db() as con:
        row = con.execute("SELECT pw_hash, role FROM users WHERE username=?",
                          (username,)).fetchone()
    if not row or not _pwd.verify(password, row[0]):
        return None
    return {"username": username, "role": row[1]}


def make_access_token(user: dict) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {"sub": user["username"], "role": user["role"], "iat": now,
         "exp": now + dt.timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)},
        settings.jwt_secret(), algorithm=settings.JWT_ALG)


def _sha(t: str) -> str:
    return hashlib.sha256(t.encode()).hexdigest()


def issue_refresh_token(username: str) -> str:
    token = secrets.token_urlsafe(48)
    exp = (dt.datetime.now(dt.timezone.utc)
           + dt.timedelta(days=settings.REFRESH_TOKEN_DAYS)).isoformat()
    with _db_lock, _db() as con:
        con.execute("INSERT INTO refresh_tokens VALUES(?,?,?)",
                    (_sha(token), username, exp))
    return token


def rotate_refresh_token(token: str):
    """Validate + revoke the presented token, return (user, new_token) or None."""
    with _db_lock, _db() as con:
        row = con.execute(
            "SELECT username, expires FROM refresh_tokens WHERE token_sha=?",
            (_sha(token),)).fetchone()
        if not row:
            return None
        con.execute("DELETE FROM refresh_tokens WHERE token_sha=?", (_sha(token),))
        if dt.datetime.fromisoformat(row[1]) < dt.datetime.now(dt.timezone.utc):
            return None
        urow = con.execute("SELECT role FROM users WHERE username=?",
                           (row[0],)).fetchone()
    if not urow:
        return None
    user = {"username": row[0], "role": urow[0]}
    return user, issue_refresh_token(row[0])


def revoke_refresh_token(token: str) -> None:
    with _db_lock, _db() as con:
        con.execute("DELETE FROM refresh_tokens WHERE token_sha=?", (_sha(token),))


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    if not token:
        raise HTTPException(401, "Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, settings.jwt_secret(),
                             algorithms=[settings.JWT_ALG])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token",
                            headers={"WWW-Authenticate": "Bearer"})
    return {"username": payload["sub"], "role": payload.get("role", "drafter")}


def require_reviewer(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "reviewer":
        raise HTTPException(403, "Reviewer role required")
    return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
