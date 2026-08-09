"""The ⚡ autonomous button via AppTest: type a topic, click once, get a
100%-compliant authentic GR — no form field touched.

Uses the blanks fixture, whose AI output carries BOTH an unsourced amount and a
literal ____, so this exercises the path the existing apptest_topic_flow cannot:
its fixture is deliberately blank-free, which is why the deferral rail had never
been driven through the UI.

Also pins two regressions:
  * generated["ai_used"] must be True — it was hardcoded False on this rail, so
    the app claimed no AI had written the prose when in fact it had;
  * auth_export_error must be absent — the authentic export used to fail behind
    a bare `except`, silently downgrading to a plain PDF with no test able to see it.

Retrieval uses the real local index (demo-rehearsal test, not CI); the LLM is
bypassed with CG_PREFILL_FIXTURE so no provider is touched.

Run:  python tests/apptest_autodraft.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT / "src" / "audit"))
sys.path.append(str(ROOT / "src" / "compliance"))
os.environ["CG_PREFILL_FIXTURE"] = str(ROOT / "tests" / "fixtures" /
                                       "prefill_fixture_blanks.json")
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

        auto = [b for b in at.button if "स्वयंचलित" in (b.label or "")]
        assert auto, [b.label for b in at.button]
        auto[0].click()
        at.run()
        assert not at.exception, [e.value for e in at.exception]

        # --- it ran autonomously and said so
        am = at.session_state["autodraft_meta"]
        assert am["ai_used"] is True, am
        assert am["deferred_clauses"], "the ____ clause should have deferred"
        assert am["scrubbed"], "the unsourced 45000 should have been scrubbed"
        assert am["open_questions"], am
        assert am["dept_code"] in ("08", "21", "22"), am["dept_code"]

        # --- the draft is real, blank-free and compliant
        g = at.session_state["generated"]
        assert g["audit"]["ok"], g["audit"]
        assert g["ai_used"] is True, \
            "regression: the round-2 rail reported ai_used=False again"
        assert "____" not in g["draft"], "a blank reached the rendered draft"
        s = score(g["draft"])
        assert s["pct"] == 100, [c["id"] for c in s["checks"] if not c["passed"]]

        # --- the authentic export really rendered (no silent downgrade)
        assert "auth_export_error" not in at.session_state, \
            at.session_state.get("auth_export_error")
        gf = at.session_state["gr_form"]
        assert gf.get("copy_to") and gf.get("code"), gf.keys()

        # --- and it is on the record
        runs = load_runs()
        assert len(runs) == 1 and runs[0]["source"] == "autodraft", \
            [r.get("source") for r in runs]

        print(f"APPTEST OK — one click, no human: {am['dept_code']} dept, "
              f"{len(am['precedents'])} precedents, {len(am['scrubbed'])} numbers "
              f"refused, {len(am['deferred_clauses'])} deferred, "
              f"{s['pct']}% compliance, authentic export ok, trail recorded")
    finally:
        TRAIL_FILE.unlink(missing_ok=True)
        if backup is not None:
            TRAIL_FILE.write_bytes(backup)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
