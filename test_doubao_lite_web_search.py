"""Smoke-test Volcengine Ark Responses API web search with Doubao Lite 2.0.

Usage:
    python test_doubao_lite_web_search.py

The script uses ARK_API_KEY or DOUBAO_API_KEY when present.  For compatibility
with this repository's existing model configuration, it otherwise reads
DOUBAO_API_KEY from ``config11.py``.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from openai import OpenAI


DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seed-2-0-lite-260215"
DEFAULT_QUERY = "今天有什么热点新闻？请列出三条，并给出来源和发布时间。"


def _load_api_key() -> str | None:
    api_key = os.getenv("ARK_API_KEY") or os.getenv("DOUBAO_API_KEY")
    if api_key:
        return api_key

    try:
        from config11 import DOUBAO_API_KEY
    except ImportError:
        return None
    return DOUBAO_API_KEY or None


def _dump(value: Any) -> Any:
    """Convert OpenAI SDK models to JSON-compatible values."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _dump(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(v) for v in value]
    if hasattr(value, "model_dump"):
        return _dump(value.model_dump(exclude_none=True))
    if hasattr(value, "to_dict"):
        return _dump(value.to_dict())
    return str(value)


def _text_from_response(response: Any) -> str:
    text = getattr(response, "output_text", None)
    if text:
        return str(text)

    data = _dump(response)
    chunks: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "output_text" and node.get("text"):
                chunks.append(str(node["text"]))
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(data)
    return "".join(chunks)


def _source_urls(response: Any) -> list[str]:
    """Collect citation/source URLs without depending on one SDK version."""
    data = _dump(response)
    urls: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"url", "uri"} and isinstance(value, str) and value.startswith(("http://", "https://")):
                    if value not in urls:
                        urls.append(value)
                visit(value)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(data)
    return urls


def _stream_response(client: OpenAI, model: str, query: str) -> tuple[str, Any]:
    stream = client.responses.create(
        model=model,
        input=query,
        tools=[{"type": "web_search"}],
        stream=True,
    )
    chunks: list[str] = []
    completed: Any = None
    saw_search = False

    for event in stream:
        event_type = getattr(event, "type", "")
        if event_type == "response.output_text.delta":
            delta = getattr(event, "delta", "")
            if delta:
                chunks.append(str(delta))
                print(delta, end="", flush=True)
        elif "web_search" in event_type:
            saw_search = True
        elif event_type == "response.completed":
            completed = getattr(event, "response", None)

    print()
    if not chunks and completed is not None:
        chunks.append(_text_from_response(completed))
    if saw_search:
        print("[web_search] detected", file=sys.stderr)
    return "".join(chunks), completed


def _non_stream_response(client: OpenAI, model: str, query: str) -> tuple[str, Any]:
    response = client.responses.create(
        model=model,
        input=query,
        tools=[{"type": "web_search"}],
    )
    text = _text_from_response(response)
    if text:
        print(text)
    return text, response


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Doubao Lite 2.0 web search via Ark Responses API")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--base-url", default=os.getenv("ARK_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--no-stream", action="store_true", help="Use a regular Responses request")
    args = parser.parse_args()

    api_key = _load_api_key()
    if not api_key:
        print("ERROR: configure ARK_API_KEY, DOUBAO_API_KEY, or config11.DOUBAO_API_KEY", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key, base_url=args.base_url)
    print(f"model: {args.model}")
    print(f"base_url: {args.base_url}")
    print(f"query: {args.query}")
    print("answer:")

    try:
        if args.no_stream:
            text, response = _non_stream_response(client, args.model, args.query)
        else:
            try:
                text, response = _stream_response(client, args.model, args.query)
            except Exception as stream_error:
                print(f"\nstream request failed; retrying non-stream: {stream_error}", file=sys.stderr)
                text, response = _non_stream_response(client, args.model, args.query)
    except Exception as error:
        print(f"ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    if not text.strip():
        print("ERROR: API returned no output text", file=sys.stderr)
        return 1

    response_id = getattr(response, "id", None) if response is not None else None
    print(f"response_id: {response_id or '<unavailable>'}")
    urls = _source_urls(response) if response is not None else []
    print(f"source_count: {len(urls)}")
    for index, url in enumerate(urls, start=1):
        print(f"source_{index}: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
