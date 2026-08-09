# Demo video script (~4–4.5 min)

> Deadline extended to Sun 2 Aug, 10:00 PM IST — the Draft→Export→Audit beat
> below is now in the main flow (it was optional when time was tight).

> Record with Xbox Game Bar (Win+G) against a WARM LLM cache. Trim in Clipchamp.
> Do a 2-minute test clip first. Max 2 full takes; take 2 ships.

| t | Beat | On screen | Voiceover (draft) |
|---|------|-----------|-------------------|
| 0:00–0:20 | Problem | Screenshot of a real GR + the portal's 503 page | "Maharashtra issues thousands of Government Resolutions. Nothing checks a new draft against what's already in force — conflicting amounts, stale references, broken formats slip through. ClauseGuard fixes that." |
| 0:20–0:50 | Architecture | One slide: corpus → e5 retrieval → LLM/classifier screen → explain; scorecard; citations | "We indexed real GRs from the Higher & Technical Education, School Education and Social Justice departments, taken from orgpedia's mahGRs — the same portal documents, but OCR'd, which is what makes the Marathi readable. Clause-level multilingual retrieval narrows candidates; a screening layer flags conflicts; an LLM explains only what's flagged." |
| 0:50–2:10 | **Scenario A — fee-reimbursement conflict** | Load planted HTE draft → Review → funnel caption (10,370 clauses → 50 candidates → MuRIL flags 12 → 1 verified conflict) → red conflict card, side-by-side clauses, explanation | "This draft sets fee reimbursement at 50%. The system searches ten thousand clauses, the fine-tuned classifier narrows fifty candidates to twelve in milliseconds, and the verifier confirms one real conflict: the existing Higher & Technical Education GR of July 2024 mandates 100% reimbursement for the same students. The reason is built from extracted values — fifty per cent versus one hundred per cent — fully auditable, not a black-box opinion." |
| 2:10–2:50 | **Scenario B — outdated reference** | References tab: citation linked (1/1), yellow **Currency check** warning listing 2 newer same-subject GRs | "The draft funds a 2022 scheme by citing the original GR. The tracker links the citation and warns: two newer GRs exist on the same subject — verify the cited one is still operative. A currency check on every citation, automatically." |
| 2:50–3:30 | **Scenario C — compliance + terminology** | Broken draft: report header shows **0%** compliance and **3** terminology flags → load the fixed draft: **100%** and **0** flags | "The scorecard runs thirteen Manual-of-Office-Procedure checks — including the financial sanction block and the budget head. The broken draft scores zero and trips three terminology flags. Load the corrected version: one hundred per cent, no flags." |
| 3:30–3:45 | Terminology beat | Glossary tab on the BROKEN draft — the three red→green correction chips | "Every term is checked against a controlled bilingual glossary. 'Govt. Resolution' should be 'Government Resolution'; 'handicapped' should be 'Person with disability' — the term Government policy actually mandates. It suggests the approved form, not just a warning." |
| 3:45–4:15 | **Draft → Export → Audit** (FR-15/16 + §1.2) | Generate tab: AI-assist toggle ON, type the brief → Generate → **100%** compliance chip → Download PDF (open it: shaped Marathi) → Audit tab: the trail with the 50%→100% diff | "ClauseGuard doesn't just review — it drafts. Give it a brief; a local model expands it into the preamble and clauses under a digit audit — no number invented, none dropped — and a deterministic template guarantees every mandatory section: one hundred per cent compliance, Marathi or English. Export the draft or the review report as Word or PDF — with correctly shaped Devanagari. And every suggestion and every human edit lands in a local audit trail." |
| 4:15–4:30 | Eval + close | Eval table screenshot (fine-tuned vs zero-shot) + repo link | "A fine-tuned MuRIL classifier screens clause pairs at milliseconds per pair — benchmarked against zero-shot LLMs on a held-out set. Code, dataset and eval are in the repo." |

## Recording checklist
- [ ] `.env` has `LLM_MODE=ollama` (fully local — quota can't ruin a take) and `ollama serve` is up
- [ ] `streamlit run app/streamlit_app.py` fresh; sidebar shows corpus stats
- [ ] Cache warmed and frozen: `python src/detect/warm_cache.py --baseline data/warm_mahgrs.txt`
      ends with `baseline matched` (frozen result: A:1 B:0 C1:0 C2:0 — C2's earlier "2" were
      cross-lingual false positives, removed by a comparator fix on Aug 6, 2026)
- [ ] Architecture slide for the 0:20 beat: open `demo/architecture_slide.html` in a browser tab, F11 fullscreen
- [ ] Browser zoom 110–125%, hide bookmarks bar
- [ ] Mic test clip watched back
- [ ] All planted drafts load from the sidebar selector
- [ ] Generate tab: submit the prefilled sample once (instant, deterministic) so the
      flow is familiar; for the recorded take use AI-assist with the brief — run it once
      BEFORE recording so the LLM response is cached and the take is instant
- [ ] Audit tab shows the Scenario A → fixed-draft diff (run A, then the fixed version,
      before recording); delete `data/audit_trail.jsonl` first for a clean trail

## Round 2 — live drafting-system demo (~3 min, localhost)

The shortlisting round asked for a full drafting system: topic in → best-format,
conflict-checked GR out, with a download indistinguishable from a real government GR.

> **Beat 0 answers the judges' "it must draft directly, without a human intervening."**
> Do it FIRST, then walk the same flow step by step to show the officer-review path exists
> too. The autonomous run reuses the warmed prefill cache, so it is fast.

| Beat | Do | Say |
|------|----|-----|
| 0. Autonomous | Generate tab. Type the topic, then click **⚡ स्वयंचलित मसुदा — Autonomous draft (no human in the loop)**. Point at the receipt panel, then **⬇️ अस्सल PDF**. | "One field: the subject. One click. ClauseGuard found the precedent GRs, inferred the department from their file numbers, had the model write the preamble and every operative clause, refused the numbers it could not source, rendered the final document with deterministic code under a digit audit, and produced a government-format GR. No field was reviewed or edited — the receipt states that. The figures it refused to invent are listed there, and it deferred them to a separate order, which is what the government itself does when a quantum is not yet fixed." |
| 0b. Or headless | (optional, terminal) `python src/draftgen/autodraft.py --topic "…"` | "Same thing with no interface at all — one command, a GR PDF on disk." |
| 1. Topic | Now step through it. Generate tab (मराठी default). Type a topic, e.g. "जिल्हा परिषद शाळांमधील विद्यार्थ्यांसाठी मोफत क्रीडा साहित्य पुरवठा" → **🔎 पूर्वसंदर्भ शोधा व फॉर्म भरा** | "Type a topic. ClauseGuard searches the real corpus, finds precedent GRs, and infers the department from their codes — the only garble-proof key." |
| 2. Prefill | Point at the precedent cards (similarity + source links), the prefilled वाचा (portal citation grammar), the file number, the ❓ needs-numbers questions | "The references are built in the portal's own citation grammar — the reference checker links them automatically. And the trust rule: the AI can propose prose, but every number must trace to a source; anything it can't source becomes a blank it asks you to fill. No hallucinated amounts, by construction." |
| 3. Generate & check | Review/edit a field, then **✍️ मसुदा तयार करा व तपासा** | "The final draft is rendered deterministically from the form you approved — a digit audit proves no numeral appears that you didn't see — and it goes straight through the same conflict, citation, compliance and terminology review as any draft." |
| 4. Conflict + fix | If a conflict card appears: value chips, then **🔧 दुरुस्ती लागू करा** → **🔁 पुन्हा तपासा** | "A verified conflict against an in-force GR — with the two values extracted and compared in code. One click aligns the draft to the in-force value, regenerates through the audit, and re-checks." |
| 5. Authentic export | Export expander → **📜 अस्सल शासकीय स्वरूप · PDF** → open it SIDE BY SIDE with `data/raw_pdfs/202402271742452721.pdf` | "The download is the real thing: US-Letter, the top-right subject block, the centred letterhead, hanging वाचा and प्रत lists, Devanagari numerals everywhere, running header and 'पृष्ठ N पैकी n' footers on page two — calibrated span-by-span against an actual portal GR, and named by its 18-digit code exactly like the portal's own files." |
| 6. Trail | Audit tab: the generate+review record | "Every generation and every fix is on the record." |

### Round-2 rehearsal checklist
- [ ] **Ollama is NOT auto-started on this machine** — run `ollama list` once (it
      boots the app) BEFORE the demo; `.env` has `LLM_MODE=ollama`
- [ ] Pre-run the EXACT demo topic once (prefill + generate & check) so every LLM
      response is disk-cached and the live run is instant
- [ ] Have `data/raw_pdfs/202402271742452721.pdf` open in a tab for the side-by-side
- [ ] If a fix-loop beat is planned, rehearse the topic first: pick one whose conflict
      candidate carries a single value (a two-valued candidate clause can re-flag with
      the 8B extractor — honest to explain, but smoother to avoid)
- [ ] Gates before the session: `python src/detect/warm_cache.py --baseline data/warm_mahgrs.txt`
      (A:1/B:0/C1:0/C2:0),
      `python tests/test_gr_layout.py`, `python tests/apptest_topic_flow.py`,
      `python tests/test_autodraft.py`, `python tests/apptest_autodraft.py`
- [ ] **Do NOT touch the `🤖 AI-assist` toggle.** It is the round-1 "expand an officer's
      brief" path and it discards the structured form, so the authentic PDF falls back to
      parsing flat text. The AI that writes the GR runs at PREFILL time and is always on —
      the toggle is unrelated to it.
- [ ] Pre-run beat 0 once so the autonomous button is cache-warm and instant on stage
