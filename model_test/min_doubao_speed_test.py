from __future__ import annotations

import importlib.util
import statistics
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

# -----------------------------
# Minimal benchmark configuration
# -----------------------------
RUNS_PER_MODEL = 5
PROMPT = "请用一句话介绍人工智能。"
REQUEST_TIMEOUT_SEC = 90.0
TEMPERATURE = 0.1
MAX_TOKENS = 64
DISABLE_THINKING_PAYLOAD: dict[str, Any] = {"enable_thinking": False}

MODELS = [
    ("doubao-1.5-pro-32k", "doubao-1-5-pro-32k-250115"),
    ("doubao-2.0-lite", "doubao-seed-2-0-lite-260215"),
]


def load_doubao_credentials_from_dialog_config() -> tuple[str, str]:
    config_path = Path(__file__).resolve().parent / "dialog_config.py"
    spec = importlib.util.spec_from_file_location("_dialog_config_for_speed_test", str(config_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load config module: {config_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    config = getattr(module, "CONFIG", None)
    if not isinstance(config, dict):
        raise RuntimeError("Invalid CONFIG in dialog_config.py")

    doubao_cfg = config.get("doubao_assistant")
    if not isinstance(doubao_cfg, dict):
        raise RuntimeError("Missing CONFIG['doubao_assistant']")

    base_url = doubao_cfg.get("base_url")
    api_key = doubao_cfg.get("api_key")
    if not isinstance(base_url, str) or not base_url.strip():
        raise RuntimeError("Invalid doubao_assistant.base_url")
    if not isinstance(api_key, str) or not api_key.strip():
        raise RuntimeError("Invalid doubao_assistant.api_key")
    return base_url.strip(), api_key.strip()


def percentile_nearest_rank(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        raise ValueError("empty values")
    idx = int(round((len(sorted_values) - 1) * p))
    idx = max(0, min(len(sorted_values) - 1, idx))
    return sorted_values[idx]


def run_non_stream_once(client: OpenAI, model_id: str) -> tuple[float, int]:
    t0 = time.perf_counter()
    resp = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": PROMPT}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        extra_body=DISABLE_THINKING_PAYLOAD,
    )
    total_s = time.perf_counter() - t0
    text = (resp.choices[0].message.content or "").strip()
    return total_s, len(text)


def run_stream_once(client: OpenAI, model_id: str) -> tuple[float | None, float, int]:
    start = time.perf_counter()
    first_output_time: float | None = None
    parts: list[str] = []
    stream = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": PROMPT}],
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        extra_body=DISABLE_THINKING_PAYLOAD,
        stream=True,
    )
    try:
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            content_piece = getattr(delta, "content", None)
            reasoning_piece = getattr(delta, "reasoning_content", None)
            tool_calls = getattr(delta, "tool_calls", None)
            if first_output_time is None and (content_piece or reasoning_piece or tool_calls):
                first_output_time = time.perf_counter()

            if content_piece:
                parts.append(str(content_piece))
    finally:
        if hasattr(stream, "close"):
            stream.close()

    end = time.perf_counter()
    ttft_s = (first_output_time - start) if first_output_time is not None else None
    total_s = end - start
    output_chars = len("".join(parts).strip())
    return ttft_s, total_s, output_chars


def print_summary(
    *,
    mode_name: str,
    totals: dict[str, list[float]],
    ttfts: dict[str, list[float]] | None,
    errors: dict[str, list[str]],
) -> None:
    print(f"--- summary ({mode_name}) ---")
    for alias, _ in MODELS:
        total_vals = totals[alias]
        errs = errors[alias]
        print(f"model={alias} success={len(total_vals)}/{RUNS_PER_MODEL} errors={len(errs)}")
        if total_vals:
            total_sorted = sorted(total_vals)
            print(
                "  "
                + f"total_mean={statistics.mean(total_vals):.3f}s "
                + f"total_p50={statistics.median(total_sorted):.3f}s "
                + f"total_p90={percentile_nearest_rank(total_sorted, 0.9):.3f}s "
                + f"total_min={min(total_vals):.3f}s total_max={max(total_vals):.3f}s"
            )
        if ttfts is not None and ttfts[alias]:
            ttft_vals = ttfts[alias]
            ttft_sorted = sorted(ttft_vals)
            print(
                "  "
                + f"ttft_mean={statistics.mean(ttft_vals):.3f}s "
                + f"ttft_p50={statistics.median(ttft_sorted):.3f}s "
                + f"ttft_p90={percentile_nearest_rank(ttft_sorted, 0.9):.3f}s "
                + f"ttft_min={min(ttft_vals):.3f}s ttft_max={max(ttft_vals):.3f}s"
            )
        if errs:
            print("  sample_error=" + errs[0])


def run_non_stream_benchmark(client: OpenAI) -> None:
    print("--- per call (non-stream total latency) ---")
    totals: dict[str, list[float]] = {alias: [] for alias, _ in MODELS}
    errors: dict[str, list[str]] = {alias: [] for alias, _ in MODELS}

    for run_idx in range(1, RUNS_PER_MODEL + 1):
        for alias, model_id in MODELS:
            try:
                total_s, output_chars = run_non_stream_once(client, model_id)
                totals[alias].append(total_s)
                print(
                    f"run={run_idx} model={alias} total_s={total_s:.3f} "
                    f"output_chars={output_chars}"
                )
            except Exception as exc:  # noqa: BLE001
                errors[alias].append(str(exc))
                print(f"run={run_idx} model={alias} ERROR: {exc}")

    print_summary(mode_name="non-stream", totals=totals, ttfts=None, errors=errors)


def run_stream_benchmark(client: OpenAI) -> None:
    print("--- per call (stream ttft + total latency) ---")
    totals: dict[str, list[float]] = {alias: [] for alias, _ in MODELS}
    ttfts: dict[str, list[float]] = {alias: [] for alias, _ in MODELS}
    errors: dict[str, list[str]] = {alias: [] for alias, _ in MODELS}

    for run_idx in range(1, RUNS_PER_MODEL + 1):
        for alias, model_id in MODELS:
            try:
                ttft_s, total_s, output_chars = run_stream_once(client, model_id)
                totals[alias].append(total_s)
                if ttft_s is not None:
                    ttfts[alias].append(ttft_s)
                    ttft_text = f"{ttft_s:.3f}"
                else:
                    ttft_text = "None"
                print(
                    f"run={run_idx} model={alias} ttft_s={ttft_text} "
                    f"total_s={total_s:.3f} output_chars={output_chars}"
                )
            except Exception as exc:  # noqa: BLE001
                errors[alias].append(str(exc))
                print(f"run={run_idx} model={alias} ERROR: {exc}")

    print_summary(mode_name="stream", totals=totals, ttfts=ttfts, errors=errors)


def main() -> int:
    base_url, api_key = load_doubao_credentials_from_dialog_config()
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=REQUEST_TIMEOUT_SEC)

    print(f"base_url={base_url}")
    print(f"runs_per_model={RUNS_PER_MODEL}")
    print(f"prompt={PROMPT}")

    run_non_stream_benchmark(client)
    run_stream_benchmark(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
