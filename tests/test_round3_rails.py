"""Round-3 hallucination rails — unit tests.

Covers: entity/word-date scrub, wording-fidelity audit, the structural
form_digit_audit (0-31 hole closed), वाचा existence gate, non-numeric
grounding in the verifier, and the DRAFT watermark on incomplete exports.
Fully offline — no LLM, no index.
"""
import io
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("llm", "index", "ingest", "detect", "reftrack", "compliance",
            "audit", "export", "draftgen", "deploy"):
    sys.path.append(str(ROOT / "src" / sub))

from prefill import scrub_unsourced_entities, wording_audit  # noqa: E402
from generate import form_digit_audit  # noqa: E402
from citations import validate_references  # noqa: E402
from pipeline import _grounded  # noqa: E402
from gr_layout import gr_pdf  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {detail}")


# ---------- 1. entity + word-date scrub ----------
SOURCES = ("जिल्हा परिषद शाळांना सादिल अनुदान वितरण MahaDBT "
           "समग्र शिक्षा अभियान अंतर्गत निधी वितरणाबाबत")

out, rem = scrub_unsourced_entities(
    "निधी थेट PMKisan पोर्टलद्वारे वितरित करण्यात यावा", SOURCES)
check("unsourced acronym scrubbed", "PMKisan" in rem and "____" in out, (out, rem))

out, rem = scrub_unsourced_entities(
    "निधी MahaDBT प्रणालीद्वारे वितरित करण्यात यावा", SOURCES)
check("sourced CamelCase kept", "MahaDBT" in out and not rem, (out, rem))

out, rem = scrub_unsourced_entities(
    "एकात्मिक बालविकासयोजना अंतर्गत मान्यता देण्यात येत आहे", SOURCES)
check("unsourced Marathi compound scrubbed",
      any("योजना" in r for r in rem), (out, rem))

out, rem = scrub_unsourced_entities(
    "दिनांक ३१ मार्च पूर्वी खर्च करण्यात यावा", SOURCES)
check("unsourced month word scrubbed", "मार्च" in rem, (out, rem))

out, rem = scrub_unsourced_entities(
    "मार्च अखेर खर्च अहवाल सादर करावा", SOURCES + " मार्च 2026 पर्यंत")
check("sourced month word kept", "मार्च" in out and not rem, (out, rem))

out, rem = scrub_unsourced_entities(
    "महाराष्ट्र शासन निर्णयानुसार कार्यवाही करावी", SOURCES)
check("stop-word vocabulary never scrubbed", not rem, (out, rem))

# ---------- 2. wording-fidelity audit ----------
PRECEDENTS = [
    {"clause": "सदर योजनेअंतर्गत पात्र लाभार्थ्यांना अनुदान थेट लाभ हस्तांतरणाद्वारे "
               "बँक खात्यात जमा करण्यात यावे."},
    {"clause": "या शासन निर्णयाच्या अंमलबजावणीची जबाबदारी संबंधित जिल्हाधिकारी "
               "यांची राहील."},
]
rep = wording_audit(
    ["सदर योजनेअंतर्गत पात्र लाभार्थ्यांना अनुदान थेट लाभ हस्तांतरणाद्वारे बँक "
     "खात्यात जमा करण्यात यावे.",
     "चंद्रावर उपकेंद्र स्थापन करून तेथील विद्यार्थ्यांची नोंदणी करण्यात यावी.",
     "स्वतंत्र आदेशाने रक्कम निश्चित होईल."],
    [0, 1, -1], PRECEDENTS)
check("adapted clause -> grounded", rep[0]["verdict"] == "grounded", rep[0])
check("alien clause -> unverified", rep[1]["verdict"] == "unverified", rep[1])
check("uncited clause -> no-precedent", rep[2]["verdict"] == "no-precedent", rep[2])

# ---------- 3. structural digit audit (0-31 hole) ----------
BASE_FORM = {
    "lang": "mr", "subject": "चाचणी अनुदान वितरणाबाबत.",
    "department": "शालेय शिक्षण व क्रीडा विभाग",
    "gr_number": "चाचणी-2026/प्र.क्र.55/एसडी-4", "date": date(2026, 8, 10),
    "references": [{"text": "शासन निर्णय, सांकेतांक 202407191857335408, दि.19.07.2024."}],
    "background": "ही बाब शासनाच्या विचाराधीन होती.",
    "clauses": ["चाचणी अनुदानास मान्यता देण्यात येत आहे.",
                "सदर शासन निर्णय निर्गमित दिनांकापासून लागू राहील."],
    "budget_head": "", "signatory": "क.ख.ग.", "designation": "उप सचिव",
}
from generate import build_draft, to_flat_fields  # noqa: E402

ok_draft = build_draft(to_flat_fields(BASE_FORM))
aud = form_digit_audit(BASE_FORM, ok_draft)
check("clean form passes structural audit", aud["ok"], aud)

aud = form_digit_audit(BASE_FORM, ok_draft + " सदर रक्कम 15 दिवसांच्या आत खर्च करावी.")
check("invented '15 days' now caught", not aud["ok"] and "15" in aud["invented"], aud)

aud = form_digit_audit(BASE_FORM, ok_draft + " टीप 3.")
check("numbering within structural range still allowed", aud["ok"], aud)

# ---------- 4. वाचा existence gate ----------
CORPUS = [{"gr_code": "202407191857335408",
           "gr_number": "संकीर्ण-2024/प्र.क्र.157/तांशि-4"},
          {"gr_code": "202302091813048908", "gr_number": "एसएसए-2023/प्र.क्र.9/एसडी-1"}]
v = validate_references(
    [{"text": "शासन निर्णय, सांकेतांक 202407191857335408, दि.19.07.2024."},
     "शासन निर्णय क्रमांक एसएसए-2023/प्र.क्र.9/एसडी-1, दि.09.02.2023.",
     "शासन निर्णय, सांकेतांक 209999999999999999, दि.01.01.2099."], CORPUS)
check("code reference resolves", len(v["resolved"]) >= 1 and
      any("202407191857335408" in r for r in v["resolved"]), v)
check("file-number reference resolves",
      any("एसएसए" in r for r in v["resolved"]), v)
check("nonexistent GR flagged", len(v["unresolved"]) == 1 and
      "2099" in v["unresolved"][0], v)

# ---------- 5. non-numeric grounding in the verifier ----------
check("numeric grounding unchanged",
      _grounded("50 टक्के", "प्रतिपूर्ती 50 टक्के मर्यादेत") and
      not _grounded("50 टक्के", "प्रतिपूर्ती 100 टक्के मर्यादेत"))
check("fabricated authority no longer grounded",
      not _grounded("राज्य निवड समिती मार्फत मंजुरी",
                    "सदर अनुदान जिल्हाधिकारी यांच्या मान्यतेने वितरित करण्यात यावे"))
check("paraphrased authority still grounded",
      _grounded("जिल्हाधिकारी यांच्या मान्यतेने",
                "सदर अनुदान जिल्हाधिकारी यांच्या मान्यतेने वितरित करण्यात यावे"))

# ---------- 6. DRAFT watermark on incomplete exports ----------
# extract_text() drops the oversized overlay line — assert on the raw chars
import pdfplumber  # noqa: E402


def _watermark_present(pdf_bytes: bytes) -> bool:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        big = "".join(c["text"] for p in pdf.pages for c in p.chars
                      if c.get("size", 0) > 40)
    return "DRAFT" in big


blank_form = dict(BASE_FORM)
blank_form["clauses"] = ["____ इतकी रक्कम मंजूर करण्यात येत आहे."]
check("blank draft carries DRAFT watermark", _watermark_present(gr_pdf(blank_form)))
check("complete GR carries NO watermark", not _watermark_present(gr_pdf(BASE_FORM)))

marked = dict(BASE_FORM)
marked["draft_marker"] = True
check("explicit draft_marker forces watermark", _watermark_present(gr_pdf(marked)))

# ---------- 7. formatting: tables, annexures, hanging indent ----------
from gr_layout import gr_docx  # noqa: E402

rich = dict(BASE_FORM)
rich["clauses"] = [
    "जिल्हानिहाय वितरण खालील तक्त्यात नमूद केल्याप्रमाणे करण्यात यावे व त्याप्रमाणे "
    "संबंधित जिल्हाधिकारी यांनी अंमलबजावणीचा अहवाल शासनास सादर करावा असे "
    "निर्देश देण्यात येत आहेत जेणेकरून सदर योजनेची प्रभावी अंमलबजावणी होईल.",
]
rich["tables"] = [{"after_clause": 1,
                   "headers": ["जिल्हा", "रक्कम (लाख)", "लाभार्थी"],
                   "rows": [["पुणे", "50", "1200"], ["नागपूर", "35", "900"],
                            ["नाशिक", "25", "640"]]}]
rich["annexures"] = [{"title": "जिल्हानिहाय सविस्तर वाटप",
                      "paras": ["सदर परिशिष्टातील आकडेवारी संबंधित जिल्हा कार्यालयांनी "
                                "प्रमाणित केली आहे."],
                      "tables": [{"headers": ["क्र", "तपशील"],
                                  "rows": [["1", "पहिला हप्ता"], ["2", "दुसरा हप्ता"]]}]}]

pdf_bytes = gr_pdf(rich)
with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
    n_pages = len(pdf.pages)
    all_text = " ".join((p.extract_text() or "") for p in pdf.pages)
check("annexure adds a page", n_pages >= 2, n_pages)
check("table content renders", "पुणे" in all_text or "नागपूर" in all_text)
# extraction of the Marathi label is unreliable (conjunct cid-mapping in the
# subset font) — assert the label via the English rendering instead
rich_en = dict(rich, lang="en", subject="Test grant distribution.",
               department="School Education & Sports Department",
               background="The matter was under consideration of the Government.",
               clauses=["Approval is hereby accorded to the district-wise "
                        "distribution shown in the table below."],
               signatory="A.B.C.", designation="Deputy Secretary")
with pdfplumber.open(io.BytesIO(gr_pdf(rich_en))) as pdf:
    en_text = " ".join((p.extract_text() or "") for p in pdf.pages)
check("annexure label renders", "Annexure-A" in en_text, en_text[-200:])

docx_bytes = gr_docx(rich)
check("DOCX with table+annexure builds", docx_bytes[:2] == b"PK" and
      len(docx_bytes) > 10_000, len(docx_bytes))

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
