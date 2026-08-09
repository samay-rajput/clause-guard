"""Draft review: async job + SSE progress (the pipeline's own progress
callbacks), synchronous mode for tests, PDF/text upload extraction."""
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from sse_starlette.sse import EventSourceResponse

from .. import domain, jobs, settings
from ..authcore import get_current_user
from ..limits import LLM_LIMIT, limiter
from ..schemas import ReviewRequest

router = APIRouter(prefix="/api", tags=["review"])


def _run_review(req: ReviewRequest, username: str):
    def work(progress):
        out = domain.run_full_review(req.draft, req.top_k, username,
                                     source=req.source, progress=progress)
        return domain.review_payload(out)
    return work


@router.post("/review")
@limiter.limit(LLM_LIMIT)
def review(request: Request, req: ReviewRequest, sync: bool = False,
           user: dict = Depends(get_current_user)):
    work = _run_review(req, user["username"])
    if sync:                                   # tests + scripted use
        return work(lambda m: None)
    return {"job_id": jobs.submit(work, owner=user["username"], kind="review")}


@router.get("/jobs/{job_id}")
def job_status(job_id: str, user: dict = Depends(get_current_user)):
    job = jobs.get(job_id, owner=user["username"])
    if not job:
        raise HTTPException(404, "unknown job")
    return {"id": job["id"], "kind": job["kind"], "status": job["status"],
            "messages": job["messages"],
            "result": job["result"] if job["status"] == "done" else None,
            "error": job["error"]}


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, user: dict = Depends(get_current_user)):
    return EventSourceResponse(jobs.sse_events(job_id, owner=user["username"]))


@router.post("/drafts/extract-text")
async def extract_text(file: UploadFile, user: dict = Depends(get_current_user)):
    blob = await file.read()
    if len(blob) > settings.UPLOAD_MAX_BYTES:
        raise HTTPException(413, "file too large")
    name = (file.filename or "upload").lower()
    if blob[:5] == b"%PDF-":                       # magic bytes, not extension
        import io
        import pdfplumber
        try:
            with pdfplumber.open(io.BytesIO(blob)) as pdf:
                text = "\n\n".join((p.extract_text() or "") for p in pdf.pages).strip()
        except Exception as e:
            raise HTTPException(422, f"could not parse PDF: {e}")
        warning = (None if text else
                   "No text layer found — if it is a scanned GR, paste the text instead.")
        return {"text": text, "warning": warning}
    if name.endswith(".pdf"):
        raise HTTPException(422, "file claims .pdf but is not a PDF")
    if not (name.endswith(".txt") or name.endswith(".md")):
        raise HTTPException(415, "only .txt, .md or .pdf drafts are accepted")
    return {"text": blob.decode("utf-8", errors="replace"), "warning": None}
