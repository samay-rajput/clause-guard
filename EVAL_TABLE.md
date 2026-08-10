# Evaluation — conflict classification on the held-out test set

## Round 3 (Aug 10, 2026): the clean-text retrain

The screener was re-fine-tuned on pairs generated from the clean mahGRs corpus —
new teacher (`gemini-flash-lite`, the labeler the round-1 audit validated at 0.88
vs adjudicated truth, replacing the ~26%-noise llama-8B), mixed Marathi/English
hypotheses (the C2 false-positive lesson), plus 889 real mined pairs
(number-swap / truncation / hard-neutral). Trained locally (RTX 2050, fp16,
same protocol as the Colab notebook: seed 42, effective batch 16, lr 2e-5,
5 epochs, best-of-epochs by dev macro-F1).

| System | Macro-F1 | Accuracy | Contradiction F1 | Consistent F1 | Neutral F1 |
|---|---|---|---|---|---|
| **MuRIL-base retrained on clean pairs (n_test=509)** | **0.9188** | 0.9194 | 0.892 | 0.870 | 0.994 |

> **Not comparable head-to-head with the 0.9134 below**: different test set
> (3,891-pair clean dataset, group-split by seed clause, TF-IDF probe 0.674),
> different teacher, different corpus. What IS directly observable: the old
> garbled-trained screener failed to flag near-identical clean-text variants of
> the demo's anchor conflict on the full 23,331-GR corpus; the retrained model
> flags them stably (verified per-pair, batch-independent). Dataset:
> `data/pairs_clean.jsonl`; metrics: `model/muril_gr_conflict_fp16/metrics_finetuned.json`.

## Round 1 record (garbled corpus) — kept as the honest history

> All rows are scored on the SAME held-out 563-pair test set (grouped split by
> seed clause, seed 42). Zero-shot judges see 5 pairs per request (few-shot
> JSON). Numbers are written by scripts from `results/*.json`, not by hand.
>
> **Measured on the garbled archival corpus — superseded as of Aug 6, 2026.**
> Every row in the table below was trained and scored on clause pairs drawn from
> `data/corpus.jsonl`, whose Marathi carries the legacy-font extraction corruption.
> The product now serves `data/corpus_mahgrs.jsonl` (clean OCR'd text; readability
> median 0.1433 → 0.2513). These numbers remain the honest record of what was
> measured, but they describe the *previous* serving condition. Re-generating pairs
> from clean text and re-fine-tuning MuRIL is outstanding work, and until it lands the
> screener is a model trained on garbled text being applied to clean text. What that
> costs is bounded rather than guessed: the screener is stage 1 of 2 and only ever
> *proposes* pairs — every flag still passes the extraction-verify stage, where code
> (not a model) compares the actual values and a hallucinated number cannot flag
> anything. Measured effect of the corpus change on screening volume: MuRIL flags
> roughly 1.8x more candidate pairs on clean text.
>
> Citation-extraction recall (AC-1) IS re-measured on the new corpus and is reported
> below and in `results/metrics_citation_recall.json`.

| System | Macro-F1 | Contradiction F1 | Consistent F1 | Neutral F1 | Latency / pair | Throughput | Marginal cost |
|---|---|---|---|---|---|---|---|
| **Fine-tuned MuRIL-base, 238M (local CPU)** | **0.9134** | 0.906 | 0.863 | 0.971 | **130 ms** | 7.7 pairs/s | $0, no rate limit |
| — same model, leak-free test subset (n=395, see note 2) | **0.8957** | — | — | — | 130 ms | 7.7 pairs/s | $0 |
| Zero-shot Groq Llama-3.3-70B (same family as generator) | 0.6521 (over 420/563 judged — see note 3) | — | — | — | ~1.5 s RTT + rate-limit waits | ~0.3 pairs/s effective | free tier |
| Zero-shot local Llama-3.1-8B (Ollama, RTX 2050) | 0.499 (over 468/563 judged; 95 batches unparseable — see note 3) | — | — | — | ~15–30 s | — | $0 |
| TF-IDF + LogReg lexical baseline (fit on train, scored on test) | 0.7754 | — | — | — | <1 ms | — | $0 |

## Label quality — measured, not assumed

A human blind-labeled 50 stratified test pairs from the readable subset
(`make_blind_check.py`), and every human-vs-dataset disagreement was then judged by an
independent blind adjudicator seeing only the two clauses (`blind_check_adjudication.json`):

| Measurement | Value |
|---|---|
| Raw human ↔ dataset-label agreement | 0.66 (94% on neutral; ~53% on the C/S boundary) |
| Adjudication of the 17 disputes | 12 sided with the human · 4 with the dataset · 1 neither |
| **Dataset label noise (readable sample)** | **~26%** — concentrated in the 8B generator's contradiction/consistent labels; neutral ≈ 6% |
| Human vs adjudicated truth | 0.90 |
| **Fine-tuned model vs adjudicated truth** | **0.70** (n=50; vs 0.92 against its own labels on the same pairs) |

Honest implication: the 0.9134 headline measures **fidelity to the synthetic labeling
function**; adjudicated-truth accuracy on readable pairs is ~0.70. The pipeline is
designed for exactly this: MuRIL only *screens* candidates (its cleanest class,
neutral-rejection, is what screening uses), and every flag still passes the
extraction-verify stage where code compares the actual values before anything is
called a conflict. Full numbers: `results/metrics_blind_check.json`,
`results/metrics_blind_truth.json`.

**Triangulated with a cross-family relabeler**: Gemini (validated at 0.88 agreement with
the adjudicated truth) relabeled the LLM-generated test pairs — on the 287 pairs with
cleaned labels so far (117 construction-correct + 170 relabeled; 64 labels changed) the
model scores **0.6975 vs cleaned labels** against 0.8851 vs the original labels on the
same subset. Two independent methods — human blind check (0.70, n=50) and cross-family
relabeling (0.6975, n=287) — converge on the same honest accuracy estimate. Coverage is
capped by free-tier daily limits; the estimate is stable across both samples
(`results/metrics_cleaned_test.json`).

## Citation extraction — SRS acceptance criterion 1 (>= 80% of cited references)

Scored against a **hand-annotated** ground truth (`data/citation_ground_truth.json`,
single annotator, Read/वाचा blocks only). It is deliberately *not* scored against
`corpus.jsonl`'s `cited_codes`/`cited_refs`: those are the output of the same
`extract_citations()` under test, so scoring on them would be circular and would
report ~100% for free.

| Population | Recall | n | AC-1 |
|---|---|---|---|
| **Clean drafts** — what the app actually receives (typed, pasted or uploaded) | **100%** | 4/4 refs over 3 drafts | **pass** |
| **Archived GR PDFs** — first-page text carrying legacy-font garble | **60%** | 12/20 refs over 12 GRs | below target |
| — same population, before the garble-tolerant pattern | **0%** | 0/20 | — |
| **Same 12 GRs, clean mahGRs text** (the serving corpus since Aug 6, 2026) | **75%** | 15/20 refs over 12 GRs | below target |
| — same population, before allowing a department name inside the reference | **55%** | 11/20 | — |

The clean-text row is worth reading twice, because the naive expectation is wrong:
clean text alone scored *worse* than the garbled archive (55% vs 60%). The reason was
not the text but the pattern — `शासन निर्णय` and `क्र.` are adjacent only when a GR cites
its **own** department. A citation of another department names it in between
("शासन निर्णय, शालेय शिक्षण व क्रीडा विभाग, क्र.पीआई-1094/…"), so the requirement that the
two be adjacent was systematically dropping exactly the *cross-departmental* citations
this project exists to track. Allowing the department name takes the population to 75%
with the clean-draft and archived rows unchanged.

The archived-GR row is the corpus-garble story showing up in a second place: the
reference patterns key on `शासन निर्णय`, which extracts font-specifically corrupted
(`मनणणय`, `वनणणय`, `शनणणय`, `रिणणय`), so **word-anchored extraction recovers formal
references from only 6.7% of the 776 corpus GRs** — while 18-digit unique codes,
being digits, are recovered from 99.1%. `extract_metadata.py` now carries a
digit-anchored fallback keyed on GR file-number *structure* rather than on any
word, which takes this population from 0% to 60%; it is applied only where the
word-anchored patterns find nothing, and is verified to leave clean-draft output
byte-identical. 3 of the 20 annotated citations name no file number at all
("this department's GR of dd.mm.yyyy"), so 85% is the ceiling on this sample
without OCR. Full numbers: `results/metrics_citation_recall.json`.

## Notes (read before quoting the numbers)

1. **The lexical baseline is protocol-matched**: TF-IDF+LogReg fit on `pairs_train`,
   scored on `pairs_test` (`src/finetune/tfidf_baseline.py`, `results/metrics_tfidf_baseline.json`).
   The fine-tuned model's **+0.14 margin** over it is the semantic-learning evidence.
   (The dataset card's 0.788 probe is a separate random-split *dataset audit*, not this row.)
2. **Split leakage, quantified honestly**: the split groups by seed clause, but
   composite-seed mined pairs and duplicate corpus clauses mean **168/563 test rows
   (29.8%) share one clause side verbatim with a train row** (0 identical full pairs).
   On the 395 leak-free rows the model scores **0.8957** — still +0.12 above the
   lexical baseline on fully unseen clause text (`results/metrics_leakfree.json`).
3. **Zero-shot F1 is computed over judged pairs only** (unparseable JSON batches are
   excluded); n_judged/n_total is reported per row in `results/metrics_zeroshot_*.json`.
4. Fine-tuned local F1 independently reproduced on-device (0.9134,
   `results/metrics_local_cpu.json`) — identical to the Colab test run.

## Contamination guardrails (honest version)

- **All LLM-generated pairs come from one local generator: Ollama llama3.1-8B**
  (plus deterministic augmentations and mined pairs — `generator` field per pair).
  There is no Gemini/Groq-generated training data.
- The **Groq Llama-3.3-70B judge shares the generator's Llama family** — treat its row
  as the family-contaminated cell. The **cross-family check is Gemini**, spent where it
  counts: not as a fourth judge row (free-tier daily caps make a full 563-pair run
  impossible in a day) but as the validated **relabeler** in the label-quality section —
  a stronger use of the same budget.
- The generator itself, judged zero-shot on the same test set, scores **0.499** —
  the fine-tuned 238M student outscores its own 8B teacher by +0.41, which is the
  cleanest evidence the dataset taught something beyond the teacher's judgment.
- Zero-shot 70B (0.652) lands BELOW the TF-IDF baseline (0.775): the trained
  baseline can exploit within-dataset lexical regularities that a zero-shot judge
  never sees. That is exactly why the fine-tuned model is compared against BOTH —
  it clears the lexical ceiling (+0.14) and the strongest zero-shot LLM (+0.26).
- Dataset provenance, distributions and limitations: `DATASET_CARD.md`.
