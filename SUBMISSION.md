# ClauseGuard — submission

**VJTI AI Hackathon 2026 · "Shaping Digital Governance" · Problem 1 (MAHA-GR-ALIGN)**

- **GitHub**: https://github.com/samay-rajput/clause-guard
- **Live demo**: https://clause-guard.streamlit.app/
- **Demo video**: `<YouTube unlisted URL — added after recording>`

## Pitch (one paragraph)

ClauseGuard drafts and reviews Government Resolutions against 776 real Maharashtra GRs
(10,389 clauses parsed, 10,370 indexed for retrieval; text from orgpedia/mahGRs, the
dataset the problem statement names — a further 23,331 GRs across 10 departments are
built by the same pipeline) and
flags the clause-level conflicts a drafting officer would otherwise miss. Retrieval
narrows thousands of clauses to ~50 candidates; a fine-tuned MuRIL cross-encoder
(238M, 130 ms/pair on CPU — no API, no rate limits) screens them to a handful; an LLM
then only *extracts* the competing values ("50 टक्के" vs "100 टक्के") — grounded
against the clauses they came from — and deterministic code makes the conflict call:
every flag ships with an auditable reason. Type a topic and the same app drafts the
whole GR: real precedent GRs seed the department, वाचा references and file number in
the portal's own grammars; an AI layer proposes the prose under a *sourced-or-blank*
rail (no numeral the user didn't see — unknowns become blanks with open questions);
the generated draft is conflict-checked immediately, with one-click deterministic
fixes; and the download reproduces the authentic government GR layout page-for-page
(calibrated against a real portal GR, Devanagari numerals, running headers, `पृष्ठ N
पैकी n` footers), named `<18-digit code>.pdf` like the portal's own files. It also
links and currency-checks every citation, scores Manual-of-Office-Procedure compliance
(0%→100% live), bundles a Marathi↔English legal glossary, and keeps an audit trail of
every suggestion and human edit. It runs fully offline on a laptop GPU.

## What makes it defensible

- **Real corpus, real mess**: the portal's PDFs carry legacy-font glyph corruption; we
  score it, filter it, and repair demo-critical documents under a digit audit that
  guarantees every numeral survives verbatim.
- **Measured evaluation, not marketing**: fine-tuned macro-F1 0.9134 (0.8957 on the
  leak-free subset) vs a protocol-matched TF-IDF baseline (0.7754), zero-shot
  Llama-70B (0.6521) and the model's own 8B teacher (0.499).
- **We audited our own labels**: a 50-pair human blind check + independent blind
  adjudication of every disagreement measured ~26% label noise in the synthetic
  contradiction/consistent labels — so we also report accuracy against adjudicated
  truth (~0.70), triangulated by a validated cross-family relabeler (0.6975 on 287
  pairs). The label-noise finding, provenance chain, and all raw artifacts are
  versioned in the repo.

- **Scoped against the SRS, openly**: all 16 functional requirements are implemented —
  including the audit trail (FR-15), PDF/DOCX export with harfbuzz-shaped Devanagari
  (FR-16), and §1.2 draft *generation* (AC-3 met as generation: every generated draft
  scores 100% on the mandatory-section checklist, verified offline in both languages) —
  and citation-extraction recall is measured against hand-annotated ground truth instead
  of against our own extractor's output. See the SRS-coverage section in `README.md`.

## Run it

See `README.md` — quickstart uses the shipped corpus: `pip install -r requirements.txt`,
add keys to `.env` (or `LLM_MODE=ollama` for fully-local), `python src/index/build_index.py`,
`streamlit run app/streamlit_app.py`.

Evaluation: `EVAL_TABLE.md` · dataset provenance: `DATASET_CARD.md` · license: MIT.
