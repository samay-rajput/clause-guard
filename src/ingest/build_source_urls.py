"""Map every corpus GR to its source document (SRS FR-6: "source GR link").

`data/cdx_english.txt` is the Wayback CDX enumeration used to build the corpus:
one `<url> <timestamp>` pair per line. The URL basename IS the GR's unique code,
so the join needs no new metadata and no corpus rebuild — it is a pure function
of `gr_code`, written once to `data/source_urls.json` and read by the app.

Build:  python src/ingest/build_source_urls.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(Path(__file__).parent))
from corpus_path import default_corpus_path  # noqa: E402

CDX_FILE = ROOT / "data" / "cdx_english.txt"
OUT_FILE = ROOT / "data" / "source_urls.json"

_cache = {"links": None}


def load_links() -> dict:
    """{gr_code: {'portal': url, 'archive': wayback permalink}} — {} if not built."""
    if _cache["links"] is None:
        _cache["links"] = (json.loads(OUT_FILE.read_text(encoding="utf-8"))
                           if OUT_FILE.exists() else {})
    return _cache["links"]


def links_for(gr_code: str):
    """Source links for one GR, or None when the code is not in the archive index."""
    return load_links().get(str(gr_code))


def build():
    corpus_codes = set()
    p = default_corpus_path()
    if p.exists():
        with open(p, encoding="utf-8") as f:
            corpus_codes |= {json.loads(l)["gr_code"] for l in f if l.strip()}

    latest = {}
    with open(CDX_FILE, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) != 2:
                continue
            url, ts = parts
            code = url.rsplit("/", 1)[-1]
            if not code.lower().endswith(".pdf"):
                continue
            code = code[:-4]
            # several snapshots per document — keep the most recent capture
            if ts > latest.get(code, ("", ""))[0]:
                latest[code] = (ts, url)

    links = {c: {"portal": url,
                 "archive": f"https://web.archive.org/web/{ts}/{url}"}
             for c, (ts, url) in latest.items() if c in corpus_codes}

    OUT_FILE.write_text(json.dumps(links, ensure_ascii=False, indent=0), encoding="utf-8")
    hit = len(links)
    print(f"corpus GRs: {len(corpus_codes)}  ·  CDX documents: {len(latest)}")
    print(f"resolved:   {hit}/{len(corpus_codes)} ({100 * hit / max(1, len(corpus_codes)):.1f}%)"
          f" -> {OUT_FILE.relative_to(ROOT)}")
    missing = sorted(corpus_codes - set(links))[:5]
    if missing:
        print("unresolved sample:", missing)


if __name__ == "__main__":
    build()
