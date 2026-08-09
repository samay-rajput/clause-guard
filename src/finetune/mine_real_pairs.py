"""Zero-LLM training-pair sources (per the hybrid-dataset decision):

1. AMENDMENT MINING — real contradictions: two GRs of the same department with
   strongly-overlapping subjects, containing near-identical clauses that differ
   in their numbers (amount/date revisions). Genuine government contradictions,
   no model involved.
2. NUMBER-SWAP AUGMENTATION — programmatic contradictions: take a clean seed
   clause, change one amount/percentage/year to a plausible alternative.
   Minimal-edit by design (the LLM-generated half of the dataset supplies the
   paraphrased contradictions; the validator's probe reports the overlap mix).
3. MINED NEUTRALS — clause pairs from different departments with near-zero
   token overlap.

Output: data/pairs_mined.jsonl (same record schema as pairs_raw.jsonl,
generator field marks provenance: mined-amendment / augment-numswap / mined-neutral).
"""
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "ingest"))
from devanagari import to_ascii_digits  # noqa: E402
from quality import is_boilerplate, readability  # noqa: E402

OUT = ROOT / "data" / "pairs_mined.jsonl"
TOK = re.compile(r"[A-Za-z]{3,}|[ऀ-ॿ]{3,}")
NUM = re.compile(r"\d[\d,.]*")


def tokens(s):
    return set(TOK.findall(s))


def jaccard(a, b):
    return len(a & b) / max(1, len(a | b))


ENUM_RE = re.compile(r"^\s*[0-9०-९]{1,2}[.)]\s*")


def digits(s):
    # ignore long numbers (GR unique codes) and the leading clause enumerator —
    # only substantive values (amounts, percentages, years) should drive mining.
    # Script is folded first: `\d` matches Devanagari numerals but does not
    # equate them, so '५०' and '50' would read as two different amounts and
    # fabricate an "amendment" pair on a mixed-script corpus.
    s = to_ascii_digits(ENUM_RE.sub("", s))
    return tuple(sorted(x.replace(",", "") for x in NUM.findall(s)
                        if len(x.replace(",", "").replace(".", "")) <= 7))


def good_clause(c):
    if not (120 <= len(c) <= 900) or is_boilerplate(c):
        return False
    # require real Marathi prose: ≥12 Devanagari words AND decent readability
    # (also rejects English table-junk clauses, which have few Devanagari words)
    q = readability(c, min_words=12)
    return q["verdict"] != "too-short" and q["score"] >= 0.13


def mine_amendments(recs, max_total=400):
    """Same dept + similar subject + near-identical clause with different numbers."""
    out = []
    by_dept = {}
    for r in recs:
        by_dept.setdefault(r["dept_code"], []).append(r)
    for dept, rs in by_dept.items():
        rs = sorted(rs, key=lambda r: r["gr_code"])
        subj_toks = [tokens(r.get("subject") or "") for r in rs]
        for i in range(len(rs)):
            if len(out) >= max_total:
                return out
            for j in range(i + 1, min(i + 40, len(rs))):
                if not subj_toks[i] or jaccard(subj_toks[i], subj_toks[j]) < 0.3:
                    continue
                found = 0
                for ca in rs[i]["clauses"]:
                    if found >= 2 or not good_clause(ca):
                        continue
                    ta, da = tokens(ca), digits(ca)
                    if not da:
                        continue
                    for cb in rs[j]["clauses"]:
                        if not good_clause(cb):
                            continue
                        db = digits(cb)
                        if not db or db == da:
                            continue
                        tb = tokens(cb)
                        # near-identical text (>=0.6) AND the non-numeric words
                        # barely differ — so the difference IS the values, not
                        # e.g. a different beneficiary institution's name.
                        # Also require a differing number of >=2 digits (a bare
                        # enumerator or list-index difference doesn't count).
                        diff_nums = set(da) ^ set(db)
                        if (jaccard(ta, tb) >= 0.6 and len(ta ^ tb) <= 3
                                and any(len(x.replace(".", "")) >= 2 for x in diff_nums)):
                            out.append({
                                "seed_id": f"mined:{rs[i]['gr_code']}x{rs[j]['gr_code']}:{found}",
                                "gr_code": rs[i]["gr_code"],
                                "generator": "mined-amendment",
                                "pairs": [{
                                    "premise": ca, "hypothesis": cb,
                                    "label": "contradiction",
                                    "conflict_type": "amount", "lang": "mr",
                                }],
                            })
                            found += 1
                            break
    return out


PLAUSIBLE_PCT = ["25", "40", "50", "60", "75", "80", "90", "100"]


CONTEXT_RE = re.compile(r"टक्के|%|रु|रूपये|लाख|कोटी|हजार|Rs|per cent|percent|सन\s*$|वर्ष")


def swap_number(clause, rng):
    """Replace one number with a different plausible one; None if not possible."""
    ms = list(NUM.finditer(clause))
    # only swap numbers that are clearly VALUES: money/percent/year context
    # nearby — never GR codes, clause enumerators, or citation file numbers
    ms = [m for m in ms
          if len(m.group(0).replace(",", "")) <= 7
          and m.start() >= 4
          and CONTEXT_RE.search(clause[max(0, m.start() - 15): m.end() + 15])]
    if not ms:
        return None
    m = rng.choice(ms)
    old = m.group(0)
    core = old.replace(",", "")
    near = clause[max(0, m.start() - 15): m.end() + 15]
    if re.search(r"टक्के|%|percent|per cent", near) and core.isdigit() and int(core) <= 100:
        new = rng.choice([p for p in PLAUSIBLE_PCT if p != core])
    elif core in PLAUSIBLE_PCT:
        new = rng.choice([p for p in PLAUSIBLE_PCT if p != core])
    elif core.isdigit() and 1900 < int(core) < 2100:  # year
        new = str(int(core) + rng.choice([-2, -1, 1, 2]))
    elif core.replace(".", "").isdigit():
        mult = rng.choice([2, 3, 5, 10])
        new = str(int(float(core.replace(".", "")) * mult))
    else:
        return None
    return clause[: m.start()] + new + clause[m.end():]


def augment_numswap(recs, rng, max_total=350):
    out = []
    clauses = []
    for r in recs:
        for i, c in enumerate(r["clauses"]):
            if good_clause(c) and digits(c):
                clauses.append((r["gr_code"], i, c))
    rng.shuffle(clauses)
    for code, i, c in clauses:
        if len(out) >= max_total:
            break
        swapped = swap_number(c, rng)
        if swapped and swapped != c:
            out.append({
                "seed_id": f"augment:{code}:{i}",
                "gr_code": code,
                "generator": "augment-numswap",
                "pairs": [{"premise": c, "hypothesis": swapped,
                           "label": "contradiction",
                           "conflict_type": "amount", "lang": "mr"}],
            })
    return out


def truncation_consistents(recs, rng, max_total=300):
    """High-overlap CONSISTENT pairs: a clause vs its own leading portion —
    a genuine subset restatement of the same rule. Purpose: give the
    'consistent' class a high-lexical-overlap cohort so surface overlap stops
    predicting the label (the number-swap contradictions are high-overlap)."""
    out = []
    pool = []
    for r in recs:
        for i, c in enumerate(r["clauses"]):
            if good_clause(c) and len(c) >= 300:
                pool.append((r["gr_code"], i, c))
    rng.shuffle(pool)
    for code, i, c in pool:
        if len(out) >= max_total:
            break
        cut = c.rfind(" ", int(len(c) * 0.45), int(len(c) * 0.7))
        if cut < 100:
            continue
        frag = c[:cut].strip()
        if digits(frag) and digits(frag) != digits(c):
            pass  # fragment keeps a subset of values — still consistent
        out.append({
            "seed_id": f"trunc:{code}:{i}",
            "gr_code": code,
            "generator": "augment-truncation",
            "pairs": [{"premise": c, "hypothesis": frag, "label": "consistent",
                       "conflict_type": "none", "lang": "mr"}],
        })
    return out


def hard_neutrals(recs, rng, max_total=250):
    """Moderate-overlap NEUTRALS: same department, shared template vocabulary,
    but different subjects — the hard negatives that punish overlap-counting."""
    out = []
    by_dept = {}
    for r in recs:
        by_dept.setdefault(r["dept_code"], []).append(r)
    for dept, rs in by_dept.items():
        rng.shuffle(rs)
        for i in range(0, len(rs) - 1, 2):
            if len(out) >= max_total:
                return out
            ra, rb = rs[i], rs[i + 1]
            # different subjects required
            if jaccard(tokens(ra.get("subject") or "a"), tokens(rb.get("subject") or "b")) > 0.2:
                continue
            for ca in ra["clauses"]:
                if not good_clause(ca):
                    continue
                best = None
                for cb in rb["clauses"]:
                    if not good_clause(cb):
                        continue
                    j = jaccard(tokens(ca), tokens(cb))
                    if 0.2 <= j <= 0.45:
                        best = cb
                        break
                if best:
                    out.append({
                        "seed_id": f"hardneutral:{ra['gr_code']}x{rb['gr_code']}",
                        "gr_code": ra["gr_code"],
                        "generator": "mined-neutral-hard",
                        "pairs": [{"premise": ca, "hypothesis": best,
                                   "label": "neutral", "conflict_type": "none",
                                   "lang": "mr"}],
                    })
                    break
    return out


def mine_neutrals(recs, rng, max_total=350, max_easy=120):
    """Neutrals with a DELIBERATE overlap spread: mostly moderate-overlap pairs
    (shared government vocabulary, different matters) so that near-zero overlap
    does not become a 'neutral' fingerprint; a smaller easy low-overlap slice."""
    out = []
    n_easy = 0
    pool = []
    for r in recs:
        for i, c in enumerate(r["clauses"]):
            if good_clause(c):
                pool.append((r["gr_code"], r["dept_code"], i, c))
    rng.shuffle(pool)
    for k in range(0, len(pool) - 1, 2):
        if len(out) >= max_total:
            break
        (ca_code, da, ia, ca), (cb_code, db, ib, cb) = pool[k], pool[k + 1]
        if ca_code == cb_code:
            continue
        j = jaccard(tokens(ca), tokens(cb))
        if 0.08 <= j <= 0.40:
            kind = "moderate"
        elif j < 0.08 and da != db and n_easy < max_easy:
            kind = "easy"
            n_easy += 1
        else:
            continue
        out.append({
            "seed_id": f"neutral:{ca_code}:{ia}x{cb_code}:{ib}",
            "gr_code": ca_code,
            "generator": "mined-neutral",
            "pairs": [{"premise": ca, "hypothesis": cb, "label": "neutral",
                       "conflict_type": "none", "lang": "mr"}],
        })
    return out


def main():
    rng = random.Random(42)
    recs = [json.loads(l) for l in
            (ROOT / "data" / "corpus.jsonl").read_text(encoding="utf-8").splitlines()]
    # Amendment candidates go to a SEPARATE review file, not training data:
    # on garbled text too many are structural look-alikes (citation-list items,
    # repeated template paragraphs) rather than true value revisions. They are
    # excellent Scenario-B/demo material after human review, though.
    amendments = mine_amendments(recs)
    cand = ROOT / "data" / "pairs_amendment_candidates.jsonl"
    with cand.open("w", encoding="utf-8") as f:
        for rec in amendments:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"amendment candidates (review file, NOT training): {len(amendments)} -> {cand}",
          flush=True)
    swaps = augment_numswap(recs, rng)
    print(f"number-swap contradictions: {len(swaps)}", flush=True)
    neutrals = mine_neutrals(recs, rng)
    print(f"mined neutrals: {len(neutrals)}", flush=True)
    truncs = truncation_consistents(recs, rng)
    print(f"truncation consistents (high-overlap): {len(truncs)}", flush=True)
    hardn = hard_neutrals(recs, rng)
    print(f"hard neutrals (moderate-overlap): {len(hardn)}", flush=True)
    rows = swaps + neutrals + truncs + hardn
    with OUT.open("w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} training records -> {OUT}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
