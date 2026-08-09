"""Domain facade: every src/ import the API needs, plus the shared corpus
provider and the review orchestration that previously lived inside the
Streamlit app. Import order matters — paths first."""
import json
import re
import threading
from pathlib import Path

from . import paths  # noqa: F401  (sys.path setup — must precede src imports)
from .paths import ROOT

from clients import GEMINI_MODEL, GROQ_MODEL, LLM_MODE, OLLAMA_MODEL  # noqa: E402,F401
from build_source_urls import links_for  # noqa: E402,F401
from trail import append_run, load_runs, to_csv  # noqa: E402,F401
from writer import draft_docx, draft_pdf, report_docx, report_pdf  # noqa: E402,F401
from gr_layout import gr_docx, gr_pdf, parse_draft  # noqa: E402,F401
from generate import SAMPLE, generate as generate_draft, generate_from_form  # noqa: E402,F401
from chunk_clauses import MIN_CHARS  # noqa: E402,F401
from corpus_path import default_corpus_path  # noqa: E402,F401
from scorecard import score  # noqa: E402,F401
from glossary_check import check_terminology, load_glossary  # noqa: E402,F401
from citations import analyze_references  # noqa: E402,F401
from prefill import retrieve_precedents, topic_prefill  # noqa: E402,F401
from autodraft import draft_gr  # noqa: E402,F401

SCENARIO_LABELS = {
    "1_fee_conflict_draft": ("Scenario A — fee-reimbursement conflict",
                             "50% draft vs an in-force 100% GR: the planted contradiction"),
    "2_stale_reference_draft": ("Scenario B — outdated reference",
                                "cites a 2022 GR that has newer same-subject successors"),
    "3_broken_format_draft": ("Scenario C1 — broken format",
                              "missing Read block, bad date format → low scorecard"),
    "3_broken_format_FIXED": ("Scenario C2 — format fixed",
                              "same draft repaired → watch the score jump"),
}

_trail_lock = threading.Lock()          # single-writer: no torn JSONL lines
_corpus_cache = {"path": None, "mtime": None, "records": []}
_corpus_lock = threading.Lock()
_stats_cache = {}


def corpus() -> list:
    """The active corpus, reloaded only when the file's mtime moves."""
    p = default_corpus_path()
    if not p.exists():
        return []
    mtime = p.stat().st_mtime
    with _corpus_lock:
        if _corpus_cache["path"] != str(p) or _corpus_cache["mtime"] != mtime:
            _corpus_cache.update(
                path=str(p), mtime=mtime,
                records=[json.loads(l) for l in
                         p.read_text(encoding="utf-8").splitlines() if l.strip()])
            _stats_cache.clear()
        return _corpus_cache["records"]


def corpus_stats() -> dict:
    recs = corpus()
    key = (_corpus_cache["path"], _corpus_cache["mtime"])
    if _stats_cache.get("key") != key:
        depts = {}
        for r in recs:
            d = r.get("department") or "?"
            depts[d] = depts.get(d, 0) + 1
        mismatch = None
        try:
            from build_index import check_against_corpus
            if _corpus_cache["path"]:
                mismatch = check_against_corpus(Path(_corpus_cache["path"]))
        except Exception:
            pass
        _stats_cache.update(key=key, value={
            "n_grs": len(recs),
            "n_clauses": sum(len(r.get("clauses", [])) for r in recs),
            "departments": dict(sorted(depts.items(), key=lambda x: -x[1])),
            "corpus_name": Path(_corpus_cache["path"]).name if recs else None,
            "index_mismatch": mismatch,
        })
    return _stats_cache["value"]


def trail_path(username: str) -> Path:
    """Per-user audit trail — attribution and diff-against-own-previous, and no
    interleaving between users (the round-2 trail was one global file)."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", username)
    return ROOT / "data" / f"audit_trail_{safe}.jsonl"


def audit_append(username: str, draft: str, **kw) -> dict:
    with _trail_lock:
        return append_run(draft, path=trail_path(username), **kw)


def audit_runs(username: str) -> list:
    return load_runs(trail_path(username))


def run_full_review(draft_text: str, top_k: int, username: str,
                    source: str = "review", progress=None) -> dict:
    """The exact orchestration the Streamlit Review button ran: scorecard,
    terminology, references, conflict pipeline, audit-trail append."""
    out = {"score": score(draft_text),
           "terms": check_terminology(draft_text)}
    corp = corpus()
    if corp:
        out["refs"] = analyze_references(draft_text, corp)
    try:
        from pipeline import MAX_COSINE_DISTANCE, review_draft
        out["max_distance"] = MAX_COSINE_DISTANCE
        out["review"] = review_draft(draft_text, top_k=top_k, progress=progress)
    except Exception as e:
        out["review"] = {"error": str(e)}
    try:
        rec = audit_append(username, draft_text, score=out.get("score"),
                           terms=out.get("terms"), refs=out.get("refs"),
                           review=out.get("review"), source=source)
        out["audit_ts"] = rec.get("ts")
    except Exception as e:                     # a trail failure never kills a review
        out["audit_error"] = str(e)
    return out


def review_payload(out: dict) -> dict:
    """Strip the response for the wire: conflict cards keep meta/values/reason/
    explanation but drop nothing the UI needs; add source links server-side."""
    r = out.get("review") or {}
    if "error" not in r:
        for c in r.get("conflicts", []):
            c["links"] = links_for(c["meta"].get("gr_code")) or None
    if refs := out.get("refs"):
        for l in refs.get("linked", []):
            l["links"] = links_for(l["match"].get("gr_code")) or None
    return out


def apply_fix(gr_form: dict, value1: str, value2: str) -> dict:
    """Deterministic one-click fix (was apply_fix_to_form in the app): replace
    the draft's conflicting value in the ONE clause that carries it, regenerate
    through the audited form rail. Returns {error} when not safely automatic."""
    if not value1 or not value2 or not gr_form:
        return {"error": "missing form or values"}
    clauses = gr_form.get("clauses", [])
    hits = [i for i, cl in enumerate(clauses) if value1 in cl]
    if len(hits) != 1:
        return {"error": f"value occurs in {len(hits)} clauses — fix manually"}
    gf = dict(gr_form)
    gf["clauses"] = list(clauses)
    gf["clauses"][hits[0]] = gf["clauses"][hits[0]].replace(value1, value2)
    g_out = generate_from_form(gf)
    if g_out.get("error") or not g_out.get("audit", {}).get("ok"):
        return {"error": g_out.get("error") or "digit audit failed after substitution"}
    return {"form": g_out["form"], "generated": g_out,
            "score": score(g_out["draft"]),
            "terms": check_terminology(g_out["draft"]),
            "fix_applied": f"'{value1}' → '{value2}'"}


def suggested_fix_text(c: dict) -> str:
    v1, v2 = c.get("value1"), c.get("value2")
    if not (v1 and v2):
        return ""
    return (f"Align the draft to **{v2}**, or keep **{v1}** and add an explicit "
            f"clause superseding GR `{c.get('meta', {}).get('gr_code', '?')}` "
            f"for this benefit.")


def coerce_date(form: dict) -> dict:
    """API dates are ISO strings; the draftgen layer wants datetime.date."""
    import datetime as dt
    f = dict(form)
    d = f.get("date")
    if isinstance(d, str) and d:
        try:
            f["date"] = dt.date.fromisoformat(d[:10])
        except ValueError:
            pass
    return f


def warm() -> dict:
    """Load every heavy artifact once, at startup, off the request path."""
    status = {}
    try:
        from bootstrap import artifacts_missing, ensure_artifacts
        if artifacts_missing():
            ensure_artifacts()
        status["artifacts"] = "ok"
    except Exception as e:
        status["artifacts"] = f"failed: {e}"
    corpus()
    status["corpus"] = corpus_stats()["n_grs"]
    try:
        from build_index import model
        model()                                 # e5 embedder (~30 s cold)
        status["embedder"] = "ok"
    except Exception as e:
        status["embedder"] = f"failed: {e}"
    try:
        from pipeline import muril_available, _muril_load
        if muril_available():
            _muril_load()
            status["muril"] = "ok"
        else:
            status["muril"] = "off"
    except Exception as e:
        status["muril"] = f"failed: {e}"
    return status
