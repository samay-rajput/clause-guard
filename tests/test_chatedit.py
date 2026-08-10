"""Chat-edit rail tests — fixture-driven, offline (no LLM)."""
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("llm", "index", "ingest", "detect", "reftrack", "compliance",
            "audit", "export", "draftgen", "deploy"):
    sys.path.append(str(ROOT / "src" / sub))

FIXTURE = ROOT / "tests" / "fixtures" / "chatedit_fixture.json"
os.environ["CG_CHATEDIT_FIXTURE"] = str(FIXTURE)

from chatedit import apply_ops, chat_edit  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {detail}")


FORM = {
    "lang": "mr", "subject": "चाचणी अनुदान वितरणाबाबत.",
    "department": "शालेय शिक्षण व क्रीडा विभाग", "dept_code": "21",
    "gr_number": "चाचणी-2026/प्र.क्र.55/एसडी-4", "date": date(2026, 8, 10),
    "references": [{"text": "शासन निर्णय, सांकेतांक 202407191857335408, दि.19.07.2024."}],
    "background": "ही बाब शासनाच्या विचाराधीन होती.",
    "clauses": ["चाचणी अनुदानास मान्यता देण्यात येत आहे.",
                "सदर शासन निर्णय निर्गमित दिनांकापासून लागू राहील."],
    "budget_head": "", "signatory": "क.ख.ग.", "designation": "उप सचिव",
}

# --- direct op application under the rails ---
msg = "पहिल्या कलमात रक्कम 5 लाख रुपये करा"
out = apply_ops(FORM, [
    {"op": "edit_clause", "index": 0,
     "text": "चाचणी अनुदानापोटी 5 लाख रुपये इतका निधी मंजूर करण्यात येत आहे."},
], msg)
check("sourced digit survives (from message)",
      "5 लाख" in out["form"]["clauses"][0], out["form"]["clauses"][0])
check("change recorded", out["changes"] == ["clause 1"], out["changes"])

out = apply_ops(FORM, [
    {"op": "edit_clause", "index": 0,
     "text": "अनुदानापोटी 75 लाख रुपये व PMShri निधी मंजूर करण्यात येत आहे."},
], "रक्कम बदला")   # 75 and PMShri are NOT in the message or form
check("unsourced digit blanked", "75" not in out["form"]["clauses"][0]
      and "____" in out["form"]["clauses"][0], out["form"]["clauses"][0])
check("unsourced entity blanked", "PMShri" not in out["form"]["clauses"][0],
      out["form"]["clauses"][0])
check("scrubs reported", out["scrubbed"] and out["scrubbed_entities"],
      (out["scrubbed"], out["scrubbed_entities"]))

out = apply_ops(FORM, [
    {"op": "add_table", "table": {"after_clause": 1,
                                  "headers": ["जिल्हा", "रक्कम"],
                                  "rows": [["पुणे", "3 लाख"], ["नागपूर", "2 लाख"]]}},
], "पुणे 3 लाख व नागपूर 2 लाख असा तक्ता जोडा")
check("table op applies with sourced digits",
      len(out["form"]["tables"]) == 1 and
      out["form"]["tables"][0]["rows"][0][1] == "3 लाख", out["form"].get("tables"))

out = apply_ops(FORM, [{"op": "remove_clause", "index": 0},
                       {"op": "remove_clause", "index": 0}], "कलमे काढा")
check("last clause protected", len(out["form"]["clauses"]) == 1, out["form"]["clauses"])

out = apply_ops(FORM, [{"op": "set_subject", "text": "सादिल अनुदान वितरण"}],
                "विषय बदला: सादिल अनुदान वितरण")
check("subject format enforced (बाबत.)",
      out["form"]["subject"].endswith("बाबत."), out["form"]["subject"])

# --- full chat_edit turn through the fixture + deterministic re-render ---
FIXTURE.write_text(json.dumps({
    "reply": "पहिल्या कलमातील रक्कम अद्ययावत केली.",
    "ops": [{"op": "edit_clause", "index": 0,
             "text": "चाचणी अनुदानापोटी 12 लाख रुपये इतका निधी मंजूर करण्यात येत आहे."}],
}, ensure_ascii=False), encoding="utf-8")
out = chat_edit(FORM, "पहिल्या कलमात 12 लाख रुपये करा")
check("chat_edit renders through the audited rail",
      out.get("generated", {}).get("audit", {}).get("ok") is True,
      out.get("generated", {}).get("audit") or out.get("error"))
check("draft carries the sourced value",
      "12" in out["generated"]["draft"], None)
check("reply surfaced", out["reply"].startswith("पहिल्या"), out["reply"])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
