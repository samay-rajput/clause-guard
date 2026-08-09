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

The corpus text comes from **[orgpedia/mahGRs](https://github.com/orgpedia/mahGRs)** —
the dataset the SRS names — which republishes the same portal GRs as text extracted by
**OCR** rather than from the PDF text layer. That is what makes it readable: the
originals are typeset in fonts whose ToUnicode maps are wrong (see below), so reading
their text layer garbles the Marathi while OCR does not.

Identity still comes from the government's own filenames: the 18-digit code, the issuing
department (its last two digits) and the date (its first eight) are taken from the
filename, and every GR stays verifiable against the portal PDF through the source link
on each card.

Two corpora are built from it:

| file | scope | use |
|---|---|---|
| `data/corpus_mahgrs.jsonl` | 776 GRs (the demo footprint: 770 clean twins of the original archive set + 6 with no mahGRs twin) | what the app and the demo run on |
| `data/corpus_mahgrs_full.jsonl` | 23,331 GRs across 10 departments | scale/citation-graph work; too large for git, rebuild locally |

`data/corpus.jsonl` (the earlier archival-text build) is kept for comparison. Which
corpus is live is **explicit**, never inferred from which files happen to exist:
`CG_CORPUS` env var → `data/corpus.active` pointer file → `data/corpus.jsonl`.
`CG_DB_DIR` does the same for the Chroma index.

## Quickstart (uses the shipped corpus — minutes, not hours)

The parsed corpus (`data/corpus_mahgrs.jsonl`, 776 GRs) ships in the repo; you only need
to embed it and run the app:

```
pip install -r requirements.txt
cp .env.example .env        # Windows: copy — add GEMINI_API_KEY + GROQ_API_KEY,
                            # or uncomment LLM_MODE=ollama for a keyless local run
python src/llm/clients.py   # smoke-test the active provider(s)
python src/index/build_index.py              # e5-small -> Chroma (~10 min CPU)
streamlit run app/streamlit_app.py
```

## Rebuild the corpus from scratch (optional)

```
# 1. fetch the source text (~400 MB, gitignored)
git clone --filter=blob:none --sparse https://github.com/orgpedia/mahGRs.git data/mahgrs
cd data/mahgrs && git sparse-checkout set GRs/Higher_and_Technical_Education_Department \
  GRs/School_Education_and_Sports_Department GRs/Social_Justice_and_Special_Assistance_Department \
  GRs/Tribal_Development_Department GRs/Other_Backward_Bahujan_Welfare_Department \
  GRs/Minorities_Development_Department GRs/Persons_with_Disabilities_Welfare_Department \
  GRs/Skill_Development_and_Entrepreneurship_Department GRs/Medical_Education_and_Drugs_Department \
  GRs/Women_and_Child_Development_Department && cd ../..

# 2. build both corpora (the full one is also the citation index for the small one)
python src/ingest/build_mahgrs_corpus.py --out data/corpus_mahgrs_full.jsonl
python src/ingest/build_mahgrs_corpus.py --out data/corpus_mahgrs.jsonl \
       --codes-from data/corpus.jsonl --carry-orphans \
       --resolve-index-from data/corpus_mahgrs_full.jsonl

# 3. gate, index, warm
python tests/test_corpus_invariants.py
python src/index/build_index.py
python src/detect/warm_cache.py --save data/warm_mahgrs.txt
```

The earlier archival-PDF route (`bulk_download_all.py` → `parse_pdfs.py corpus`) still
works and is what `data/corpus.jsonl` was built with.

### Indexing the full 10-department corpus (long, optional)

The 23,331-GR corpus is *parsed* in ~6 minutes, and that is what produces the department
coverage and the 15,254-edge citation graph. **Embedding it is the slow part** and is not
needed for the demo:

```
set CG_DB_DIR=chroma_db_full
set CG_CORPUS=data/corpus_mahgrs_full.jsonl
python src/index/build_index.py --dedupe        # 295,587 clauses -> 191,537 unique
```

Measured on this machine (i5-12450HX, CPU-only — `torch.cuda.is_available()` is False even
with an RTX 2050 present): **5–13 clauses/s**, so 4–10 h wall clock and ~1.5 GB on disk. It is
linear, one-off per document, and independent of the demo index — `CG_DB_DIR` keeps the two
side by side, and the app reads whichever the env var points at. Run it when the machine is
free; a partially-built index should be deleted rather than kept, since nothing downstream
validates an index's completeness against its corpus.

Fine-tune track: `src/finetune/generate_pairs.py` → `validate_dataset.py` → `split_dataset.py`
→ `notebooks/finetune_muril_colab.ipynb` (Colab T4) → `eval_zeroshot.py` + `eval_local_latency.py`.
Results land in `EVAL_TABLE.md` / `DATASET_CARD.md`.

## The corpus-garble story (worth reading)

Most Maharashtra GR PDFs are text-based but typeset in **subsetted Type0/Identity-H
CIDFontType2** fonts (Sakal Marathi in 678 of the original 776 documents, plus
DVOT-SurekhMR, Mangal, Kokila, Nirmala UI). Word writes a **wrong ToUnicode entry for a
few glyph IDs per subset**, and because each document is subsetted differently the damage
is *per-document*: text extracts garbled (`निर्णय` → `दनणचय`), and no single substitution
table can undo it. Text-level repair is provably impossible in general — in one subset
eight distinct characters (च ड थ द व श ह ौ) all map to `ि`, and 1.88% of glyph draws
delete a character outright (`र` standing for `ट्र`, which is how महाराष्ट्र breaks).

The digits, however, survive intact — which is why every identity in this project
(GR code, department, date) is digit- or filename-derived, and why the LLM repair pass
that was used on demo-visible documents is gated by a **digit audit** that rejects any
output where a numeral changed (`src/ingest/upsert_clean.py`).

**The root-cause fix is rendering the pages and OCR-ing them.** That is exactly what
orgpedia's pipeline does ("crawler → OCR to handle non-standard fonts → paragraph
detection → table detection → translation"), so adopting mahGRs *is* the fix, arrived at
independently by two teams. Measured effect on the same 776 GRs:

| | archival text layer | mahGRs (OCR) |
|---|---|---|
| readability score, median | 0.1433 | **0.2513** |
| subject extracted | 550/776 | **762/776** |
| department extracted | 552/776, **146 different spellings**, 81 well-formed | **763/776, 15 spellings**, 762 well-formed |
| citation-graph edges | **0** (761 of 769 codes were a GR citing itself) | **119** |

What mahGRs costs, stated plainly: **42.6% of its pages carry no text at all** — the
extraction drops annexure/table pages and usually the signature-and-availability tail —
and it carries its own OCR noise at ~1.4% of word occurrences (`आर्थिकदृष्ट्ट्या` for
`आर्थिकदृष्या`, `शिष्ट्यवृ` for `शिष्यवृ`). It is a cleaner corpus, not a complete one,
and `pages_empty` is recorded on every record rather than papered over.

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
- **Dataset** — §6 names `orgpedia/mahGRs` as the primary dataset, and that is now the
  corpus text source. The first build used the portal itself via the Wayback Machine
  (§1.3's first-listed source) because the live portal returned 503 throughout the
  hackathon window; the cost of that choice was the legacy-font garble described above.
  Cross-department coverage came with the switch: 10 departments and 23,331 GRs are
  available locally, against the 3 departments the archival crawl reached.
- **Acceptance criteria** — AC-1 is measured rather than assumed, over three populations
  against one hand-annotated ground truth: **100%** citation recall on clean drafts,
  **60%** on garbled archive PDFs, **75%** on the same GRs in clean mahGRs text
  (`EVAL_TABLE.md`, `data/citation_ground_truth.json`, `results/metrics_citation_recall.json`).
  The residual misses are `समक्रमांकाचा` back-references that carry no file number at all.
  AC-2, AC-4 and AC-5 are demonstrated by the four planted scenarios. AC-3 is asserted by
  `python src/draftgen/generate.py` (generated drafts score 100% in both languages,
  offline) and the app-level tests in `tests/`.

## License

MIT — see `LICENSE`.
