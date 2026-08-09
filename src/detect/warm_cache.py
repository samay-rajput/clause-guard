"""Run every planted scenario through the full pipeline to warm the LLM disk
cache (and as an end-to-end smoke test). The demo video is recorded only after
this reports all scenarios green.

Two layers are reported, because they fail for different reasons:

  retrieval + MuRIL  deterministic — same corpus and index give the same pair
                     and flag counts every run, with no LLM involved. Freeze
                     these exactly; a change here means the corpus moved.
  conflicts          LLM output. The 8B model is not perfectly stable across
                     cold runs, so what is frozen is the conflict IDENTITY
                     (which GR is flagged), not only the count.

`--baseline data/warm_ollama2.txt` re-checks a previous run's numbers instead of
just printing them.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "detect"))
from pipeline import review_draft  # noqa: E402

LINE_RE = re.compile(
    r"^(?P<name>\S+)\s+clauses=(?P<clauses>\d+)\s+pairs=(?P<pairs>\d+)\s+"
    r"muril=(?P<muril>\S+)\s+conflicts=(?P<conflicts>\d+)\s+grs=(?P<grs>\S*)"
)


def run_all():
    rows = []
    for p in sorted((ROOT / "data" / "planted").glob("*.txt")):
        t0 = time.time()
        print(f"=== {p.stem}", flush=True)
        out = review_draft(p.read_text(encoding="utf-8"),
                           progress=lambda m: print("   ", m, flush=True))
        grs = sorted({c["meta"].get("gr_code", "?") for c in out["conflicts"]})
        rows.append({"name": p.stem, "clauses": out["n_clauses"],
                     "pairs": out["n_pairs"],
                     "muril": out["n_muril_flagged"],
                     "conflicts": len(out["conflicts"]), "grs": grs,
                     "secs": round(time.time() - t0, 1)})
        print(f"    clauses={rows[-1]['clauses']} pairs={rows[-1]['pairs']} "
              f"muril={rows[-1]['muril']} conflicts={rows[-1]['conflicts']} "
              f"grs={','.join(grs) or '-'} ({rows[-1]['secs']}s)", flush=True)
        for c in out["conflicts"]:
            print(f"    CONFLICT vs {c['meta'].get('gr_code','?')}: {c['reason'][:100]}",
                  flush=True)
    return rows


def parse_baseline(path):
    base = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        m = LINE_RE.match(line.strip())
        if m:
            d = m.groupdict()
            base[d["name"]] = {
                "clauses": int(d["clauses"]), "pairs": int(d["pairs"]),
                "muril": None if d["muril"] == "None" else int(d["muril"]),
                "conflicts": int(d["conflicts"]),
                "grs": sorted(x for x in d["grs"].split(",") if x and x != "-"),
            }
    return base


def compare(rows, base):
    """Deterministic layers must match exactly; conflicts must match by identity."""
    bad = []
    for r in rows:
        b = base.get(r["name"])
        if not b:
            print(f"  (no baseline for {r['name']})")
            continue
        for k in ("clauses", "pairs", "muril"):
            if b[k] != r[k]:
                bad.append(f"{r['name']}: {k} {b[k]} -> {r[k]} (deterministic layer moved)")
        if b["grs"] != r["grs"]:
            bad.append(f"{r['name']}: conflicting GRs {b['grs'] or '-'} -> {r['grs'] or '-'}")
    return bad


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--save", default=None, help="write the summary lines here")
    a = ap.parse_args(argv)

    drafts = sorted((ROOT / "data" / "planted").glob("*.txt"))
    if not drafts:
        print("no planted drafts in data/planted/")
        return 1
    rows = run_all()

    summary = [f"{r['name']} clauses={r['clauses']} pairs={r['pairs']} "
               f"muril={r['muril']} conflicts={r['conflicts']} "
               f"grs={','.join(r['grs']) or '-'}" for r in rows]
    print("\n--- summary ---")
    print("\n".join(summary))
    if a.save:
        Path(a.save).write_text("\n".join(summary) + "\n", encoding="utf-8")
        print(f"-> {a.save}")

    if a.baseline:
        bad = compare(rows, parse_baseline(a.baseline))
        print()
        if bad:
            print("BASELINE MISMATCH")
            for b in bad:
                print("  -", b)
            return 1
        print(f"baseline matched: {a.baseline}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
