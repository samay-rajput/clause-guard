"""LLM cleanup pass over the parsed corpus (fixes legacy-font extraction garble).

Reads data/corpus.jsonl, asks Gemini to repair the Marathi extraction artifacts
(digits/numbers MUST be copied verbatim — they are not affected by the font
corruption and must never be 'corrected'), re-parses header metadata from the
cleaned text, re-chunks, and writes data/corpus_clean.jsonl.

Resumable: GRs already present in the output are skipped. ~1 call per GR.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "llm"))
sys.path.append(str(ROOT / "src" / "ingest"))
from clients import llm_with_fallback, LLMError  # noqa: E402
from chunk_clauses import chunk  # noqa: E402
from devanagari import to_ascii_digits  # noqa: E402
from extract_metadata import extract_citations, parse_header  # noqa: E402
from quality import readability  # noqa: E402

IN = ROOT / "data" / "corpus.jsonl"
OUT = ROOT / "data" / "corpus_clean.jsonl"

PROMPT = """The following text was extracted from a Maharashtra Government Resolution PDF whose legacy Devanagari font corrupts extraction (wrong glyph-to-character mapping: misplaced ि matras, wrong conjuncts, stray spaces inside words).

Reconstruct the correct Marathi text.

STRICT RULES:
1. Copy ALL digits, numbers, amounts, dates, and GR reference codes VERBATIM — never alter, add, or "fix" any numeral.
2. Fix only script corruption: wrong characters, broken conjuncts, misplaced matras, spaces inside words.
3. Keep the line structure and section order exactly as given.
4. If a word is unrecoverable, keep it unchanged.
5. Output ONLY the corrected text, no commentary.

TEXT:
{text}"""


def clean_one(rec, max_chars):
    raw = "\n".join(rec["clauses"])[:max_chars]
    fixed = llm_with_fallback(PROMPT.format(text=raw), preferred="gemini",
                              temperature=0.0, max_tokens=8192)
    # digit-preservation audit: the multiset of digit-runs must survive.
    # Folded to one script first — a repair that rewrites 50 as ५० preserves the
    # value, and the raw comparison would reject it as a lost number.
    d_in = sorted(re.findall(r"\d+", to_ascii_digits(raw)))
    d_out = sorted(re.findall(r"\d+", to_ascii_digits(fixed)))
    digit_ok = d_in == d_out
    h = parse_header(fixed[:2500])
    cites = extract_citations(fixed)
    return {
        **rec,
        "clauses": chunk(fixed) or rec["clauses"],
        "department": h["department"] or rec.get("department"),
        "gr_number": h["gr_number"] or rec.get("gr_number"),
        "date": h["date"] or rec.get("date"),
        "subject": h["subject"] or rec.get("subject"),
        "cited_codes": cites["cited_codes"] or rec.get("cited_codes", []),
        "cited_refs": cites["cited_refs"] or rec.get("cited_refs", []),
        "cleaned": True,
        "digit_audit_ok": digit_ok,
        "readability_after": readability(fixed)["score"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-chars", type=int, default=9000)
    ap.add_argument("--sleep", type=float, default=5.0)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["gr_code"])
            except Exception:
                pass

    recs = [json.loads(l) for l in IN.read_text(encoding="utf-8").splitlines()]
    todo = [r for r in recs if r["gr_code"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(recs)} in corpus, {len(done)} already cleaned, {len(todo)} to do", flush=True)

    n_bad_digits = 0
    with OUT.open("a", encoding="utf-8") as out:
        for i, rec in enumerate(todo, 1):
            try:
                c = clean_one(rec, args.max_chars)
                if not c["digit_audit_ok"]:
                    n_bad_digits += 1
                    print(f"  DIGIT-AUDIT-FAIL {rec['gr_code']} (kept, flagged)", flush=True)
                out.write(json.dumps(c, ensure_ascii=False) + "\n")
                out.flush()
            except LLMError as e:
                print(f"  SKIP {rec['gr_code']}: {str(e)[:100]}", flush=True)
            if i % 10 == 0:
                print(f"[clean] {i}/{len(todo)} (digit-fails: {n_bad_digits})", flush=True)
            time.sleep(args.sleep)
    print(f"DONE -> {OUT} (digit-audit failures: {n_bad_digits})", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
