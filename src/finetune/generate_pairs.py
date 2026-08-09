"""Generate the synthetic NLI pair dataset (contradiction / consistent / neutral)
grounded in real corpus clauses.

Anti-artifact measures (per plan):
- 50% of contradictions must be PARAPHRASED (low lexical overlap), 50% minimal-edit;
  consistent/neutral classes mirror that overlap spread so surface overlap cannot
  predict the label.
- Neutral pairs: half are hard negatives (same scheme vocabulary, unrelated obligations).
- Premise/hypothesis order randomized; dedup downstream in validate_dataset.py.

Runs unattended, resumable: appends to data/pairs_raw.jsonl after every response.
Rate limits respected by the client's backoff + a fixed inter-call sleep.
"""
import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "llm"))
from clients import llm, LLMError, LLM_MODE, OLLAMA_MODEL  # noqa: E402

OUT = ROOT / "data" / "pairs_raw.jsonl"

# One label per call — small models follow narrow single-task prompts far better.
# The premise is ALWAYS the seed clause verbatim; only the hypothesis is generated.
LABEL_PROMPTS = {
    "contradiction": """A clause from a real Maharashtra Government Resolution is given. Write {n} DIFFERENT hypothesis clauses in {hyp_lang} that each CONTRADICT it — the two clauses could not both be in force.

Each hypothesis must contradict on exactly ONE aspect, and you must state which:
- "amount": a different number/percentage/money amount FOR THE SAME benefit or item
- "date": a different date/deadline/duration FOR THE SAME event or scheme
- "eligibility": the SAME group/condition included where the clause excludes it, or vice versa
- "authority": a DIFFERENT authority/procedure for the SAME action
- "scope": the SAME scheme covering a different area/category than stated

CRITICAL: the hypothesis must be about the SAME scheme/subject as the clause. A different scheme with different numbers is NOT a contradiction.
Make at least one hypothesis a full rephrasing (different sentence structure, synonyms), not a copy with one number changed.

CLAUSE:
{seed}

Output ONLY JSON: {{"items": [{{"hypothesis": "...", "conflict_type": "amount|date|eligibility|authority|scope"}}]}}""",

    "consistent": """A clause from a real Maharashtra Government Resolution is given. Write {n} DIFFERENT hypothesis clauses in {hyp_lang} that are each CONSISTENT with it — restating, paraphrasing, or elaborating the SAME rule without changing any fact, number, date, or condition.

At least one must be a heavy paraphrase with very different wording. Do NOT add new facts that the clause does not state; do NOT merely comment about the clause (e.g. "this will be reviewed") — restate its content.

CLAUSE:
{seed}

Output ONLY JSON: {{"items": [{{"hypothesis": "..."}}]}}""",

    "neutral": """A clause from a real Maharashtra Government Resolution is given. Write {n} DIFFERENT hypothesis clauses in {hyp_lang} about UNRELATED government matters — different schemes/subjects with no logical relation to the clause (neither restating nor contradicting it).

At least one must be a HARD case: reuse similar government vocabulary (sanction, scheme, disbursement, eligible, academic year) while being about a genuinely different matter.

CLAUSE:
{seed}

Output ONLY JSON: {{"items": [{{"hypothesis": "..."}}]}}""",
}


def load_seed_clauses(min_len=120, max_len=900, min_doc_quality=0.14):
    """Seed only from the cleanest-extracting docs — garbled seeds would poison
    the dataset. Which corpus counts as active is resolved explicitly (CG_CORPUS
    / data/corpus.active); the quality gates below were calibrated against the
    garbled distribution and barely bind on clean text — see DATASET_CARD.md."""
    sys.path.append(str(ROOT / "src" / "ingest"))
    from corpus_path import default_corpus_path
    from quality import readability

    corpus = default_corpus_path()
    seeds = []
    with open(corpus, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("quality", 1.0) < min_doc_quality and not r.get("cleaned"):
                continue
            for i, c in enumerate(r["clauses"]):
                if not (min_len <= len(c) <= max_len):
                    continue
                # clause-level gate: a clean doc can still contain garbled clauses
                q = readability(c, min_words=12)
                if q["verdict"] != "too-short" and q["score"] < 0.13:
                    continue
                seeds.append({"seed_id": f"{r['gr_code']}:{i}", "text": c,
                              "gr_code": r["gr_code"]})
    return seeds


def already_done():
    done = set()
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(line)["seed_id"])
            except Exception:
                pass
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-pairs", type=int, default=3600)
    ap.add_argument("--per-label", type=int, default=3, help="hypotheses per label per seed")
    ap.add_argument("--provider", default="gemini", choices=["gemini", "groq"])
    ap.add_argument("--hyp-lang", default="en", choices=["en", "same", "mixed"],
                    help="hypothesis language: en=English (safe for small models), "
                         "same=language of the seed, mixed=random per seed")
    ap.add_argument("--sleep", type=float, default=6.5)
    args = ap.parse_args()

    seeds = load_seed_clauses()
    random.seed(42)
    random.shuffle(seeds)
    done = already_done()
    print(f"{len(seeds)} seed clauses, {len(done)} already generated", flush=True)

    total_pairs = 0
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try:
                total_pairs += len(json.loads(line)["pairs"])
            except Exception:
                pass

    gen = f"ollama:{OLLAMA_MODEL}" if LLM_MODE == "ollama" else args.provider

    with OUT.open("a", encoding="utf-8") as out:
        for s in seeds:
            if total_pairs >= args.target_pairs:
                break
            if s["seed_id"] in done:
                continue
            seed_is_mr = bool(re.search(r"[ऀ-ॿ]{3,}", s["text"]))
            if args.hyp_lang == "en":
                hyp_lang = "English"
            elif args.hyp_lang == "same":
                hyp_lang = "Marathi (Devanagari)" if seed_is_mr else "English"
            else:
                hyp_lang = random.choice(["English", "Marathi (Devanagari)"])
            pairs = []
            for label, tmpl in LABEL_PROMPTS.items():
                prompt = tmpl.format(n=args.per_label, seed=s["text"][:1200],
                                     hyp_lang=hyp_lang)
                try:
                    raw = llm(prompt, provider=args.provider, temperature=0.6,
                              max_tokens=2048, json_mode=True, use_cache=False)
                    m = re.search(r"\{.*\}", raw, re.DOTALL)
                    data = json.loads(m.group(0) if m else raw)
                    for item in data.get("items", []):
                        hyp = (item.get("hypothesis") or "").strip()
                        if len(hyp) < 30:
                            continue
                        pairs.append({
                            "premise": s["text"],
                            "hypothesis": hyp,
                            "label": label,
                            "conflict_type": item.get("conflict_type", "none")
                            if label == "contradiction" else "none",
                            "lang": ("mr" if seed_is_mr else "en") +
                                    ("-en" if hyp_lang == "English" and seed_is_mr else ""),
                        })
                except (LLMError, json.JSONDecodeError, ValueError) as e:
                    print(f"{s['seed_id']}/{label}: SKIP ({str(e)[:100]})", flush=True)
                time.sleep(args.sleep)
            if pairs:
                out.write(json.dumps({"seed_id": s["seed_id"],
                                      "gr_code": s["gr_code"],
                                      "generator": gen,
                                      "pairs": pairs}, ensure_ascii=False) + "\n")
                out.flush()
                total_pairs += len(pairs)
                print(f"{s['seed_id']}: +{len(pairs)} (total {total_pairs})", flush=True)
    print(f"DONE: {total_pairs} pairs in {OUT}", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
