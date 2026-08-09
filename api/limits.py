"""One shared slowapi limiter. LLM-spending endpoints get tight per-user
limits — the free-tier daily quotas are the resource being protected."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

LLM_LIMIT = "10/minute"       # review / prefill / autodraft / generate
