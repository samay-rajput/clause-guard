"""Topic → prefilled GR form (round 2: anyone types a topic and gets a
complete, editable draft form seeded from real precedent GRs).

Deterministic core, garble-aware by construction:

* Precedents come from the same e5/Chroma index the conflict pipeline uses —
  a topic-level query, wider distance cut than the conflict path's 0.18.
* The DEPARTMENT is inferred from the precedents' 18-digit codes (the last
  two digits are the issuing department — the only garble-proof key in the
  corpus); the canonical clean names live in the curated table below, never
  the corrupted corpus `department` strings.
* वाचा references are built ONLY from metadata (code + authoritative
  date_iso) in the portal's own citation grammar, so the reference checker
  links every one of them without special-casing.
* The GR file number follows the real grammar <प्रत्यय>-<वर्ष>/प्र.क्र.<n>/<कार्यासन>
  with a stable per-topic serial.

The AI layer (ai_prefill) only ever proposes PROSE on top of this skeleton;
every numeral it emits must trace to a shown source or it is scrubbed to a
"____" blank the user must fill (see scrub_unsourced_digits).
"""
import hashlib
import re
import sys
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "draftgen"))
from generate import SAMPLE, financial_year, unique_code  # noqa: E402

MAX_TOPIC_DISTANCE = 0.30      # topic queries sit farther out than clause pairs
DEFAULT_DEPT = "08"

DEPARTMENTS = {
    "08": {
        "name": {"mr": "उच्च व तंत्र शिक्षण विभाग",
                 "en": "Higher and Technical Education Department"},
        "minister": {"mr": "उच्च व तंत्र शिक्षण", "en": "Higher and Technical Education"},
        "file_prefix": {"mr": "तंशि", "en": "TEM"},
        "desk": {"mr": "ताशि-2", "en": "TE-2"},
        "directorate": {"mr": "संचालक, तंत्रशिक्षण संचालनालय, महाराष्ट्र राज्य, मुंबई",
                        "en": "Director of Technical Education, Maharashtra State, Mumbai"},
        "budget_heads": ["2203-00-105-01", "2203-00-001-01"],
        "keywords": ["तंत्रनिकेतन", "महाविद्यालय", "विद्यापीठ", "शिष्यवृत्ती",
                     "अभियांत्रिकी", "तंत्र शिक्षण", "उच्च शिक्षण", "polytechnic",
                     "college", "university", "scholarship", "technical"],
    },
    "21": {
        "name": {"mr": "शालेय शिक्षण व क्रीडा विभाग",
                 "en": "School Education and Sports Department"},
        "minister": {"mr": "शालेय शिक्षण", "en": "School Education"},
        "file_prefix": {"mr": "शैशि", "en": "SED"},
        "desk": {"mr": "एसएम-4", "en": "SM-4"},
        "directorate": {"mr": "आयुक्त (शिक्षण), शिक्षण आयुक्तालय, महाराष्ट्र राज्य, पुणे",
                        "en": "Commissioner (Education), Education Commissionerate, "
                              "Maharashtra State, Pune"},
        "budget_heads": ["2202-00-101-01", "2202-00-109-01"],
        "keywords": ["शाळा", "शालेय", "जिल्हा परिषद", "क्रीडा", "सादिल",
                     "प्राथमिक शिक्षण", "माध्यमिक", "school", "sports",
                     "zilla parishad", "primary education"],
    },
    "22": {
        "name": {"mr": "सामाजिक न्याय व विशेष सहाय्य विभाग",
                 "en": "Social Justice and Special Assistance Department"},
        "minister": {"mr": "सामाजिक न्याय", "en": "Social Justice"},
        "file_prefix": {"mr": "सामअ", "en": "SJS"},
        "desk": {"mr": "एसजेएस-1", "en": "SJS-1"},
        "directorate": {"mr": "आयुक्त, समाज कल्याण आयुक्तालय, महाराष्ट्र राज्य, पुणे",
                        "en": "Commissioner, Social Welfare Commissionerate, "
                              "Maharashtra State, Pune"},
        "budget_heads": ["2225-00-277-01"],
        "keywords": ["मागास", "अनुसूचित", "दिव्यांग", "सामाजिक न्याय", "वसतिगृह",
                     "विशेष सहाय्य", "निवृत्तिवेतन", "scheduled", "backward",
                     "hostel", "disability", "pension"],
    },
}


def _copy_to(dept: dict, lang: str) -> list:
    """Protocol-ordered distribution list, modelled on the gold specimen."""
    d = lambda k: dept[k][lang]  # noqa: E731
    if lang == "mr":
        return [
            "मा. मुख्यमंत्री यांचे प्रधान सचिव, मंत्रालय, मुंबई",
            "मा. उपमुख्यमंत्री (वित्त व नियोजन) यांचे सचिव, मंत्रालय, मुंबई",
            f"मा. मंत्री ({d('minister')}) यांचे खाजगी सचिव, मंत्रालय, मुंबई",
            "मा. मुख्य सचिव, महाराष्ट्र शासन, मंत्रालय, मुंबई",
            "अपर मुख्य सचिव, वित्त विभाग, मंत्रालय, मुंबई",
            f"प्रधान सचिव, {d('name')}, मंत्रालय, मुंबई",
            d("directorate"),
            "जिल्हाधिकारी, सर्व",
            "महालेखापाल (लेखा व अनुज्ञेयता)-1/2 महाराष्ट्र, मुंबई/नागपूर",
            "महालेखापाल (लेखापरीक्षा)-1/2, महाराष्ट्र, मुंबई/नागपूर",
            f"{d('name')}ातील सर्व कार्यासने",
            f"निवड नस्ती, {d('desk')}.",
        ]
    return [
        "Principal Secretary to the Hon. Chief Minister, Mantralaya, Mumbai",
        f"Private Secretary to the Hon. Minister ({d('minister')}), Mantralaya, Mumbai",
        f"Principal Secretary, {d('name')}, Mantralaya, Mumbai",
        d("directorate"),
        "Accountant General (A&E)-1/2, Maharashtra, Mumbai/Nagpur",
        f"All desks, {d('name')}",
        f"Select file, {d('desk')}.",
    ]


def retrieve_precedents(topic: str, corpus=None, k: int = 8, retrieve_fn=None,
                        max_grs: int = 4) -> list:
    """Nearest real GRs for a topic — deduped per GR, joined to the full
    corpus record (for the authoritative date_iso) when a corpus is given."""
    if retrieve_fn is None:
        sys.path.append(str(ROOT / "src" / "index"))
        from build_index import retrieve as retrieve_fn
    by_code = {r["gr_code"]: r for r in corpus or []}
    best = {}
    for cand in retrieve_fn(topic, k=k):
        if cand.get("distance", 1.0) > MAX_TOPIC_DISTANCE:
            continue
        code = cand["gr_code"]
        if code not in best or cand["distance"] < best[code]["distance"]:
            best[code] = cand
    out = []
    for cand in sorted(best.values(), key=lambda c: c["distance"])[:max_grs]:
        rec = by_code.get(cand["gr_code"], {})
        out.append({
            "gr_code": cand["gr_code"],
            "distance": round(cand["distance"], 4),
            "subject": (rec.get("subject") or cand.get("subject") or "")[:200],
            "date_iso": rec.get("date_iso") or f"{cand['gr_code'][:4]}-"
                        f"{cand['gr_code'][4:6]}-{cand['gr_code'][6:8]}",
            "dept_code": cand["gr_code"][-2:],
        })
    return out


def infer_department(precedents: list, topic: str) -> tuple:
    """(dept_code, DEPARTMENTS entry) — majority vote over the precedents'
    code-derived dept digits; keyword fallback; stable default."""
    low = topic.lower()
    votes = {}
    for p in precedents:
        c = p.get("dept_code")
        if c in DEPARTMENTS:
            votes[c] = votes.get(c, 0) + 1
    if votes:
        top = max(votes.values())
        tied = sorted(c for c, v in votes.items() if v == top)
        if len(tied) > 1:
            # break ties by topic keywords, then by the nearest precedent
            for code in tied:
                if any(kw.lower() in low for kw in DEPARTMENTS[code]["keywords"]):
                    return code, DEPARTMENTS[code]
            for p in sorted(precedents, key=lambda p: p["distance"]):
                if p["dept_code"] in tied:
                    return p["dept_code"], DEPARTMENTS[p["dept_code"]]
        return tied[0], DEPARTMENTS[tied[0]]
    for code, dept in DEPARTMENTS.items():
        if any(kw.lower() in low for kw in dept["keywords"]):
            return code, dept
    return DEFAULT_DEPT, DEPARTMENTS[DEFAULT_DEPT]


def build_references(precedents: list, lang: str) -> list:
    """वाचा entries from precedent metadata only (never the garbled text), in
    the portal's सांकेतांक citation grammar, oldest first — exactly the shape
    extract_citations parses, so the reference checker links each one."""
    refs = []
    for p in sorted(precedents, key=lambda p: p["date_iso"])[:3]:
        y, m, d = p["date_iso"].split("-")
        dept = DEPARTMENTS.get(p.get("dept_code"), DEPARTMENTS[DEFAULT_DEPT])
        if lang == "mr":
            text = (f"शासन निर्णय, {dept['name']['mr']}, सांकेतांक {p['gr_code']}, "
                    f"दि.{d}.{m}.{y}.")
        else:
            text = (f"Government Resolution, {dept['name']['en']}, Unique Code "
                    f"{p['gr_code']}, dated {d}.{m}.{y}.")
        refs.append({"text": text, "gr_code": p["gr_code"],
                     "date": f"{d}.{m}.{y}", "source": "corpus"})
    return refs


def propose_gr_number(dept: dict, lang: str, on_date: date_cls, topic: str) -> str:
    """<प्रत्यय>-<वर्ष>/प्र.क्र.<n>/<कार्यासन> with a stable per-topic serial."""
    n = int(hashlib.sha256(topic.encode("utf-8")).hexdigest(), 16) % 199 + 1
    if lang == "mr":
        return f"{dept['file_prefix']['mr']}-{on_date.year}/प्र.क्र.{n}/{dept['desk']['mr']}"
    return f"{dept['file_prefix']['en']}-{on_date.year}/C.R.{n}/{dept['desk']['en']}"


def _subject_line(topic: str, lang: str) -> str:
    t = topic.strip().rstrip(".")
    if lang == "mr":
        return t if t.endswith("बाबत") else f"{t}बाबत." if t.endswith("देण्या") \
            else f"{t} करण्याबाबत." if not t.endswith("बाबत") else f"{t}."
    return f"{t}."


def deterministic_prefill(topic: str, lang: str = "mr", corpus=None,
                          retrieve_fn=None, on_date=None) -> dict:
    """A complete GRForm from the topic alone — no LLM anywhere. The prose is
    templated (the AI layer improves it when available); every structural
    field is real: department, references, file number, budget head, date,
    code, distribution list."""
    on_date = on_date or date_cls.today()
    precedents = retrieve_precedents(topic, corpus, retrieve_fn=retrieve_fn)
    dept_code, dept = infer_department(precedents, topic)
    subject = _subject_line(topic, lang)
    if lang == "mr":
        background = f"{topic.strip().rstrip('.')} ही बाब शासनाच्या विचाराधीन होती."
        clauses = [f"{topic.strip().rstrip('.')} यास शासन मान्यता देण्यात येत आहे.",
                   "सदर शासन निर्णय निर्गमित झाल्याच्या दिनांकापासून लागू राहील."]
    else:
        background = (f"The matter of {topic.strip().rstrip('.')} was under "
                      f"consideration of the Government.")
        clauses = [f"Approval of the Government is hereby accorded to "
                   f"{topic.strip().rstrip('.')}.",
                   "This Government Resolution shall come into effect from the "
                   "date of its issue."]
    return {
        "lang": lang,
        "topic": topic.strip(),
        "subject": subject,
        "department": dept["name"][lang],
        "dept_code": dept_code,
        "gr_number": propose_gr_number(dept, lang, on_date, topic),
        "date": on_date,
        "references": build_references(precedents, lang),
        "background": background,
        "clauses": clauses,
        "budget_head": dept["budget_heads"][0],
        "signatory": SAMPLE[lang]["signatory"],
        "designation": SAMPLE[lang]["designation"],
        "copy_to": _copy_to(dept, lang),
        "fy": financial_year(on_date),
        "code": unique_code(on_date, subject),
        "precedents": precedents,
    }


def topic_prefill(topic: str, lang: str = "mr", corpus=None, retrieve_fn=None,
                  use_ai: bool = False, llm_fn=None, on_date=None) -> dict:
    """Orchestrator: deterministic skeleton now; the audited AI prose layer
    (ai_prefill) plugs in on top of it. Never dead-ends: any AI failure
    leaves the deterministic form intact."""
    form = deterministic_prefill(topic, lang, corpus, retrieve_fn, on_date)
    result = {"form": form, "ai_used": False, "ai_error": None,
              "scrubbed": [], "needs_numbers": []}
    # use_ai branch lands with ai_prefill (audited prose proposal)
    return result


if __name__ == "__main__":
    # Offline self-test: injected retrieval, no index, no LLM.
    sys.stdout.reconfigure(encoding="utf-8")

    def fake_retrieve(q, k=8):
        return [
            {"gr_code": "202303151204391421", "distance": 0.18, "subject": "x",
             "department": "?", "date": "?", "gr_number": "?", "clause": "…"},
            {"gr_code": "202303151204391421", "distance": 0.22, "subject": "x",
             "department": "?", "date": "?", "gr_number": "?", "clause": "…"},
            {"gr_code": "202407191857335421", "distance": 0.24, "subject": "y",
             "department": "?", "date": "?", "gr_number": "?", "clause": "…"},
            {"gr_code": "202201011111111108", "distance": 0.29, "subject": "z",
             "department": "?", "date": "?", "gr_number": "?", "clause": "…"},
            {"gr_code": "209901011111111199", "distance": 0.45, "subject": "far",
             "department": "?", "date": "?", "gr_number": "?", "clause": "…"},
        ]

    topic = "जिल्हा परिषद शाळांना सादिल अनुदान वितरण"
    form = deterministic_prefill(topic, "mr", corpus=[], retrieve_fn=fake_retrieve,
                                 on_date=date_cls(2026, 8, 5))
    assert form["dept_code"] == "21", form["dept_code"]          # majority vote
    assert form["department"] == "शालेय शिक्षण व क्रीडा विभाग"
    assert len(form["precedents"]) == 3                          # dedup + cut
    assert form["subject"].endswith("बाबत.")
    assert re.match(r"^[^\s/]{2,8}-\d{4}/प्र\.क्र\.\d{1,3}/[^\s/]+$",
                    form["gr_number"]), form["gr_number"]
    assert form["references"][0]["date"] < form["references"][-1]["date"] or \
        len(form["references"]) == 1

    # every built reference must round-trip through the citation extractor
    sys.path.append(str(ROOT / "src" / "ingest"))
    from extract_metadata import extract_citations
    blob = "\n".join(r["text"] for r in form["references"])
    cited = extract_citations(blob)
    for r in form["references"]:
        assert any(r["gr_code"] in c for c in cited["cited_codes"]), \
            (r["text"], cited)

    # keyword fallback when retrieval returns nothing usable
    form2 = deterministic_prefill("दिव्यांग विद्यार्थ्यांसाठी वसतिगृह योजना", "mr",
                                  corpus=[], retrieve_fn=lambda q, k=8: [],
                                  on_date=date_cls(2026, 8, 5))
    assert form2["dept_code"] == "22", form2["dept_code"]

    en = deterministic_prefill("merit scholarship for polytechnic students", "en",
                               corpus=[], retrieve_fn=lambda q, k=8: [],
                               on_date=date_cls(2026, 8, 5))
    assert en["dept_code"] == "08" and en["gr_number"].startswith("TEM-2026/C.R.")
    print("prefill self-test OK —", form["gr_number"], "/", en["gr_number"])
