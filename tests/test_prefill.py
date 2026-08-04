"""Topic-prefill rails — fully offline (injected retrieval + canned LLM).

Verifies the round-2 trust story end to end at the unit level:
department vote from code digits, references that round-trip through the
citation extractor, file numbers in the real grammar, and the sourced-or-blank
digit scrub on AI prose (invented numbers become ____, sourced ones survive).

Run:  python tests/test_prefill.py
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src" / "draftgen"))
sys.path.append(str(ROOT / "src" / "ingest"))

from prefill import (scrub_unsourced_digits, topic_prefill)  # noqa: E402
from generate import _digit_runs  # noqa: E402
from extract_metadata import extract_citations  # noqa: E402


def fake_retrieve(q, k=8):
    return [
        {"gr_code": "202303151204391421", "distance": 0.15, "subject": "s1",
         "department": "?", "date": "?", "gr_number": "?", "clause": "…"},
        {"gr_code": "202407191857335421", "distance": 0.20, "subject": "s2",
         "department": "?", "date": "?", "gr_number": "?", "clause": "…"},
        {"gr_code": "202201011111111108", "distance": 0.25, "subject": "s3",
         "department": "?", "date": "?", "gr_number": "?", "clause": "…"},
    ]


AI_JSON = {
    "subject": "जिल्हा परिषद शाळांना सादिल अनुदान वितरित करण्याबाबत.",
    "file_prefix": "सादिल",
    "background": "सन 2026-27 मध्ये जिल्हा परिषद शाळांना सादिल अनुदान देण्याची "
                  "बाब शासनाच्या विचाराधीन होती.",
    "clauses": ["जिल्हा परिषद शाळांना रु. 5,000 इतके सादिल अनुदान मंजूर करण्यात "
                "येत आहे व सदर रक्कम तात्काळ वितरित करण्यात यावी.",
                "उर्वरित रक्कम रु. ____ नंतरच्या टप्प्यात वितरित करण्यात यावी "
                "याबाबत स्वतंत्र आदेश निर्गमित करण्यात येतील."],
    "needs_numbers": ["एकूण अनुदानाची रक्कम किती?"],
}


def main():
    # --- scrub: invented blanked, sourced kept -------------------------------
    allowed = _digit_runs("2026-27 अनुदान 14.11.1994")
    txt, removed = scrub_unsourced_digits(
        "रु. 5,000 सन 2026-27 पासून, दि.14.11.1994 च्या निर्णयानुसार.", allowed)
    assert "5,000" not in txt and "____" in txt, txt
    assert "2026-27" in txt and "14.11.1994" in txt, txt
    assert removed == ["5,000"], removed

    # --- full prefill with canned AI ----------------------------------------
    out = topic_prefill("जिल्हा परिषद शाळांना सादिल अनुदान वितरण", "mr",
                        corpus=[], retrieve_fn=fake_retrieve,
                        llm_fn=lambda *a, **k: json.dumps(AI_JSON,
                                                          ensure_ascii=False),
                        on_date=date(2026, 8, 5))
    f = out["form"]
    assert out["ai_used"] and out["ai_error"] is None
    assert f["dept_code"] == "21", f["dept_code"]           # majority vote
    # AI's invented 5,000 was scrubbed; its ____ survives; year sourced
    joined = " ".join(f["clauses"])
    assert "5,000" not in joined and "____" in joined, joined
    assert "2026-27" in f["background"]
    assert out["scrubbed"] == ["5,000"], out["scrubbed"]
    assert out["needs_numbers"] == ["एकूण अनुदानाची रक्कम किती?"]
    # validated AI file_prefix used in the real grammar
    assert f["gr_number"].startswith("सादिल-2026/प्र.क्र."), f["gr_number"]
    # references round-trip through the citation extractor
    blob = "\n".join(r["text"] for r in f["references"])
    codes = extract_citations(blob)["cited_codes"]
    assert all(r["gr_code"] in codes for r in f["references"]), (blob, codes)

    # --- AI failure degrades to the deterministic form ----------------------
    def boom(*a, **k):
        raise __import__("clients").LLMError("provider down")
    sys.path.append(str(ROOT / "src" / "llm"))
    out2 = topic_prefill("शालेय क्रीडा स्पर्धा अनुदान", "mr", corpus=[],
                         retrieve_fn=fake_retrieve, llm_fn=boom,
                         on_date=date(2026, 8, 5))
    assert not out2["ai_used"] and "provider down" in out2["ai_error"]
    assert out2["form"]["subject"].endswith("बाबत.")        # skeleton intact

    # --- bad JSON also degrades ---------------------------------------------
    out3 = topic_prefill("शालेय क्रीडा स्पर्धा अनुदान", "mr", corpus=[],
                         retrieve_fn=fake_retrieve,
                         llm_fn=lambda *a, **k: "not json at all",
                         on_date=date(2026, 8, 5))
    assert not out3["ai_used"] and out3["ai_error"]

    print("test_prefill OK — scrub rail, canned-AI prefill, degradation paths")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
