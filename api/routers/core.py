"""Corpus stats, demo scenarios, glossary — cheap, deterministic reads."""
from fastapi import APIRouter, Depends, HTTPException

from .. import domain
from ..authcore import get_current_user
from ..paths import ROOT

router = APIRouter(prefix="/api", tags=["core"])


@router.get("/corpus/stats")
def corpus_stats(user: dict = Depends(get_current_user)):
    return domain.corpus_stats()


@router.get("/scenarios")
def scenarios(user: dict = Depends(get_current_user)):
    out = []
    for p in sorted((ROOT / "data" / "planted").glob("*.txt")):
        label, desc = domain.SCENARIO_LABELS.get(p.stem, (p.stem, ""))
        out.append({"id": p.stem, "label": label, "desc": desc})
    return out


@router.get("/scenarios/{scenario_id}")
def scenario_text(scenario_id: str, user: dict = Depends(get_current_user)):
    if "/" in scenario_id or "\\" in scenario_id or ".." in scenario_id:
        raise HTTPException(400, "bad scenario id")
    p = ROOT / "data" / "planted" / f"{scenario_id}.txt"
    if not p.exists():
        raise HTTPException(404, "unknown scenario")
    return {"id": scenario_id, "text": p.read_text(encoding="utf-8")}


@router.get("/glossary")
def glossary(q: str = "", user: dict = Depends(get_current_user)):
    rows = domain.load_glossary()
    if q:
        rows = [g for g in rows
                if q.lower() in g["en"].lower() or q in g["mr"]]
    return {"n": len(rows), "terms": rows}


@router.get("/sample-form")
def sample_form(lang: str = "mr", user: dict = Depends(get_current_user)):
    if lang not in ("mr", "en"):
        raise HTTPException(400, "lang must be mr|en")
    return domain.SAMPLE[lang]
