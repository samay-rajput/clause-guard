# ClauseGuard

AI-assisted Government Resolution (GR) drafting for Maharashtra — VJTI AI Hackathon 2026
("Shaping Digital Governance", Problem 1: MAHA-GR-ALIGN).

**Live demo**: https://clause-guard.streamlit.app/ (cloud LLM mode; the four sidebar
demo scenarios are pre-cached — fully local Ollama mode is the recording setup, see
`DEPLOYMENT.md`).

Drafts and reviews Maharashtra GRs against a corpus of real ones:

1. **Cross-departmental conflict detection** — retrieval narrows candidate clause pairs,
   an LLM (and optionally a fine-tuned MuRIL cross-encoder) screens them, and flagged
   conflicts get a drafting-officer-grade explanation citing the conflicting GRs.
2. **Reference tracking** — extracts cited GR numbers/codes, links them to the corpus,
   flags stale (superseded) references, suggests successors.
3. **Template compliance** — deterministic scorecard against Manual of Office Procedure
   conventions (header, Read block, preamble, numbered clauses, financial-sanction block,
   budget head, signature formula, code).
4. **Bilingual terminology** — Marathi ↔ English legal/administrative glossary.
5. **Topic-driven drafting studio** — type a topic and ClauseGuard retrieves real
   precedent GRs from the corpus, infers the issuing department from their 18-digit
   codes, builds the वाचा reference list in the portal's own citation grammar, proposes
   a file number in the real `<प्रत्यय>-<वर्ष>/प्र.क्र.<n>/<कार्यासन>` grammar, and prefills
   the whole form. An AI layer proposes the prose under a *sourced-or-blank* rail:
   every number it emits must trace to the topic or a shown precedent, anything else
   becomes a `____` blank the user must fill (with the open questions listed). The
   final draft is rendered deterministically from the reviewed form and a digit audit
   proves no numeral appears that the user did not approve. The classic
   brief-expansion path (digit-audited both ways) remains.
6. **Draft-time conflict checking** — a generated draft goes straight through the full
   conflict/reference/compliance/glossary review; verified conflicts appear inline
   with a one-click deterministic fix (substitute the in-force value, regenerate
   through the audit, re-check). Extracted numeric values must be *grounded* in the
   clause they came from — a hallucinated number can never flag a conflict.
7. **Audit trail** — every review and generation appends to a local JSONL: the
   suggestions offered, the deterministic results, and a unified diff of the officer's
   edits between submissions.
8. **Authentic-format export** — the draft downloads as a PDF/DOCX that reproduces the
   real Government-of-Maharashtra GR layout, calibrated span-by-span against an actual
   portal GR (US-Letter geometry, top-right bold subject block, centred letterhead,
   hanging वाचा/प्रत lists, justified body, running header with the thin-over-thick
   rule and `पृष्ठ N पैकी n` footers on continuation pages, Devanagari numerals
   throughout, clickable `www.maharashtra.gov.in`), named `<18-digit code>.pdf` like
   the portal's own files. Plain DOCX/PDF and the review report remain available.

## Corpus note

The live portal gr.maharashtra.gov.in returned 503 throughout the hackathon window
(Jul 26–28, 2026). The corpus was therefore built from the **Wayback Machine's archive
of the same portal** (≥20,000 archived **Marathi** GR PDFs enumerated via the CDX API —
the portal folder is labeled "English" but that reflects the portal UI language, not
the documents) — real GRs, archival copies. See `src/ingest/download_wayback.py`.

## Quickstart (uses the shipped corpus — minutes, not hours)

The parsed corpus (`data/corpus.jsonl`, 776 GRs) ships in the repo; you only need to
embed it and run the app:

```
pip install -r requirements.txt
cp .env.example .env        # Windows: copy — add GEMINI_API_KEY + GROQ_API_KEY,
                            # or uncomment LLM_MODE=ollama for a keyless local run
python src/llm/clients.py   # smoke-test the active provider(s)
python src/index/build_index.py              # e5-small -> Chroma (~10 min CPU)
streamlit run app/streamlit_app.py
```

## Rebuild the corpus from scratch (optional — several hours + LLM quota)

```
python src/ingest/bulk_download_all.py       # ~1,000 archival PDFs (HTE=08, SJ=22, SchoolEd=21)
python src/ingest/parse_pdfs.py corpus --min-quality 0.10
python src/index/build_index.py
python src/ingest/upsert_clean.py --top-retrieved 25   # targeted LLM repair, digit-audited
python src/detect/warm_cache.py              # planted scenarios end-to-end (warms the LLM cache)
```

Fine-tune track: `src/finetune/generate_pairs.py` → `validate_dataset.py` → `split_dataset.py`
→ `notebooks/finetune_muril_colab.ipynb` (Colab T4) → `eval_zeroshot.py` + `eval_local_latency.py`.
Results land in `EVAL_TABLE.md` / `DATASET_CARD.md`.

## The corpus-garble story (worth reading)

Most Maharashtra GR PDFs are text-based but typeset in legacy Devanagari fonts with
broken ToUnicode CMaps — text extracts *garbled* (e.g. `निर्णय` → `दनणचय`), differently
per font family. We (1) score every document's extraction quality against a common-word
list (`src/ingest/quality.py`), (2) keep the best-extracting documents, (3) repair
demo-visible documents with an LLM pass whose **digit audit** guarantees every numeral
survives verbatim (`src/ingest/upsert_clean.py`) — amounts and dates are the substance
of conflict detection and must never be "fixed" by the repair step.

**Validated next step (not run within the hackathon window)**: the glyphs *render*
correctly — only the extraction mapping is broken — so rendering pages to images and
OCR-ing them recovers clean text and would upgrade the whole corpus at the root.

Evaluation: `EVAL_TABLE.md` · dataset provenance and limitations: `DATASET_CARD.md`.

## SRS coverage (Problem 1 — MAHA-GR-ALIGN)

Against the problem statement's 16 functional requirements:

- **Met — all 16** — reference parsing + archive verification (FR-1–3); semantic conflict
  detection reporting similarity score and source-GR links (FR-4–6); bilingual glossary
  with mismatch flagging and standard-term suggestions (FR-7–9); Manual-of-Office-Procedure
  enforcement including the financial-sanction block and budget head (FR-10–12); web
  dashboard accepting upload or paste (FR-13); side-by-side clause comparison with a
  code-built suggested fix (FR-14); append-only audit trail of AI suggestions and
  human-edit diffs with JSONL/CSV download (FR-15); DOCX/PDF export of the draft and the
  review report, with harfbuzz-shaped Devanagari in the PDF path (FR-16).
- **Drafting (§1.2)** — the Generate tab writes GRs, not just reviews them: a
  deterministic Manual-template scaffold plus an optional LLM layer that expands the
  officer's brief (local-only in ollama mode, per NFR-2) under a digit audit — output
  that invents or drops any numeral is rejected. AC-3 is met as *generation*: every
  generated draft carries all mandatory sections, verified inline by the same scorecard
  (100% in both languages, including offline). Full legal advice and automatic approval
  remain out of scope, as the SRS itself requires.
- **Dataset divergence** — §6 names `orgpedia/mahGRs` as the primary dataset; we built
  from the portal itself via the Wayback Machine, §1.3's first-listed source, because the
  live portal returned 503 throughout the window. The cost of that choice is the
  legacy-font garble described above (orgpedia's copies are already machine-readable),
  and OCR remains the documented root-cause fix.
- **Acceptance criteria** — AC-1 is measured rather than assumed: 100% citation recall on
  clean drafts, 60% on garbled archive PDFs, against a hand-annotated ground truth
  (`EVAL_TABLE.md`, `data/citation_ground_truth.json`). AC-2, AC-4 and AC-5 are
  demonstrated by the four planted scenarios. AC-3 is asserted by
  `python src/draftgen/generate.py` (generated drafts score 100% in both languages,
  offline) and the app-level tests in `tests/`.

## License

MIT — see `LICENSE`.
