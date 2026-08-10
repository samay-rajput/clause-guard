"""Build the Chroma retrieval index over corpus clauses.

Embeddings: intfloat/multilingual-e5-small (CPU-fast, multilingual).
E5 convention: documents are embedded with "passage: " prefix, queries with
"query: " (handled in retrieve()).
"""
import json
import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "ingest"))
from corpus_path import db_dir, default_corpus_path  # noqa: E402

DB_DIR = db_dir()  # CG_DB_DIR lets a full-scale index be built beside the demo one
MODEL_NAME = "intfloat/multilingual-e5-small"
COLLECTION = "gr_clauses"

import threading as _threading

_model = None
_model_lock = _threading.Lock()


def model():
    # locked: a server warm-up thread racing the first request through
    # from_pretrained yields a half-initialized meta-device model
    global _model
    with _model_lock:
        if _model is None:
            _model = SentenceTransformer(MODEL_NAME)
    return _model


_client = None
_client_lock = _threading.Lock()


def client():
    # one PersistentClient per process — retrieve() runs per draft clause and
    # a long-lived server must not reopen the sqlite/hnsw store on every query
    global _client
    with _client_lock:
        if _client is None:
            _client = chromadb.PersistentClient(path=DB_DIR)
    return _client


def build(corpus_path=None, max_clauses_per_gr=60, dedupe=False):
    """Embed every corpus clause into a fresh Chroma collection.

    dedupe=True indexes each distinct clause once and records the other GRs it
    appears in as metadata. Government template clauses recur verbatim across
    dozens of GRs (29% of clauses at full corpus scale, one seen in 392 GRs) and
    would otherwise flood every top-k with copies of the same sentence.
    """
    corpus_path = corpus_path or default_corpus_path()
    print(f"corpus: {corpus_path}\nindex:  {DB_DIR}", flush=True)
    cl = client()
    try:
        cl.delete_collection(COLLECTION)
    except Exception:
        pass

    ids, docs, metas = [], [], []
    seen = {}
    n_dupes = n_records = 0
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            n_records += 1
            for i, clause in enumerate(r["clauses"][:max_clauses_per_gr]):
                if dedupe:
                    key = " ".join(clause.split())
                    if key in seen:
                        m = metas[seen[key]]
                        m["n_grs"] += 1
                        if len(m["gr_codes"]) < 200:  # metadata values stay small
                            m["gr_codes"] += "," + r["gr_code"]
                        n_dupes += 1
                        continue
                    seen[key] = len(ids)
                ids.append(f"{r['gr_code']}:{i}")
                docs.append(clause)
                metas.append({
                    "gr_code": r["gr_code"],
                    "department": r.get("department") or "?",
                    "date": r.get("date") or "?",
                    "subject": (r.get("subject") or "?")[:200],
                    "gr_number": r.get("gr_number") or "?",
                    "gr_codes": r["gr_code"],
                    "n_grs": 1,
                })
    if dedupe:
        print(f"deduped: {n_dupes} duplicate clauses collapsed", flush=True)

    # Fingerprint of the corpus this index was built from. bootstrap.py validates
    # downloaded artifacts by file EXISTENCE only, so without this an index and a
    # corpus that disagree pair up silently — the app would answer from one and
    # cite the other. `index_fingerprint()` lets any caller check.
    col = cl.create_collection(COLLECTION, metadata={
        "hnsw:space": "cosine",
        "corpus_name": Path(corpus_path).name,
        "corpus_records": n_records,
        "indexed_clauses": len(docs),
        "deduped": bool(dedupe),
    })
    print(f"embedding {len(docs)} clauses...", flush=True)
    m = model()
    B = 128
    for s in range(0, len(docs), B):
        embs = m.encode([f"passage: {d}" for d in docs[s:s + B]],
                        normalize_embeddings=True, show_progress_bar=False)
        col.add(ids=ids[s:s + B], documents=docs[s:s + B],
                metadatas=metas[s:s + B], embeddings=embs.tolist())
        if (s // B) % 5 == 0:
            print(f"  {s + len(embs)}/{len(docs)}", flush=True)
    print(f"index built: {col.count()} clauses -> {DB_DIR}", flush=True)


def index_fingerprint() -> dict:
    """What corpus this index was built from, or {} for an index built before
    fingerprinting (or no index at all)."""
    try:
        md = client().get_collection(COLLECTION).metadata or {}
    except Exception:
        return {}
    return {k: md[k] for k in ("corpus_name", "corpus_records", "indexed_clauses")
            if k in md}


def check_against_corpus(corpus_path) -> str | None:
    """Return a human-readable warning when the live index does not match the
    active corpus, else None. Compares record counts, which is cheap and catches
    the case that matters: a stale index shipped alongside a rebuilt corpus."""
    fp = index_fingerprint()
    if not fp:
        return None  # pre-fingerprint index — nothing to compare against
    name = Path(corpus_path).name
    n = sum(1 for line in open(corpus_path, encoding="utf-8") if line.strip())
    if fp.get("corpus_name") != name or fp.get("corpus_records") != n:
        return (f"index was built from {fp.get('corpus_name')} "
                f"({fp.get('corpus_records')} GRs) but the active corpus is "
                f"{name} ({n} GRs) — rebuild the index")
    return None


def retrieve(query_text: str, k=5, exclude_gr=None, n_results=None):
    col = client().get_collection(COLLECTION)
    # Deterministic query encoding: multi-threaded CPU matmul varies its
    # reduction order run-to-run, and on a dense index those last-decimal
    # differences reshuffle borderline ranks — the near-dup suppressor then
    # drops DIFFERENT lookalikes each run and the candidate set flickers.
    # Single-threading just this encode pins the vector bytes; MuRIL and the
    # bulk index build keep their threads.
    import torch
    n_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        emb = model().encode([f"query: {query_text}"], normalize_embeddings=True)
    finally:
        torch.set_num_threads(n_threads)
    # the fetch width has to grow with the index: at full corpus scale the old
    # hard cap of 40 could be filled entirely by copies of one template clause
    res = col.query(query_embeddings=emb.tolist(),
                    n_results=n_results or min(k * 8 + 10, 120))
    # Deterministic candidate order BEFORE suppression: thousands of
    # near-identical reference lines tie on distance to the 6th decimal, and
    # whichever copy the ANN returns first survives the near-dup filter. A
    # stable (rounded-distance, id) sort makes the surviving set identical
    # across runs — without it the candidate pairs (and therefore the MuRIL
    # flags and the frozen baseline) flicker between processes.
    hits = sorted(
        zip(res["ids"][0], res["documents"][0], res["metadatas"][0],
            res["distances"][0]),
        key=lambda h: (round(h[3], 6), h[0]))
    out, seen_text = [], set()
    for hid, doc, meta, dist in hits:
        if exclude_gr and meta["gr_code"] == exclude_gr:
            continue
        # near-duplicate suppression: identical template clauses recur across
        # dozens of GRs and would flood the top-k, crowding out real matches
        key = " ".join(doc.split())[:120]
        if key in seen_text:
            continue
        seen_text.add(key)
        out.append({"clause": doc, "distance": dist, **meta})
        if len(out) >= k:
            break
    return out


if __name__ == "__main__":
    import argparse

    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Build the Chroma clause index")
    ap.add_argument("--corpus", default=None, help="corpus .jsonl (default: CG_CORPUS / corpus.active)")
    ap.add_argument("--dedupe", action="store_true", help="index each distinct clause once")
    ap.add_argument("--max-clauses-per-gr", type=int, default=60)
    a = ap.parse_args()
    build(Path(a.corpus) if a.corpus else None,
          max_clauses_per_gr=a.max_clauses_per_gr, dedupe=a.dedupe)
