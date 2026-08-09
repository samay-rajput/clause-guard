"""Regenerate the human blind-check from the most READABLE test pairs.

The legacy-font garble makes many corpus clauses unreadable to humans; a human
check on unreadable text validates nothing. This samples the test pairs whose
Devanagari sides a Marathi reader can actually judge (highest readability
first), stratified by label with generator diversity, and writes the check MD +
the hidden answer key. The result is reported honestly as the 'readable-subset'
human agreement number.
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "ingest"))
from quality import DEV_WORD, is_boilerplate, readability  # noqa: E402

OUT_MD = Path(r"C:\Users\samay\OneDrive\Desktop\hackathon ai\5-plans-and-logs\BLIND-CHECK-50.md")
OUT_KEY = ROOT / "data" / "blind_check_key.json"
PER_LABEL = {"contradiction": 17, "consistent": 17, "neutral": 16}

HEADER = """# Blind label check — 50 pairs (readable subset)

For each pair, write ONE letter on the answer line:
**C** = the two clauses CLASH (cannot both be rules at once) ·
**S** = they SAY THE SAME thing (restatement) ·
**N** = UNRELATED matters

Some Marathi may still show minor font-garbling (that is the real corpus text —
judge the meaning). If a pair is genuinely unjudgeable, write **?** instead;
those are counted separately, never guessed.

---
"""


def side_score(text: str):
    """Human-judgeability of a side, 0..1, comparable across scripts.

    Devanagari sides: COMMON-vocab readability rescaled so 'clean' (>=0.25) ~ 1.0.
    Latin sides: fraction of prose-like tokens — English table-extract debris
    (ALL-CAPS columns, numbers, parens) sinks, real sentences float."""
    words = DEV_WORD.findall(text or "")
    if len(words) >= 6:
        return min(1.0, readability(text, min_words=6)["score"] / 0.25)
    toks = (text or "").split()
    if len(toks) < 4:
        return 0.3
    prose = sum(1 for t in toks if any(c.islower() for c in t))
    return prose / len(toks)


def main():
    rows = [json.loads(l) for l in
            (ROOT / "data" / "pairs_test.jsonl").read_text(encoding="utf-8").splitlines()]
    cands = []
    for r in rows:
        if is_boilerplate(r["premise"]) or is_boilerplate(r["hypothesis"]):
            continue
        score = min(side_score(r["premise"]), side_score(r["hypothesis"]))
        if score < 0.4:  # neither a human check nor good optics below this
            continue
        cands.append((score, r))

    rng = random.Random(42)
    taken = []
    for label, n in PER_LABEL.items():
        pool = sorted((c for c in cands if c[1]["label"] == label), key=lambda c: -c[0])
        cap = max(1, int(n * 0.6))  # generator diversity: max 60% from one generator
        per_gen, sel = {}, []
        for sc, r in pool:
            g = r.get("generator", "?")
            if per_gen.get(g, 0) >= cap:
                continue
            sel.append((sc, r))
            per_gen[g] = per_gen.get(g, 0) + 1
            if len(sel) >= n:
                break
        taken += sel

    rng.shuffle(taken)
    lines, key = [HEADER], []
    for i, (sc, r) in enumerate(taken, 1):
        a, b = r["premise"], r["hypothesis"]
        swapped = rng.random() < 0.5
        if swapped:
            a, b = b, a
        lines += [f"### {i}", f"A) {a.strip()}", "", f"B) {b.strip()}", "",
                  "**Your answer:** ", "", "---", ""]
        key.append({"n": i, "id": r.get("id"), "label": r["label"],
                    "generator": r.get("generator"),
                    "min_readability": round(sc, 4), "swapped": swapped})

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    OUT_KEY.write_text(json.dumps(key, indent=1, ensure_ascii=False), encoding="utf-8")

    scores = [k["min_readability"] for k in key]
    gens = {}
    for k in key:
        gens[k["generator"]] = gens.get(k["generator"], 0) + 1
    print(f"wrote {len(key)} pairs -> {OUT_MD}")
    print(f"readability of taken set: min {min(scores):.3f}, "
          f"mean {sum(scores) / len(scores):.3f}")
    print(f"labels: {[(l, sum(1 for k in key if k['label'] == l)) for l in PER_LABEL]}")
    print(f"generators: {gens}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
