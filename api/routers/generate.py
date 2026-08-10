"""Drafting rail: instant precedent preview (no LLM), audited prefill,
autonomous topic→GR (job), form/brief generation, one-click conflict fix."""
from fastapi import APIRouter, Depends, HTTPException, Request

from pydantic import BaseModel, Field

from .. import domain, jobs
from ..authcore import get_current_user
from ..limits import LLM_LIMIT, limiter
from ..schemas import (ApplyFixRequest, AutodraftRequest, GenerateRequest,
                       PrefillRequest, PreviewRequest)

router = APIRouter(prefix="/api/generate", tags=["generate"])


class ChatEditRequest(BaseModel):
    form: dict
    message: str = Field(min_length=1, max_length=2000)


@router.get("/clause-templates")
def clause_templates(dept_code: str = "", k: int = 12,
                     user: dict = Depends(get_current_user)):
    """Canonical clause templates mined from the full corpus (verbatim
    government wording, per department)."""
    from prefill import templates_for
    return {"templates": templates_for(dept_code, k=max(1, min(k, 12)))}


@router.post("/chat-edit")
@limiter.limit(LLM_LIMIT)
def chat_edit(request: Request, req: ChatEditRequest,
              user: dict = Depends(get_current_user)):
    """Conversational editing: the LLM proposes form OPERATIONS, the server
    applies them under the digit/entity rails and re-renders deterministically.
    The chat can never write draft text directly."""
    from chatedit import chat_edit as run_chat_edit
    out = run_chat_edit(domain.coerce_date(req.form), req.message)
    if out.get("error"):
        raise HTTPException(502, out["error"])
    if g := out.get("generated"):
        out["score"] = domain.score(g["draft"])
        out["terms"] = domain.check_terminology(g["draft"])
        try:
            domain.audit_append(user["username"], g["draft"], score=out["score"],
                                terms=out["terms"], source="chat-edit")
        except Exception:
            pass
    return out


@router.post("/preview")
def preview(req: PreviewRequest, user: dict = Depends(get_current_user)):
    """Retrieval-only precedent cards for as-you-type feedback — no LLM call."""
    precedents = domain.retrieve_precedents(req.topic, corpus=domain.corpus(),
                                            k=req.k)
    for p in precedents:
        p["links"] = domain.links_for(p.get("gr_code")) or None
    return {"precedents": precedents}


@router.post("/prefill")
@limiter.limit(LLM_LIMIT)
def prefill(request: Request, req: PrefillRequest,
            user: dict = Depends(get_current_user)):
    out = domain.topic_prefill(req.topic, req.lang, corpus=domain.corpus())
    for p in out["form"].get("precedents", []):
        p["links"] = domain.links_for(p.get("gr_code")) or None
    return out


@router.post("/autodraft")
@limiter.limit(LLM_LIMIT)
def autodraft(request: Request, req: AutodraftRequest,
              user: dict = Depends(get_current_user)):
    corp = domain.corpus()
    username = user["username"]

    def _strip_bytes(obj):
        """Binary payloads never ride the JSON job result — exports are
        fetched from the export endpoints instead."""
        if isinstance(obj, dict):
            return {k: _strip_bytes(v) for k, v in obj.items()
                    if not isinstance(v, (bytes, bytearray))}
        if isinstance(obj, list):
            return [_strip_bytes(v) for v in obj
                    if not isinstance(v, (bytes, bytearray))]
        return obj

    def work(progress):
        res = domain.draft_gr(req.topic, req.lang, corpus=corp, progress=progress)
        res = _strip_bytes(res)
        if res.get("ok"):
            try:
                domain.audit_append(username, res["draft"],
                                    score=res.get("compliance"),
                                    terms=res.get("terminology"),
                                    source="autodraft")
            except Exception:
                pass
        return res

    return {"job_id": jobs.submit(work, owner=username, kind="autodraft")}


@router.post("")
@limiter.limit(LLM_LIMIT)
def generate(request: Request, req: GenerateRequest,
             user: dict = Depends(get_current_user)):
    form = domain.coerce_date(req.form)
    if req.use_ai:
        # legacy brief-expansion path: AI may write beyond the form, so no
        # structured gr_form is claimed — authentic export parses the flat text
        g_out = domain.generate_draft(form, use_ai=True, brief=req.brief,
                                      n_clauses=req.n_clauses)
        g_out.pop("form", None)
    else:
        g_out = domain.generate_from_form(form)
        if g_out.get("error"):
            raise HTTPException(422, {"error": g_out["error"],
                                      "blanks": g_out.get("blanks", [])})
    sc = domain.score(g_out["draft"])
    terms = domain.check_terminology(g_out["draft"])
    clauses = (g_out.get("form") or {}).get("clauses") or form.get("clauses") or []
    short = [c for c in clauses if len(str(c).strip()) < domain.MIN_CHARS]
    if req.record:
        try:
            domain.audit_append(user["username"], g_out["draft"], score=sc,
                                terms=terms, source="generate")
        except Exception:
            pass
    return {**g_out, "score": sc, "terms": terms, "short_clauses": short}


@router.post("/apply-fix")
def apply_fix(req: ApplyFixRequest, user: dict = Depends(get_current_user)):
    out = domain.apply_fix(domain.coerce_date(req.form), req.value1, req.value2)
    if out.get("error"):
        raise HTTPException(409, out["error"])
    try:
        domain.audit_append(user["username"], out["generated"]["draft"],
                            score=out["score"], terms=out["terms"],
                            source="apply-fix")
    except Exception:
        pass
    return out
