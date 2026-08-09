"""Audit trail (FR-15), now per-user: each account has its own append-only
JSONL; a reviewer may read any user's trail, a drafter only their own."""
from fastapi import APIRouter, Depends, HTTPException, Response

from .. import domain
from ..authcore import get_current_user

router = APIRouter(prefix="/api/audit", tags=["audit"])


def _resolve_user(user: dict, for_user: str | None) -> str:
    if for_user and for_user != user["username"]:
        if user["role"] != "reviewer":
            raise HTTPException(403, "Only a reviewer can read other users' trails")
        return for_user
    return user["username"]


@router.get("/runs")
def runs(for_user: str | None = None, offset: int = 0, limit: int = 50,
         user: dict = Depends(get_current_user)):
    records = domain.audit_runs(_resolve_user(user, for_user))
    total = len(records)
    page = records[::-1][offset:offset + max(1, min(limit, 200))]  # newest first
    return {"total": total, "offset": offset,
            "with_edits": sum(1 for r in records if r.get("human_edit")),
            "runs": page}


@router.get("/export")
def export(fmt: str = "jsonl", for_user: str | None = None,
           user: dict = Depends(get_current_user)):
    username = _resolve_user(user, for_user)
    if fmt == "csv":
        return Response(domain.to_csv(domain.audit_runs(username)),
                        media_type="text/csv",
                        headers={"Content-Disposition":
                                 'attachment; filename="audit_trail.csv"'})
    if fmt != "jsonl":
        raise HTTPException(400, "fmt must be jsonl|csv")
    p = domain.trail_path(username)
    return Response(p.read_bytes() if p.exists() else b"",
                    media_type="application/jsonl",
                    headers={"Content-Disposition":
                             'attachment; filename="audit_trail.jsonl"'})
