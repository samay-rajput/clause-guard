"""Build a ClauseGuard corpus from the clean-Marathi mahGRs text.

    python src/ingest/build_mahgrs_corpus.py --out data/corpus_mahgrs_full.jsonl
    python src/ingest/build_mahgrs_corpus.py --out data/corpus_mahgrs.jsonl \
           --codes-from data/corpus.jsonl --carry-orphans

Same record shape as `parse_pdfs.py corpus`, so every downstream module works
unchanged. Two things are done differently, both forced by what mahGRs is:

**Identity comes from the filename, not the text.** The 18-digit code is printed
in only 3.3% of mahGRs documents (98.1% of archive PDFs carried it) because the
availability footer is one of the sections orgpedia's extraction drops. The
filename IS that code, so `gr_code`, `dept_code` and `date_iso` are taken from it
— which is also why they are the only fields in this project that never garble.

**Citations are resolved through a file-number index.** With the 18-digit codes
gone from the body text, `cited_codes` collapses to ~6 across the whole corpus
and the citation graph — already empty — could never populate. But clean text
DOES carry the formal file numbers (शासन निर्णय क्र.शिष्यवृ-२०२४/प्र.क्र.१०५/तांशि-४),
in 98.9% of documents. Building {normalised file number -> gr_code} over every
record and resolving each `cited_ref` against it recovers the links the codes
used to provide, and gives this project its first non-empty citation graph.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(Path(__file__).parent))
sys.path.append(str(ROOT / "src" / "reftrack"))
from chunk_clauses import chunk  # noqa: E402
from extract_metadata import extract_citations  # noqa: E402
from mahgrs import iter_files, read_clean  # noqa: E402
from parse_pdfs import parse_header_bilingual  # noqa: E402
from quality import readability  # noqa: E402

MIN_CHARS = 400  # below this the extraction is empty rather than short


# The identifying core of a Maharashtra file number: <prefix>-<year>/<serial>/<desk>.
# A citation wraps it in words the header line does not have ("शासन निर्णय, शालेय
# शिक्षण व क्रीडा विभाग, क्र.पीआई-1094/704/प्रा..."), so both sides are reduced to
# this core before they are compared — otherwise the department name alone makes
# a reference and its target look like different GRs.
FILE_NO_CORE_RE = re.compile(
    r"([^\s,;:()]{0,25}[-–]\s*[०-९0-9]{2,4}\s*/\s*[^\s,;:]{1,40}(?:\s*/\s*[^\s,;:]{1,25})?)"
)


def file_number_core(s: str) -> str:
    m = FILE_NO_CORE_RE.search(s or "")
    return m.group(1) if m else (s or "")


def _same_file_number(a: str, b: str) -> bool:
    """True when two normalised references denote the same file number. The
    citing form carries a date tail the header line lacks, so this is a prefix
    comparison rather than equality."""
    return bool(a) and bool(b) and len(a) >= 8 and len(b) >= 8 and (
        a.startswith(b) or b.startswith(a))


def build_record(dept_dir: str, code: str, path: Path) -> dict | None:
    from citations import _norm_ref

    got = read_clean(path)
    text = got["text"]
    if len(text.strip()) < MIN_CHARS:
        return None
    header = parse_header_bilingual(text[:3000])
    cites = extract_citations(text)
    # page 1 states the GR's OWN number; without this every record cites itself
    own = _norm_ref(file_number_core(header["gr_number"] or ""))
    cites["cited_refs"] = [r for r in cites["cited_refs"]
                           if not _same_file_number(_norm_ref(file_number_core(r)), own)]
    cites["cited_codes"] = [c for c in cites["cited_codes"] if c != code]
    q = readability(text)
    ymd = code[:8]
    return {
        "id": code,
        "gr_code": code,
        "dept_code": code[-2:],
        "department": header["department"],
        "gr_number": header["gr_number"],
        "date": header["date"] or (f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if ymd.isdigit() else None),
        "date_iso": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}" if ymd.isdigit() else None,
        "subject": header["subject"],
        "n_chars": len(text),
        "quality": q["score"],
        "quality_verdict": q["verdict"],
        "clauses": chunk(text),
        "source": "mahgrs",
        "dept_dir": dept_dir,
        "pages_total": got["pages_total"],
        "pages_empty": got["pages_empty"],
        **cites,
    }


def resolve_citations(records: list, index_records: list = None) -> dict:
    """Fill each record's `cited_codes` by resolving its `cited_refs` against a
    file-number index. `index_records` defaults to `records`; a demo-sized
    corpus should pass the full corpus so a reference to a GR outside the subset
    still resolves (an out-of-corpus code is inert downstream, never a mislink).
    """
    from citations import _norm_ref

    PREFIX = 10  # a file number is identified well before its date tail

    index, ambiguous = {}, set()
    for r in (index_records if index_records is not None else records):
        n = _norm_ref(file_number_core(r.get("gr_number") or ""))
        if len(n) < 8:  # too short to identify a GR — would mislink
            continue
        if n in index and index[n] != r["gr_code"]:
            ambiguous.add(n)
        index[n] = r["gr_code"]
    for n in ambiguous:
        index.pop(n, None)
    # bucket by leading characters so the prefix fallback stays O(1) per
    # reference — scanning the whole index per reference is ~10^9 comparisons
    # at full corpus scale
    buckets = {}
    for k, code in index.items():
        if len(k) >= PREFIX:
            buckets.setdefault(k[:PREFIX], []).append((k, code))

    stats = Counter()
    for r in records:
        found = set(r.get("cited_codes") or [])
        for ref in r.get("cited_refs") or []:
            n = _norm_ref(file_number_core(ref))
            if len(n) < 8:
                stats["ref_too_short"] += 1
                continue
            hit = index.get(n)
            if hit is None and len(n) >= PREFIX:
                # the citing form carries a date tail the header line lacks
                cands = {code for k, code in buckets.get(n[:PREFIX], [])
                         if n.startswith(k) or k.startswith(n)}
                if len(cands) == 1:
                    hit = cands.pop()
                elif cands:
                    stats["ambiguous_ref"] += 1
            if hit and hit != r["gr_code"]:
                found.add(hit)
                stats["resolved"] += 1
            elif hit:
                stats["self"] += 1
            else:
                stats["unresolved"] += 1
        r["cited_codes"] = sorted(found)
    stats["index_size"] = len(index)
    stats["ambiguous_dropped"] = len(ambiguous)
    return dict(stats)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--depts", nargs="*", default=None,
                    help="department directory names (default: all)")
    ap.add_argument("--codes-from", default=None,
                    help="restrict to the gr_codes present in this corpus .jsonl")
    ap.add_argument("--carry-orphans", action="store_true",
                    help="with --codes-from: keep records that have no mahGRs "
                         "twin, marked source='archive'")
    ap.add_argument("--resolve-index-from", default=None,
                    help="build the file-number index from this corpus .jsonl "
                         "instead of the records being written")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args(argv)

    wanted, old_by_code = None, {}
    if a.codes_from:
        with open(ROOT / a.codes_from if not Path(a.codes_from).is_absolute()
                  else a.codes_from, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                old_by_code[r["gr_code"]] = r
        wanted = set(old_by_code)
        print(f"restricting to {len(wanted)} codes from {a.codes_from}", flush=True)

    records, seen, skipped = [], set(), Counter()
    for dept_dir, code, path in iter_files(a.depts):
        if wanted is not None and code not in wanted:
            continue
        if code in seen:            # one GR is filed under two departments
            skipped["duplicate_code"] += 1
            continue
        rec = build_record(dept_dir, code, path)
        if rec is None:
            skipped["too_short"] += 1
            continue
        seen.add(code)
        records.append(rec)
        if a.limit and len(records) >= a.limit:
            break
        if len(records) % 2000 == 0:
            print(f"  parsed {len(records)}", flush=True)

    orphans = 0
    if wanted is not None and a.carry_orphans:
        for code in sorted(wanted - seen):
            old = dict(old_by_code[code])
            old["source"] = "archive"
            # the archive build never filtered a GR's own code out of its
            # citations — 761 of the old corpus's 769 cited_codes were self-refs
            old["cited_codes"] = [c for c in (old.get("cited_codes") or []) if c != code]
            records.append(old)
            orphans += 1

    records.sort(key=lambda r: r["gr_code"])
    index_records = None
    if a.resolve_index_from:
        p = Path(a.resolve_index_from)
        with open(ROOT / p if not p.is_absolute() else p, encoding="utf-8") as f:
            index_records = [json.loads(line) for line in f if line.strip()]
        print(f"resolving citations against {len(index_records)} indexed GRs", flush=True)
    stats = resolve_citations(records, index_records)

    out = ROOT / a.out if not Path(a.out).is_absolute() else Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_clauses = sum(len(r["clauses"]) for r in records)
    empty = sum(r.get("pages_empty", 0) for r in records)
    total = sum(r.get("pages_total", 0) for r in records)
    with_code = sum(1 for r in records if r.get("cited_codes"))
    print(f"\nrecords {len(records)} (mahGRs {len(seen)}, carried-over archive {orphans})")
    print(f"clauses {n_clauses}  ({n_clauses / max(1, len(records)):.2f}/GR)")
    print(f"pages   {total} of which empty {empty} ({empty / max(1, total):.1%})")
    print(f"gr_number present {sum(1 for r in records if r.get('gr_number'))}/{len(records)}"
          f"  subject {sum(1 for r in records if r.get('subject'))}/{len(records)}")
    print(f"citations resolved: {stats}")
    print(f"records with >=1 cited_code: {with_code}")
    if skipped:
        print(f"skipped: {dict(skipped)}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
