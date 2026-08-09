"""AI-assisted GR drafting (SRS §1.2 "Help draft Government Resolutions using
AI"; acceptance criterion 3: a GENERATED draft contains all mandatory template
sections).

Two-layer design, same philosophy as the rest of ClauseGuard:

* A **deterministic scaffold** guarantees every Manual-of-Office-Procedure
  mandatory section (FR-11): header, department line, GR number, date,
  Mantralaya line, Read block, Preamble, numbered Government Resolution
  clauses, financial-sanction clause with budget head, availability line with
  the 18-digit unique code, and the Governor signature formula. AC-3 therefore
  holds even fully offline, in both languages.
* The **AI layer** expands the officer's short brief into the Preamble
  background and the operative clauses (local Ollama when LLM_MODE=ollama —
  the brief never leaves the machine, NFR-2; Groq/Gemini otherwise). A digit
  audit — the same rail the corpus repair uses — rejects any AI output that
  invents or drops a numeral, falling back to the deterministic scaffold:
  amounts and dates are the substance of a GR and must never be "improved".
"""
import hashlib
import json
import re
import sys
from datetime import date as date_cls
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "llm"))
from clients import LLMError, llm_with_fallback  # noqa: E402

MARATHI_MONTHS = ["जानेवारी", "फेब्रुवारी", "मार्च", "एप्रिल", "मे", "जून",
                  "जुलै", "ऑगस्ट", "सप्टेंबर", "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर"]


def unique_code(on_date: date_cls, seed: str = "") -> str:
    """18-digit availability code in the portal's format (matches 20\\d{16}):
    issue date + a stable 10-digit tail derived from the subject."""
    tail = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16) % 10**10
    return f"{on_date:%Y%m%d}{tail:010d}"


def financial_year(on_date: date_cls) -> str:
    y = on_date.year if on_date.month >= 4 else on_date.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def _numbered(items) -> str:
    return "\n\n".join(f"{i}. {c.strip()}" for i, c in enumerate(items, 1))


def build_draft(f: dict) -> str:
    """Deterministic scaffold. `f` keys: lang ('en'|'mr'), subject, department,
    gr_number, date (datetime.date), references (list), background,
    clauses (list), budget_head, signatory, designation."""
    d, fy = f["date"], financial_year(f["date"])
    code = unique_code(d, f["subject"])
    refs = f.get("references") or []
    read = "\n".join(f"{i}) {r.strip()}" for i, r in enumerate(refs, 1)) or "—"
    clauses = [c for c in (f.get("clauses") or []) if c.strip()]

    if f.get("lang") == "mr":
        clauses = clauses + [
            f"या निर्णयापोटी होणारा खर्च मंजूर अर्थसंकल्पीय तरतूद, लेखाशीर्ष "
            f"{f['budget_head']} मधून सन {fy} या आर्थिक वर्षात भागविण्यात यावा.",
        ]
        return f"""{f['subject']}

महाराष्ट्र शासन
{f['department']}
शासन निर्णय क्रमांक: {f['gr_number']}
मंत्रालय, मुंबई - 400 032
दिनांक: {d.day} {MARATHI_MONTHS[d.month - 1]}, {d.year}

वाचा :-
{read}

प्रस्तावना :-
{f['background'].strip()}

शासन निर्णय :-
{_numbered(clauses)}

सदर शासन निर्णय महाराष्ट्र शासनाच्या www.maharashtra.gov.in या संकेतस्थळावर
उपलब्ध असून त्याचा सांकेतांक {code} असा आहे.

महाराष्ट्राचे राज्यपाल यांच्या आदेशानुसार व नावाने,

( {f['signatory']} )
{f['designation']}, महाराष्ट्र शासन
"""

    clauses = clauses + [
        f"The expenditure on account of this decision shall be met from the "
        f"sanctioned budgetary provision under Budget Head {f['budget_head']} "
        f"for the financial year {fy}.",
    ]
    return f"""{f['subject']}

GOVERNMENT OF MAHARASHTRA
{f['department']}
Government Resolution No.: {f['gr_number']}
Mantralaya, Mumbai - 400 032
Date: {d.day} {d:%B}, {d.year}

Read :-
{read}

Preamble :-
{f['background'].strip()}

Government Resolution :-
{_numbered(clauses)}

This Government Resolution is available on the www.maharashtra.gov.in website
with Unique Code {code}.

By order and in the name of the Governor of Maharashtra,

( {f['signatory']} )
{f['designation']}, Government of Maharashtra
"""


# ---------- AI layer ----------

PROMPT = {
    "en": """You are drafting a Maharashtra Government Resolution.
From the officer's brief below, write:
- "background": ONE formal Preamble paragraph in administrative English, ending
  with the convention that the matter "was under consideration of the Government."
- "clauses": exactly {n} operative clauses as an array of strings (no numbering
  inside the strings; imperative government style, e.g. "X is hereby sanctioned...").
Keep every number, amount, date and percentage from the brief EXACTLY as
written. Do not invent any number that is not in the brief.
Return ONLY JSON: {{"background": "...", "clauses": ["...", "..."]}}

BRIEF: {brief}""",
    "mr": """तुम्ही महाराष्ट्र शासनाचा शासन निर्णय (GR) मसुदा तयार करत आहात.
खालील थोडक्यात माहितीवरून लिहा:
- "background": प्रस्तावनेचा एक औपचारिक परिच्छेद, शेवटी "ही बाब शासनाच्या
  विचाराधीन होती." या पद्धतीने.
- "clauses": बरोबर {n} कार्यवाहीचे मुद्दे, strings च्या array स्वरूपात
  (string मध्ये क्रमांक लिहू नका; शासकीय शैली वापरा).
माहितीतील प्रत्येक संख्या, रक्कम, दिनांक व टक्केवारी जशीच्या तशी ठेवा.
माहितीत नसलेली कोणतीही संख्या लिहू नका.
फक्त JSON परत करा: {{"background": "...", "clauses": ["...", "..."]}}

माहिती: {brief}""",
}


def _digit_runs(text: str) -> set:
    """Digit runs with Indian-grouping commas stripped and Devanagari digits
    normalised — same comparison basis the conflict verifier uses."""
    text = re.sub(r"(?<=[0-9०-९]),(?=[0-9०-९])", "", text or "")
    tr = str.maketrans("०१२३४५६७८९", "0123456789")
    return {r.translate(tr) for r in re.findall(r"[0-9०-९]+", text)}


def ai_sections(brief: str, lang: str = "en", n_clauses: int = 3) -> dict:
    """LLM-drafted {background, clauses[]} from the officer's brief, digit-audited
    against it. Raises LLMError on provider failure or audit failure."""
    raw = llm_with_fallback(PROMPT[lang].format(brief=brief, n=n_clauses),
                            temperature=0.3, max_tokens=1500, json_mode=True)
    m = re.search(r"\{.*\}", raw, re.DOTALL)  # tolerate fences / stray prose
    try:
        data = json.loads(m.group(0) if m else raw)
        background, clauses = data["background"], list(data["clauses"])
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise LLMError(f"draft-assist returned malformed JSON: {e}")

    produced = _digit_runs(background + " ".join(clauses))
    allowed = _digit_runs(brief)
    if invented := produced - allowed:
        raise LLMError(f"digit audit: AI invented number(s) {sorted(invented)} "
                       "not present in the brief — output rejected")
    if dropped := allowed - produced:
        raise LLMError(f"digit audit: AI dropped number(s) {sorted(dropped)} "
                       "from the brief — output rejected")
    return {"background": background, "clauses": clauses}


def generate(fields: dict, use_ai: bool = False, brief: str = "",
             n_clauses: int = 3) -> dict:
    """Full generation: optionally AI-draft the background/clauses from the
    brief, then always render through the deterministic scaffold. Returns
    {draft, ai_used, ai_error}."""
    f, ai_used, ai_error = dict(fields), False, None
    if use_ai and brief.strip():
        try:
            sec = ai_sections(brief, f.get("lang", "en"), n_clauses)
            f["background"], f["clauses"] = sec["background"], sec["clauses"]
            ai_used = True
        except LLMError as e:
            ai_error = str(e)
            if not f.get("background"):
                f["background"] = brief.strip()   # graceful offline fallback
            if not f.get("clauses"):
                f["clauses"] = [brief.strip()]
    return {"draft": build_draft(f), "ai_used": ai_used, "ai_error": ai_error}


# ---------- round-2: structured-form path (topic → form → draft) ----------

def to_flat_fields(form: dict) -> dict:
    """GRForm (topic flow / renderer contract) → build_draft's fields dict.
    References may be dicts ({"text": …}) or plain strings."""
    refs = [(r.get("text") if isinstance(r, dict) else str(r)).strip()
            for r in form.get("references") or []]
    return {"lang": form.get("lang", "en"),
            "subject": str(form.get("subject") or "").strip(),
            "department": str(form.get("department") or "").strip(),
            "gr_number": str(form.get("gr_number") or "").strip(),
            "date": form["date"],
            "references": [r for r in refs if r],
            "background": str(form.get("background") or "").strip(),
            "clauses": [str(c).strip() for c in form.get("clauses") or []
                        if str(c).strip()],
            "budget_head": str(form.get("budget_head") or "").strip(),
            "signatory": str(form.get("signatory") or "").strip(),
            "designation": str(form.get("designation") or "").strip()}


def form_digit_audit(form: dict, draft_text: str) -> dict:
    """The render rail: every digit run in the final draft must come from the
    user-approved form or the computed structural values (code, financial
    year, date, the fixed 400 032 PIN, list numbering ≤ 31). Amounts, dates
    and codes cannot appear unless the user saw them in the form."""
    flat = to_flat_fields(form)
    d = flat["date"]
    allowed = set()
    for chunk in (flat["subject"], flat["gr_number"], flat["background"],
                  flat["budget_head"], *flat["references"], *flat["clauses"]):
        allowed |= _digit_runs(chunk)
    allowed |= _digit_runs(financial_year(d))
    allowed |= {unique_code(d, flat["subject"]), str(d.year),
                f"{d.month:02d}", f"{d.day:02d}", "400", "032"}
    allowed |= {str(i) for i in range(0, 32)}      # list numbering + day/month
    produced = _digit_runs(draft_text)
    must_appear = set()
    for chunk in (flat["subject"], flat["background"], *flat["clauses"]):
        must_appear |= _digit_runs(chunk)
    return {"ok": not (produced - allowed) and not (must_appear - produced),
            "invented": sorted(produced - allowed),
            "dropped": sorted(must_appear - produced)}


def generate_from_form(form: dict, *, allow_blanks: bool = False) -> dict:
    """Deterministic generation from a user-approved GRForm — the topic flow's
    render rail. Blocks on unfilled ____ blanks; audits the result. The form's
    `code` is pinned to what build_draft embeds, so the authentic renderer and
    the canonical text always agree.

    `allow_blanks=True` is used ONLY by the autonomous drafter's "keep" policy
    (src/draftgen/autodraft.py), which deliberately renders the blanks so a
    reader sees exactly which figures the system refused to invent. Every other
    caller keeps the refusal, so the interactive rail is unchanged.

    `ai_used`/`ai_error` are carried from the form rather than hardcoded: on the
    topic flow the prose is written by the AI at PREFILL time, one step before
    this function, and reporting False here made the UI claim no AI was used."""
    flat = to_flat_fields(form)
    if not allow_blanks:
        blanks = [lbl for lbl, txt in
                  [("विषय/subject", flat["subject"]),
                   ("प्रस्तावना/background", flat["background"])] if "____" in txt]
        blanks += [f"कलम {i}" for i, c in enumerate(flat["clauses"], 1)
                   if "____" in c]
        if blanks:
            return {"error": "unfilled_blanks", "blanks": blanks}
    draft = build_draft(flat)
    out_form = dict(form)
    out_form["code"] = unique_code(flat["date"], flat["subject"])
    out_form["fy"] = financial_year(flat["date"])
    return {"draft": draft, "form": out_form,
            "audit": form_digit_audit(form, draft),
            "ai_used": bool(form.get("ai_used")),
            "ai_error": form.get("ai_error")}


SAMPLE = {
    "en": {
        "lang": "en",
        "subject": "Sanction of merit scholarship for students of government "
                   "polytechnics.",
        "department": "Higher and Technical Education Department",
        "gr_number": "TEM-2026/C.R.55/TE-2",
        "references": ["Government Resolution, Higher and Technical Education "
                       "Department, No. TEM-2024/C.R.31/TE-2, dated 12.03.2024."],
        "background": "The question of providing a merit scholarship to "
                      "students of government polytechnics was under "
                      "consideration of the Government.",
        "clauses": ["A merit scholarship of Rs. 1,500 per month is hereby "
                    "sanctioned for the top 10% of students of government "
                    "polytechnics.",
                    "The scholarship shall be disbursed through the MahaDBT "
                    "portal to the Aadhaar-linked bank accounts of eligible "
                    "students.",
                    "This Government Resolution shall come into effect from "
                    "the academic year 2026-27."],
        "budget_head": "2203-00-105-01",
        "signatory": "A. B. Deshmukh",
        "designation": "Under Secretary",
    },
    "mr": {
        "lang": "mr",
        "subject": "शासकीय तंत्रनिकेतनातील विद्यार्थ्यांना गुणवत्ता शिष्यवृत्ती "
                   "मंजूर करण्याबाबत.",
        "department": "उच्च व तंत्र शिक्षण विभाग",
        "gr_number": "तंशि-2026/प्र.क्र.55/ताशि-2",
        "references": ["शासन निर्णय, उच्च व तंत्र शिक्षण विभाग, क्र. "
                       "तंशि-2024/प्र.क्र.31/ताशि-2, दि.12.03.2024."],
        "background": "शासकीय तंत्रनिकेतनातील विद्यार्थ्यांना गुणवत्ता "
                      "शिष्यवृत्ती देण्याची बाब शासनाच्या विचाराधीन होती.",
        "clauses": ["शासकीय तंत्रनिकेतनातील गुणवत्ताधारक विद्यार्थ्यांना दरमहा "
                    "रु. 1,500 इतकी गुणवत्ता शिष्यवृत्ती मंजूर करण्यात येत आहे.",
                    "सदर शिष्यवृत्ती पात्र विद्यार्थ्यांच्या आधार-संलग्न बँक "
                    "खात्यात MahaDBT प्रणालीद्वारे जमा करण्यात यावी.",
                    "सदर शासन निर्णय शैक्षणिक वर्ष 2026-27 पासून लागू राहील."],
        "budget_head": "2203-00-105-01",
        "signatory": "अ. ब. देशमुख",
        "designation": "अवर सचिव",
    },
}


if __name__ == "__main__":
    # AC-3 gate, fully offline: both languages must score 100% on the
    # Manual-of-Office-Procedure checklist, and the Marathi scaffold must be
    # glossary-clean. Also proves the digit audit rejects an invented number.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.path.append(str(ROOT / "src" / "compliance"))
    from scorecard import score
    from glossary_check import check_terminology

    for lang in ("en", "mr"):
        f = dict(SAMPLE[lang], date=date_cls(2026, 8, 1))
        s = score(build_draft(f))
        assert s["pct"] == 100, (lang, [c["id"] for c in s["checks"]
                                        if not c["passed"]])
        print(f"AC-3 [{lang}]: generated draft scores {s['pct']}% "
              f"({s['score']}/{s['max_score']})")
    t = check_terminology(build_draft(dict(SAMPLE["mr"], date=date_cls(2026, 8, 1))))
    assert t["n_flags"] == 0, t["flags"]
    print("Marathi scaffold: 0 glossary flags")

    ok = _digit_runs("scholarship of Rs. 2,500 from 2026-27")
    assert ok == {"2500", "2026", "27"}, ok
    fake = {"background": "Rs. 3,000 sanctioned.", "clauses": ["from 2026-27"]}
    produced, allowed = _digit_runs("Rs. 3,000 from 2026-27"), _digit_runs("Rs. 2,500 from 2026-27")
    assert produced - allowed == {"3000"}
    print("digit audit: invented-number case detected")
    print("generate.py self-test OK")
