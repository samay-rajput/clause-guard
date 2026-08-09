"""DOCX/PDF exports, generated on demand. The authentic renderer is the
default; the plain writers and the review report ride along."""
from fastapi import APIRouter, Depends, HTTPException, Response

from .. import domain
from ..authcore import get_current_user
from ..schemas import (ExportAuthenticRequest, ExportDraftRequest,
                       ExportReportRequest)

router = APIRouter(prefix="/api/export", tags=["export"])

DOCX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document")


def _fmt(fmt: str):
    if fmt not in ("pdf", "docx"):
        raise HTTPException(400, "fmt must be pdf|docx")
    return fmt


def _file(content: bytes, name: str, fmt: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf" if fmt == "pdf" else DOCX_MIME,
        headers={"Content-Disposition":
                 f'attachment; filename="{name}.{fmt}"'})


@router.post("/authentic")
def authentic(req: ExportAuthenticRequest, fmt: str = "pdf",
              user: dict = Depends(get_current_user)):
    fmt = _fmt(fmt)
    if not (req.form or req.draft):
        raise HTTPException(422, "form or draft required")
    form = domain.coerce_date(req.form) if req.form else domain.parse_draft(req.draft)
    try:
        blob = domain.gr_pdf(form) if fmt == "pdf" else domain.gr_docx(form)
    except Exception as e:
        raise HTTPException(422, f"authentic render failed: {type(e).__name__}: {e}")
    return _file(blob, form.get("code") or "clauseguard_gr", fmt)


@router.post("/draft")
def draft(req: ExportDraftRequest, fmt: str = "pdf",
          user: dict = Depends(get_current_user)):
    fmt = _fmt(fmt)
    blob = (domain.draft_pdf(req.draft) if fmt == "pdf"
            else domain.draft_docx(req.draft))
    return _file(blob, "clauseguard_draft", fmt)


@router.post("/report")
def report(req: ExportReportRequest, fmt: str = "pdf",
           user: dict = Depends(get_current_user)):
    fmt = _fmt(fmt)
    kw = dict(score=req.score, terms=req.terms, refs=req.refs, review=req.review)
    blob = domain.report_pdf(**kw) if fmt == "pdf" else domain.report_docx(**kw)
    return _file(blob, "clauseguard_review_report", fmt)
