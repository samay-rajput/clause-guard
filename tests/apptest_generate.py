"""§1.2 / AC-3 verification via AppTest — offline deterministic path.

Submitting the Generate form ("Draft only" — the path that skips the conflict
review) with its prefilled sample must produce a draft scoring 100% on the
template checklist, record a source="generate" trail entry, and raise 0
exceptions. No LLM, no index required.

Run:  python tests/apptest_generate.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src" / "audit"))
sys.path.append(str(ROOT / "src" / "compliance"))
from trail import TRAIL_FILE, load_runs  # noqa: E402
from scorecard import score  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402


def main():
    backup = TRAIL_FILE.read_bytes() if TRAIL_FILE.exists() else None
    if backup is not None:
        TRAIL_FILE.unlink()
    try:
        at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"),
                               default_timeout=900)
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        gen = [b for b in at.button if "Draft only" in (b.label or "")]
        assert gen, f"Draft-only button not found among {[b.label for b in at.button]}"
        gen[0].click()
        at.run()
        assert not at.exception, [e.value for e in at.exception]

        runs = load_runs()
        assert len(runs) == 1 and runs[0]["source"] == "generate", runs
        draft = runs[0]["draft"]
        s = score(draft)
        assert s["pct"] == 100, [c["id"] for c in s["checks"] if not c["passed"]]
        assert runs[0]["deterministic"]["compliance_pct"] == 100
        print("APPTEST OK — generated draft recorded (source=generate), "
              "scores 100%, 0 exceptions")
    finally:
        TRAIL_FILE.unlink(missing_ok=True)
        if backup is not None:
            TRAIL_FILE.write_bytes(backup)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
