"""MAHA-GR-ALIGN — Streamlit demo app.

Tabs: Conflicts | References | Scorecard | Glossary | About.
Degrades gracefully: each analysis that is unavailable (no index yet, no API
keys yet) explains itself instead of crashing the app.
"""
import json
import os
import re
import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parents[1]
for sub in ("llm", "index", "ingest", "detect", "reftrack", "compliance",
            "audit", "export", "draftgen", "deploy"):
    sys.path.append(str(ROOT / "src" / sub))

from clients import GEMINI_MODEL, GROQ_MODEL, LLM_MODE, OLLAMA_MODEL  # noqa: E402
from build_source_urls import links_for  # noqa: E402
from trail import TRAIL_FILE, append_run, load_runs, to_csv  # noqa: E402
from writer import draft_docx, draft_pdf, report_docx, report_pdf  # noqa: E402
from generate import SAMPLE, generate as generate_draft  # noqa: E402
from chunk_clauses import MIN_CHARS  # noqa: E402

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

st.set_page_config(page_title="ClauseGuard", page_icon="📜", layout="wide")

# Cloud hosts boot from the git repo alone — pull the fine-tuned model, the
# vector index and the warmed LLM cache from the HF Hub on first boot. Local
# checkouts already have them on disk, so this is a no-op in development.
from bootstrap import artifacts_missing, ensure_artifacts  # noqa: E402
if artifacts_missing():
    try:
        with st.spinner("First boot on this host — downloading the fine-tuned "
                        "model and vector index (~600 MB, one time)…"):
            ensure_artifacts()
    except Exception as e:
        st.warning(f"Artifact download failed — running without the local "
                   f"model/index: {e}")

MURIL_ON = (os.environ.get("USE_MURIL", "1") != "0"
            and (ROOT / "model" / "muril_gr_conflict_fp16" / "config.json").exists())
MODE_BADGE = (f"🖥️ local · Ollama {OLLAMA_MODEL}" if LLM_MODE == "ollama"
              else f"☁️ cloud · {GROQ_MODEL.split('-versatile')[0]} + {GEMINI_MODEL}")

st.markdown(
    f"""
    <div style="padding:0.9rem 1.3rem;border-radius:14px;
         background:linear-gradient(100deg,#152452 0%,#1c3a6e 55%,#1d5f6b 100%);
         border:1px solid #2b3a55">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem">
      <div>
        <h2 style="margin:0;color:#fff">📜 ClauseGuard</h2>
        <p style="margin:.15rem 0 0;color:#c9d6ea">Conflict-aware Government Resolution drafting —
        detection · references · compliance · bilingual</p>
      </div>
      <div style="text-align:right">
        <span style="background:#0e1a30;border:1px solid #33507e;border-radius:999px;
              padding:.3rem .8rem;color:#9fc0ff;font-size:.85rem">{MODE_BADGE}</span><br>
        <span style="background:#0e1a30;border:1px solid #2f5e46;border-radius:999px;
              padding:.3rem .8rem;color:#8fd0a0;font-size:.85rem;display:inline-block;margin-top:.35rem">
              {'🧠 MuRIL screening ON · 130 ms/pair' if MURIL_ON else 'MuRIL screening off — LLM verifies all pairs'}</span>
      </div>
    </div></div>
    """,
    unsafe_allow_html=True,
)

SCENARIOS = {
    "1_fee_conflict_draft": ("Scenario A — fee-reimbursement conflict",
                             "50% draft vs an in-force 100% GR: the planted contradiction"),
    "2_stale_reference_draft": ("Scenario B — outdated reference",
                                "cites a 2022 GR that has newer same-subject successors"),
    "3_broken_format_draft": ("Scenario C1 — broken format",
                              "missing Read block, bad date format → low scorecard"),
    "3_broken_format_FIXED": ("Scenario C2 — format fixed",
                              "same draft repaired → watch the score jump"),
}


def _corpus_file():
    # prefer the LLM-cleaned corpus when it exists
    for name in ("corpus_clean.jsonl", "corpus.jsonl"):
        p = ROOT / "data" / name
        if p.exists():
            return p
    return None


@st.cache_data
def load_corpus_cached(path_str, mtime):
    # mtime participates in the cache key so a rebuilt corpus refreshes the app
    return [json.loads(l) for l in Path(path_str).read_text(encoding="utf-8").splitlines()
            if l.strip()]


@st.cache_data
def load_glossary():
    return json.loads((ROOT / "data" / "glossary.json").read_text(encoding="utf-8"))


_cf = _corpus_file()
corpus = load_corpus_cached(str(_cf), _cf.stat().st_mtime) if _cf else []

# ---------- sidebar ----------
with st.sidebar:
    st.subheader("📚 Corpus")
    if corpus:
        n_clauses = sum(len(r.get("clauses", [])) for r in corpus)
        c1, c2 = st.columns(2)
        c1.metric("Real GRs", f"{len(corpus):,}")
        c2.metric("Clauses", f"{n_clauses:,}",
                  help="Clauses parsed from the corpus. Retrieval indexes at most 60 "
                       "clauses per GR, so the searchable index is slightly smaller.")
        depts = {}
        for r in corpus:
            depts[r.get("department") or "?"] = depts.get(r.get("department") or "?", 0) + 1
        with st.expander("Departments"):
            for k, v in sorted(depts.items(), key=lambda x: -x[1])[:8]:
                st.caption(f"{k.split('(')[0][:34]} — **{v}**")
    else:
        st.warning("corpus.jsonl not built yet")

    st.subheader("🎬 Demo scenarios")
    planted = sorted((ROOT / "data" / "planted").glob("*.txt"))
    labels = {"—": "— none —"}
    labels.update({p.stem: SCENARIOS.get(p.stem, (p.stem, ""))[0] for p in planted})
    choice = st.selectbox("Load a planted draft", list(labels), format_func=labels.get)
    if choice != "—" and choice in SCENARIOS:
        st.caption(SCENARIOS[choice][1])

    with st.expander("⚙️ Advanced"):
        # default matches the pipeline / warm-cache default so demo runs stay cached
        top_k = st.slider("Candidates per clause", 2, 8, 6)

def read_upload(f) -> str:
    """Text of an uploaded draft (FR-13). PDFs reuse pdfplumber — already the
    corpus parser's dependency, so this adds nothing to requirements."""
    if f.name.lower().endswith(".pdf"):
        import pdfplumber
        with pdfplumber.open(f) as pdf:
            return "\n\n".join((p.extract_text() or "") for p in pdf.pages).strip()
    return f.getvalue().decode("utf-8", errors="replace")


def run_full_review(draft_text: str, k: int, source: str = "review"):
    """Score + terminology + references + conflict review of one draft, writing
    the same session keys every tab reads. Called by the Review button AND by
    the generate flow, so a generated draft goes through the identical pipeline
    instead of asking the user to copy-paste it into the review box."""
    # Scorecard (always available, deterministic)
    from scorecard import score
    if "score" in st.session_state:  # keep the previous run for the before/after delta
        st.session_state["score_prev"] = st.session_state["score"]
    st.session_state["score"] = score(draft_text)

    # Terminology (always available, deterministic — FR-8/FR-9)
    from glossary_check import check_terminology
    st.session_state["terms"] = check_terminology(draft_text)

    # References (needs corpus)
    if corpus:
        from citations import analyze_references
        st.session_state["refs"] = analyze_references(draft_text, corpus)

    # Conflicts (needs index + LLM keys)
    try:
        with st.spinner("Loading retrieval model (first run takes ~30 s)…"):
            from pipeline import review_draft, MAX_COSINE_DISTANCE
        st.session_state["max_distance"] = MAX_COSINE_DISTANCE
        prog = st.progress(0.0, text="analysing…")
        msgs = {"n": 0}

        def cb(msg):
            msgs["n"] += 1
            prog.progress(min(0.95, msgs["n"] / 40), text=msg)

        st.session_state["review"] = review_draft(draft_text, top_k=k, progress=cb)
        prog.progress(1.0, text="done")
    except Exception as e:
        st.session_state["review"] = {"error": str(e)}

    # FR-15: append this run — every suggestion offered, the deterministic
    # results, and the diff vs the previous submission — to the local audit
    # trail. A trail failure must never break a review.
    try:
        st.session_state["audit_last"] = append_run(
            draft_text,
            score=st.session_state.get("score"),
            terms=st.session_state.get("terms"),
            refs=st.session_state.get("refs"),
            review=st.session_state.get("review"),
            source=source,
        )
    except Exception as e:
        st.session_state["audit_error"] = str(e)


default_text = ""
if choice != "—":
    default_text = (ROOT / "data" / "planted" / f"{choice}.txt").read_text(encoding="utf-8")

# Picking a scenario reclaims the review box from a previously generated draft.
if st.session_state.get("last_choice") != choice:
    st.session_state["last_choice"] = choice
    if choice != "—":
        st.session_state["send_generated"] = False

upload = st.file_uploader("📎 Upload a draft GR — or paste one below",
                          type=["txt", "md", "pdf"])
if upload is not None:
    try:
        default_text = read_upload(upload)          # an upload overrides the scenario picker
        if not default_text.strip():
            st.warning(f"No text layer found in **{upload.name}** — if it is a scanned GR, "
                       "paste the text instead.")
    except Exception as e:
        st.error(f"Could not read {upload.name}: {e}")
elif st.session_state.get("send_generated") and st.session_state.get("generated"):
    # A freshly generated draft lands straight in the review box (an upload
    # still overrides it; picking a scenario reclaims the box above).
    default_text = st.session_state["generated"]["draft"]

draft = st.text_area("Paste / edit the draft GR under review:", value=default_text,
                     height=240, placeholder="Paste a draft Government Resolution here…")

run = st.button("🔍 Review draft", type="primary", use_container_width=True,
                disabled=not draft.strip())

if run and draft.strip():
    run_full_review(draft, top_k)


if draft.strip():
    # FR-16: export the draft — and, once a review has run, the review report —
    # as DOCX (Nirmala UI, Word shapes the Devanagari) or PDF (embedded Noto
    # fonts with harfbuzz shaping, so Marathi conjuncts render correctly).
    with st.expander("📤 Export — draft / review report as DOCX · PDF"):
        e1, e2, e3, e4 = st.columns(4)
        e1.download_button("📄 Draft · DOCX", draft_docx(draft),
                           file_name="clauseguard_draft.docx", mime=DOCX_MIME,
                           use_container_width=True)
        e2.download_button("📄 Draft · PDF", draft_pdf(draft),
                           file_name="clauseguard_draft.pdf", mime="application/pdf",
                           use_container_width=True)
        if st.session_state.get("score"):
            kw = dict(score=st.session_state.get("score"),
                      terms=st.session_state.get("terms"),
                      refs=st.session_state.get("refs"),
                      review=st.session_state.get("review"))
            e3.download_button("📋 Report · DOCX", report_docx(**kw),
                               file_name="clauseguard_review_report.docx",
                               mime=DOCX_MIME, use_container_width=True)
            e4.download_button("📋 Report · PDF", report_pdf(**kw),
                               file_name="clauseguard_review_report.pdf",
                               mime="application/pdf", use_container_width=True)
        else:
            e3.caption("Run **Review draft** to export the review report too.")


def report_header():
    """One-glance review report — the four numbers that summarise a run, above
    the tabs so a single screenshot carries the whole outcome."""
    s = st.session_state.get("score")
    if not s:
        return
    r = st.session_state.get("review") or {}
    refs = st.session_state.get("refs") or {}
    terms = st.session_state.get("terms") or {}

    conflicts = "n/a" if "error" in r else len(r.get("conflicts", []))
    warnings = len(refs.get("stale", [])) + len(refs.get("newer_related", []))
    prev = st.session_state.get("score_prev")
    delta = (f"{s['pct'] - prev['pct']:+d}%" if prev and prev["pct"] != s["pct"] else None)

    st.markdown("##### Review report")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Verified conflicts", conflicts,
              help="Clause pairs where extracted values actually disagree")
    k2.metric("Citation warnings", warnings if refs else "n/a",
              help="Superseded references + cited GRs with newer same-subject GRs")
    k3.metric("Template compliance", f"{s['pct']}%", delta,
              help=f"{len(s['checks'])} Manual-of-Office-Procedure checks")
    k4.metric("Terminology flags", terms.get("n_flags", "n/a"),
              help="Non-approved variants and wrong-language terms vs the glossary")
    st.divider()


report_header()

t_conf, t_refs, t_score, t_gloss, t_gen, t_audit, t_about = st.tabs(
    ["⚠️ Conflicts", "🔗 References", "✅ Scorecard", "📖 Glossary",
     "✍️ Generate", "🗂️ Audit", "ℹ️ About"]
)


def source_links(gr_code) -> str:
    """Markdown links to the source GR — live portal + archival copy (FR-6)."""
    l = links_for(gr_code)
    return f"[📄 source PDF]({l['portal']}) · [🕘 archived]({l['archive']})" if l else ""


def match_caption(meta: dict) -> str:
    """Similarity score + source links for a retrieved corpus clause (FR-6).

    The index is cosine-space over normalised embeddings, so `1 - distance`
    IS the cosine similarity — reported alongside the raw distance and the
    retrieval cut-off rather than rescaled into a flattering percentage.
    """
    bits = []
    d = meta.get("distance")
    if d is not None:
        cut = st.session_state.get("max_distance")
        tail = f" · cut-off {cut}" if cut else ""
        bits.append(f"similarity **{1 - d:.3f}** (cosine distance {d:.3f}{tail})")
    if link := source_links(meta.get("gr_code")):
        bits.append(link)
    return "  ·  ".join(bits)


# Shared chip styling — one definition for every red/green comparison chip in
# the app (conflict values, terminology corrections).
CHIP_ROW = "display:flex;gap:.8rem;align-items:center;flex-wrap:wrap;margin:.4rem 0 .6rem"
CHIP_BAD = ("background:#3a1520;border:1px solid #8a3a4a;border-radius:10px;"
            "padding:.45rem 1rem;color:#ff9fb0")
CHIP_GOOD = ("background:#12301f;border:1px solid #2f5e46;border-radius:10px;"
             "padding:.45rem 1rem;color:#8fd0a0")
CHIP_SEP = "color:#93a1b8;font-size:1.2rem"


def compare_chips(left_label, left, right_label, right, note=""):
    """left (problem) vs right (correct) as a chip pair."""
    tail = f'<span style="color:#7d8ca3;font-size:.85rem">{note}</span>' if note else ""
    st.markdown(
        f"""<div style="{CHIP_ROW}">
        <span style="{CHIP_BAD}">{left_label}<b>{left}</b></span>
        <span style="{CHIP_SEP}">→</span>
        <span style="{CHIP_GOOD}">{right_label}<b>{right}</b></span>{tail}
        </div>""",
        unsafe_allow_html=True,
    )


def value_chips(reason: str):
    """Render the two extracted values from a code-built reason as compare chips."""
    vals = re.findall(r"'([^']+)'", reason or "")
    if len(vals) < 2:
        return
    compare_chips("draft&nbsp;·&nbsp;", vals[0], "in&nbsp;force&nbsp;·&nbsp;", vals[1])


def suggested_fix(c: dict) -> str:
    """Deterministic drafting suggestion built from the extracted values (FR-14).

    Code-built from the same two values the verdict rests on — no extra LLM call,
    so it is available even when the explanation stage is unavailable.
    """
    vals = re.findall(r"'([^']+)'", c.get("reason") or "")
    if len(vals) < 2:
        return ""
    return (f"**Suggested fix** — align the draft to **{vals[1]}**, or keep **{vals[0]}** "
            f"and add an explicit clause superseding GR "
            f"`{c['meta'].get('gr_code', '?')}` for this benefit.")


def render_conflict_card(c: dict):
    """One verified conflict as a bordered card — shared by the Conflicts tab
    and the generate flow's inline results."""
    m = c["meta"]
    with st.container(border=True):
        st.markdown(f"#### 🔴 Conflict with GR `{m.get('gr_code','?')}`")
        if cap := match_caption(m):
            st.caption(cap)
        value_chips(c["reason"])
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Draft clause**")
            st.warning(c["draft"])
        with col2:
            st.markdown(f"**Existing GR** — {m.get('department','?')}  \n"
                        f"№ `{m.get('gr_number','?')}` · {m.get('date','?')}")
            st.info(c["candidate"])
        st.markdown(f"**Why it conflicts:** {c['reason']}")
        if fix := suggested_fix(c):
            st.markdown(fix)
        with st.expander("📝 Drafting-officer explanation"):
            st.markdown(c["explanation"])


with t_conf:
    r = st.session_state.get("review")
    if not r:
        st.info("Paste a draft (or pick a scenario in the sidebar) and press **Review draft**.")
    elif "error" in r:
        st.error(f"Conflict analysis unavailable: {r['error']}")
        st.caption("Needs the Chroma index (`python src/index/build_index.py`) and "
                   "API keys in `.env` (or `LLM_MODE=ollama`).")
    else:
        # the funnel: thousands of clauses -> candidates -> model flags -> verified
        f1, f2, f3, f4 = st.columns(4)
        f1.metric("Draft clauses", r["n_clauses"],
                  help="Numbered clauses extracted from the draft (boilerplate filtered)")
        f2.metric("Candidate pairs", r["n_pairs"],
                  help="Semantically-nearest corpus clauses per draft clause "
                       "(e5-small → Chroma, near-duplicate suppressed)")
        if r.get("n_muril_flagged") is not None:
            f3.metric("MuRIL flags", r["n_muril_flagged"],
                      delta=f"-{r['n_pairs'] - r['n_muril_flagged']} screened out",
                      delta_color="off",
                      help="Fine-tuned 238M cross-encoder, ~130 ms/pair on CPU")
        else:
            f3.metric("MuRIL flags", "off")
        f4.metric("Verified conflicts", len(r["conflicts"]),
                  help="LLM extracts the competing values; code makes the call")

        n_err = sum(1 for v in r.get("verdicts", []) if v.get("label") == "error")
        if n_err:
            st.error(f"{n_err} of {len(r.get('verdicts', []))} pair verifications "
                     f"failed (LLM errors) — results are incomplete.")
        if not r["conflicts"]:
            if n_err:
                st.warning("No conflicts confirmed, but verification was incomplete — "
                           "not a clean pass.")
            else:
                st.success("No conflicts flagged against the indexed corpus.")
        for c in r["conflicts"]:
            render_conflict_card(c)

with t_refs:
    refs = st.session_state.get("refs")
    if not refs:
        st.info("Run a review (corpus must be built) to analyse the draft's references.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Citations found", refs["n_citations"],
                  help="Formal GR references + 18-digit unique codes in the draft "
                       "(the draft's own header/footer are excluded)")
        c2.metric("Linked to corpus", len(refs["linked"]))
        c3.metric("Currency warnings", len(refs.get("newer_related", [])),
                  help="Cited GRs with newer same-subject GRs in force")
        c4.metric("Explicit supersessions", len(refs["stale"]))
        for s in refs["stale"]:
            st.error(f"⚠️ Cites **{s['cited']}** which appears superseded by "
                     f"`{s['superseded_by']}` — {s.get('successor_subject','')}")
        for a in refs.get("newer_related", []):
            newest = a["newer"][0]
            with st.container(border=True):
                st.markdown(f"🕐 **Currency check** — the draft cites a GR dated "
                            f"**{a['cited_date']}**, but {len(a['newer'])} newer GR(s) "
                            f"exist on the same subject. Verify it is still operative.")
                for nr in a["newer"]:
                    st.caption(f"↳ `{nr['gr_code']}` · {nr['date']} — {nr['subject']}")
        if refs["linked"]:
            st.markdown("**Linked references**")
            for l in refs["linked"]:
                m = l["match"]
                with st.container(border=True):
                    lc1, lc2 = st.columns([2, 3])
                    lc1.markdown(f"`{l['cited'][:60]}`  \n*via {l['via']}*")
                    lc2.markdown(f"**{m.get('department','?')}** · {m.get('date','?')}  \n"
                                 f"{(m.get('subject') or '')[:110]}")
                    if link := source_links(m.get("gr_code")):
                        lc2.caption(link)
        if refs["unknown"]:
            with st.expander(f"Unmatched citations ({len(refs['unknown'])})"):
                for u in refs["unknown"]:
                    st.markdown(f"- `{u[:90]}`")

with t_score:
    s = st.session_state.get("score")
    if not s:
        st.info("Run a review to score the draft against the Manual of Office Procedure template.")
    else:
        prev = st.session_state.get("score_prev")
        delta = (f"{s['pct'] - prev['pct']:+d}% vs previous draft"
                 if prev and prev["pct"] != s["pct"] else None)
        st.metric("Template compliance", f"{s['pct']}%", delta,
                  help=f"{s['score']}/{s['max_score']} weighted points — "
                       f"{len(s['checks'])} deterministic Manual-of-Office-Procedure checks")
        st.progress(s["pct"] / 100)
        fails = [c for c in s["checks"] if not c["passed"]]
        passes = [c for c in s["checks"] if c["passed"]]
        if fails:
            st.markdown("**Fix these:**")
            for c in fails:
                st.markdown(f"❌ {c['desc']}  *(weight {c['weight']})*")
        else:
            st.success("Every template check passes.")
        with st.expander(f"✅ Passing checks ({len(passes)})"):
            for c in passes:
                st.markdown(f"✅ {c['desc']}  *(weight {c['weight']})*")

with t_gloss:
    terms = st.session_state.get("terms")
    if terms:
        lang = "Marathi" if terms["primary_lang"] == "mr" else "English"
        if terms["n_flags"]:
            st.markdown(f"#### 📝 Terminology check — {terms['n_flags']} flag(s) "
                        f"in this {lang} draft")
            for f in terms["flags"]:
                approved = (f["approved_mr"] if terms["primary_lang"] == "mr"
                            else f["approved_en"])
                with st.container(border=True):
                    label = ("non-approved variant" if f["kind"] == "variant"
                             else "wrong-language term")
                    compare_chips("", f["found"], "", approved, note=label)
                    st.caption(f"…{f['context']}…")
                    if f["note"]:
                        st.caption(f"ℹ️ {f['note']}")
        else:
            st.success(f"No terminology mismatches — every glossary term in this "
                       f"{lang} draft uses its approved form.")
        st.divider()

    q = st.text_input("🔎 Filter terms (Marathi or English)")
    rows = load_glossary()
    if q:
        rows = [g for g in rows if q.lower() in g["en"].lower() or q in g["mr"]]
    st.caption(f"{len(rows)} terms")
    cols = st.columns(2)
    for i, g in enumerate(rows):
        note = f" — *{g['note']}*" if g.get("note") else ""
        cols[i % 2].markdown(f"**{g['mr']}** · {g['en']}{note}")

with t_gen:
    ai_where = ("locally via Ollama — nothing typed here leaves this machine"
                if LLM_MODE == "ollama" else "via the configured cloud LLMs")
    st.markdown(
        f"**विषय लिहा → मसुदा मिळवा.** Type a topic and ClauseGuard finds real "
        f"precedent GRs, infers the department, builds the वाचा references and "
        f"file number, and prefills the whole form — review any field, then "
        f"generate. The deterministic template guarantees every mandatory "
        f"Manual-of-Office-Procedure section (AC-3), and the generated draft "
        f"goes straight through the full conflict/reference review "
        f"({ai_where})."
    )
    lang = "en" if st.radio("Language", ["English", "मराठी"], horizontal=True,
                            index=1,
                            label_visibility="collapsed") == "English" else "mr"
    sample = SAMPLE[lang]

    # ---- पायरी 1: topic → prefill ----
    tp1, tp2 = st.columns([4, 2])
    g_topic = tp1.text_input(
        "GR चा विषय · Topic",
        placeholder=("उदा. जिल्हा परिषद शाळांना सादिल अनुदान वितरण"
                     if lang == "mr" else
                     "e.g. merit scholarship for polytechnic students"))
    tp2.markdown("<div style='height:1.7rem'></div>", unsafe_allow_html=True)
    if tp2.button("🔎 पूर्वसंदर्भ शोधा व फॉर्म भरा", use_container_width=True,
                  disabled=not g_topic.strip(),
                  help="Find precedent GRs and prefill the form from the topic"):
        from prefill import topic_prefill
        with st.status("पूर्वसंदर्भ शोधत आहे… (first run loads the retrieval "
                       "model, ~30 s)", expanded=False) as status:
            try:
                pf_out = topic_prefill(g_topic, lang, corpus=corpus)
                st.session_state["prefill"] = pf_out["form"]
                st.session_state["prefill_meta"] = {
                    k: pf_out[k] for k in ("ai_used", "ai_error", "scrubbed",
                                           "needs_numbers")}
                n_prec = len(pf_out["form"]["precedents"])
                status.update(label=f"फॉर्म भरला — {n_prec} पूर्वसंदर्भ सापडले",
                              state="complete")
            except Exception as e:
                status.update(label=f"प्रीफिल अयशस्वी — फॉर्म रिकामाच ठेवला: {e}",
                              state="error")
    if pf := st.session_state.get("prefill"):
        with st.container(border=True):
            st.caption(f"**पूर्वसंदर्भ · precedents** — विभाग ओळखला: "
                       f"**{pf['department']}** (कोड {pf['dept_code']})")
            for p in pf["precedents"]:
                bits = [f"`{p['gr_code']}` · {p['date_iso']} · "
                        f"similarity **{1 - p['distance']:.3f}**"]
                if link := source_links(p["gr_code"]):
                    bits.append(link)
                st.markdown("  ·  ".join(bits))
                if p.get("subject"):
                    st.caption(p["subject"][:120])
    pf = st.session_state.get("prefill") or {}
    pf_refs = "\n".join(r["text"] for r in pf.get("references", []))
    use_ai = st.toggle("🤖 AI-assist — draft the preamble and clauses from a "
                       "brief (digit-audited: no number invented or dropped)")
    with st.form("gen_form"):
        g1, g2 = st.columns(2)
        g_subject = g1.text_input("विषय-ओळ · Subject",
                                  pf.get("subject", sample["subject"]))
        g_department = g2.text_input("विभाग · Department",
                                     pf.get("department", sample["department"]))
        g_number = g1.text_input("शासन निर्णय क्रमांक · GR number",
                                 pf.get("gr_number", sample["gr_number"]))
        g_date = g2.date_input("दिनांक · Date")
        g_refs = st.text_area("वाचा — one reference per line",
                              pf_refs or "\n".join(sample["references"]),
                              height=68)
        if use_ai:
            g_brief = st.text_area(
                "Officer's brief", height=100,
                placeholder="e.g. sanction a merit scholarship of Rs. 1,500 per "
                            "month for the top 10% of polytechnic students, "
                            "paid via MahaDBT, from academic year 2026-27")
            g_n = st.slider("Operative clauses to draft", 2, 6, 3)
            g_background, g_clauses = "", ""
        else:
            g_brief, g_n = "", 3
            g_background = st.text_area("प्रस्तावना · Preamble background",
                                        pf.get("background", sample["background"]),
                                        height=80)
            g_clauses = st.text_area("कार्यवाहीचे मुद्दे · Operative clauses — one per line",
                                     "\n".join(pf.get("clauses", sample["clauses"])),
                                     height=130)
        g3, g4, g5 = st.columns(3)
        g_head = g3.text_input("लेखाशीर्ष · Budget head",
                               pf.get("budget_head", sample["budget_head"]))
        g_sign = g4.text_input("स्वाक्षरी · Signatory",
                               pf.get("signatory", sample["signatory"]))
        g_desig = g5.text_input("पदनाम · Designation",
                                pf.get("designation", sample["designation"]))
        gb1, gb2 = st.columns([3, 2])
        g_submit = gb1.form_submit_button("✍️ Generate & check draft", type="primary",
                                          use_container_width=True,
                                          help="Generate, then run the full conflict / "
                                               "reference / compliance review on it")
        g_draft_only = gb2.form_submit_button("📝 Draft only (no review)",
                                              use_container_width=True)
    if g_submit or g_draft_only:
        from scorecard import score
        from glossary_check import check_terminology
        fields = {"lang": lang, "subject": g_subject, "department": g_department,
                  "gr_number": g_number, "date": g_date,
                  "references": [r for r in g_refs.splitlines() if r.strip()],
                  "background": g_background,
                  "clauses": [c for c in g_clauses.splitlines() if c.strip()],
                  "budget_head": g_head, "signatory": g_sign,
                  "designation": g_desig}
        with st.spinner("drafting…"):
            g_out = generate_draft(fields, use_ai=use_ai, brief=g_brief,
                                   n_clauses=g_n)
        st.session_state["generated"] = g_out
        st.session_state["generated_score"] = score(g_out["draft"])
        st.session_state["generated_terms"] = check_terminology(g_out["draft"])
        # clauses under the chunker's floor never enter conflict screening —
        # surface that instead of letting them silently skip the check
        st.session_state["generated_short"] = [
            c for c in fields["clauses"] if len(c.strip()) < MIN_CHARS]
        st.session_state["send_generated"] = True   # review box shows this draft
        st.session_state["generated_reviewed"] = bool(g_submit)
        if g_submit:
            # the identical pipeline the Review button runs — one trail record
            # with source="generate+review" covers generation AND review (FR-15)
            run_full_review(g_out["draft"], top_k, source="generate+review")
        else:
            # a generated draft IS an AI suggestion — it belongs in the trail (FR-15)
            try:
                append_run(g_out["draft"], score=st.session_state["generated_score"],
                           terms=st.session_state["generated_terms"], source="generate")
            except Exception as e:
                st.session_state["audit_error"] = str(e)
        st.rerun()   # re-render so the review box + report header show this draft
    if g_out := st.session_state.get("generated"):
        if g_out["ai_used"]:
            st.caption("🤖 Preamble and clauses drafted by the AI layer — "
                       "digit audit passed against the brief.")
        elif g_out["ai_error"]:
            st.warning(f"AI assist unavailable — deterministic scaffold used "
                       f"instead. ({g_out['ai_error']})")
        gs = st.session_state.get("generated_score")
        gt = st.session_state.get("generated_terms")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Template compliance", f"{gs['pct']}%",
                  help="AC-3: a generated draft contains all mandatory sections")
        m2.metric("Terminology flags", gt["n_flags"])
        m3.download_button("⬇️ DOCX", draft_docx(g_out["draft"]),
                           file_name="clauseguard_generated_draft.docx",
                           mime=DOCX_MIME, use_container_width=True)
        m4.download_button("⬇️ PDF", draft_pdf(g_out["draft"]),
                           file_name="clauseguard_generated_draft.pdf",
                           mime="application/pdf", use_container_width=True)
        if short := st.session_state.get("generated_short"):
            st.caption(f"⚠️ {len(short)} operative clause(s) shorter than {MIN_CHARS} "
                       "characters — too short for conflict screening. Lengthen them "
                       "for full coverage.")
        if st.session_state.get("generated_reviewed"):
            r = st.session_state.get("review") or {}
            if "error" in r:
                st.warning(f"Draft is ready, but the conflict check was unavailable: "
                           f"{r['error']} — re-run it any time from the review box above.")
            else:
                n_conf = len(r.get("conflicts", []))
                if n_conf:
                    st.markdown(f"##### ⚠️ Conflict check — {n_conf} verified "
                                f"conflict(s) against the corpus")
                else:
                    st.success("Conflict check — no conflicts flagged against the "
                               "indexed corpus.")
                for c in r.get("conflicts", []):
                    render_conflict_card(c)
        st.text_area("Generated draft — it is also in the review box above; the "
                     "report header and tabs cover it like any reviewed draft",
                     g_out["draft"], height=340)

with t_audit:
    if err := st.session_state.pop("audit_error", None):
        st.warning(f"Last run could not be recorded: {err}")
    runs = load_runs()
    if not runs:
        st.info("No reviews recorded yet. Every **Review draft** click appends "
                "one record here: the suggestions offered, the deterministic "
                "results, and a diff of your edits since the previous "
                "submission (FR-15).")
    else:
        a1, a2, a3 = st.columns([1, 1, 2])
        a1.metric("Recorded runs", len(runs))
        a2.metric("With edits", sum(1 for r in runs if r.get("human_edit")))
        with a3:
            d1, d2 = st.columns(2)
            d1.download_button("⬇️ JSONL (full)", TRAIL_FILE.read_bytes(),
                               file_name="audit_trail.jsonl", mime="application/jsonl",
                               use_container_width=True)
            d2.download_button("⬇️ CSV (summary)", to_csv(runs),
                               file_name="audit_trail.csv", mime="text/csv",
                               use_container_width=True)
        for rec in reversed(runs):
            sug = rec.get("ai_suggestions", {})
            det = rec.get("deterministic", {})
            n_sug = sum(len(v) for v in sug.values())
            pct = det.get("compliance_pct")
            label = (f"{rec['ts']} · {rec.get('source','review')} · "
                     f"{'—' if pct is None else f'{pct}%'} compliance · "
                     f"{n_sug} suggestion(s) · draft {rec['draft_sha256'][:10]}")
            with st.expander(label):
                if f := det.get("funnel"):
                    st.caption(f"funnel: {f.get('n_clauses')} clauses → "
                               f"{f.get('n_pairs')} pairs → "
                               f"{f.get('n_muril_flagged')} MuRIL flags → "
                               f"{f.get('n_conflicts')} verified conflicts")
                for c in sug.get("conflicts", []):
                    st.markdown(f"🔴 **Conflict vs `{c['gr_code']}`** — {c['reason']}")
                    if c.get("suggested_fix"):
                        st.caption(f"suggested fix: {c['suggested_fix']}")
                for w in sug.get("citation_warnings", []):
                    if w.get("kind") == "superseded":
                        st.markdown(f"⚠️ cites **{w.get('cited')}**, superseded by "
                                    f"`{w.get('superseded_by')}`")
                    else:
                        st.markdown(f"🕐 cited GR dated **{w.get('cited_date')}** has "
                                    f"{w.get('n_newer')} newer same-subject GR(s)")
                for t in sug.get("terminology", []):
                    st.markdown(f"📝 [{t.get('kind')}] `{t.get('found')}` → approved "
                                f"term available")
                if fails := det.get("failed_checks"):
                    st.caption(f"failed template checks: {', '.join(fails)}")
                if edit := rec.get("human_edit"):
                    st.markdown(f"**Human edits since previous submission** "
                                f"(+{edit['lines_added']} / −{edit['lines_removed']} lines)")
                    st.code(edit["diff"] or "(no line changes)", language="diff")
                else:
                    st.caption("first recorded version of this draft — no prior "
                               "submission to diff against")
    st.caption("Local file only — `data/audit_trail.jsonl` never leaves this "
               "machine (NFR-2).")

with t_about:
    slide = ROOT / "demo" / "architecture_slide.html"
    if slide.exists():
        components.html(slide.read_text(encoding="utf-8"), height=560, scrolling=False)
    st.markdown(
        """
**ClauseGuard** (Problem 1: MAHA-GR-ALIGN) reviews a draft Maharashtra Government Resolution against a corpus of
real GRs (archival copies via the Wayback Machine — the live portal returned 503 during
the hackathon window).

**Honest evaluation**: fine-tuned macro-F1 0.9134 (0.8957 on the leak-free subset) vs a
protocol-matched lexical baseline (0.7754) and zero-shot Llama-70B (0.6521). We also
blind-checked our own labels (~26% noise found in the synthetic C/S classes) and report
accuracy against adjudicated truth — see `EVAL_TABLE.md` and `DATASET_CARD.md`.

Built for VJTI AI Hackathon 2026 · Problem 1 · "Shaping Digital Governance" · MIT license.
        """
    )
