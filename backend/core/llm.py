"""
LLM Router
===========
Supports two providers:
  - OpenAI API  (gpt-4o, gpt-4o-mini) — cloud, fast, requires API key
  - Ollama      (llama3.2:3b)          — local, free, requires Ollama running

Cloud alternatives to Ollama (OpenAI-compatible APIs):
  - Groq        (groq.com)      — free tier, runs Llama 3.2 3B at 800 tokens/sec
  - Together AI (together.ai)   — pay-per-token, many open source models
  - Fireworks AI (fireworks.ai) — fast inference, Llama 3.2 3B supported
  - Replicate   (replicate.com) — pay-per-second, easy setup
  All of these expose an OpenAI-compatible API — just change OLLAMA_BASE_URL
  to their endpoint and set the appropriate API key.
"""

import os
import logging
from backend.core.config import env
from typing import Optional
import openai

log = logging.getLogger("transitbot.llm")

# ── Model definitions ──────────────────────────────────────────────────────────

OPENAI_MODELS = {
    "gpt-4o":        {"name": "GPT-4o",      "provider": "openai"},
    "gpt-4o-mini":   {"name": "GPT-4o mini", "provider": "openai"},
}

OLLAMA_MODELS = {
    "llama3.2:3b":   {"name": "Llama 3.2 3B (local)", "provider": "ollama"},
}

ALL_MODELS = {**OPENAI_MODELS, **OLLAMA_MODELS}

# ── Clients ────────────────────────────────────────────────────────────────────

_openai_client: Optional[openai.AsyncOpenAI] = None
_ollama_client: Optional[openai.AsyncOpenAI] = None


def get_openai_client() -> openai.AsyncOpenAI:
    global _openai_client
    if not _openai_client:
        key = env("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        _openai_client = openai.AsyncOpenAI(api_key=key)
    return _openai_client


def get_ollama_client() -> openai.AsyncOpenAI:
    global _ollama_client
    if not _ollama_client:
        base_url = env("OLLAMA_BASE_URL") or "http://host.docker.internal:11434/v1"
        _ollama_client = openai.AsyncOpenAI(base_url=base_url, api_key="ollama")
    return _ollama_client


# ── Router ─────────────────────────────────────────────────────────────────────

def _is_openai(model: str) -> bool:
    return model in OPENAI_MODELS or model.startswith("gpt") or model.startswith("o1") or model.startswith("o3")


def _is_ollama(model: str) -> bool:
    return model in OLLAMA_MODELS or model.startswith("llama") or model.startswith("mistral") or model.startswith("phi")


def _clean_response(text: str) -> str:
    """Strip role-play artifacts that small local models sometimes add."""
    import re
    # "Response: ..." pattern from TinyLlama / small models
    m = re.search(r'Response:\s*["\']?(.*?)["\']?\s*$', text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    # Strip "Assistant:" prefix
    text = re.sub(r'^(Assistant|Bot|TransitBot)\s*:\s*', '', text, flags=re.IGNORECASE).strip()
    return text


async def generate(
    system: str,
    messages: list[dict],
    model: str = "gpt-4o-mini",
    max_tokens: int = 1000,
) -> str:
    """
    Single entry point for all LLM calls.
    Routes to OpenAI or Ollama based on model name.
    """
    log.info("LLM generate: model=%s messages=%d", model, len(messages))

    all_messages = [{"role": "system", "content": system}] + messages

    try:
        if _is_openai(model):
            client = get_openai_client()
            response = await client.chat.completions.create(
                model=model,
                messages=all_messages,
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()

        elif _is_ollama(model):
            client = get_ollama_client()

            # Shorter system prompt for small models
            if "3b" in model.lower() or "1b" in model.lower():
                system_trimmed = system[:1200]
                all_messages = [{"role": "system", "content": system_trimmed}] + messages
                max_tokens = min(max_tokens, 400)

            response = await client.chat.completions.create(
                model=model,
                messages=all_messages,
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return _clean_response(response.choices[0].message.content.strip())

        else:
            raise ValueError(f"Unknown model: {model}. Use gpt-4o, gpt-4o-mini, or llama3.2:3b")

    except openai.AuthenticationError:
        raise RuntimeError("Invalid OpenAI API key. Check your OPENAI_API_KEY in .env")
    except openai.RateLimitError:
        raise RuntimeError("OpenAI rate limit reached. Try again in a moment.")
    except Exception as e:
        log.error("LLM error model=%s: %s", model, e)
        raise


def get_model_info(model: str) -> dict:
    """Return display info for a model."""
    return ALL_MODELS.get(model, {"name": model, "provider": "unknown"})


def is_openai_available() -> bool:
    return bool(env("OPENAI_API_KEY"))


def is_ollama_available() -> bool:
    """Quick check if Ollama is reachable."""
    import httpx
    try:
        base = env("OLLAMA_BASE_URL") or "http://host.docker.internal:11434/v1"
        r = httpx.get(base.replace("/v1", ""), timeout=2)
        return r.status_code == 200
    except Exception:
        return False
