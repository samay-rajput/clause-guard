"""Parse downloaded GR PDFs into structured records.

Modes:
  headers --dir data/raw_pdfs/sample     print filename-code vs parsed department
                                         (used to verify the trailing-code=dept hypothesis)
  corpus  [--dir data/raw_pdfs]          build data/corpus.jsonl from all PDFs in dir
"""
import argparse
import json
import sys
from pathlib import Path

import pdfplumber

sys.path.append(str(Path(__file__).parent))
from chunk_clauses import chunk  # noqa: E402
from extract_metadata import extract_citations, parse_header  # noqa: E402
from quality import readability  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

# Marathi header fallbacks (the corpus turned out to be Marathi-primary)
import re  # noqa: E402

MR_DEPT_RE = re.compile(r"^\s*([ऀ-ॿ][ऀ-ॿ ,()&.\-]*(?:विभाग|वभाग|भवभाग|जवभाग|शवभाग|नवभाग|मवभाग|ववभाग|चवभाग|खवभाग))\s*[,.]?\s*$",
                        re.MULTILINE)
# GR date lines are written "दिनांक : २७ सप्टेंबर, २०१८" — the comma between the
# month and the year sits INSIDE the date, so excluding commas dropped 53% of them.
# `तारीख` is used instead of `दिनांक` by a minority of departments.
MR_DATE_RE = re.compile(
    r"(?:दिनांक|ददनांक|नदनांक|मदनांक|भदनांक|खदनांक|दिनाक|तारीख)"
    r"\s*[:\-. ]*\s*([0-9०-९]{1,2}[^\n]{0,28}?[0-9०-९]{4})"
)
# A Maharashtra file number is <prefix>-<year>/प्र.क्र.<serial>/<desk>. Anchoring on
# that shape matters: a bare `क्र` also occurs inside ordinary words
# (अभ्यासक्रमाच्या), and the loose pattern below "found" a GR number in 100% of
# documents by returning fragments of prose like "माच्या संस्थेत".
MR_GRNO_TIGHT_RE = re.compile(
    r"(?:क्रमांक|क्रमाांक|क्रमाकं|क्र)\s*[:ः.\-]*\s*"
    r"((?:[^\s\n,][^\n,]{0,24})?[-–][०-९0-9]{2,4}\s*/[^\n,]{4,60})"
)
MR_GRNO_RE = re.compile(r"(?:क्रमांक|क्रमाकं|क्रमाांक|क्र\.?)\s*[:\-ः]*\s*([^\n]{4,80})")
# minimum shape for the loose fallback to be believable at all
_GRNO_PLAUSIBLE = re.compile(r"[०-९0-9]{4}").search


def parse_header_bilingual(text: str) -> dict:
    h = parse_header(text)
    if not h["department"]:
        m = MR_DEPT_RE.search(text)
        if m:
            h["department"] = re.sub(r"\s+", " ", m.group(1)).strip()
    if not h["date"]:
        m = MR_DATE_RE.search(text)
        if m:
            h["date"] = re.sub(r"\s+", " ", m.group(1)).strip()
    if not h["gr_number"]:
        m = MR_GRNO_TIGHT_RE.search(text)
        if m:
            h["gr_number"] = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(",.")
        else:
            m = MR_GRNO_RE.search(text)
            # no number is better than a fragment of prose: a junk gr_number
            # becomes a junk citation key and mislinks other GRs to this one
            if m and _GRNO_PLAUSIBLE(m.group(1)):
                h["gr_number"] = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(",.")
    if not h["subject"]:
        # subject block = lines before the महाराष्ट्र शासन-ish line
        m = re.search(r"^(.*?)(?:महाराष्ट्र शासन|महाराष्र शासन|िहाराष्र िासन|िहाराष्ट्र िासन|महाराष्ट्र िासन|र्महाराष्र शासन)",
                      text, re.DOTALL)
        if m and 10 < len(m.group(1).strip()) < 600:
            h["subject"] = re.sub(r"\s+", " ", m.group(1).strip())[:300]
    return h


def read_pdf(path: Path, max_pages: int = 30):
    """Return (first_page_text, full_text) or (None, None) on failure."""
    try:
        with pdfplumber.open(path) as pdf:
            pages = []
            for pg in pdf.pages[:max_pages]:
                pages.append(pg.extract_text() or "")
            return (pages[0] if pages else ""), "\n".join(pages)
    except Exception as e:
        print(f"  PARSE-FAIL {path.name}: {type(e).__name__}: {e}", flush=True)
        return None, None


def cmd_headers(dir_: Path):
    rows = []
    for p in sorted(dir_.glob("*.pdf")):
        first, _ = read_pdf(p, max_pages=1)
        if first is None:
            rows.append((p.stem[-2:], p.stem, "UNREADABLE", ""))
            continue
        h = parse_header(first)
        rows.append((p.stem[-2:], p.stem, h["department"] or "?", (h["subject"] or "")[:60]))
    rows.sort()
    for code, stem, dept, subj in rows:
        print(f"{code} | {stem} | {dept} | {subj}")


def cmd_corpus(dir_: Path, out: Path, min_quality: float = 0.0):
    n_ok = n_thin = n_fail = n_lowq = 0
    with out.open("w", encoding="utf-8") as f:
        for p in sorted(dir_.glob("*.pdf")):
            first, full = read_pdf(p)
            if first is None:
                n_fail += 1
                continue
            if len((full or "").strip()) < 400:  # likely scanned/empty
                n_thin += 1
                continue
            q = readability(full)
            if q["score"] < min_quality:
                n_lowq += 1
                continue
            h = parse_header_bilingual(first)
            cites = extract_citations(full)
            clauses = chunk(full)
            # filename first 8 digits = GR date (authoritative; header fonts garble)
            ymd = p.stem[:8]
            date_iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if ymd.isdigit() else None
            rec = {
                "id": p.stem,
                "gr_code": p.stem,
                "dept_code": p.stem[-2:],
                "department": h["department"],
                "gr_number": h["gr_number"],
                "date": h["date"] or date_iso,
                "date_iso": date_iso,
                "subject": h["subject"],
                "n_chars": len(full),
                "quality": q["score"],
                "quality_verdict": q["verdict"],
                "clauses": clauses,
                **cites,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n_ok += 1
    print(f"corpus: ok={n_ok} thin/scanned={n_thin} low-quality={n_lowq} fail={n_fail} -> {out}",
          flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["headers", "corpus"])
    ap.add_argument("--dir", default=str(ROOT / "data" / "raw_pdfs"))
    ap.add_argument("--out", default=str(ROOT / "data" / "corpus.jsonl"))
    ap.add_argument("--min-quality", type=float, default=0.0)
    a = ap.parse_args()
    if a.mode == "headers":
        cmd_headers(Path(a.dir))
    else:
        cmd_corpus(Path(a.dir), Path(a.out), a.min_quality)
