"""ClauseGuard API — FastAPI application.

Run:  uvicorn api.main:app --port 8000
The React build (web/dist) is served from / when present; /api/* is the JSON
surface. Heavy artifacts warm in the lifespan, off the request path — the
frontend polls /api/health until status == "ready".
"""
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from . import authcore, domain, settings
from .limits import limiter
from .paths import ROOT
from .routers import audit, auth_routes, core, export, generate, review

WARM = {"status": "warming", "detail": {}}


def _warm():
    try:
        WARM["detail"] = domain.warm()
        WARM["status"] = "ready"
    except Exception as e:
        WARM["detail"] = {"error": str(e)}
        WARM["status"] = "degraded"


@asynccontextmanager
async def _lifespan(app):
    authcore.seed_users()
    threading.Thread(target=_warm, daemon=True, name="cg-warm").start()
    yield


app = FastAPI(title="ClauseGuard API", version="3.0", lifespan=_lifespan,
              docs_url="/api/docs", openapi_url="/api/openapi.json")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS,
                   allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"])

for r in (auth_routes, core, review, generate, export, audit):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    """Unauthenticated: warm state + mode badges the UI shows pre-login."""
    from pipeline import muril_available
    out = {"status": WARM["status"], "warm": WARM["detail"],
           "llm_mode": domain.LLM_MODE, "muril_on": muril_available(),
           "models": {"ollama": domain.OLLAMA_MODEL, "groq": domain.GROQ_MODEL,
                      "gemini": domain.GEMINI_MODEL}}
    if WARM["status"] == "ready":
        s = domain.corpus_stats()
        out["corpus"] = {"n_grs": s["n_grs"], "n_clauses": s["n_clauses"],
                         "index_mismatch": s["index_mismatch"]}
    return out


# React production build. StaticFiles(html=True) does NOT fall back to
# index.html for client-side routes like /login — the catch-all below does.
# It is registered after every router, so /api/* keeps priority.
_dist = ROOT / "web" / "dist"
if _dist.exists():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        f = _dist / full_path
        if full_path and ".." not in full_path and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
