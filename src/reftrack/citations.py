"""Reference tracking: extract citations from a draft, link them to the corpus,
flag stale (superseded) references, and suggest related GRs to cite.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "ingest"))
from corpus_path import default_corpus_path  # noqa: E402
from devanagari import to_ascii_digits  # noqa: E402
from extract_metadata import extract_citations  # noqa: E402


def load_corpus(path=None):
    if path is None:
        path = default_corpus_path()
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            recs.append(json.loads(line))
    return recs


def _norm_ref(s: str) -> str:
    """Normalise a formal GR reference string for fuzzy matching.

    Devanagari digits are folded to ASCII and Devanagari letters are KEPT: a
    clean Marathi file number (शिष्यवृ-२०२४/प्र.क्र.१०५/तांशि-४) is the only
    identifier most GRs carry, and the old ASCII-only keep-set reduced 96% of
    them to the empty string. The boilerplate words that open every reference
    are dropped in both languages so they cannot dominate a substring match.
    """
    s = to_ascii_digits(s.lower())
    s = re.sub(r"\b(government|resolution|circular|no|dated|dt)\b", " ", s)
    s = re.sub(r"(शासन|निर्णय|परिपत्रक|शुध्दीपत्रक|ज्ञापन|क्रमांक|क्रमाांक|क्र|दिनांक|दि)", " ", s)
    s = re.sub(r"[^a-z0-9ऀ-ॿ]+", "", s)
    return s


def analyze_references(draft_text: str, corpus: list) -> dict:
    """Return citations found in the draft, matched corpus GRs, and stale flags."""
    cites = extract_citations(draft_text)

    # The draft's own header number (before the वाचा/Read block) and its own
    # footer availability code ("...सांकेतांक <code> असा आहे") are not citations.
    markers = [i for i in (draft_text.find("वाचा"), draft_text.find("Read")) if i != -1]
    header_end = min(markers) if markers else 0

    def _is_self_ref(ref):
        i = draft_text.find(ref)
        return i != -1 and i < header_end

    def _is_self_code(code):
        i = draft_text.find(code)
        if i == -1:
            return False
        after = draft_text[i + len(code): i + len(code) + 30]
        before = draft_text[max(0, i - 60): i]
        return ("असा आहे" in after) or ("उपलब्ध" in before)

    cites = {"cited_codes": [c for c in cites["cited_codes"] if not _is_self_code(c)],
             "cited_refs": [r for r in cites["cited_refs"] if not _is_self_ref(r)]}

    by_code = {r["gr_code"]: r for r in corpus}
    by_grno = {}
    for r in corpus:
        if r.get("gr_number"):
            by_grno.setdefault(_norm_ref(r["gr_number"]), []).append(r)

    linked, unknown = [], []
    for code in cites["cited_codes"]:
        if code in by_code:
            linked.append({"cited": code, "match": by_code[code], "via": "unique-code"})
        else:
            unknown.append(code)
    for ref in cites["cited_refs"]:
        n = _norm_ref(ref)
        hit = None
        # degenerate normals ('' or bare years like '2024') would substring-match
        # arbitrary GRs — require substance on BOTH sides before fuzzy matching.
        # Garbled Marathi gr_numbers normalise to bare digits (year+file-no) that
        # collide across GRs: require an alpha char or >=10 chars on the corpus
        # side, and never link into a collision group.
        if len(n) >= 6:
            for k, rs in by_grno.items():
                solid = len(k) >= 6 and (any(c.isalpha() for c in k) or len(k) >= 10)
                if solid and len(rs) == 1 and (k in n or n in k):
                    hit = rs[0]
                    break
        if hit:
            linked.append({"cited": ref, "match": hit, "via": "gr-number"})
        else:
            unknown.append(ref)

    # Stale check: a linked GR is 'superseded' if any LATER corpus GR cites it
    # AND contains supersession language near that citation (cheap heuristic:
    # later GR cites it and uses supersede/cancel/revise wording anywhere).
    stale = []
    superseders = {}
    for entry in linked:
        m = entry["match"]
        code = m["gr_code"]
        for r in corpus:
            if r["gr_code"] <= code:  # codes start with YYYYMMDD → sortable by date
                continue
            cited_here = code in r.get("cited_codes", [])
            if not cited_here and m.get("gr_number"):
                mn = _norm_ref(m["gr_number"])
                # empty/short normals (355 corpus gr_numbers normalise to '')
                # must never satisfy this equality
                cited_here = len(mn) >= 6 and any(
                    mn == _norm_ref(x) for x in r.get("cited_refs", [])
                )
            if cited_here:
                blob = " ".join(r.get("clauses", []))[:20000].lower()
                if re.search(r"supersed|cancel|repeal|in place of|revis|अधिक्रमित|रद्द", blob):
                    stale.append({"cited": entry["cited"], "superseded_by": r["gr_code"],
                                  "successor_subject": r.get("subject")})
                    superseders[code] = r["gr_code"]
                    break

    # Currency advisory: a cited GR that has NEWER corpus GRs on the same
    # subject may be outdated even when no explicit supersession is extractable
    # (font garble often hides the formal supersession language).
    TOKR = re.compile(r"[A-Za-z]{3,}|[ऀ-ॿ]{3,}")

    def _toks(s):
        return set(TOKR.findall(s or ""))

    def _jac(a, b):
        return len(a & b) / max(1, len(a | b))

    newer_related = []
    for entry in linked:
        m = entry["match"]
        tx = _toks(m.get("subject"))
        if len(tx) < 4:
            continue
        newer = [r for r in corpus
                 if r["gr_code"] > m["gr_code"] and _jac(tx, _toks(r.get("subject"))) >= 0.35]
        if newer:
            newer.sort(key=lambda r: r["gr_code"], reverse=True)
            newer_related.append({
                "cited": entry["cited"],
                "cited_date": m.get("date_iso") or m.get("date"),
                "newer": [{"gr_code": r["gr_code"],
                           "date": r.get("date_iso") or r.get("date"),
                           "subject": (r.get("subject") or "")[:120]} for r in newer[:3]],
            })

    return {"linked": linked, "unknown": unknown, "stale": stale,
            "newer_related": newer_related,
            "n_citations": len(cites["cited_codes"]) + len(cites["cited_refs"])}


def build_citation_graph(corpus: list) -> list:
    """Edges (citing_code -> cited_code) within the corpus, for the graph view."""
    codes = {r["gr_code"] for r in corpus}
    edges = []
    for r in corpus:
        for c in r.get("cited_codes", []):
            if c in codes and c != r["gr_code"]:
                edges.append((r["gr_code"], c))
    return edges
