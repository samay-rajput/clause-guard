"""API configuration. Secrets come from the environment; the JWT signing key is
generated once and persisted locally so restarts do not invalidate sessions."""
import os
import secrets

from .paths import ROOT

DATA_DIR = ROOT / "data"

ACCESS_TOKEN_MINUTES = int(os.environ.get("CG_ACCESS_MINUTES", "15"))
REFRESH_TOKEN_DAYS = int(os.environ.get("CG_REFRESH_DAYS", "7"))
JWT_ALG = "HS256"

# Vite dev server + same-origin production build
CORS_ORIGINS = [o for o in os.environ.get(
    "CG_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",") if o]

UPLOAD_MAX_BYTES = int(os.environ.get("CG_UPLOAD_MAX_BYTES", str(5 * 1024 * 1024)))

from pathlib import Path as _Path

USERS_DB = _Path(os.environ.get("CG_USERS_DB", DATA_DIR / "users.db"))
_SECRET_FILE = DATA_DIR / "api_jwt_secret.key"


def jwt_secret() -> str:
    env = os.environ.get("CG_JWT_SECRET")
    if env:
        return env
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text(encoding="ascii").strip()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s = secrets.token_hex(32)
    _SECRET_FILE.write_text(s, encoding="ascii")
    return s


# Demo seed accounts (role -> env var holding the password). A missing env var
# gets a generated password printed ONCE at seed time — never a hardcoded one.
SEED_USERS = {
    "drafter": {"role": "drafter", "pw_env": "CG_DRAFTER_PW"},
    "reviewer": {"role": "reviewer", "pw_env": "CG_REVIEWER_PW"},
}
