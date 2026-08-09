"""Mine canonical clause templates from the full mahGRs corpus.

Government boilerplate recurs verbatim across dozens-to-hundreds of GRs (the
dedupe pass found one clause in 392 GRs). A clause that appears verbatim in
N>=MIN_GRS real GRs *is* the official wording — the drafting rail offers it to
the LLM as the base to adapt, and the wording audit measures fidelity against
it. Zero-hallucination by construction for standard sections.

Usage: python src/draftgen/mine_templates.py [--corpus data/corpus_mahgrs_full.jsonl]
Writes data/clause_templates.jsonl: {"dept_code", "text", "n_grs"} sorted by
dept then frequency.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "ingest"))
from quality import is_boilerplate  # noqa: E402

OUT = ROOT / "data" / "clause_templates.jsonl"
MIN_GRS = 20          # verbatim in >=20 GRs = established official wording
MIN_LEN, MAX_LEN = 60, 400
PER_DEPT = 12


def mine(corpus_path: Path) -> list:
    counts = defaultdict(Counter)          # dept -> normalized clause -> n GRs
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            dept = (r.get("gr_code") or "")[-2:] or "?"
            seen = set()
            for c in r.get("clauses", []):
                key = " ".join(c.split())
                if not (MIN_LEN <= len(key) <= MAX_LEN) or key in seen:
                    continue
                seen.add(key)              # count GRs, not repetitions within one
                counts[dept][key] += 1
    rows = []
    for dept, ctr in sorted(counts.items()):
        kept = 0
        for text, n in ctr.most_common():
            if n < MIN_GRS or kept >= PER_DEPT:
                break
            if is_boilerplate(text):       # page furniture is not a template
                continue
            rows.append({"dept_code": dept, "text": text, "n_grs": n})
            kept += 1
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(ROOT / "data" / "corpus_mahgrs_full.jsonl"))
    a = ap.parse_args()
    rows = mine(Path(a.corpus))
    with OUT.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    by_dept = Counter(r["dept_code"] for r in rows)
    print(f"{len(rows)} templates -> {OUT}")
    for d, n in sorted(by_dept.items()):
        print(f"  dept {d}: {n}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
