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
import json
import os
import re
import sys
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "draftgen"))
sys.path.append(str(ROOT / "src" / "llm"))
sys.path.append(str(ROOT / "src" / "ingest"))
from generate import SAMPLE, _digit_runs, financial_year, unique_code  # noqa: E402
from clients import LLMError, llm_with_fallback  # noqa: E402
from devanagari import to_ascii_digits  # noqa: E402

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
    # --- the seven scholarship-adjacent departments -------------------------
    # Added with the mahGRs corpus (Aug 2026). Before this, every GR from these
    # departments — 11,109 of 23,333, i.e. 48% — fell through to DEFAULT_DEPT and
    # was drafted under Higher & Technical Education's name, desk and file
    # grammar. Names, file prefixes, desks and directorates are the most frequent
    # forms observed in each department's own GRs; budget heads are the major
    # heads those GRs actually charge to (sub-major/minor/sub-head are
    # scheme-specific and belong to the desk, so they are not invented here).
    "24": {
        "name": {"mr": "आदिवासी विकास विभाग", "en": "Tribal Development Department"},
        "minister": {"mr": "आदिवासी विकास", "en": "Tribal Development"},
        "file_prefix": {"mr": "आविवि", "en": "TDD"},
        "desk": {"mr": "कार्यासन-6", "en": "Desk-6"},
        "directorate": {"mr": "आयुक्त, आदिवासी विकास आयुक्तालय, महाराष्ट्र राज्य, नाशिक",
                        "en": "Commissioner, Tribal Development Commissionerate, "
                              "Maharashtra State, Nashik"},
        "budget_heads": ["2225", "2401"],
        "keywords": ["आदिवासी", "अनुसूचित जमाती", "आश्रमशाळा", "वसतीगृह", "स्वयंम",
                     "tribal", "ashram school"],
    },
    "34": {
        "name": {"mr": "इतर मागास बहुजन कल्याण विभाग",
                 "en": "Other Backward Bahujan Welfare Department"},
        "minister": {"mr": "इतर मागास बहुजन कल्याण", "en": "Other Backward Bahujan Welfare"},
        "file_prefix": {"mr": "इमाव", "en": "OBC"},
        "desk": {"mr": "योजना-1", "en": "Plan-1"},
        "directorate": {"mr": "संचालक, इतर मागास बहुजन कल्याण संचालनालय, महाराष्ट्र राज्य, पुणे",
                        "en": "Director, Other Backward Bahujan Welfare Directorate, "
                              "Maharashtra State, Pune"},
        "budget_heads": ["2225"],
        "keywords": ["इतर मागासवर्ग", "विमुक्त जाती", "भटक्या जमाती", "विशेष मागास प्रवर्ग",
                     "ज्ञानज्योती", "धनगर", "obc", "nomadic"],
    },
    "14": {
        "name": {"mr": "अल्पसंख्याक विकास विभाग", "en": "Minorities Development Department"},
        "minister": {"mr": "अल्पसंख्याक विकास", "en": "Minorities Development"},
        "file_prefix": {"mr": "अविवि", "en": "MDD"},
        "desk": {"mr": "का-9", "en": "Desk-9"},
        "directorate": {"mr": "आयुक्त, अल्पसंख्याक आयुक्तालय, छत्रपती संभाजीनगर",
                        "en": "Commissioner, Minorities Commissionerate, "
                              "Chhatrapati Sambhajinagar"},
        "budget_heads": ["2235"],
        "keywords": ["अल्पसंख्याक", "मदरसा", "हज", "उर्दू", "वक्फ", "minority", "madrasa"],
    },
    "35": {
        # renamed from दिव्यांग कल्याण विभाग; older GRs still sign under सा.न्या.
        "name": {"mr": "दिव्यांग सक्षमीकरण विभाग", "en": "Divyang Empowerment Department"},
        "minister": {"mr": "दिव्यांग कल्याण", "en": "Divyang Welfare"},
        "file_prefix": {"mr": "दिव्यांग", "en": "EDD"},
        "desk": {"mr": "दि.क.1", "en": "DE-1"},
        "directorate": {"mr": "आयुक्त, दिव्यांग सक्षमीकरण आयुक्तालय, महाराष्ट्र राज्य, पुणे",
                        "en": "Commissioner, Divyang Empowerment Commissionerate, "
                              "Maharashtra State, Pune"},
        "budget_heads": ["2235"],
        "keywords": ["दिव्यांग", "अपंग", "सक्षमीकरण", "कर्णबधीर", "अंध", "divyang"],
    },
    "03": {
        # renamed twice; the current form is used from ~2023 onward
        "name": {"mr": "कौशल्य, रोजगार, उद्योजकता व नाविन्यता विभाग",
                 "en": "Skill, Employment, Entrepreneurship and Innovation Department"},
        "minister": {"mr": "कौशल्य, रोजगार, उद्योजकता व नाविन्यता",
                     "en": "Skill, Employment, Entrepreneurship and Innovation"},
        "file_prefix": {"mr": "कौविउ", "en": "SED"},
        "desk": {"mr": "व्यशि-1", "en": "VE-1"},
        "directorate": {"mr": "संचालक, व्यवसाय शिक्षण व प्रशिक्षण संचालनालय, "
                              "महाराष्ट्र राज्य, मुंबई",
                        "en": "Director, Vocational Education and Training, "
                              "Maharashtra State, Mumbai"},
        "budget_heads": ["2230", "2225"],
        "keywords": ["कौशल्य", "आयटीआय", "औद्योगिक प्रशिक्षण", "रोजगार", "उद्योजकता",
                     "अप्रेंटिस", "skill", "iti", "apprentice"],
    },
    "13": {
        "name": {"mr": "वैद्यकीय शिक्षण व औषधी द्रव्ये विभाग",
                 "en": "Medical Education and Drugs Department"},
        "minister": {"mr": "वैद्यकीय शिक्षण", "en": "Medical Education"},
        "file_prefix": {"mr": "वैशिवि", "en": "MED"},
        "desk": {"mr": "शिक्षण-2", "en": "Edu-2"},
        "directorate": {"mr": "आयुक्त, वैद्यकीय शिक्षण व संशोधन संचालनालय, मुंबई",
                        "en": "Commissioner, Directorate of Medical Education and "
                              "Research, Mumbai"},
        "budget_heads": ["2210", "4210"],
        "keywords": ["वैद्यकीय", "एमबीबीएस", "बीडीएस", "रुग्णालय", "आरोग्य विज्ञान",
                     "औषधी", "medical", "mbbs"],
    },
    "30": {
        "name": {"mr": "महिला व बाल विकास विभाग",
                 "en": "Women and Child Development Department"},
        "minister": {"mr": "महिला व बाल विकास", "en": "Women and Child Development"},
        "file_prefix": {"mr": "एबावि", "en": "WCD"},
        "desk": {"mr": "का.6", "en": "Desk-6"},
        "directorate": {"mr": "आयुक्त, महिला व बाल विकास आयुक्तालय, महाराष्ट्र राज्य, पुणे",
                        "en": "Commissioner, Women and Child Development "
                              "Commissionerate, Maharashtra State, Pune"},
        "budget_heads": ["2235", "2236"],
        "keywords": ["अंगणवाडी", "बालगृह", "महिला", "बाल विकास", "पोषण", "स्वाधारगृह",
                     "सखी", "anganwadi", "women"],
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
            # the nearest CLAUSE BODY rides along: the AI wording rail adapts
            # real official phrasing instead of free-writing, and the wording
            # audit needs the reference text to measure fidelity against
            "clause": (cand.get("clause") or "")[:400],
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


def propose_gr_number(dept: dict, lang: str, on_date: date_cls, topic: str,
                      prefix: str = None) -> str:
    """<प्रत्यय>-<वर्ष>/प्र.क्र.<n>/<कार्यासन> with a stable per-topic serial. An AI-
    proposed prefix is used only when it validates against the real grammar."""
    n = int(hashlib.sha256(topic.encode("utf-8")).hexdigest(), 16) % 199 + 1
    if not (prefix and re.fullmatch(r"[ऀ-ॿA-Za-z]{2,8}", prefix)):
        prefix = dept["file_prefix"][lang]
    if lang == "mr":
        return f"{prefix}-{on_date.year}/प्र.क्र.{n}/{dept['desk']['mr']}"
    return f"{prefix}-{on_date.year}/C.R.{n}/{dept['desk']['en']}"


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


# ---------- AI prose layer (sourced-or-blank rail) ----------

AI_PROMPT = {
    "mr": """तुम्ही महाराष्ट्र शासनाच्या शासन निर्णयाचा (GR) फॉर्म भरत आहात.
विषय (वापरकर्त्याने दिलेला): {topic}

संदर्भ म्हणून खालील खऱ्या शासन निर्णयांचे विषय व नमुना-कलमे दिली आहेत —
त्यांतील मजकुरात OCR-दोष असू शकतो; तुम्ही मात्र शुद्ध प्रमाण मराठीत लिहा:
{precedent_lines}

फक्त JSON परत करा, keys:
- "subject": विषय-ओळ, शेवट "बाबत." असा
- "file_prefix": फाईल क्रमांकासाठी 2-6 अक्षरी संक्षेप (उदा. शिष्यवृ, सादिल)
- "background": प्रस्तावनेचा एक औपचारिक परिच्छेद, शेवट "ही बाब शासनाच्या
  विचाराधीन होती." असा
- "clauses": बरोबर {n} कार्यवाहीचे मुद्दे — प्रत्येक घटक {{"text": "...",
  "src": <वरीलपैकी ज्या संदर्भ-कलमाच्या शब्दयोजनेवर आधारित आहे त्याचा क्रमांक,
  नाहीतर -1>}} असा object. शक्य तिथे संदर्भ-कलमाची अधिकृत शब्दयोजना कमीत कमी
  बदलांसह वापरा — नव्याने वाक्यरचना करू नका. क्रमांक लिहू नका; प्रत्येक मुद्दा
  15-30 शब्दांचा, शासकीय शैलीत.
- "needs_numbers": ज्या रकमा/दिनांक/टक्केवारी तुम्हाला माहीत नाहीत त्यांबद्दलचे
  प्रश्न (array of strings, कमाल 5)
रक्कम/दिनांक माहीत नसल्यास मजकुरात "____" वापरा. विषयात किंवा वरील संदर्भांत
नसलेली कोणतीही संख्या, योजना-नाव किंवा संस्था-नाव स्वतः लिहू नका. JSON पूर्ण
करा — मध्येच थांबू नका.""",
    "en": """You are filling the form for a Maharashtra Government Resolution (GR).
Topic (from the user): {topic}

Subjects and sample clauses of real precedent GRs are given below — their text
may carry OCR damage; you must write clean formal English:
{precedent_lines}

Return ONLY JSON with keys:
- "subject": the subject line, ending with a full stop
- "file_prefix": a 2-6 letter file-number abbreviation (e.g. TEM, SCH)
- "background": ONE formal Preamble paragraph ending with the convention that
  the matter "was under consideration of the Government."
- "clauses": exactly {n} operative clauses — each an object {{"text": "...",
  "src": <index of the precedent clause above whose official wording it
  adapts, else -1>}}. Wherever possible ADAPT the precedent clause's official
  phrasing with minimal edits rather than writing fresh prose. No numbering
  inside the strings; each 15-30 words, imperative government style.
- "needs_numbers": questions about any amounts/dates/percentages you do not
  know (array of strings, max 5)
Use "____" in the text wherever an amount or date is unknown. Do not invent
any number, scheme name or institution name that is not in the topic or the
precedents above. Complete the JSON — never stop midway.""",
}

_DIGIT_RUN_RE = re.compile(r"[0-9०-९][0-9०-९,]*")


def scrub_unsourced_digits(text: str, allowed: set) -> tuple:
    """Replace every digit run whose normalised form is not in `allowed` with
    a ____ blank. Returns (scrubbed_text, [removed runs]). This is the prefill
    rail: every number the user sees is sourced or blank."""
    removed = []

    def sub(m):
        runs = _digit_runs(m.group(0))
        if runs and not runs <= allowed:
            removed.append(m.group(0))
            return "____"
        # A sourced number may still arrive in Devanagari — clean precedent
        # subjects are full of them and the AI copies the script it sees. The
        # canonical draft stays ASCII (gr_layout converts at render time, and
        # only for Marathi), so fold here rather than let Devanagari numerals
        # reach the English PDF and the form digit audit.
        return to_ascii_digits(m.group(0))

    return _DIGIT_RUN_RE.sub(sub, text or ""), removed


# ---------- entity + word-date rail (round 3) ----------
# The digit scrub cannot see "MahaDBT", "एकात्मिक बालविकास योजना" or "thirty-first
# March". Candidate ENTITIES are detected narrowly (compound scheme/portal names,
# CamelCase, multi-word TitleCase, 3+ letter acronyms, quoted spans) and month
# names; anything that does not trace to the topic/precedents is blanked.
# NOTE: Devanagari matras are NOT \w in Python re, so \b misfires around
# Marathi words — these patterns use explicit block lookarounds instead.
_ENTITY_RES = [
    re.compile(r"[‘’'\"«“]([^'\"»”‘’]{3,60})['\"»”’]"),  # quoted spans
    re.compile(r"(?<![ऀ-ॿ])[ऀ-ॿ]{3,}(?:योजना|अभियान|पोर्टल|महामंडळ|प्राधिकरण)(?![ऀ-ॿ])"),
    re.compile(r"\b[A-Za-z]*[a-z][A-Z][A-Za-z]+\b"),     # CamelCase (MahaDBT)
    re.compile(r"\b[A-Z]{2,}[a-z][A-Za-z]*\b"),          # PMKisan-style mixed caps
    re.compile(r"\b(?:[A-Z][a-z]+ ){1,3}(?:Yojana|Abhiyan|Portal|Mission|Scheme)\b"),
    re.compile(r"\b[A-Z]{3,}\b"),                        # acronyms
]
_MONTHS = ("जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून", "जुलै",
           "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर",
           "January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")
_MONTH_RE = re.compile(r"(?<![ऀ-ॿA-Za-z])(" + "|".join(_MONTHS) + r")(?![ऀ-ॿa-z])")
# generic government vocabulary that must never be treated as an entity
_ENTITY_STOP = {"शासन", "निर्णय", "महाराष्ट्र", "मंत्रालय", "मुंबई", "विभाग",
                "GR", "PDF", "DBT", "Government", "Resolution", "Maharashtra"}


def _norm_span(s: str) -> str:
    return " ".join((s or "").lower().split())


def scrub_unsourced_entities(text: str, allowed_blob: str) -> tuple:
    """Blank every detected entity/month whose normalised form does not occur
    in the allowed sources. Returns (scrubbed_text, [removed spans])."""
    removed = []
    blob = _norm_span(allowed_blob)
    out = text or ""
    spans = set()
    for rx in _ENTITY_RES:
        for m in rx.finditer(out):
            span = m.group(1) if m.groups() else m.group(0)
            spans.add(span.strip())
    for m in _MONTH_RE.finditer(out):
        spans.add(m.group(1))
    for span in sorted(spans, key=len, reverse=True):
        if span in _ENTITY_STOP or "____" in span or not span:
            continue
        if _norm_span(span) in blob:
            continue
        removed.append(span)
        out = out.replace(span, "____")
    return out, removed


_TEMPLATES = {"loaded": False, "by_dept": {}}


def templates_for(dept_code: str, k: int = 2) -> list:
    """Top canonical clause templates for a department, mined from the full
    corpus by src/draftgen/mine_templates.py (verbatim in >=20 real GRs).
    Empty list when the mined file is absent — the rail degrades gracefully."""
    if not _TEMPLATES["loaded"]:
        p = ROOT / "data" / "clause_templates.jsonl"
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    _TEMPLATES["by_dept"].setdefault(row["dept_code"], []).append(row)
        _TEMPLATES["loaded"] = True
    return _TEMPLATES["by_dept"].get(dept_code, [])[:k]


def _char3grams(s: str) -> set:
    s = re.sub(r"[0-9०-९\s]+", " ", _norm_span(s))
    return {s[i:i + 3] for i in range(len(s) - 2)} if len(s) >= 3 else set()


def wording_audit(clauses: list, srcs: list, precedents: list,
                  threshold: float = 0.28) -> list:
    """Per-clause wording-fidelity report: char-3-gram containment of the
    generated clause in its cited precedent clause (digits stripped — the
    digit rails own numerals). Below threshold → 'unverified' — the UI flags
    the clause and the export carries the DRAFT marker."""
    report = []
    for i, clause in enumerate(clauses):
        src = srcs[i] if i < len(srcs) else -1
        ref = precedents[src]["clause"] if 0 <= src < len(precedents) else ""
        if not ref:
            report.append({"idx": i, "src": src, "containment": None,
                           "verdict": "no-precedent"})
            continue
        gen = _char3grams(clause)
        containment = (len(gen & _char3grams(ref)) / len(gen)) if gen else 0.0
        report.append({"idx": i, "src": src,
                       "containment": round(containment, 3),
                       "verdict": "grounded" if containment >= threshold
                       else "unverified"})
    return report


def ai_prefill(topic: str, lang: str, precedents: list, n_clauses: int = 3,
               llm_fn=None, templates: list = None) -> dict:
    """One LLM call proposing PROSE only: subject, file prefix, background,
    clauses, and the open questions. Raises LLMError on failure; the caller
    scrubs every unsourced digit before anything reaches the form."""
    fixture = os.environ.get("CG_PREFILL_FIXTURE")
    if fixture:
        data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    else:
        # canonical dept templates ride behind the precedents in the same
        # index space — the model may cite either as a wording source
        entries = ([(p["date_iso"], p["subject"][:150], p.get("clause", ""))
                    for p in precedents]
                   + [("प्रमाण-नमुना", f"वापर {t['n_grs']} शासन निर्णयांत",
                       t["text"]) for t in (templates or [])])
        lines = "\n".join(
            f"[{i}] [{a}] {b}" + (f"\n    कलम/clause: {c[:220]}" if c else "")
            for i, (a, b, c) in enumerate(entries)) or "- (no precedents found)"
        # wording quality is the whole point of this call — Gemini leads the
        # Indic benchmarks by a wide margin, so it drafts; Groq is the fallback
        fn = llm_fn or (lambda p, **kw: llm_with_fallback(p, preferred="gemini", **kw))
        raw = fn(AI_PROMPT[lang].format(topic=topic, precedent_lines=lines,
                                        n=n_clauses),
                 temperature=0.3, max_tokens=2000, json_mode=True)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            data = json.loads(m.group(0) if m else raw)
        except json.JSONDecodeError as e:
            raise LLMError(f"topic-prefill returned malformed JSON: {e}")
    try:
        clauses, srcs = [], []
        for c in data.get("clauses") or []:
            if isinstance(c, dict):                 # round-3 shape {text, src}
                clauses.append(str(c.get("text") or ""))
                try:
                    srcs.append(int(c.get("src", -1)))
                except (TypeError, ValueError):
                    srcs.append(-1)
            else:                                    # legacy/fixture: plain string
                clauses.append(str(c))
                srcs.append(-1)
        return {"subject": str(data.get("subject") or ""),
                "file_prefix": str(data.get("file_prefix") or ""),
                "background": str(data.get("background") or ""),
                "clauses": clauses, "clause_srcs": srcs,
                "needs_numbers": [str(q) for q in
                                  (data.get("needs_numbers") or [])][:5]}
    except (TypeError, AttributeError) as e:
        raise LLMError(f"topic-prefill JSON had a wrong shape: {e}")


def topic_prefill(topic: str, lang: str = "mr", corpus=None, retrieve_fn=None,
                  use_ai: bool = True, llm_fn=None, on_date=None,
                  n_clauses: int = 3) -> dict:
    """Orchestrator. Deterministic skeleton first; the AI layer only replaces
    PROSE on top of it, digit-scrubbed against (topic ∪ shown precedents ∪
    calendar). Never dead-ends: any AI failure leaves the deterministic form
    intact and reports itself in ai_error."""
    form = deterministic_prefill(topic, lang, corpus, retrieve_fn, on_date)
    result = {"form": form, "ai_used": False, "ai_error": None,
              "scrubbed": [], "scrubbed_entities": [], "wording": None,
              "needs_numbers": []}
    if not use_ai:
        return result
    tmpls = templates_for(form["dept_code"])
    try:
        prose = ai_prefill(topic, lang, form["precedents"],
                           n_clauses=n_clauses, llm_fn=llm_fn, templates=tmpls)
    except LLMError as e:
        result["ai_error"] = str(e)
        return result

    y = form["date"].year
    allowed = (_digit_runs(topic)
               | _digit_runs(" ".join(f"{p['date_iso']} {p['subject'][:150]}"
                                      for p in form["precedents"]))
               | _digit_runs(form["fy"])
               | {str(y), str(y + 1), f"{y % 100:02d}", f"{(y + 1) % 100:02d}"})
    # everything the AI was shown = the only legitimate source of entities
    dept = DEPARTMENTS[form["dept_code"]]
    ent_blob = " ".join([topic, dept["name"]["mr"], dept["name"]["en"],
                         *(f"{p['subject']} {p.get('clause', '')}"
                           for p in form["precedents"]),
                         *(t["text"] for t in tmpls)])
    scrubbed_all, ent_all = [], []

    def _rails(text: str) -> str:
        out, rem = scrub_unsourced_digits(text, allowed)
        scrubbed_all.extend(rem)
        out, rem = scrub_unsourced_entities(out, ent_blob)
        ent_all.extend(rem)
        return out

    if prose["subject"].strip():
        subj = _rails(prose["subject"].strip())
        form["subject"] = subj if lang == "en" or subj.endswith("बाबत.") \
            else _subject_line(subj, lang)
    if prose["background"].strip():
        form["background"] = _rails(prose["background"].strip())
    srcs = prose.get("clause_srcs") or []
    if prose["clauses"]:
        cleaned, kept_srcs = [], []
        for i, c in enumerate(prose["clauses"]):
            c2 = _rails(c.strip())
            if c2:
                cleaned.append(c2)
                kept_srcs.append(srcs[i] if i < len(srcs) else -1)
        if cleaned:
            form["clauses"] = cleaned
            # wording-fidelity: each AI clause measured against the precedent
            # clause (or dept template) it claims to adapt — sourced-or-flagged,
            # like the digits. Templates share the prompt's index space.
            refs = form["precedents"] + [{"clause": t["text"]} for t in tmpls]
            form["wording_audit"] = wording_audit(cleaned, kept_srcs, refs)
    form["gr_number"] = propose_gr_number(
        DEPARTMENTS[form["dept_code"]], lang, form["date"], topic,
        prefix=prose["file_prefix"].strip() or None)
    form["code"] = unique_code(form["date"], form["subject"])
    result.update(ai_used=True, scrubbed=scrubbed_all,
                  scrubbed_entities=ent_all,
                  wording=form.get("wording_audit"),
                  needs_numbers=prose["needs_numbers"])
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
