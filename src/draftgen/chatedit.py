"""Conversational GR editing — the chat NEVER writes the draft.

The LLM's only job is to translate an officer's instruction ("दुसऱ्या कलमातील
रक्कम ५ लाख करा", "add a clause about utilization certificates") into a small
set of FORM OPERATIONS. The server applies them under the same rails as every
other AI path — digits must trace to the user's message or the existing form,
entities likewise — and the draft is re-rendered deterministically from the
form. A hallucinated figure cannot enter the GR through the chat.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src" / "llm"))
sys.path.append(str(ROOT / "src" / "draftgen"))
from clients import LLMError, llm_with_fallback  # noqa: E402
from generate import _digit_runs, generate_from_form  # noqa: E402
from prefill import (_subject_line, scrub_unsourced_digits,  # noqa: E402
                     scrub_unsourced_entities)

ALLOWED_OPS = {"set_subject", "set_background", "set_budget_head",
               "set_signatory", "set_designation", "edit_clause", "add_clause",
               "remove_clause", "add_reference", "remove_reference",
               "add_table", "remove_table"}

CHAT_PROMPT = """You are the form-editing assistant inside a Maharashtra Government Resolution (GR) drafting tool. The officer edits the GR by chatting; you translate their instruction into form OPERATIONS. You never write the final document — a deterministic renderer does.

CURRENT FORM (JSON):
{form_json}

OFFICER'S INSTRUCTION ({lang_name}):
{message}

Return ONLY JSON:
{{"reply": "<one short sentence in the officer's language confirming what you changed or asking for the missing detail>",
  "ops": [{{"op": "set_subject|set_background|set_budget_head|set_signatory|set_designation|edit_clause|add_clause|remove_clause|add_reference|remove_reference|add_table|remove_table",
           "index": <0-based clause/reference/table index, when the op targets one>,
           "text": "<full new text for text ops>",
           "table": {{"after_clause": <1-based clause number>, "headers": ["..."], "rows": [["..."]]}} }}]}}

Rules:
- Formal government Marathi/English matching the form's language.
- NEVER introduce a number, amount, date, scheme name or institution name that is not in the officer's instruction or already in the form — leave "____" instead and say so in reply.
- edit_clause rewrites ONE clause (give the complete clause text). add_clause appends unless index given.
- A Marathi subject must end with "बाबत."
- If the instruction is unclear or needs a value you don't have, return ops: [] and ask in reply.
- Complete the JSON. Never stop midway."""


def _form_view(form: dict) -> dict:
    """The slice of the form the model may edit (and needs to see)."""
    return {
        "lang": form.get("lang", "mr"),
        "subject": form.get("subject", ""),
        "background": form.get("background", ""),
        "clauses": list(form.get("clauses") or []),
        "references": [(r.get("text") if isinstance(r, dict) else str(r))
                       for r in form.get("references") or []],
        "budget_head": form.get("budget_head", ""),
        "signatory": form.get("signatory", ""),
        "designation": form.get("designation", ""),
        "tables": form.get("tables") or [],
    }


def _allowed_digits(message: str, form: dict) -> set:
    view = _form_view(form)
    blob = " ".join([message, view["subject"], view["background"],
                     view["budget_head"], *view["clauses"], *view["references"],
                     json.dumps(view["tables"], ensure_ascii=False)])
    import datetime as dt
    y = dt.date.today().year
    return (_digit_runs(blob)
            | {str(y), str(y + 1), f"{y % 100:02d}", f"{(y + 1) % 100:02d}"})


def _rails(text: str, message: str, form: dict, allowed: set,
           scrubbed: list, ents: list) -> str:
    out, rem = scrub_unsourced_digits(text, allowed)
    scrubbed.extend(rem)
    view = _form_view(form)
    blob = " ".join([message, view["subject"], view["background"],
                     *view["clauses"], *view["references"]])
    out, rem = scrub_unsourced_entities(out, blob)
    ents.extend(rem)
    return out.strip()


def apply_ops(form: dict, ops: list, message: str) -> dict:
    """Apply validated ops under the digit/entity rails. Returns
    {form, changes[], scrubbed[], scrubbed_entities[]}."""
    f = dict(form)
    f["clauses"] = list(f.get("clauses") or [])
    f["references"] = list(f.get("references") or [])
    f["tables"] = list(f.get("tables") or [])
    allowed = _allowed_digits(message, form)
    changes, scrubbed, ents = [], [], []

    for op in ops[:8]:                        # a chat turn is a small edit
        kind = op.get("op")
        if kind not in ALLOWED_OPS:
            continue
        idx = op.get("index")
        text = _rails(str(op.get("text") or ""), message, form, allowed,
                      scrubbed, ents)
        if kind == "set_subject" and text:
            f["subject"] = text if f.get("lang") == "en" or \
                text.endswith("बाबत.") else _subject_line(text, "mr")
            changes.append("subject")
        elif kind == "set_background" and text:
            f["background"] = text
            changes.append("background")
        elif kind == "set_budget_head" and text:
            f["budget_head"] = text
            changes.append("budget_head")
        elif kind == "set_signatory" and text:
            f["signatory"] = text
            changes.append("signatory")
        elif kind == "set_designation" and text:
            f["designation"] = text
            changes.append("designation")
        elif kind == "edit_clause" and text and isinstance(idx, int) \
                and 0 <= idx < len(f["clauses"]):
            f["clauses"][idx] = text
            changes.append(f"clause {idx + 1}")
        elif kind == "add_clause" and text:
            if isinstance(idx, int) and 0 <= idx <= len(f["clauses"]):
                f["clauses"].insert(idx, text)
            else:
                f["clauses"].append(text)
            changes.append("clause added")
        elif kind == "remove_clause" and isinstance(idx, int) \
                and 0 <= idx < len(f["clauses"]) and len(f["clauses"]) > 1:
            f["clauses"].pop(idx)
            changes.append(f"clause {idx + 1} removed")
        elif kind == "add_reference" and text:
            f["references"].append({"text": text})
            changes.append("reference added")
        elif kind == "remove_reference" and isinstance(idx, int) \
                and 0 <= idx < len(f["references"]):
            f["references"].pop(idx)
            changes.append(f"reference {idx + 1} removed")
        elif kind == "add_table" and isinstance(op.get("table"), dict):
            tbl = op["table"]
            headers = [_rails(str(h), message, form, allowed, scrubbed, ents)
                       for h in (tbl.get("headers") or [])][:8]
            rows = [[_rails(str(c), message, form, allowed, scrubbed, ents)
                     for c in row][:8] for row in (tbl.get("rows") or [])][:40]
            if rows or headers:
                f["tables"].append({
                    "after_clause": max(1, min(int(tbl.get("after_clause") or
                                                   len(f["clauses"])),
                                               len(f["clauses"]))),
                    "headers": headers, "rows": rows})
                changes.append("table added")
        elif kind == "remove_table" and isinstance(idx, int) \
                and 0 <= idx < len(f["tables"]):
            f["tables"].pop(idx)
            changes.append(f"table {idx + 1} removed")

    return {"form": f, "changes": changes, "scrubbed": scrubbed,
            "scrubbed_entities": ents}


def chat_edit(form: dict, message: str, llm_fn=None) -> dict:
    """One chat turn: instruction -> ops -> railed application -> re-render.
    Returns {reply, form, changes, scrubbed, scrubbed_entities, generated}
    or {error}. CG_CHATEDIT_FIXTURE bypasses the LLM for tests."""
    lang = form.get("lang", "mr")
    fixture = os.environ.get("CG_CHATEDIT_FIXTURE")
    if fixture:
        data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    else:
        prompt = CHAT_PROMPT.format(
            form_json=json.dumps(_form_view(form), ensure_ascii=False),
            lang_name="Marathi" if lang == "mr" else "English",
            message=message.strip()[:1200])
        fn = llm_fn or (lambda p, **kw: llm_with_fallback(p, preferred="gemini", **kw))
        try:
            raw = fn(prompt, temperature=0.2, max_tokens=2000, json_mode=True)
        except LLMError as e:
            return {"error": str(e)}
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        try:
            data = json.loads(m.group(0) if m else raw)
        except json.JSONDecodeError as e:
            return {"error": f"chat edit returned malformed JSON: {e}"}

    applied = apply_ops(form, data.get("ops") or [], message)
    out = {"reply": str(data.get("reply") or ""), **applied}
    g = generate_from_form(applied["form"])
    if g.get("error"):
        out["blanks"] = g.get("blanks", [])
        return out                       # form updated; render blocked on ____
    out["generated"] = g
    return out
