#!/usr/bin/env python3
from __future__ import annotations
"""url2markdown.py — Convert URL content to Markdown via Lightpanda + ReaderLM.

Workflow:
1. Use lightpanda to fetch HTML from URL (with --dump html)
2. Use local LLM API (jinaai-ReaderLM-v2) to convert HTML to Markdown

Configuration is loaded from scripts/wiki_config.yaml (readerlm section).
Copy scripts/wiki_config.yaml.example to scripts/wiki_config.yaml and edit.
Command-line flags override config file values.

Usage:
    python scripts/url2markdown.py <url> [--output file.md]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_config() -> dict:
    """Load configuration from wiki_config.yaml, returning defaults if missing."""
    config_path = Path(__file__).parent / "wiki_config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


CONFIG = _load_config()
READERLM = CONFIG.get("readerlm", {})

LLM_API_BASE = READERLM.get("api_base", os.environ.get("READERLM_API_BASE", "http://127.0.0.1:12345"))
LLM_MODEL = READERLM.get("model", os.environ.get("READERLM_MODEL", "jinaai-ReaderLM-v2"))


def _get_api_key() -> str:
    """Resolve API key: config file → env var → error."""
    key = READERLM.get("api_key") or os.environ.get("READERLM_API_KEY")
    if not key:
        raise RuntimeError(
            "API key not configured. Set readerlm.api_key in scripts/wiki_config.yaml "
            "or set READERLM_API_KEY environment variable."
        )
    return key


def fetch_html_with_lightpanda(url: str, timeout: int = 30000) -> str:
    """Fetch HTML from URL using lightpanda browser.

    Uses lightpanda fetch --dump html to render the page and dump HTML to stdout.

    Args:
        url: The URL to fetch
        timeout: Timeout in milliseconds (converted to seconds for subprocess)

    Returns:
        HTML content as string

    Raises:
        RuntimeError: If lightpanda is not found or fails
    """
    lightpanda_path = shutil.which("lightpanda")
    if not lightpanda_path:
        raise RuntimeError(
            "lightpanda not found. Install from: https://lightpanda.io/docs/open-source/installation"
        )

    # Convert timeout from ms to seconds for subprocess
    timeout_sec = timeout / 1000

    cmd = [
        lightpanda_path,
        "fetch",
        "--dump", "html",
        "--wait-ms", str(timeout),
        "--wait-until", "done",
        url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 30,  # Give subprocess extra time
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"lightpanda failed: {error_msg}")
        return result.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"lightpanda timed out after {timeout_sec}s")
    except Exception as e:
        raise RuntimeError(f"lightpanda error: {e}")


def html_to_markdown_via_llm(
    html: str,
    api_base: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Convert HTML to Markdown using local LLM API (ReaderLM-v2).

    Uses OpenAI-compatible chat completion API.

    Args:
        html: Raw HTML content
        api_base: LLM API base URL
        api_key: API key for authentication
        model: Model name to use

    Returns:
        Markdown content

    Raises:
        RuntimeError: If API call fails
    """
    if not html or not html.strip():
        raise RuntimeError("Empty HTML content provided")

    api_base = api_base or LLM_API_BASE
    api_key = api_key or _get_api_key()
    model = model or LLM_MODEL

    # Prepare the API request
    system_prompt = (
        "You are a precise HTML to Markdown converter. "
        "Convert the provided HTML content to clean, well-formatted Markdown. "
        "Preserve all meaningful content including headings, paragraphs, lists, "
        "tables, links, and images. Remove navigation, ads, and boilerplate. "
        "Output ONLY the markdown content without any explanations."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": html},
        ],
        "temperature": 0.1,
        "max_tokens": 8192,
    }

    url = f"{api_base}/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("API returned no choices")

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("API returned empty content")

        return content.strip()

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(f"API HTTP error {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"API connection error: {e.reason}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"API response parse error: {e}")
    except Exception as e:
        raise RuntimeError(f"API error: {e}")


def url_to_markdown(
    url: str,
    timeout: int = 30000,
    api_base: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """Full pipeline: URL → HTML → Markdown.

    Args:
        url: The URL to process
        timeout: Timeout for lightpanda in milliseconds
        api_base: LLM API base URL
        api_key: API key for authentication
        model: Model name to use

    Returns:
        Markdown content
    """
    print(f"Fetching HTML from: {url}", file=sys.stderr)
    html = fetch_html_with_lightpanda(url, timeout=timeout)
    print(f"Fetched {len(html)} characters of HTML", file=sys.stderr)

    print("Converting HTML to Markdown via ReaderLM...", file=sys.stderr)
    markdown = html_to_markdown_via_llm(html, api_base=api_base, api_key=api_key, model=model)
    print(f"Generated {len(markdown)} characters of Markdown", file=sys.stderr)

    return markdown


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert URL content to Markdown using lightpanda + ReaderLM"
    )
    parser.add_argument("url", help="URL to fetch and convert")
    parser.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30000,
        help="Timeout for lightpanda in milliseconds (default: 30000)"
    )
    parser.add_argument(
        "--api-base",
        default=None,
        help="LLM API base URL (from config or env if omitted)"
    )
    parser.add_argument(
        "--model",
        default=LLM_MODEL,
        help=f"LLM model name (default: {LLM_MODEL})"
    )

    args = parser.parse_args()

    try:
        markdown = url_to_markdown(
            args.url,
            timeout=args.timeout,
            api_base=args.api_base,
            api_key=None,
            model=args.model,
        )

        if args.output:
            os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(markdown)
            print(f"Markdown written to: {args.output}", file=sys.stderr)
        else:
            print(markdown)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    _main()
