"""Conflict-detection pipeline: retrieve -> screen (Groq, batched) -> explain (Gemini).

Conflict definition is deliberately NARROW (per plan): numeric/amount changes,
date/deadline changes, eligibility reversals, authority/procedure changes,
scope changes. Subtle legal interpretation is out of scope.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "llm"))
sys.path.append(str(ROOT / "src" / "index"))
sys.path.append(str(ROOT / "src" / "ingest"))

from clients import llm, llm_with_fallback, LLMError  # noqa: E402
from build_index import retrieve  # noqa: E402
from chunk_clauses import chunk  # noqa: E402

# e5-small cosine distances compress to ~[0.10, 0.25] on this index: related
# clauses measure <=0.16, off-topic >=0.18 (calibrated live). 0.18 is the cut.
#
# The cut still holds on the clean-text corpus — what changed is DEPTH. Clean
# clauses are ~13% longer and near-neighbours cluster tighter, so a genuine
# conflict partner can sit at rank 7-9 while still measuring 0.14. Measured on
# the four planted drafts: top_k=6 loses the Scenario C2 anchor
# 202403271818429322 entirely (it retrieves at d=0.1428, rank 9); top_k=8
# recovers it with no margin; top_k=10 recovers it with margin, at 189 candidate
# pairs across all four scenarios instead of 113. MuRIL screens all of them
# locally, so the extra depth costs milliseconds, not LLM calls.
MAX_COSINE_DISTANCE = 0.18

# Boilerplate detection is shared with the pair miners — lives in quality.py.
from quality import is_boilerplate  # noqa: E402

SCREEN_PROMPT = """You are screening clauses of a DRAFT Maharashtra Government Resolution (GR) against clauses from EXISTING GRs for conflicts.

A CONFLICT means the two clauses cannot both be in force for the same beneficiaries/institutions, specifically:
- different numeric amounts/percentages/limits for the same benefit or fee
- different dates/deadlines/durations for the same scheme or process
- eligibility reversal (one includes a group/condition the other excludes)
- different sanctioning authority or procedure for the same action
- different coverage/scope (districts, categories, institution types) for the same scheme

NOT a conflict: paraphrase, one elaborating the other, different schemes/subjects entirely, or clauses about unrelated matters (label these consistent or neutral).

For each numbered pair below, output a JSON object: {{"results": [{{"pair": <n>, "label": "conflict"|"consistent"|"neutral", "reason": "<one sentence>"}}]}}
Output ONLY the JSON.

{pairs}"""

# ---- Fine-tuned MuRIL screening layer (the trained model, in the product) ----
# Classifies every candidate pair locally in ~130 ms; only pairs it flags as
# contradiction proceed to the LLM extraction-verify + explanation. Set
# USE_MURIL=0 to fall back to LLM-verifying every pair.
MURIL_DIR = ROOT / "model" / "muril_gr_conflict_fp16"
_muril = {"model": None, "tok": None}


def muril_available():
    import os
    return os.environ.get("USE_MURIL", "1") != "0" and (MURIL_DIR / "config.json").exists()


def _muril_load():
    if _muril["model"] is None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        _muril["tok"] = AutoTokenizer.from_pretrained(str(MURIL_DIR))
        _muril["model"] = AutoModelForSequenceClassification.from_pretrained(
            str(MURIL_DIR), dtype=torch.float32)
        _muril["model"].eval()
    return _muril["model"], _muril["tok"]


def muril_screen(pairs, batch_size=16):
    """Return predicted label per pair from the fine-tuned classifier."""
    import torch
    model, tok = _muril_load()
    labels = []
    id2label = model.config.id2label
    with torch.no_grad():
        for s in range(0, len(pairs), batch_size):
            batch = pairs[s:s + batch_size]
            enc = tok([p["draft"][:1000] for p in batch],
                      [p["candidate"][:1000] for p in batch],
                      truncation=True, max_length=256, padding=True,
                      return_tensors="pt")
            out = model(**enc).logits.argmax(-1).tolist()
            labels += [id2label[i] for i in out]
    return labels


# The screener sometimes states an exclusion rule in its own reason and then
# flags anyway ("introduces a new benefit not covered by..."). Catch the
# self-reported exclusions in code and downgrade without wasting a verify call.
SELF_EXCLUDED_REASON_RE = re.compile(
    r"new benefit|not covered|not present in|not mentioned in|introduces a new"
    r"|different URL|unique code|file number",
    re.IGNORECASE,
)

# Extraction beats judgment for small models: instead of asking "is this a
# contradiction?", ask for each clause's value for the shared benefit and
# compare the values in code.
VERIFY_PROMPT = """Two clauses from Maharashtra Government Resolutions were flagged as possibly conflicting. Extract facts — do not judge.

CLAUSE 1 (draft): {draft}

CLAUSE 2 (existing): {existing}

1. same_scheme: Do BOTH clauses govern the SAME specific scheme/benefit for the SAME beneficiary group? (A different scholarship, a different stipend scheme, a different year's one-time sanction, or a merely similar topic = false.)
2. benefit: In 3-8 words, what shared benefit/rule do they both address (empty string if none)?
3. value1: What amount/percentage/date/authority/condition does CLAUSE 1 state or presuppose for that benefit? Quote it briefly (e.g. "50 टक्के", "Rs. 2,000", "31 March 2025"). Empty string if none.
4. value2: Same for CLAUSE 2 (e.g. "100 टक्के"). A value counts even if presupposed ("students entitled to 100% reimbursement" -> "100 टक्के"). Empty string if none.

Output ONLY JSON: {{"same_scheme": true|false, "benefit": "...", "value1": "...", "value2": "..."}}"""


def _script(s: str) -> str:
    """'mr' if the string's letters are mostly Devanagari, 'en' if mostly Latin,
    'mixed' when neither dominates (an acronym in a Marathi phrase stays 'mr')."""
    dev = sum(1 for c in s if "ऀ" <= c <= "ॿ")
    lat = sum(1 for c in s if c.isascii() and c.isalpha())
    if not (dev or lat):
        return "none"
    if dev >= 3 * lat:
        return "mr"
    if lat >= 3 * dev:
        return "en"
    return "mixed"


def _values_conflict(v1: str, v2: str) -> bool:
    """Compare extracted values in code: different digit-content = conflict."""
    # strip Indian-grouping commas first ('1,00,000' vs '100000' is the SAME
    # number, not three different ones)
    v1 = re.sub(r"(?<=[0-9०-९]),(?=[0-9०-९])", "", v1 or "")
    v2 = re.sub(r"(?<=[0-9०-९]),(?=[0-9०-९])", "", v2 or "")
    d1 = re.findall(r"[0-9०-९]+(?:\.[0-9०-९]+)?", v1)
    d2 = re.findall(r"[0-9०-९]+(?:\.[0-9०-९]+)?", v2)
    tr = str.maketrans("०१२३४५६७८९", "0123456789")
    n1 = {x.translate(tr).replace(",", "") for x in d1}
    n2 = {x.translate(tr).replace(",", "") for x in d2}
    if n1 and n2:
        return n1 != n2
    # Non-numeric values (authority/procedure) are compared as strings, which is
    # only meaningful when both are written in the same script. A draft clause in
    # English and a corpus clause in Marathi produce values that never share a
    # substring even when they say precisely the same thing — "directly through
    # the MahaDBT portal to Aadhaar-linked bank accounts" vs "सदर निधी थेट लाभ
    # हस्तांतरणाद्वारे (DBT) लाभार्थ्यांच्या बँक खात्यामध्ये जमा करण्यात यावा" is agreement, not
    # contradiction. Code cannot tell those apart across scripts, so it must not
    # assert a conflict it has not actually established.
    a, b = (v1 or "").strip().lower(), (v2 or "").strip().lower()
    if not (a and b):
        return False
    if _script(a) != _script(b):
        return False
    return a != b and a not in b and b not in a


# A financial year is a PERIOD LABEL, not a value. Government schemes are
# re-sanctioned every year, so a GR releasing funds "सन 2025-26 या आर्थिक वर्षामध्ये"
# does not contradict last year's GR releasing them for 2024-25 — it succeeds it,
# which is what the reference tab's currency advisory is for. This only matches a
# bare financial-year label: a real deadline ("दि.31.03.2025", "31 March 2025") is
# not one, so genuine date/deadline conflicts still fire.
_FY_WORD = r"(?:आर्थिक\s*वर्ष\S*|वित्तीय\s*वर्ष\S*|financial\s*year|f\.?\s*y\.?)"
_FY_RANGE = r"[0-9०-९]{4}\s*[-–—]\s*[0-9०-९]{2,4}"
_FY_LEAD = r"(?:सन\s*|for\s+|in\s+|during\s+|the\s+)?"
_FY_TAIL = r"(?:मध्ये|पासून|साठी|करिता|अखेर|मधील)?"
FY_LABEL_RE = re.compile(
    # Marathi puts the year first ("सन 2025-26 या आर्थिक वर्षामध्ये"),
    # English puts it last ("financial year 2025-26"). One of the two forms must
    # be present — a bare "2025-26" is deliberately NOT a financial-year label.
    rf"^\s*{_FY_LEAD}{_FY_RANGE}\s*(?:(?:या|चा|च्या|मधील)\s*)?{_FY_WORD}\s*{_FY_TAIL}\s*$"
    rf"|^\s*{_FY_LEAD}{_FY_WORD}\s*{_FY_RANGE}\s*{_FY_TAIL}\s*$",
    re.IGNORECASE,
)


def _is_financial_year_label(v: str) -> bool:
    return bool(FY_LABEL_RE.match(v or ""))


def _grounded(value: str, text: str) -> bool:
    """An extracted NUMERIC value only counts if its digits actually occur in
    the clause it was extracted from — the deterministic guard against the
    extractor hallucinating a number (e.g. reporting '50 टक्के' for a clause
    that only ever says '100 टक्के'). Non-numeric values pass through: they
    are legitimately paraphrased."""
    tr = str.maketrans("०१२३४५६७८९", "0123456789")
    strip = lambda s: re.sub(r"(?<=[0-9०-९]),(?=[0-9०-९])", "", s or "")  # noqa: E731
    runs = {x.translate(tr) for x in
            re.findall(r"[0-9०-९]+", strip(value))}
    if not runs:
        return True
    text_runs = {x.translate(tr) for x in
                 re.findall(r"[0-9०-९]+", strip(text))}
    return runs <= text_runs

EXPLAIN_PROMPT = """A draft Maharashtra Government Resolution contains a clause that conflicts with an existing GR. Explain the conflict precisely for a government drafting officer.

DRAFT CLAUSE:
{draft}

EXISTING GR CLAUSE (from {gr_label}):
{existing}

Screening reason: {reason}

Write 3-5 sentences: (1) state the specific contradiction (quote the conflicting values/terms), (2) name the existing GR it conflicts with, (3) recommend what the drafter should do (align the value, explicitly supersede the old GR, or narrow the scope). Be concrete and cite the GR identifiers given."""


def screen_pairs(pairs, batch_size=5, provider="groq"):
    """pairs: list of dicts {draft, candidate, meta}. Returns verdicts aligned to input."""
    verdicts = [None] * len(pairs)
    for s in range(0, len(pairs), batch_size):
        batch = pairs[s:s + batch_size]
        listing = []
        for i, p in enumerate(batch, 1):
            listing.append(
                f"PAIR {i}\nDRAFT: {p['draft'][:700]}\nEXISTING ({p['meta'].get('gr_code','?')}): "
                f"{p['candidate'][:700]}\n"
            )
        prompt = SCREEN_PROMPT.format(pairs="\n".join(listing))
        try:
            raw = llm_with_fallback(prompt, preferred=provider, temperature=0.0,
                                    max_tokens=2048, json_mode=True)
            data = json.loads(_json_slice(raw))
            for item in data.get("results", []):
                idx = s + int(item.get("pair", 0)) - 1
                if s <= idx < s + len(batch):  # in-batch only; stray ids dropped
                    lab = str(item.get("label", "neutral")).lower()
                    if lab not in ("conflict", "consistent", "neutral"):
                        lab = "neutral"
                    verdicts[idx] = {"label": lab, "reason": item.get("reason", "")}
        except (LLMError, json.JSONDecodeError, ValueError) as e:
            for i in range(s, min(s + batch_size, len(pairs))):
                verdicts[i] = {"label": "error", "reason": f"screening failed: {e}"}
    for i, v in enumerate(verdicts):
        if v is None:
            verdicts[i] = {"label": "neutral", "reason": "no verdict returned"}
    return verdicts


def _json_slice(text):
    """Tolerate markdown fences / stray prose around the JSON object."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


def explain_conflict(draft, existing, meta, reason):
    gn = meta.get("gr_number")
    gr_id = gn if gn and gn != "?" else meta.get("gr_code", "?")
    label = f"{meta.get('department','?')} GR {gr_id} dated {meta.get('date','?')}"
    prompt = EXPLAIN_PROMPT.format(draft=draft[:900], existing=existing[:900],
                                   gr_label=label, reason=reason)
    return llm_with_fallback(prompt, preferred="gemini", temperature=0.2, max_tokens=1024)


def review_draft(draft_text: str, top_k=10, max_draft_clauses=25, progress=None):
    """Full pipeline for the app. Returns dict with clauses, pairs, verdicts, conflicts."""
    clauses = chunk(draft_text)[:max_draft_clauses]
    pairs = []
    for ci, cl in enumerate(clauses):
        if is_boilerplate(cl):
            continue
        if progress:
            progress(f"retrieving candidates for clause {ci + 1}/{len(clauses)}")
        for cand in retrieve(cl, k=top_k):
            if cand["distance"] > MAX_COSINE_DISTANCE:
                continue
            if is_boilerplate(cand["clause"]):
                continue
            pairs.append({"draft": cl, "draft_idx": ci,
                          "candidate": cand["clause"], "meta": cand})
    # Stage 1 (when the trained model is present): MuRIL screens every pair in
    # milliseconds; only its "contradiction" flags go to the LLM stage. Without
    # it, every pair is LLM-verified (slower, same end result).
    screened = pairs
    muril_labels = None
    if muril_available():
        if progress:
            progress(f"MuRIL screening {len(pairs)} pairs (fine-tuned, local)")
        try:
            muril_labels = muril_screen(pairs)
            screened = [p for p, lab in zip(pairs, muril_labels)
                        if lab == "contradiction"]
        except Exception as e:
            print(f"muril screening unavailable ({e}); LLM-verifying all pairs")
            screened = pairs
            muril_labels = None

    # Stage 2: extraction-verify each surviving pair — the LLM extracts facts,
    # code makes the judgment. (Batched LLM judgment proved unstable on 8B.)
    verdicts = []
    conflicts = []
    for i, p in enumerate(screened):
        if progress:
            progress(f"extracting values for pair {i + 1}/{len(screened)}")
        v = {"label": "neutral", "reason": ""}
        try:
            raw = llm_with_fallback(
                VERIFY_PROMPT.format(draft=p["draft"][:700], existing=p["candidate"][:700]),
                temperature=0.0, max_tokens=512, json_mode=True)
            chk = json.loads(_json_slice(raw))
            v1, v2 = chk.get("value1", ""), chk.get("value2", "")
            if _is_financial_year_label(v1) and _is_financial_year_label(v2) and v1 != v2:
                v = {"label": "annual-reissue",
                     "reason": f"same scheme, different financial year "
                               f"('{v1}' vs '{v2}') — a re-sanction, not a conflict"}
            elif (chk.get("same_scheme")
                    and _grounded(v1, p["draft"])
                    and _grounded(v2, p["candidate"])
                    and _values_conflict(v1, v2)):
                v = {"label": "conflict",
                     "reason": f"For {chk.get('benefit') or 'the same benefit'}, "
                               f"the draft specifies '{chk.get('value1')}' but the "
                               f"existing GR specifies '{chk.get('value2')}'."}
        except (LLMError, json.JSONDecodeError, ValueError) as e:
            v = {"label": "error", "reason": f"verification failed: {e}"}
        verdicts.append(v)
        if v["label"] == "conflict":
            if progress:
                progress("explaining flagged conflict")
            try:
                expl = explain_conflict(p["draft"], p["candidate"], p["meta"], v["reason"])
            except LLMError as e:
                # a failed explanation must never discard an already-verified
                # conflict — the code-built reason string stands on its own
                expl = f"_(LLM explanation unavailable: {e})_"
            conflicts.append({**p, "reason": v["reason"], "explanation": expl})
    return {"n_clauses": len(clauses), "clauses": clauses,
            "n_pairs": len(pairs), "n_muril_flagged": (len(screened) if muril_labels else None),
            "verdicts": verdicts, "pairs": screened, "conflicts": conflicts}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    t = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else \
        "1. The fee reimbursement shall be 50% of tuition fees for EBC students."
    out = review_draft(t)
    print(f"clauses={out['n_clauses']} pairs={out['n_pairs']} conflicts={len(out['conflicts'])}")
    for c in out["conflicts"]:
        print("-", c["reason"])
