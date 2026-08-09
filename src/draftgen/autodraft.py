"""Autonomous GR drafting — a topic goes in, an authentic Government Resolution
comes out, with no human in the loop.

Everything this module needs already existed; what was missing was an entry
point and a policy for one hard case. The chain is:

    topic → topic_prefill()      retrieval + AI prose, sourced-or-blank
          → resolve_blanks()     THIS module: what to do about ____
          → generate_from_form() deterministic render + digit audit
          → gr_pdf()/gr_docx()   authentic government layout

**The ____ problem.** The prefill rail refuses to let the model introduce a
number it cannot trace to the topic, a precedent GR, or the calendar; every
untraceable figure becomes ``____``. The render rail then refuses to produce a
GR that still contains one. Together those two refusals are the product's core
safety property — and they also mean a fully autonomous run can dead-end.

Rather than weaken either rail, this module resolves the blanks the way the
government itself does. A GR whose financial quantum is not yet fixed is issued
as **तत्वतः मान्यता** — approval in principle — with the amount to follow by a
**स्वतंत्र आदेश** (separate order). So the default policy, ``defer``:

  * a clause containing a blank is lifted out of the operative body and kept
    verbatim in the report (never silently deleted),
  * one constant, digit-free clause is appended saying the rates and amounts
    will be issued separately,
  * the questions the system refused to guess are returned to the caller — and
    are never printed on the page.

The result is a complete, compliant, legally coherent GR that contains no
invented figure and no blank. Nothing here calls an LLM, so the deferral path
introduces no new failure mode and no new numeral.

Policies: ``defer`` (default), ``omit`` (drop blank clauses, say nothing),
``keep`` (render the blanks as-is), ``block`` (the pre-existing refusal).

Nothing in this module edits a prompt, so the LLM disk cache — and with it the
frozen demo baseline — is untouched by construction.
"""
import argparse
import json
import re
import sys
import time
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _sub in ("draftgen", "export", "compliance", "llm", "index", "ingest"):
    _p = str(ROOT / "src" / _sub)
    if _p not in sys.path:
        sys.path.append(_p)

from corpus_path import default_corpus_path  # noqa: E402
from generate import _digit_runs, generate_from_form  # noqa: E402
from gr_layout import gr_docx, gr_pdf  # noqa: E402
from prefill import deterministic_prefill, topic_prefill  # noqa: E402

BLANK = "____"
BLANK_POLICIES = ("defer", "omit", "keep", "block")

# Constant, digit-free, glossary-clean. This is the government's own instrument
# for "approved in principle, amount to follow", not a placeholder we invented.
DEFER_CLAUSE = {
    "mr": "सदर योजनेसाठीचे दर, रक्कम व सविस्तर मार्गदर्शक सूचना स्वतंत्र "
          "आदेशाद्वारे निर्गमित करण्यात येतील.",
    "en": "The rates, amounts and detailed guidelines for this scheme shall be "
          "issued by a separate order.",
}

# Marathi danda or a full stop, followed by whitespace.
_SENTENCE_SPLIT = re.compile(r"(?<=[.।])\s+")


def _stub_retrieve(query, k=8):
    """Retrieval that finds nothing — used when the vector index is missing so
    a draft is still produced (department falls back to the keyword vote)."""
    return []


def _baseline_prose(topic: str, lang: str = "mr", on_date=None) -> dict:
    """Digit-free subject/background/clauses derived from the topic alone.

    Reuses deterministic_prefill with a stub retriever: no index is touched and
    no numeral is introduced, so this is always a safe replacement for prose
    that had to be discarded."""
    form = deterministic_prefill(topic, lang, corpus=[],
                                 retrieve_fn=_stub_retrieve, on_date=on_date)
    return {k: form[k] for k in ("subject", "background", "clauses")}


def resolve_blanks(form: dict, policy: str = "defer", *,
                   baseline: dict = None) -> tuple:
    """Return (new_form, report) with the ____ blanks resolved per `policy`.

    Only ever removes or replaces text — never writes a numeral. The caller can
    assert that, and the self-test does:
        _digit_runs(output) <= _digit_runs(input)
    """
    if policy not in BLANK_POLICIES:
        raise ValueError(f"blank_policy must be one of {BLANK_POLICIES}")

    report = {"policy": policy, "deferred": [], "replaced_fields": [],
              "fallback_used": False}
    if policy in ("keep", "block"):
        return dict(form), report

    lang = form.get("lang", "mr")
    out = dict(form)
    baseline = baseline or _baseline_prose(form.get("topic") or
                                           form.get("subject") or "", lang,
                                           on_date=form.get("date"))

    # --- clauses: lift out any clause carrying a blank, keep it in the report
    kept = []
    for c in out.get("clauses") or []:
        (report["deferred"] if BLANK in str(c) else kept).append(str(c).strip())
    if not kept:
        # everything was deferred — fall back to the digit-free template so the
        # operative body is never empty (the scorecard requires numbered clauses)
        kept = [str(c).strip() for c in baseline["clauses"]]
        report["fallback_used"] = True
    out["clauses"] = kept

    # --- subject: never dropped (unique_code and the scorecard depend on it)
    if BLANK in str(out.get("subject") or ""):
        out["subject"] = baseline["subject"]
        report["replaced_fields"].append("subject")

    # --- background: drop only the offending sentences, then sanity-check
    bg = str(out.get("background") or "")
    if BLANK in bg:
        keep_sents = [s for s in _SENTENCE_SPLIT.split(bg)
                      if s.strip() and BLANK not in s]
        bg2 = " ".join(keep_sents).strip()
        out["background"] = bg2 if len(bg2) >= 20 else baseline["background"]
        report["replaced_fields"].append("background")

    # --- say so, in the GR's own voice
    if policy == "defer" and (report["deferred"] or report["replaced_fields"]):
        defer_line = DEFER_CLAUSE.get(lang, DEFER_CLAUSE["en"])
        if defer_line not in out["clauses"]:
            out["clauses"] = list(out["clauses"]) + [defer_line]

    return out, report


def draft_gr(topic: str, lang: str = "mr", *, corpus=None, retrieve_fn=None,
             llm_fn=None, on_date=None, n_clauses: int = 3,
             blank_policy: str = "defer", use_ai: bool = True,
             review: bool = False, top_k: int = 10,
             exports=("pdf", "docx"), progress=None) -> dict:
    """Topic → finished GR, autonomously. Never raises; inspect `ok`/`error`.

    Degrades rather than fails: a missing vector index, an unreachable LLM or a
    renderer error each leave a valid GR and a note in meta["degraded"]."""
    t0 = time.time()

    def say(msg):
        if progress:
            progress(msg)

    if blank_policy not in BLANK_POLICIES:
        raise ValueError(f"blank_policy must be one of {BLANK_POLICIES}")

    degraded = []
    say("पूर्वसंदर्भ शोधत आहे… · retrieving precedent GRs")
    try:
        pf = topic_prefill(topic, lang, corpus=corpus, retrieve_fn=retrieve_fn,
                           use_ai=use_ai, llm_fn=llm_fn, on_date=on_date,
                           n_clauses=n_clauses)
    except Exception as e:                      # missing/corrupt Chroma index
        degraded.append(f"no_index:{type(e).__name__}")
        say("index unavailable — drafting without precedents")
        try:
            pf = topic_prefill(topic, lang, corpus=corpus,
                               retrieve_fn=_stub_retrieve, use_ai=use_ai,
                               llm_fn=llm_fn, on_date=on_date,
                               n_clauses=n_clauses)
        except Exception as e2:
            return {"ok": False, "error": f"prefill failed: {e2}", "draft": "",
                    "form": {}, "pdf_bytes": None, "docx_bytes": None,
                    "audit": {}, "compliance": {}, "terminology": {},
                    "review": None,
                    "meta": {"degraded": degraded + [f"prefill_failed:{e2}"],
                             "elapsed_s": round(time.time() - t0, 2)}}

    form = dict(pf["form"])
    # carry provenance so generate_from_form can report it truthfully
    form["ai_used"], form["ai_error"] = pf["ai_used"], pf["ai_error"]
    if pf["ai_error"]:
        degraded.append("llm_unavailable")

    say("रिकाम्या जागा सोडवत आहे… · resolving unsourced figures")
    baseline = _baseline_prose(topic, lang, on_date=form.get("date"))
    form2, blank_report = resolve_blanks(form, blank_policy, baseline=baseline)

    say("मसुदा तयार करत आहे… · rendering")
    g = generate_from_form(form2, allow_blanks=(blank_policy == "keep"))
    if g.get("error"):
        return {"ok": False, "error": g["error"], "blanks": g.get("blanks", []),
                "draft": "", "form": form2, "pdf_bytes": None,
                "docx_bytes": None, "audit": {}, "compliance": {},
                "terminology": {}, "review": None,
                "meta": _meta(pf, blank_report, degraded, t0, form2)}

    draft, out_form = g["draft"], g["form"]

    from glossary_check import check_terminology
    from scorecard import score
    compliance, terminology = score(draft), check_terminology(draft)

    pdf_bytes = docx_bytes = None
    if "pdf" in exports:
        try:
            pdf_bytes = gr_pdf(out_form)
        except Exception as e:
            degraded.append(f"pdf_export_failed:{type(e).__name__}: {e}")
    if "docx" in exports:
        try:
            docx_bytes = gr_docx(out_form)
        except Exception as e:
            degraded.append(f"docx_export_failed:{type(e).__name__}: {e}")

    review_out = None
    if review:
        say("संघर्ष तपासत आहे… · reviewing against in-force GRs")
        try:
            from pipeline import review_draft      # lazy: pulls torch/MuRIL
            review_out = review_draft(draft, top_k=top_k)
        except Exception as e:
            degraded.append(f"review_failed:{type(e).__name__}: {e}")

    return {"ok": bool(draft) and bool(g["audit"].get("ok")), "error": None,
            "draft": draft, "form": out_form,
            "pdf_bytes": pdf_bytes, "docx_bytes": docx_bytes,
            "audit": g["audit"], "compliance": compliance,
            "terminology": terminology, "review": review_out,
            "meta": _meta(pf, blank_report, degraded, t0, out_form)}


def _meta(pf, blank_report, degraded, t0, form) -> dict:
    deferred = list(blank_report.get("deferred") or [])
    return {"ai_used": pf["ai_used"], "ai_error": pf["ai_error"],
            "scrubbed": pf["scrubbed"], "needs_numbers": pf["needs_numbers"],
            "open_questions": list(pf["needs_numbers"]) + deferred,
            "deferred_clauses": deferred,
            "replaced_fields": blank_report.get("replaced_fields", []),
            "blank_policy": blank_report.get("policy"),
            "fallback_used": blank_report.get("fallback_used", False),
            "department": form.get("department"),
            "dept_code": form.get("dept_code"),
            "gr_number": form.get("gr_number"),
            "code": form.get("code"),
            "precedents": form.get("precedents") or [],
            "degraded": degraded,
            "elapsed_s": round(time.time() - t0, 2)}


# ---------------------------------------------------------------- self-test

def _selftest():
    """Fully offline: injected retrieval, injected LLM, no index, no network."""
    on = date_cls(2026, 8, 6)
    topic = "जिल्हा परिषद शाळांमधील विद्यार्थ्यांसाठी मोफत क्रीडा साहित्य पुरवठा"

    def fake_retrieve(q, k=8):
        return [{"gr_code": "202401151200000021", "distance": 0.12,
                 "subject": "जिल्हा परिषद शाळांना क्रीडा साहित्य पुरवठा",
                 "clause": "क्रीडा साहित्य पुरवठा करण्यास मान्यता."},
                {"gr_code": "202312011200000021", "distance": 0.19,
                 "subject": "शालेय क्रीडा स्पर्धा अनुदान वितरण",
                 "clause": "अनुदान वितरित करण्यात यावे."}]

    def fake_llm(prompt, **kw):
        # deliberately contains BOTH an unsourced number and a literal blank
        return json.dumps({
            "subject": "जिल्हा परिषद शाळांमधील विद्यार्थ्यांना मोफत क्रीडा "
                       "साहित्य पुरवठा करण्याबाबत.",
            "file_prefix": "क्रीसा",
            "background": "ही बाब शासनाच्या विचाराधीन होती.",
            "clauses": [
                "प्रत्येक शाळेस रु. 45000 इतके क्रीडा साहित्य पुरविण्यात यावे.",
                "सदर साहित्य ____ पर्यंत वितरित करण्यात यावे.",
                "सदर शासन निर्णय निर्गमित दिनांकापासून लागू राहील.",
            ],
            "needs_numbers": ["प्रति शाळा किती रक्कम मंजूर आहे?"],
        }, ensure_ascii=False)

    from scorecard import score

    # --- defer (the default, autonomous path)
    r = draft_gr(topic, "mr", corpus=[], retrieve_fn=fake_retrieve,
                 llm_fn=fake_llm, on_date=on, blank_policy="defer",
                 exports=())
    assert r["ok"], r
    assert r["meta"]["ai_used"] is True, r["meta"]
    assert r["meta"]["scrubbed"], "the unsourced 45000 should have been scrubbed"
    assert r["meta"]["deferred_clauses"], "a blank-bearing clause should defer"
    assert r["meta"]["open_questions"], r["meta"]
    assert BLANK not in r["draft"], "a blank reached the rendered draft"
    assert DEFER_CLAUSE["mr"] in r["draft"], "deferral clause missing"
    assert r["audit"]["ok"] and not r["audit"]["invented"], r["audit"]
    assert score(r["draft"])["pct"] == 100, score(r["draft"])
    print(f"defer   : ok, {len(r['meta']['deferred_clauses'])} deferred, "
          f"compliance {r['compliance']['pct']}%, audit ok")

    # --- block reproduces the pre-existing refusal exactly
    b = draft_gr(topic, "mr", corpus=[], retrieve_fn=fake_retrieve,
                 llm_fn=fake_llm, on_date=on, blank_policy="block", exports=())
    assert b["ok"] is False and b["error"] == "unfilled_blanks", b
    assert b["blanks"], b
    print(f"block   : refused as before ({b['blanks']})")

    # --- keep renders the blanks deliberately
    k = draft_gr(topic, "mr", corpus=[], retrieve_fn=fake_retrieve,
                 llm_fn=fake_llm, on_date=on, blank_policy="keep", exports=())
    assert k["ok"] and BLANK in k["draft"], "keep should preserve the blank"
    print("keep    : blanks rendered as-is")

    # --- omit drops the clause without the deferral sentence
    o = draft_gr(topic, "mr", corpus=[], retrieve_fn=fake_retrieve,
                 llm_fn=fake_llm, on_date=on, blank_policy="omit", exports=())
    assert o["ok"] and BLANK not in o["draft"], o
    assert DEFER_CLAUSE["mr"] not in o["draft"], "omit must stay silent"
    assert score(o["draft"])["pct"] == 100
    print("omit    : clause dropped, still 100% compliant")

    # --- resolve_blanks never introduces a digit
    src = {"lang": "mr", "topic": topic, "date": on,
           "subject": "चाचणी विषय ____ बाबत.",
           "background": "रु. ____ मंजूर. ही बाब विचाराधीन होती.",
           "clauses": ["रु. ____ द्यावेत.", "क्रमांक 12 नुसार कार्यवाही करावी."]}
    got, rep = resolve_blanks(src, "defer")
    before = _digit_runs(" ".join([src["subject"], src["background"],
                                   *src["clauses"]]))
    after = _digit_runs(" ".join([got["subject"], got["background"],
                                  *got["clauses"]]))
    assert after <= before, (before, after)
    assert BLANK not in " ".join([got["subject"], got["background"],
                                  *got["clauses"]])
    print(f"safety  : no digit invented ({sorted(before)} -> {sorted(after)})")

    # --- degrades to a valid GR when the index is gone
    def boom(q, k=8):
        raise RuntimeError("chroma unavailable")

    d = draft_gr(topic, "mr", corpus=[], retrieve_fn=boom, llm_fn=fake_llm,
                 on_date=on, exports=())
    assert d["ok"] and any(x.startswith("no_index") for x in d["meta"]["degraded"])
    assert score(d["draft"])["pct"] == 100
    print(f"no index: still 100% compliant ({d['meta']['degraded'][0]})")

    # --- degrades when the LLM is unreachable
    from clients import LLMError

    def dead(prompt, **kw):
        raise LLMError("ollama down")

    l = draft_gr(topic, "mr", corpus=[], retrieve_fn=fake_retrieve,
                 llm_fn=dead, on_date=on, exports=())
    assert l["ok"] and l["meta"]["ai_used"] is False and l["meta"]["ai_error"]
    assert BLANK not in l["draft"] and score(l["draft"])["pct"] == 100
    print("no LLM  : deterministic prose, still 100% compliant")

    # --- English
    e = draft_gr("free sports equipment for zilla parishad school students",
                 "en", corpus=[], retrieve_fn=fake_retrieve, llm_fn=fake_llm,
                 on_date=on, exports=())
    assert e["ok"] and score(e["draft"])["pct"] == 100
    print("english : 100% compliant")

    print("autodraft.py self-test OK")


# ---------------------------------------------------------------------- CLI

def _load_corpus():
    p = default_corpus_path()
    if p.exists():
        with p.open(encoding="utf-8") as f:
            return [json.loads(line) for line in f]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Draft a Maharashtra GR autonomously from a topic.")
    ap.add_argument("--topic", help="the GR subject, in Marathi or English")
    ap.add_argument("--lang", default="mr", choices=["mr", "en"])
    ap.add_argument("--clauses", type=int, default=3)
    ap.add_argument("--date", help="issue date YYYY-MM-DD (default: today)")
    ap.add_argument("--blank-policy", default="defer", choices=list(BLANK_POLICIES))
    ap.add_argument("--no-ai", action="store_true",
                    help="deterministic prose only (no LLM call)")
    ap.add_argument("--review", action="store_true",
                    help="also run the conflict/reference review (loads MuRIL)")
    ap.add_argument("--out", default=str(ROOT / "data" / "autodraft"))
    ap.add_argument("--json", action="store_true", help="print the meta as JSON")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        _selftest()
        return 0
    if not a.topic:
        ap.error("--topic is required (or use --selftest)")

    on = date_cls.fromisoformat(a.date) if a.date else None
    res = draft_gr(a.topic, a.lang, corpus=_load_corpus(), on_date=on,
                   n_clauses=a.clauses, blank_policy=a.blank_policy,
                   use_ai=not a.no_ai, review=a.review,
                   progress=None if a.quiet else lambda m: print(f"  … {m}",
                                                                 flush=True))
    m = res["meta"]
    if not res["ok"] and res.get("error"):
        print(f"FAILED: {res['error']} {res.get('blanks') or ''}")
        if res["error"] == "unfilled_blanks":
            print("  (that is --blank-policy block; the autonomous default is "
                  "'defer', which resolves these)")
        return 1 if res.get("draft") is not None else 2

    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    code = m.get("code") or "draft"
    written = []
    (outdir / f"{code}.txt").write_text(res["draft"], encoding="utf-8")
    written.append(outdir / f"{code}.txt")
    for ext, blob in (("pdf", res["pdf_bytes"]), ("docx", res["docx_bytes"])):
        if blob:
            (outdir / f"{code}.{ext}").write_bytes(blob)
            written.append(outdir / f"{code}.{ext}")
    (outdir / f"{code}.json").write_text(
        json.dumps({"topic": a.topic, "meta": m,
                    "compliance": res["compliance"].get("pct"),
                    "audit": res["audit"]}, ensure_ascii=False, indent=2,
                   default=str), encoding="utf-8")
    written.append(outdir / f"{code}.json")

    if not a.quiet:
        print()
        print(f"  department  : {m['department']} (code {m['dept_code']})")
        print(f"  GR number   : {m['gr_number']}")
        print(f"  precedents  : {len(m['precedents'])} "
              + ", ".join(f"{p['gr_code']}({1 - p['distance']:.2f})"
                          for p in m["precedents"][:4]))
        print(f"  AI prose    : {m['ai_used']}"
              + (f"  [{m['ai_error'][:60]}]" if m["ai_error"] else ""))
        print(f"  compliance  : {res['compliance']['pct']}%   "
              f"digit audit: {'ok' if res['audit'].get('ok') else 'FAILED'}   "
              f"terminology flags: {res['terminology'].get('n_flags')}")
        print(f"  refused     : {len(m['scrubbed'])} unsourced number(s), "
              f"{len(m['deferred_clauses'])} clause(s) deferred")
        for q in m["open_questions"]:
            print(f"      ❓ {q}")
        if m["degraded"]:
            print(f"  degraded    : {', '.join(m['degraded'])}")
        print(f"  elapsed     : {m['elapsed_s']}s")
        print()
        for p in written:
            print(f"  wrote {p}")
    if a.json:
        print(json.dumps(m, ensure_ascii=False, indent=2, default=str))

    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
