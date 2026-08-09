# Deploying ClauseGuard

The repo is self-deploying: on a host that has only the git checkout, the app's
first boot downloads the heavy runtime artifacts from the public Hugging Face Hub
(`src/deploy/bootstrap.py`):

| Artifact | HF repo | Lands in |
|---|---|---|
| Fine-tuned MuRIL cross-encoder (475 MB) | `samay-rajput/clauseguard-muril` (model) | `model/muril_gr_conflict_fp16/` |
| e5-small Chroma index, 11,817 clauses (112 MB) | `samay-rajput/clauseguard-index` (dataset) | `chroma_db/` |
| Warmed LLM disk cache — the 4 demo scenarios cost zero quota | same dataset | `cache/llm/` |

No token is needed to download; both repos are public.

> **The published artifacts are the pre-migration ones** (archival-text corpus, 11,817
> clauses, and the LLM cache warmed against it) and the deployed app still serves them —
> deliberately: the clean-corpus rebuild is local-only until you choose to publish it.
> Re-publishing means uploading the new `chroma_db/` (10,370 clauses) **and** the new
> `cache/llm/` **and** committing `data/corpus_mahgrs.jsonl` + `data/corpus.active`
> together. They are one unit: a corpus without its matching cache means every demo
> scenario runs live against the cloud LLM, and `bootstrap.py` validates artifacts by file
> existence only, so a stale index would be accepted silently.

## Streamlit Community Cloud (recommended free host)

1. Sign in at https://share.streamlit.io with the GitHub account that owns
   `samay-rajput/clause-guard`.
2. **New app** → repository `samay-rajput/clause-guard`, branch `master`,
   main file `app/streamlit_app.py`. Python 3.11 (Advanced settings).
3. Paste the app secrets (Advanced settings → Secrets), TOML:
   `GROQ_API_KEY = "…"` and `GEMINI_API_KEY = "…"` — the deployed app runs in
   cloud LLM mode (no `LLM_MODE` set): Groq screens/extracts, Gemini explains,
   with cross-provider fallback. The four demo scenarios are pre-cached and
   spend no quota.
4. Deploy. First boot takes a few minutes (pip install + 600 MB artifact
   download), then the app is live at the URL you chose.

If the host is memory-tight (MuRIL wants ~1 GB on top of torch), set the
secret/env `USE_MURIL = "0"` — the app degrades exactly as designed: the LLM
screens all candidate pairs instead of the local model.

## Notes for other hosts

Any box with `python -m pip install -r requirements.txt` +
`streamlit run app/streamlit_app.py` works the same way; requirements are
pinned to the artifact-compatible versions (chromadb index schema,
e5 embedding reproducibility, MuRIL checkpoint loading). Fully-local mode
(zero API keys, needs ~8 GB RAM + Ollama): set `LLM_MODE=ollama` in `.env`.
