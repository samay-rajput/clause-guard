"""Single, explicit resolver for which corpus file and index directory are live.

Six modules used to pick their corpus with the same silent two-line fallback
(`corpus_clean.jsonl` if it exists, else `corpus.jsonl`). Writing a rebuild to
that filename repointed the app, the index builder, reference tracking, pair
generation and source-URL building at once, with nothing in the logs. Corpus
selection is now explicit and loud:

  1. `CG_CORPUS` environment variable  — an explicit path, wins over everything
  2. `data/corpus.active`             — one line naming the active corpus file
  3. `data/corpus.jsonl`              — the shipped default (what the deployed
                                        app and the HF artifacts still use)

The index directory follows the same rule via `CG_DB_DIR`, so a full-scale
rebuild can be exercised side by side with the demo index instead of over it.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = "corpus.jsonl"
POINTER_FILE = "corpus.active"


def default_corpus_path() -> Path:
    env = os.environ.get("CG_CORPUS")
    if env:
        p = Path(env)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            raise FileNotFoundError(f"CG_CORPUS={env} does not exist")
        return p

    pointer = ROOT / "data" / POINTER_FILE
    if pointer.exists():
        name = pointer.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        if name and not name.startswith("#"):
            p = ROOT / "data" / name
            if p.exists():
                return p
            raise FileNotFoundError(
                f"data/{POINTER_FILE} points at {name}, which does not exist"
            )
    return ROOT / "data" / DEFAULT_CORPUS


def active_corpus_name() -> str:
    return default_corpus_path().name


def set_active_corpus(name: str) -> Path:
    """Point data/corpus.active at `name` (a filename inside data/)."""
    p = ROOT / "data" / name
    if not p.exists():
        raise FileNotFoundError(p)
    (ROOT / "data" / POINTER_FILE).write_text(name + "\n", encoding="utf-8")
    return p


def db_dir() -> str:
    env = os.environ.get("CG_DB_DIR")
    if env:
        p = Path(env)
        return str(p if p.is_absolute() else ROOT / p)
    return str(ROOT / "chroma_db")
