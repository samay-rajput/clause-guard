"""Dual-provider LLM client: Groq (screening) + Gemini (explanations/generation).

Design rules (from the build plan):
- Disk cache from day one, keyed on sha256(provider|model|temp|prompt).
  The demo video is recorded against a warm cache, so a live API failure can
  never ruin a recording. Cache entries are one JSON file each (parallel-safe).
- Retry with exponential backoff on 429/5xx; cross-provider fallback helper.
- Plain requests, no SDKs (nothing extra to install).
"""
import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "cache" / "llm"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _load_env():
    """Minimal .env loader (no python-dotenv dependency)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()  # must run BEFORE the model constants read os.environ

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
# high-volume, user-facing prose (conflict explanations) rides the lite tier —
# ~4x the free daily quota of full Flash after the Dec-2025 quota cuts
GEMINI_LITE_MODEL = os.environ.get("GEMINI_LITE_MODEL", "gemini-flash-lite-latest")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
# LLM_MODE=ollama routes EVERY call to a local Ollama server (testing without
# API keys); delete the line from .env to switch back to Gemini/Groq. The disk
# cache keys on provider+model, so ollama-era cache never pollutes cloud runs.
LLM_MODE = os.environ.get("LLM_MODE", "cloud").lower()
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")


class LLMError(RuntimeError):
    pass


def _cache_key(provider, model, temperature, prompt):
    h = hashlib.sha256(f"{provider}|{model}|{temperature}|{prompt}".encode()).hexdigest()
    return CACHE_DIR / f"{h[:24]}.json"


def _cached(provider, model, temperature, prompt):
    p = _cache_key(provider, model, temperature, prompt)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))["text"]
        except Exception:
            p.unlink(missing_ok=True)
    return None


def _store(provider, model, temperature, prompt, text):
    p = _cache_key(provider, model, temperature, prompt)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"provider": provider, "model": model, "text": text}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(p)


def _post_with_retry(url, headers, payload, tries=4):
    delay = 5.0
    last = None
    for _ in range(tries):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=120)
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code in (400, 401, 403, 404):
                break  # non-retryable
            if r.status_code == 429 and re.search(r"per\s*day|PerDay", r.text, re.I):
                break  # daily quota won't clear in seconds — retrying burns more of it
            ra = r.headers.get("retry-after")
            if ra:
                try:
                    delay = max(delay, float(ra) + 1)
                except ValueError:
                    pass
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(delay)
        delay *= 2.5
    raise LLMError(last or "unknown error")


def _gemini(prompt, temperature, max_tokens, json_mode, model=None):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY not set (.env)")
    # key travels in the x-goog-api-key header, never the URL — query strings
    # end up in proxy/server logs
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model or GEMINI_MODEL}:generateContent"
    )
    gc = {"temperature": temperature, "maxOutputTokens": max_tokens}
    # Gemini 3 spends output budget on internal thinking; on hard inputs it can
    # exhaust max_tokens before emitting any text — for JSON *and* prose calls.
    # Gemini 3 models take thinkingLevel, not thinkingBudget (that's a 400 now).
    gc["thinkingConfig"] = {"thinkingLevel": "low"}
    if json_mode:
        gc["responseMimeType"] = "application/json"
    data = _post_with_retry(url, {"Content-Type": "application/json",
                                  "x-goog-api-key": key},
                            {"contents": [{"parts": [{"text": prompt}]}],
                             "generationConfig": gc})
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise LLMError(f"gemini: unexpected response shape: {str(data)[:300]}")


def _groq(prompt, temperature, max_tokens, json_mode, model=None,
          json_schema=None):
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise LLMError("GROQ_API_KEY not set (.env)")
    payload = {
        "model": model or GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_schema:
        # schema-GUARANTEED constrained decoding (gpt-oss models only) — the
        # extractor can no longer return a shape the verifier has to regex-slice
        payload["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "extraction", "strict": True, "schema": json_schema}}
    elif json_mode:
        payload["response_format"] = {"type": "json_object"}
    data = _post_with_retry(
        "https://api.groq.com/openai/v1/chat/completions",
        {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        payload,
    )
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        raise LLMError(f"groq: unexpected response shape: {str(data)[:300]}")


def _ollama(prompt, temperature, max_tokens, json_mode):
    # seed pins sampling: temperature 0 alone is NOT reproducible across Ollama
    # runs/hardware paths, and a borderline same_scheme judgment that flips
    # between runs poisons the warmed cache with whichever answer came first
    options = {"temperature": temperature, "num_predict": max_tokens, "seed": 42}
    # CG_OLLAMA_NUM_GPU=0 forces CPU inference — the 4 GB laptop GPU can crash
    # the runner ("terminated: CUDA error") on partial offload of llama3.1
    if (ng := os.environ.get("CG_OLLAMA_NUM_GPU")) is not None:
        try:
            options["num_gpu"] = int(ng)
        except ValueError:
            pass
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": options,
    }
    if json_mode:
        payload["format"] = "json"
    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=600)
        if r.status_code != 200:
            raise LLMError(f"ollama HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["message"]["content"]
    except requests.RequestException as e:
        raise LLMError(f"ollama: {type(e).__name__}: {e}")


def llm(prompt, provider="groq", temperature=0.2, max_tokens=2048,
        json_mode=False, use_cache=True, refresh=False, model=None,
        json_schema=None):
    """refresh=True skips the cache READ but still stores the fresh result —
    use it to overwrite a cached-but-malformed response. `model` overrides the
    provider's default (cache keys on the resolved model). `json_schema` asks
    for schema-guaranteed output where the provider supports it (Groq gpt-oss);
    elsewhere it degrades to plain JSON mode."""
    if LLM_MODE == "ollama":
        provider, model = "ollama", OLLAMA_MODEL
    elif model is None:
        model = GROQ_MODEL if provider == "groq" else GEMINI_MODEL
    if use_cache and not refresh:
        hit = _cached(provider, model, temperature, prompt)
        if hit is not None:
            return hit
    json_mode = json_mode or bool(json_schema)
    if provider == "groq":
        text = _groq(prompt, temperature, max_tokens, json_mode, model=model,
                     json_schema=json_schema)
    elif provider == "gemini":
        text = _gemini(prompt, temperature, max_tokens, json_mode, model=model)
    else:
        text = _ollama(prompt, temperature, max_tokens, json_mode)
    if use_cache:
        _store(provider, model, temperature, prompt, text)
    return text


def llm_with_fallback(prompt, preferred="groq", model=None, json_schema=None, **kw):
    """Try preferred provider; on failure, silently try the other one. The
    model override and strict schema apply to the PREFERRED provider only —
    model IDs are provider-specific and the fallback runs best-effort JSON.
    In ollama mode there is no second provider — the single call is the ball game."""
    if LLM_MODE == "ollama":
        return llm(prompt, json_mode=kw.pop("json_mode", False) or bool(json_schema), **kw)
    other = "gemini" if preferred == "groq" else "groq"
    try:
        return llm(prompt, provider=preferred, model=model,
                   json_schema=json_schema, **kw)
    except LLMError:
        return llm(prompt, provider=other,
                   json_mode=kw.pop("json_mode", False) or bool(json_schema), **kw)


if __name__ == "__main__":
    # M0 gate: one live round-trip per active provider.
    provs = ["ollama"] if LLM_MODE == "ollama" else ["groq", "gemini"]
    for prov in provs:
        try:
            out = llm("Reply with exactly: OK", provider=prov, use_cache=False, max_tokens=1024)
            print(f"{prov}: {out.strip()[:40]!r}")
        except LLMError as e:
            print(f"{prov}: FAILED — {e}")
