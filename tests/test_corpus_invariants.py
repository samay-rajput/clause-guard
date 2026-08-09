"""Deterministic corpus gate — no LLM, no index, no network.

This is the layer that would have caught the clean-text migration's real hazards
before they reached the demo: a 39% clause loss from a chunker that missed
Devanagari clause markers, page furniture leaking into indexed clauses, and the
scenario anchors silently losing the numbers the whole demo turns on.

Run: python tests/test_corpus_invariants.py [corpus.jsonl]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src" / "ingest"))
from corpus_path import default_corpus_path  # noqa: E402
from devanagari import to_ascii_digits  # noqa: E402

# Every scenario the demo shows rests on these four GRs. `digits` are the values
# the beat depends on — if one disappears from the record, the beat is dead even
# though every count still looks healthy.
ANCHORS = {
    "202407191857335408": {"what": "Scenario A — 100% vs 50% fee reimbursement",
                           "digits": ["100", "50"]},
    "202403271818429322": {"what": "Scenario C2 — DBT conflict #1", "digits": []},
    "202302091813048908": {"what": "Scenario C2 — DBT conflict #2", "digits": []},
    "202402271742452721": {"what": "gold layout specimen", "digits": []},
}

MIN_RECORDS = 700
MIN_CLAUSES_PER_GR = 7.0
MIN_READABILITY_MEDIAN = 0.20
PAGE_FURNITURE = re.compile(r"#\s*Page\s+\d+|पृष्ठ\s*[०-९0-9]+\s*पैकी")


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main(argv):
    path = Path(argv[1]) if len(argv) > 1 else default_corpus_path()
    recs = load(path)
    by_code = {r["gr_code"]: r for r in recs}
    fails = []

    def check(ok, msg):
        print(f"  {'OK  ' if ok else 'FAIL'} {msg}")
        if not ok:
            fails.append(msg)

    print(f"corpus: {path}")
    print(f"records: {len(recs)}")

    check(len(recs) >= MIN_RECORDS, f"record count {len(recs)} >= {MIN_RECORDS}")
    check(len(by_code) == len(recs), "gr_code is unique across the corpus")

    n_clauses = sum(len(r["clauses"]) for r in recs)
    per_gr = n_clauses / max(1, len(recs))
    check(per_gr >= MIN_CLAUSES_PER_GR,
          f"clauses/GR {per_gr:.2f} >= {MIN_CLAUSES_PER_GR} (total {n_clauses})")

    furniture = [r["gr_code"] for r in recs
                 if any(PAGE_FURNITURE.search(c) for c in r["clauses"])]
    check(not furniture, f"no page furniture in clauses ({len(furniture)} records affected)")

    quals = sorted(r.get("quality", 0) for r in recs)
    median = quals[len(quals) // 2]
    check(median >= MIN_READABILITY_MEDIAN,
          f"readability median {median:.4f} >= {MIN_READABILITY_MEDIAN}")

    bad_code = [r["gr_code"] for r in recs
                if not (len(r["gr_code"]) == 18 and r["gr_code"].isdigit())]
    check(not bad_code, f"every gr_code is 18 digits ({len(bad_code)} bad)")
    check(all(r.get("dept_code") == r["gr_code"][-2:] for r in recs),
          "dept_code always equals the code's last two digits")

    self_citing = [r["gr_code"] for r in recs
                   if r["gr_code"] in (r.get("cited_codes") or [])]
    check(not self_citing, f"no record cites itself ({len(self_citing)})")

    print("\nanchors:")
    for code, spec in ANCHORS.items():
        r = by_code.get(code)
        if r is None:
            check(False, f"{code} present — {spec['what']}")
            continue
        blob = to_ascii_digits(" ".join(r["clauses"]))
        missing = [d for d in spec["digits"] if d not in blob]
        check(not missing and len(r["clauses"]) >= 3,
              f"{code} {spec['what']}: {len(r['clauses'])} clauses"
              + (f", MISSING {missing}" if missing else ""))

    print()
    if fails:
        print(f"FAILED {len(fails)} invariant(s)")
        return 1
    print("test_corpus_invariants OK")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv))
