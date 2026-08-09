"""Single place the domain layer's flat-module import scheme is set up.

The src/ tree ships flat modules (`clients`, `pipeline`, `trail`, ...) resolved
via sys.path, exactly as app/streamlit_app.py does. Import THIS module before
any domain import; nothing else in api/ touches sys.path.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

for sub in ("llm", "index", "ingest", "detect", "reftrack", "compliance",
            "audit", "export", "draftgen", "deploy"):
    p = str(ROOT / "src" / sub)
    if p not in sys.path:
        sys.path.append(p)
