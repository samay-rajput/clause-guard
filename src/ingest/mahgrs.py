"""Reader for the orgpedia/mahGRs clean-Marathi GR text corpus.

`data/mahgrs/GRs/<Department>/<18-digit code>.pdf.mr.txt` — one file per GR,
produced by orgpedia's own pipeline (crawler -> OCR to defeat the non-standard
fonts -> paragraph/table detection -> translation). It is the same source
material as `data/raw_pdfs`, but OCR'd instead of text-layer-extracted, so it
does NOT carry the broken-ToUnicode garble.

What it *does* carry, and what this module strips:

  `# Page N`      a marker line before every page. Left in, these inject ASCII
                  digits into clause text and defeat pipeline._grounded — an
                  invented "5" reads as sourced because the clause contains
                  "# Page 5". Present in 32.6% of chunks before stripping.
  running header  pages 2+ repeat `शासन निर्णय क्रमांकः <file no>`. Left in, every
                  GR cites ITSELF (47% of records) and 15% of indexed clauses are
                  that header. Page 1's copy is the GR's own number line and is
                  kept — parse_header needs it.
  page footer     `पृष्ठ ६ पैकी २` (page 2 of 6).
  empty pages     40.3% of pages carry no text at all: orgpedia's extraction
                  drops annexure/table pages and usually the signature tail.
                  Recorded per document as pages_empty rather than papered over.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAHGRS_DIR = ROOT / "data" / "mahgrs" / "GRs"

PAGE_MARKER_RE = re.compile(r"^#\s*Page\s+(\d+)\s*$")
# `शासन <निर्णय|परिपत्रक|...> क्रमांकः ...` — the word between शासन and क्रमांक is
# left open because mahGRs' own OCR damages it (ननर्णय, ननणय seen in the wild).
RUNNING_HEADER_RE = re.compile(
    r"^\s*शासन\s+\S{2,14}\s*(?:क्रमांक|क्रमाांक|क्रमाक|क्र)\s*[:ः.\-]"
)
PAGE_FOOTER_RE = re.compile(r"^\s*पृष्ठ\s*[०-९0-9]+\s*पैकी\s*[०-९0-9]+\s*$")
# The same footer is often OCR'd into the middle of a body line, splitting a
# sentence around it ("...वसूल करुनच पृष्ठ १७ पैकी १४ उर्वरीत अनुदान वितरीत..."),
# so it also has to be removed inline — a whole-line rule misses those.
INLINE_FOOTER_RE = re.compile(r"\s*पृष्ठ\s*[०-९0-9]{1,3}\s*पैकी\s*[०-९0-9]{1,3}\s*")


def split_pages(text: str) -> list[list[str]]:
    """Split on `# Page N` markers into a list of pages, each a list of lines."""
    pages, cur = [], None
    for ln in text.split("\n"):
        if PAGE_MARKER_RE.match(ln):
            cur = []
            pages.append(cur)
        elif cur is not None:
            cur.append(ln)
        else:  # text before the first marker (shouldn't happen; 0/23,333 files)
            cur = [ln]
            pages.append(cur)
    return pages


def clean_text(text: str) -> dict:
    """Strip page furniture. Returns {text, pages_total, pages_empty, headers_stripped}."""
    pages = split_pages(text)
    kept, empty, headers = [], 0, 0
    for i, page in enumerate(pages):
        lines = []
        for ln in page:
            if PAGE_FOOTER_RE.match(ln):
                continue
            if INLINE_FOOTER_RE.search(ln):
                ln = INLINE_FOOTER_RE.sub(" ", ln)
                if not ln.strip():
                    continue
            # The header repeats at the TOP of pages 2+. Restricting the strip to
            # the leading lines keeps genuine mid-body citations of other GRs.
            if i > 0 and not lines and RUNNING_HEADER_RE.match(ln):
                headers += 1
                continue
            lines.append(ln)
        if any(l.strip() for l in lines):
            kept.append("\n".join(lines).strip())
        else:
            empty += 1
    return {
        "text": "\n".join(kept),
        "pages_total": len(pages),
        "pages_empty": empty,
        "headers_stripped": headers,
    }


def gr_path(code: str, dept_dir: str | None = None) -> Path | None:
    """Locate a GR's Marathi text file by its 18-digit code."""
    if dept_dir:
        p = MAHGRS_DIR / dept_dir / f"{code}.pdf.mr.txt"
        return p if p.exists() else None
    for d in MAHGRS_DIR.iterdir():
        p = d / f"{code}.pdf.mr.txt"
        if p.exists():
            return p
    return None


def iter_files(depts: list[str] | None = None):
    """Yield (department_dir_name, gr_code, Path) for every Marathi GR text file."""
    if not MAHGRS_DIR.exists():
        raise FileNotFoundError(
            f"{MAHGRS_DIR} not found — clone the corpus first (see DATASET_CARD.md)"
        )
    for d in sorted(MAHGRS_DIR.iterdir()):
        if not d.is_dir() or (depts and d.name not in depts):
            continue
        for p in sorted(d.glob("*.mr.txt")):
            yield d.name, p.name.split(".")[0], p


def read_clean(path: Path) -> dict:
    """Read one .mr.txt and return the cleaned text plus page statistics."""
    return clean_text(path.read_text(encoding="utf-8"))
