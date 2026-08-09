"""The code-side conflict rails — no LLM, no index, no corpus.

Everything the pipeline calls a conflict is decided here, in code, from values the
LLM only *extracted*. These are the assertions that keep that judgment honest.

Run: python tests/test_pipeline_rules.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src" / "detect"))
sys.path.append(str(ROOT / "src" / "llm"))
sys.path.append(str(ROOT / "src" / "index"))
sys.path.append(str(ROOT / "src" / "ingest"))
from pipeline import (  # noqa: E402
    _grounded, _is_financial_year_label, _values_conflict)


def check(cond, msg):
    print(f"  {'OK  ' if cond else 'FAIL'} {msg}")
    return bool(cond)


def main():
    ok = True

    print("value comparison is script-agnostic")
    ok &= check(_values_conflict("५० टक्के", "१०० टक्के"), "५० vs १०० conflicts")
    ok &= check(_values_conflict("50 टक्के", "१०० टक्के"), "mixed script still compares")
    ok &= check(not _values_conflict("५० टक्के", "50%"), "same number in two scripts is NOT a conflict")
    ok &= check(not _values_conflict("रु.१,००,०००", "रु.100000"), "Indian grouping is not a difference")
    ok &= check(not _values_conflict("दि.३१.०३.२०२५", "31.03.2025"), "same date in two scripts agrees")
    ok &= check(_values_conflict("31.03.2025", "31.03.2026"), "a changed deadline year IS a conflict")

    print("\nnon-numeric values are only compared within one script")
    ok &= check(_values_conflict("संचालक, तंत्रशिक्षण", "आयुक्त, समाज कल्याण"),
                "two different Marathi authorities conflict")
    ok &= check(_values_conflict("the Director of Technical Education",
                                 "the Commissioner of Social Welfare"),
                "two different English authorities conflict")
    ok &= check(not _values_conflict(
        "directly through the MahaDBT portal to Aadhaar-linked bank accounts",
        "सदर निधी थेट लाभ हस्तांतरणाद्वारे (DBT) लाभार्थ्यांच्या बँक खात्यामध्ये जमा करण्यात यावा"),
        "the SAME procedure in English and Marathi is not a conflict")
    ok &= check(not _values_conflict("MahaDBT portal", "महाडीबीटी पोर्टल"),
                "cross-script agreement is never asserted as disagreement")

    print("\nextracted values must be grounded in their own clause")
    ok &= check(_grounded("50 टक्के", "…प्रतिपूर्ती ५० टक्के इतकी…"), "value present in Devanagari")
    ok &= check(not _grounded("100 टक्के", "…प्रतिपूर्ती ५० टक्के इतकी…"), "hallucinated value rejected")
    ok &= check(_grounded("the sanctioning authority", "…अधिकार…"), "non-numeric values pass through")
    # the page-marker hole: '# Page 5' used to ground an invented '5'
    ok &= check(not _grounded("5 टक्के", "सदर प्रतिपूर्ती १०० टक्के इतकी राहील."),
                "no stray digits to borrow from a cleaned clause")

    print("\na different financial year is a re-sanction, not a contradiction")
    ok &= check(_is_financial_year_label("सन 2025-26 या आर्थिक वर्षामध्ये"), "मराठी FY label")
    ok &= check(_is_financial_year_label("सन २०२४-२५ या आर्थिक वर्षामध्ये"), "Devanagari FY label")
    ok &= check(_is_financial_year_label("financial year 2025-26"), "English FY label")
    ok &= check(not _is_financial_year_label("दि.30 जानेवारी, 2024"), "a full date is not an FY label")
    ok &= check(not _is_financial_year_label("31.03.2025"), "a deadline is not an FY label")
    ok &= check(not _is_financial_year_label("शैक्षणिक वर्ष 2026-27"),
                "an academic year is NOT covered — effective-date conflicts must still fire")
    ok &= check(not _is_financial_year_label("रु. 2,500"), "an amount is not an FY label")

    print()
    if not ok:
        print("test_pipeline_rules FAILED")
        return 1
    print("test_pipeline_rules OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
