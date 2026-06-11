"""Shared LLM utilities — unified API call with retry logic.

Extracted from benchmark_ragas.py retry pattern and deduplicated from
compile_v2.py / query.py call_llm implementations.
"""

import json
import sys
import time

import requests

from config import get_api_url, get_llm_config


def call_llm(
    system_prompt: str,
    user_content: str,
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: int = 120,
    max_retries: int = 3,
) -> str:
    """Call the configured LLM with automatic retry on transient failures.

    Retries with exponential backoff on network errors and 429 rate limits.
    Non-retryable errors (401, 403) raise immediately without retrying.

    Args:
        system_prompt: System-level instruction for the model.
        user_content: User message / document content.
        max_tokens: Override the config default for max output tokens.
        temperature: Override the config default for sampling temperature.
        timeout: Request timeout in seconds (default 120s; typical compile < 60s).
        max_retries: Maximum attempts including the first call (default 3).

    Returns:
        Stripped text content from the LLM response.

    Raises:
        RuntimeError: On auth failure (401/403), exhausted retries, or
                      malformed response structure.
    """
    llm_config = get_llm_config()
    provider = llm_config.get("provider", "deepseek")

    # ── provider-specific payload & headers ──────────────────────────
    if provider == "ollama":
        api_url = f"{llm_config['base_url'].rstrip('/')}/api/chat"
        payload: dict = {
            "model": llm_config.get("model", "llama3.2"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "stream": False,
            "options": {
                "temperature": (
                    temperature
                    if temperature is not None
                    else llm_config.get("temperature", 0.3)
                ),
                "num_ctx": llm_config.get("num_ctx", 32768),
            },
        }
        headers = {"Content-Type": "application/json"}
    elif provider == "custom":
        api_url = get_api_url()
        payload = {
            "model": llm_config.get("model", ""),
            "temperature": (
                temperature
                if temperature is not None
                else llm_config.get("temperature", 0.3)
            ),
            "max_tokens": (
                max_tokens
                if max_tokens is not None
                else llm_config.get("max_tokens", 32000)
            ),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {llm_config.get('api_key', '')}",
        }
    else:
        # deepseek, openai, or any OpenAI-compatible provider
        api_url = get_api_url()
        api_key = llm_config.get("api_key", "")
        if not api_key:
            raise RuntimeError(
                "LLM API key not configured. "
                "Set llm.api_key in wiki_config.yaml or DEEPSEEK_API_KEY env var."
            )
        payload = {
            "model": llm_config.get("model", "deepseek-v4-flash"),
            "temperature": (
                temperature
                if temperature is not None
                else llm_config.get("temperature", 0.3)
            ),
            "max_tokens": (
                max_tokens
                if max_tokens is not None
                else llm_config.get("max_tokens", 32000)
            ),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        if provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    # ── retry loop ───────────────────────────────────────────────────
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                api_url, json=payload, headers=headers, timeout=timeout
            )

            # Rate limit — retry with exponential backoff
            if resp.status_code == 429:
                if attempt < max_retries - 1:
                    wait = min(2**attempt * 3, 30)
                    print(
                        f"LLM rate limited (429), retrying in {wait}s... "
                        f"(attempt {attempt + 1}/{max_retries})",
                        file=sys.stderr,
                    )
                    time.sleep(wait)
                    continue
                raise RuntimeError(
                    f"LLM API rate limited after {max_retries} attempts"
                )

            # Auth errors — do NOT retry (will never succeed)
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    f"LLM API authentication failed ({resp.status_code}). "
                    f"Check your API key in wiki_config.yaml or environment variable."
                )

            resp.raise_for_status()
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"LLM API returned invalid JSON: {e}"
                ) from e

            # Parse provider-specific response
            if provider == "ollama":
                return (
                    data.get("message", {}).get("content", "") or ""
                ).strip()
            else:
                msg = data["choices"][0]["message"]
                return (msg.get("content") or "").strip()

        except RuntimeError:
            raise  # auth errors and other intentional RuntimeErrors

        except (requests.RequestException, OSError) as e:
            if attempt < max_retries - 1:
                wait = min(2**attempt * 2, 15)
                print(
                    f"LLM call attempt {attempt + 1}/{max_retries} failed: {e}, "
                    f"retrying in {wait}s...",
                    file=sys.stderr,
                )
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"LLM API call failed after {max_retries} attempts: {e}"
                ) from e

        except (KeyError, IndexError) as e:
            raise RuntimeError(
                f"Unexpected LLM API response structure: {e}"
            ) from e

    # Should never reach here, but makes type checkers happy
    raise RuntimeError(f"LLM API call failed after {max_retries} attempts")


# ── Model context detection ───────────────────────────────────────────

# Known context windows by model family (tokens). Conservative lower bounds.
_MODEL_CONTEXT_FALLBACK = 131072  # 128K — safe default for most modern models
_MODEL_CONTEXT_MAP: dict[str, int] = {
    # DeepSeek family
    "deepseek-v4": 131072,       # 128K
    "deepseek-v3": 65536,        # 64K
    "deepseek-r1": 131072,       # 128K
    "deepseek-chat": 65536,      # 64K
    "deepseek-coder": 65536,     # 64K
    "deepseek-v2": 131072,       # 128K
    # OpenAI family
    "gpt-4o": 131072,            # 128K
    "gpt-4-turbo": 131072,       # 128K
    "gpt-4": 8192,               # 8K (older)
    "gpt-4-32k": 32768,          # 32K
    "gpt-3.5-turbo": 16384,      # 16K
    "gpt-3.5-turbo-16k": 16384,  # 16K
    "o1": 200000,                # 200K
    "o3": 200000,                # 200K
    # Anthropic family
    "claude": 200000,            # 200K (Sonnet/Opus/Haiku 4+)
    # Meta family
    "llama3.2": 131072,          # 128K
    "llama3.1": 131072,          # 128K
    "llama3": 8192,              # 8K
    "llama2": 4096,              # 4K
    # Qwen family
    "qwen3": 131072,             # 128K
    "qwen2.5": 131072,           # 128K
    "qwen2": 32768,              # 32K
    "qwen": 32768,               # 32K
    # Mistral family
    "mistral-large": 131072,     # 128K
    "mistral-small": 32768,      # 32K
    "mistral": 32768,            # 32K
    "mixtral": 32768,            # 32K
    # Google family
    "gemini-2": 1048576,         # 1M
    "gemini-1.5": 1048576,       # 1M
    "gemini": 32768,             # 32K
    # Yi family
    "yi": 200000,                # 200K
}

# Prompt overhead estimate: system prompt + user prompt template + response headroom
_PROMPT_OVERHEAD_ESTIMATE = 4000  # tokens


def get_model_max_context() -> int:
    """Detect the model's maximum context window (tokens).

    Resolution order:
    1. Explicit ``num_ctx`` in config (Ollama) or ``max_context`` (generic).
    2. Model-name-based heuristic from known context windows.
    3. Fallback: 128K (safe for most modern LLMs).
    """
    llm_config = get_llm_config()
    model_name = llm_config.get("model", "").lower()

    # Explicit config overrides
    if llm_config.get("num_ctx"):
        return int(llm_config["num_ctx"])
    if llm_config.get("max_context"):
        return int(llm_config["max_context"])

    # Match by model family prefix (most specific first)
    for prefix, ctx in sorted(
        _MODEL_CONTEXT_MAP.items(), key=lambda x: -len(x[0])
    ):
        if model_name.startswith(prefix) or prefix in model_name:
            return ctx

    return _MODEL_CONTEXT_FALLBACK


def get_chunk_threshold(override: int | None = None) -> int:
    """Return the token threshold above which documents should be chunked.

    Default: 60% of model max context minus prompt overhead.
    This leaves ~40% for system prompt, user prompt template, and LLM response.

    Args:
        override: If provided, use this absolute token value instead.
    """
    if override is not None and override > 0:
        return override

    max_ctx = get_model_max_context()
    usable = max_ctx - _PROMPT_OVERHEAD_ESTIMATE
    return max(int(usable * 0.6), 4000)  # floor at 4K tokens
