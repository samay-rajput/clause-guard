"""Autonomous drafting: topic → authentic GR PDF, with no human in the loop.

Fully offline — retrieval and the LLM are both injected, so this needs no index,
no Ollama and no network. It is also the ONLY test that carries a prefill-derived
form all the way into the authentic renderer; the app does that inside a
try/except, so a renderer regression on that path was previously invisible.

The injected LLM deliberately returns BOTH an unsourced number and a literal
____, so every rail is exercised: the prefill scrub, the deferral policy, the
render-rail digit audit, and the AC-3 compliance guarantee.
"""
import json
import re
import sys
from datetime import date as date_cls
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
for _sub in ("draftgen", "export", "compliance", "llm", "index", "ingest"):
    sys.path.append(str(ROOT / "src" / _sub))

import fitz  # noqa: E402
from autodraft import BLANK, DEFER_CLAUSE, draft_gr, resolve_blanks  # noqa: E402
from clients import LLMError  # noqa: E402
from generate import _digit_runs  # noqa: E402
from gr_layout import to_devanagari_digits  # noqa: E402
from scorecard import score  # noqa: E402

ON = date_cls(2026, 8, 6)
TOPIC = "जिल्हा परिषद शाळांमधील विद्यार्थ्यांसाठी मोफत क्रीडा साहित्य पुरवठा"
BLANK_CLAUSE = "सदर साहित्य ____ पर्यंत वितरित करण्यात यावे."


def fake_retrieve(q, k=8):
    return [{"gr_code": "202401151200000021", "distance": 0.12,
             "subject": "जिल्हा परिषद शाळांना क्रीडा साहित्य पुरवठा",
             "clause": "क्रीडा साहित्य पुरवठा करण्यास मान्यता देण्यात येत आहे."},
            {"gr_code": "202312011200000021", "distance": 0.19,
             "subject": "शालेय क्रीडा स्पर्धा अनुदान वितरण",
             "clause": "अनुदान वितरित करण्यात यावे."}]


EN_BLANK_CLAUSE = "The equipment shall be distributed on or before ____."


def fake_llm(prompt, **kw):
    """Answers in the language the real AI_PROMPT asked in. Detect on the
    English template's opening phrase — NOT on "does the prompt contain
    Devanagari", because the English prompt interpolates Marathi precedent
    subjects and would be misread as a Marathi request."""
    if prompt.lstrip().startswith("You are filling the form"):
        return json.dumps({
            "subject": "Supply of free sports equipment to students of zilla "
                       "parishad schools.",
            "file_prefix": "SPE",
            "background": "The matter was under consideration of the Government.",
            "clauses": ["Sports equipment worth Rs. 45000 is hereby sanctioned "
                        "for each school.",
                        EN_BLANK_CLAUSE,
                        "This Government Resolution shall come into effect from "
                        "the date of its issue."],
            "needs_numbers": ["What amount is sanctioned per school?"],
        })
    return json.dumps({
        "subject": "जिल्हा परिषद शाळांमधील विद्यार्थ्यांना मोफत क्रीडा साहित्य "
                   "पुरवठा करण्याबाबत.",
        "file_prefix": "क्रीसा",
        "background": "ही बाब शासनाच्या विचाराधीन होती.",
        "clauses": ["प्रत्येक शाळेस रु. 45000 इतके क्रीडा साहित्य पुरविण्यात यावे.",
                    BLANK_CLAUSE,
                    "सदर शासन निर्णय निर्गमित दिनांकापासून लागू राहील."],
        "needs_numbers": ["प्रति शाळा किती रक्कम मंजूर आहे?"],
    }, ensure_ascii=False)


def dead_llm(prompt, **kw):
    raise LLMError("ollama unreachable")


def boom_retrieve(q, k=8):
    raise RuntimeError("chroma unavailable")


def run(**kw):
    base = dict(corpus=[], retrieve_fn=fake_retrieve, llm_fn=fake_llm,
                on_date=ON)
    base.update(kw)
    return draft_gr(TOPIC, base.pop("lang", "mr"), **base)


# ---------------------------------------------------------------- 1. the happy path
r = run(blank_policy="defer")
assert r["ok"], r
assert r["error"] is None, r
m = r["meta"]
assert m["ai_used"] is True, m
assert m["scrubbed"], "the unsourced 45000 must have been scrubbed"
assert m["deferred_clauses"], "the ____ clause must have deferred"
assert m["open_questions"], m
assert BLANK not in r["draft"], "a blank reached the rendered draft"
assert BLANK not in r["form"]["subject"]
assert BLANK not in r["form"]["background"]
assert not any(BLANK in str(c) for c in r["form"]["clauses"])
print(f"1. autonomous draft ok — {len(m['deferred_clauses'])} deferred, "
      f"{len(m['scrubbed'])} numbers refused, {m['elapsed_s']}s")

# ------------------------------------------------- 2. AC-3 on a prefill-derived form
s = score(r["draft"])
assert s["pct"] == 100, [c["id"] for c in s["checks"] if not c["passed"]]
assert r["compliance"]["pct"] == 100
assert r["terminology"]["n_flags"] == 0, r["terminology"]["flags"]
print(f"2. AC-3 holds on the AI-written form — {s['pct']}% "
      f"({s['score']}/{s['max_score']}), 0 glossary flags")

# ------------------------------------------------------------- 3. the digit rail
assert r["audit"]["ok"], r["audit"]
assert r["audit"]["invented"] == [], r["audit"]
assert r["audit"]["dropped"] == [], r["audit"]
assert "45000" not in _digit_runs(r["draft"]), "an unsourced amount survived"
print("3. digit audit ok — nothing invented, nothing dropped")

# --------------------------------------------- 4. nothing lost silently + deferral
assert BLANK_CLAUSE in m["deferred_clauses"], m["deferred_clauses"]
assert DEFER_CLAUSE["mr"] in r["draft"], "the deferral clause must be stated"
print("4. every deferred clause preserved verbatim; deferral stated in the GR")

# ------------------------------------------------------- 5. the authentic PDF
pdf = r["pdf_bytes"]
assert pdf and pdf[:4] == b"%PDF", type(pdf)
doc = fitz.open(stream=pdf, filetype="pdf")
page = doc[0]
pw, ph = round(page.rect.width), round(page.rect.height)
assert (pw, ph) == (612, 792), (pw, ph)   # real GRs are US Letter, not A4
text = "\n".join(p.get_text() for p in doc)
assert "महाराष्ट्र शासन" in text
assert "www.maharashtra.gov.in" in text
assert to_devanagari_digits(r["form"]["code"]) in text.replace(" ", ""), \
    "the 18-digit code should render in Devanagari numerals"
assert not re.search(r"[0-9]{3,}", text), \
    f"ASCII digit run leaked into the rendered GR: {re.findall(r'[0-9]{3,}', text)[:5]}"
assert BLANK not in text, "a blank reached the authentic PDF"
doc.close()
assert r["docx_bytes"] and r["docx_bytes"][:2] == b"PK"
print(f"5. authentic PDF ok — US Letter {pw}x{ph}, Devanagari numerals, "
      "link present, DOCX ok")

# ------------------------------------------ 6. block reproduces the old refusal
b = run(blank_policy="block")
assert b["ok"] is False and b["error"] == "unfilled_blanks", b
assert b["blanks"], b
print(f"6. blank_policy=block still refuses, unchanged — {b['blanks']}")

# ------------------------------------------------------- 7. keep / omit policies
k = run(blank_policy="keep")
assert k["ok"] and BLANK in k["draft"], "keep must render the blanks"
o = run(blank_policy="omit")
assert o["ok"] and BLANK not in o["draft"]
assert DEFER_CLAUSE["mr"] not in o["draft"], "omit must not add the deferral line"
assert score(o["draft"])["pct"] == 100
print("7. keep renders blanks; omit drops them silently, both still valid")

# -------------------------------------------------------- 8. degradation paths
d = run(retrieve_fn=boom_retrieve)
assert d["ok"], d
assert any(x.startswith("no_index") for x in d["meta"]["degraded"]), d["meta"]
assert score(d["draft"])["pct"] == 100
assert d["pdf_bytes"][:4] == b"%PDF"

l = run(llm_fn=dead_llm)
assert l["ok"], l
assert l["meta"]["ai_used"] is False and l["meta"]["ai_error"], l["meta"]
assert "llm_unavailable" in l["meta"]["degraded"], l["meta"]
assert BLANK not in l["draft"] and score(l["draft"])["pct"] == 100
print("8. degrades safely — no index and no LLM each still yield a 100% GR")

# --------------------------------------- 9. resolve_blanks never invents a digit
src = {"lang": "mr", "topic": TOPIC, "date": ON,
       "subject": "चाचणी विषय ____ बाबत.",
       "background": "रु. ____ मंजूर करण्यात आले. ही बाब विचाराधीन होती.",
       "clauses": ["रु. ____ अदा करावेत.", "क्रमांक 12 नुसार कार्यवाही करावी."]}
got, rep = resolve_blanks(src, "defer")
joined_in = " ".join([src["subject"], src["background"], *src["clauses"]])
joined_out = " ".join([got["subject"], got["background"], *got["clauses"]])
assert _digit_runs(joined_out) <= _digit_runs(joined_in), \
    (_digit_runs(joined_in), _digit_runs(joined_out))
assert BLANK not in joined_out
assert rep["deferred"] and "subject" in rep["replaced_fields"]
for policy in ("keep", "block"):
    same, _ = resolve_blanks(src, policy)
    assert same["clauses"] == src["clauses"], policy
print("9. resolve_blanks is digit-safe and only removes; keep/block are no-ops")

# ------------------------------------------------------------------ 10. English
e = draft_gr("free sports equipment for zilla parishad school students", "en",
             corpus=[], retrieve_fn=fake_retrieve, llm_fn=fake_llm, on_date=ON)
assert e["ok"] and score(e["draft"])["pct"] == 100
assert DEFER_CLAUSE["en"] in e["draft"]
edoc = fitz.open(stream=e["pdf_bytes"], filetype="pdf")
assert not re.search(r"[ऀ-ॿ]", "".join(p.get_text() for p in edoc)), \
    "Devanagari leaked into the English GR"
edoc.close()
print("10. English path ok — 100% compliant, no Devanagari leakage")

print("test_autodraft OK — topic → authentic GR with no human in the loop")
