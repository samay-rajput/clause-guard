"""Round-2 topic flow via AppTest: type a topic → prefill (AI via fixture) →
"Draft only" generation → 100% compliant draft, gr_form in session state, a
source="generate" trail record, 0 exceptions.

Retrieval uses the real local index (this is a demo-rehearsal test, not CI);
the LLM is bypassed with CG_PREFILL_FIXTURE so no provider is touched.

Run:  python tests/apptest_topic_flow.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src" / "audit"))
sys.path.append(str(ROOT / "src" / "compliance"))
os.environ["CG_PREFILL_FIXTURE"] = str(ROOT / "tests" / "fixtures" /
                                       "prefill_fixture.json")
from trail import TRAIL_FILE, load_runs  # noqa: E402
from scorecard import score  # noqa: E402

from streamlit.testing.v1 import AppTest  # noqa: E402

TOPIC = "जिल्हा परिषद शाळांमधील विद्यार्थ्यांसाठी मोफत क्रीडा साहित्य पुरवठा"


def main():
    backup = TRAIL_FILE.read_bytes() if TRAIL_FILE.exists() else None
    if backup is not None:
        TRAIL_FILE.unlink()
    try:
        at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"),
                               default_timeout=900)
        at.run()
        assert not at.exception, [e.value for e in at.exception]

        topic_in = [t for t in at.text_input if "Topic" in (t.label or "")]
        assert topic_in, [t.label for t in at.text_input]
        topic_in[0].set_value(TOPIC)
        at.run()

        pre = [b for b in at.button if "पूर्वसंदर्भ" in (b.label or "")]
        assert pre, [b.label for b in at.button]
        pre[0].click()
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        pf = at.session_state["prefill"]
        assert pf["dept_code"] in ("08", "21", "22"), pf["dept_code"]
        assert pf["subject"].endswith("बाबत."), pf["subject"]
        assert pf["references"], "prefill produced no references"
        assert pf["copy_to"], "prefill produced no distribution list"
        assert at.session_state["prefill_meta"]["ai_used"] is True

        gen = [b for b in at.button if "Draft only" in (b.label or "")]
        assert gen, [b.label for b in at.button]
        gen[0].click()
        at.run()
        assert not at.exception, [e.value for e in at.exception]

        gf = at.session_state["gr_form"]
        assert gf["copy_to"] and gf["dept_code"] == pf["dept_code"]
        assert at.session_state["generated"]["audit"]["ok"], \
            at.session_state["generated"]["audit"]

        runs = load_runs()
        assert len(runs) == 1 and runs[0]["source"] == "generate", \
            [(r.get("source")) for r in runs]
        s = score(runs[0]["draft"])
        assert s["pct"] == 100, [c["id"] for c in s["checks"] if not c["passed"]]
        print("APPTEST OK — topic prefill (fixture AI) → draft: 100% "
              "compliance, gr_form + digit audit ok, trail recorded")
    finally:
        TRAIL_FILE.unlink(missing_ok=True)
        if backup is not None:
            TRAIL_FILE.write_bytes(backup)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
