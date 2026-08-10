# ClauseGuard — Round 3 Architecture

*The one-page diagram lives in the presentation folder
(`ClauseGuard_Architecture_R3.svg` / `.png`). This document is its narration:
every numbered block, what it does, and — the part judges ask about — **why**.
The design principle behind all of it:* **AI proposes, deterministic code
decides, and every number and name is sourced or blank.**

---

## The one-breath summary

> A draft Government Resolution goes in — or just a topic. Real precedent GRs
> come out of a 23,331-document corpus; an AI adapts their official wording
> under audits that blank anything it cannot source; a deterministic renderer
> produces an authentic-format GR; and every clause of every draft is screened
> against the whole corpus for conflicts, where a fine-tuned model only
> *nominates* pairs and plain code makes every verdict. Nothing leaves the
> system unaudited, and the whole demo replays from a frozen, cache-backed
> baseline with the network unplugged.

---

## Data foundation (blocks 1–4)

**1 · orgpedia/mahGRs source.** The portal's own PDFs carry broken font
tables — copying their text yields garbage, and repair is provably impossible
(one document maps eight different letters to the same glyph). mahGRs
republishes the same GRs as OCR text, sidestepping the fonts entirely. It is
also the dataset the problem statement names.

**2 · Corpus.** 23,331 GRs across 10 departments, 295,587 clauses
(`data/corpus_mahgrs_full.jsonl`). Identity comes from the government's own
filenames (18-digit codes; 20-digit from May 2025 — a portal format change we
detect and accept). The citation graph (15,254 edges) links GRs by **file
number**, because clean text prints the numeric code in only 3% of documents.
Which corpus and index are live is **explicit** (`data/corpus.active`,
`CG_CORPUS`/`CG_DB_DIR`, loaded independent of import order) — a corpus/index
mismatch is a hard startup error, not a silent wrong answer.

**3 · Vector index.** Every clause embedded with multilingual e5-small into
Chroma: 191,537 clauses after exact-duplicate collapse (government boilerplate
recurs verbatim — one clause appears in 392 GRs), ~2 GB, built on the laptop
GPU in ~40 minutes. The index stores a fingerprint of the corpus it was built
from, checked at boot. Retrieval is **deterministic by construction**:
single-threaded query encoding (multi-threaded CPU float math reorders
reductions and reshuffles borderline ranks), stable distance+id tie-breaking,
and near-duplicate suppression — the candidate set is byte-identical across
runs. We learned each of those the hard way; the execution log has the story.

**4 · Canonical clause templates.** 107 clauses that appear verbatim in ≥20
real GRs each, mined per department. A sentence the government has published
twenty times *is* the official wording — so standard sections start from it.

## Drafting lane (blocks 5–9) — विषय ते अस्सल GR

**5 · Three ways in.** A topic (with GR-type presets — निधी वितरण, योजनेस
मान्यता, प्रशासकीय मान्यता, समिती गठन, वार्षिक पुनर्मंजुरी — seeding the
subject grammar and skeleton clauses with `____` slots); an officer's brief;
or a **chat instruction** ("दुसऱ्या कलमातील रक्कम ५ लाख करा"). Precedent cards
appear as you type — retrieval only, no LLM spend. The chat never writes draft
text: it emits whitelisted **form operations** (edit/add/remove clause,
subject, references, tables) that pass through the same rails as every other
AI path.

**6 · Deterministic structure — never AI.** Department (majority vote over the
precedents' code digits, 10-department curated table), the वाचा reference list
(built from precedent *metadata* in the portal's own citation grammar, so the
reference checker links every entry), the file number (real
`<प्रत्यय>-<वर्ष>/प्र.क्र.<n>/<कार्यासन>` grammar), the budget head (mined
per-department major heads). Structure is too important to generate.

**7 · AI wording layer.** Gemini (the strongest Indic-language model on public
benchmarks) writes the prose — but the prompt carries the precedent **clause
bodies** and the canonical templates, and each generated clause must declare
which source it adapts. In the fully-offline demo mode, seeded local Ollama
takes this role and nothing leaves the machine.

**8 · The rails (the heart of the system).** On every AI path:
- **Digit scrub** — any numeral not present in the topic, the shown
  precedents, or the user's own message becomes `____`, with the open question
  listed for the officer.
- **Entity scrub** — unsourced scheme/portal/institution names and month words
  get the same treatment. (Devanagari matras are not word characters in
  standard regex engines; the scrubs use script-aware boundaries.)
- **Wording-fidelity audit** — every clause is scored (character-3-gram
  containment) against the source it claims to adapt; drift is flagged in the
  UI per clause.
The model is never trusted to know a rupee amount, a date, or a scheme name it
was not shown.

**9 · Deterministic render + structural audit.** The final draft is rendered
*only* from the reviewed form. A digit audit then proves every numeral in the
output traces to that form — and the allowance for list numbering is
positional (clause 1..n, reference 1..n), not a blanket "small numbers are
fine", so an invented "within 15 days" is caught. Unfilled `____` blocks
generation (the autonomous path instead defers such clauses to a स्वतंत्र
आदेश, the real government instrument for it). The browser shows a live paper
preview of exactly what the renderer will produce.

## Checking lane (blocks 10–14)

**10 · Candidate retrieval.** The draft is chunked into clauses; each clause
pulls its nearest corpus clauses (cosine cut 0.18, top-k 10) from the
deterministic index.

**11 · MuRIL screening.** A 238M cross-encoder fine-tuned for
contradiction/consistent/neutral runs locally at ~130 ms/pair and *nominates*
pairs. Round 3 retrained it on **clean-text pairs**: 3,891 pairs = 3,002
synthetic (teacher: the Gemini labeler our round-1 blind audit validated at
0.88 vs adjudicated truth — replacing the ~26%-noise 8B teacher — with mixed
Marathi/English hypotheses after the cross-script false-positive lesson)
+ 889 deterministically mined real pairs. Leakage-safe split by seed clause;
TF-IDF probe 0.674 (below the 0.75 "lexically too easy" line). Test macro-F1
**0.9188** — trained on the laptop's 4 GB GPU in four minutes. Screening is
per-pair, so a label can never depend on what else shared its batch.

**12 · Extract-verify — code makes the call.** For each nominated pair the LLM
does *extraction only* (strict JSON schema: same scheme? the two values), and
then **code** decides: the values must be *grounded* (numeric digit-runs — and
non-numeric tokens — must occur in their source clause, so a hallucinated
value can never flag anything); English-vs-Marathi values are "cannot tell",
never "conflict" (the C2 lesson); a financial-year label is a re-sanction, not
a contradiction. Verdicts carry the structured values, so the one-click fix is
a string substitution through the audited form — no LLM involved.

**13 · The review surface.** Conflict cards with value chips, source-PDF
links, and a drafting-officer explanation (Gemini flash-lite — the
high-quota tier); reference linking with currency warnings ("this GR you cite
has newer same-subject successors"); the 13-check Manual-of-Office-Procedure
scorecard; bilingual terminology flags. A generated draft flows through this
identical pipeline automatically.

**14 · The frozen baseline.** `data/warm_round3.txt` freezes the four demo
scenarios **by GR identity**: A:4 conflicts (including the original anchor GR
and two more in-force 100% GRs), B:8 (the stale-reference draft genuinely
conflicts with newer in-force GRs), C1:0, C2:9 (in-force DBT GRs spanning
2018–2026). One command replays the entire pipeline from the sha-keyed LLM
disk cache — network unplugged — and asserts every count and identity. No
change ships without this gate.

## What leaves the system (blocks 15–17)

**15 · Authentic export.** PDF and DOCX calibrated span-by-span against a real
portal GR: US-Letter grid, hanging वाचा/प्रति and clause indents, in-body
tables, परिशिष्ट annexure pages, Devanagari digits applied at render time only
(the canonical text stays ASCII so every audit sees one number system), named
`<code>.pdf` like the portal's own files.

**16 · The export gate.** Every वाचा reference must resolve against the corpus
(code or file-number) or the authentic export refuses. Overriding — or any
surviving `____` — stamps a **मसुदा · DRAFT** watermark on every page. The
system would rather label its own output a draft than let an unverified line
wear the government's format.

**17 · Per-user audit trail (FR-15).** Append-only JSONL per account: every
suggestion offered, every deterministic result, and the officer's edits as
unified diffs between submissions. Drafters see their own trail; reviewers see
all. It never leaves the machine.

## Platform (bottom strip)

React SPA (two complete interfaces, मराठी and English, one switch apart; live
GR paper; SSE-streamed pipeline progress driving the funnel animation) over a
FastAPI backend (JWT + argon2, drafter/reviewer roles, rotating refresh
tokens, rate limits on the LLM-spending endpoints, magic-byte upload checks,
models warmed at boot off the request path). The LLM router splits work by
strength — Gemini flash for Marathi wording, flash-lite for explanations, Groq
gpt-oss-120b for schema-guaranteed extraction, seeded Ollama for the sovereign
offline demo — behind one disk cache keyed on provider|model|temperature|
prompt, which is what makes the demo cost zero API calls and replay exactly.

## The numbers to say out loud

| | |
|---|---|
| Corpus | 23,331 GRs · 10 departments · 295,587 clauses |
| Index | 191,537 deduped clauses · deterministic retrieval |
| Screener | macro-F1 0.9188 on clean pairs · 130 ms/pair · local |
| Dataset | 3,891 pairs · validated teacher · probe 0.674 · leakage-checked |
| Templates | 107 canonical clauses, each verbatim in ≥20 real GRs |
| Citation recall | 75% on clean text (hand-annotated ground truth) |
| Frozen demo | A:4 · B:8 · C1:0 · C2:9 — by GR identity, offline-replayable |
| Tests | 37-check API suite + 26 rail checks + 11 chat-edit checks, all green |
