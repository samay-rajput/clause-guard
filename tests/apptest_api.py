"""API-level verification of the FastAPI backend (round 3) — the same layer
apptest_audit / apptest_generate covered for the Streamlit app.

Runs offline: the review path is exercised with Scenario A, whose LLM calls are
all warm-cache hits, and the prefill path through CG_PREFILL_FIXTURE.
Usage:  python tests/apptest_api.py
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CG_DRAFTER_PW", "apptest-drafter-pw")
os.environ.setdefault("CG_REVIEWER_PW", "apptest-reviewer-pw")
# scratch users DB — the test must never seed the real data/users.db
os.environ["CG_USERS_DB"] = str(ROOT / "data" / "users_apptest.db")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {detail}")


def main():
    with TestClient(app) as client:              # context manager runs the lifespan
        return _run(client)


def _run(client):
    # -- health is public
    h = client.get("/api/health").json()
    check("health responds", "status" in h, h)

    # -- everything else is not
    check("unauthenticated corpus/stats -> 401",
          client.get("/api/corpus/stats").status_code == 401)

    # -- login
    r = client.post("/api/auth/login",
                    data={"username": "drafter", "password": "apptest-drafter-pw"})
    check("login ok", r.status_code == 200, r.text[:200])
    tok = r.json()["access_token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    check("refresh cookie set", "cg_refresh" in r.cookies)

    r = client.post("/api/auth/login",
                    data={"username": "drafter", "password": "wrong"})
    check("bad password -> 401", r.status_code == 401)

    # -- refresh rotates
    r = client.post("/api/auth/refresh")
    check("refresh rotates", r.status_code == 200 and r.json().get("access_token"),
          r.text[:200])

    # -- core reads
    r = client.get("/api/corpus/stats", headers=hdr)
    check("corpus stats", r.status_code == 200 and r.json()["n_grs"] > 0, r.text[:200])
    scen = client.get("/api/scenarios", headers=hdr).json()
    check("scenarios list", any(s["id"] == "1_fee_conflict_draft" for s in scen))
    a_text = client.get("/api/scenarios/1_fee_conflict_draft",
                        headers=hdr).json()["text"]
    check("scenario text", len(a_text) > 100)
    g = client.get("/api/glossary?q=अनुदान", headers=hdr).json()
    check("glossary filter", g["n"] >= 1, g)

    # -- review (sync; scenario A is fully warm-cached)
    r = client.post("/api/review?sync=true", headers=hdr,
                    json={"draft": a_text, "top_k": 10})
    check("review runs", r.status_code == 200, r.text[:300])
    rev = r.json()
    conflicts = rev.get("review", {}).get("conflicts", [])
    check("scenario A -> exactly 1 conflict", len(conflicts) == 1,
          json.dumps(rev.get("review", {}).get("error", ""))[:200])
    if conflicts:
        c = conflicts[0]
        check("conflict carries structured values",
              c.get("value1") and c.get("value2"), c.keys())
        check("conflict vs the anchor GR",
              c["meta"]["gr_code"] == "202407191857335408", c["meta"])
        check("conflict carries source links", bool(c.get("links")))
    check("audit ts recorded", bool(rev.get("audit_ts")), rev.get("audit_error"))

    # -- job-mode review + SSE endpoint exists
    r = client.post("/api/review", headers=hdr,
                    json={"draft": a_text, "top_k": 10})
    job_id = r.json().get("job_id")
    check("job submitted", bool(job_id), r.text[:200])
    import time
    for _ in range(240):
        j = client.get(f"/api/jobs/{job_id}", headers=hdr).json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.5)
    check("job finishes", j["status"] == "done", j.get("error"))
    check("job progress streamed", len(j["messages"]) > 3, len(j["messages"]))

    # -- prefill via fixture (no LLM)
    os.environ["CG_PREFILL_FIXTURE"] = str(ROOT / "tests" / "fixtures"
                                           / "prefill_fixture.json")
    r = client.post("/api/generate/prefill", headers=hdr,
                    json={"topic": "जिल्हा परिषद शाळांना सादिल अनुदान वितरण",
                          "lang": "mr"})
    check("prefill (fixture)", r.status_code == 200, r.text[:300])
    form = r.json()["form"]
    check("prefill has precedents", len(form.get("precedents", [])) >= 1)

    # -- instant preview (retrieval only)
    r = client.post("/api/generate/preview", headers=hdr,
                    json={"topic": "शिष्यवृत्ती", "k": 4})
    check("preview", r.status_code == 200 and
          len(r.json().get("precedents", [])) >= 1, r.text[:200])

    # -- form generation + authentic export
    r = client.post("/api/generate", headers=hdr,
                    json={"form": form, "use_ai": False, "record": True})
    check("generate from form", r.status_code == 200, r.text[:300])
    gen = r.json()
    check("digit audit ok", gen.get("audit", {}).get("ok") is True,
          gen.get("audit"))
    r = client.post("/api/export/authentic?fmt=pdf", headers=hdr,
                    json={"form": gen["form"]})
    check("authentic PDF", r.status_code == 200 and r.content[:5] == b"%PDF-",
          r.status_code)
    r = client.post("/api/export/authentic?fmt=docx", headers=hdr,
                    json={"form": gen["form"]})
    check("authentic DOCX", r.status_code == 200 and r.content[:2] == b"PK")

    # -- report export from the review payload
    r = client.post("/api/export/report?fmt=pdf", headers=hdr,
                    json={"score": rev["score"], "terms": rev["terms"],
                          "refs": rev.get("refs"), "review": rev["review"]})
    check("report PDF", r.status_code == 200 and r.content[:5] == b"%PDF-")

    # -- audit: drafter sees own runs; cannot read others; reviewer can
    r = client.get("/api/audit/runs", headers=hdr).json()
    check("audit runs recorded", r["total"] >= 2, r["total"])
    check("audit diff appears on resubmission",
          any(x.get("human_edit") is not None for x in r["runs"]))
    check("drafter blocked from other trails",
          client.get("/api/audit/runs?for_user=reviewer",
                     headers=hdr).status_code == 403)
    r2 = client.post("/api/auth/login",
                     data={"username": "reviewer",
                           "password": "apptest-reviewer-pw"})
    rhdr = {"Authorization": f"Bearer {r2.json()['access_token']}"}
    check("reviewer reads drafter trail",
          client.get("/api/audit/runs?for_user=drafter",
                     headers=rhdr).status_code == 200)

    # -- upload extraction guards
    r = client.post("/api/drafts/extract-text", headers=hdr,
                    files={"file": ("x.txt", b"hello clause", "text/plain")})
    check("txt upload", r.json().get("text") == "hello clause", r.text[:200])
    r = client.post("/api/drafts/extract-text", headers=hdr,
                    files={"file": ("x.pdf", b"MZfakebinary", "application/pdf")})
    check("fake pdf rejected", r.status_code == 422)
    r = client.post("/api/drafts/extract-text", headers=hdr,
                    files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    check("unknown type rejected", r.status_code == 415)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
