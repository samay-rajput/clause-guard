"""Request models. Responses stay as the domain layer's dicts — FastAPI's
encoder handles dates; re-modelling every payload would just drift."""
from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    draft: str = Field(min_length=1, max_length=200_000)
    top_k: int = Field(default=10, ge=2, le=16)
    source: str = Field(default="review", max_length=40)


class PrefillRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)
    lang: str = Field(default="mr", pattern="^(mr|en)$")


class PreviewRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)
    k: int = Field(default=4, ge=1, le=8)


class AutodraftRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=500)
    lang: str = Field(default="mr", pattern="^(mr|en)$")


class GenerateRequest(BaseModel):
    form: dict                       # full gr_form (form rail) or flat fields (AI path)
    use_ai: bool = False
    brief: str = Field(default="", max_length=4000)
    n_clauses: int = Field(default=3, ge=2, le=6)
    record: bool = True              # append to the audit trail as source="generate"


class ApplyFixRequest(BaseModel):
    form: dict
    value1: str = Field(min_length=1, max_length=300)
    value2: str = Field(min_length=1, max_length=300)


class ExportAuthenticRequest(BaseModel):
    form: dict | None = None
    draft: str | None = Field(default=None, max_length=200_000)


class ExportDraftRequest(BaseModel):
    draft: str = Field(min_length=1, max_length=200_000)


class ExportReportRequest(BaseModel):
    score: dict | None = None
    terms: dict | None = None
    refs: dict | None = None
    review: dict | None = None
