from __future__ import annotations

import copy
import json
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from config11 import (
    Ali_API_KEY,
    Ali_API_URL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_API_URL,
    GLM_API_KEY,
    GLM_API_URL,
)

# -----------------------------
# Fixed benchmark configuration
# -----------------------------
TEST_PROMPT = "Explain the role of AI in one sentence."
RUNS_PER_MODEL = 10
REQUEST_TIMEOUT_SEC = 90.0
RETRY_TIMES = 3
RETRY_BACKOFF_SEC = 1.5
DISABLE_THINKING = True

MODEL_BENCHMARKS: list[dict[str, Any]] = [
    # {
    #     "alias": "GLM-4.7-Flash",
    #     "provider": "glm",
    #     "model": "GLM-4.7-Flash",
    #     "params": {
    #         "temperature": 0.1,
    #         "max_tokens": 256,
    #         "top_p": 0.9,
    #     },
    #     "disable_thinking_payload": {"thinking": {"type": "disabled"}},
    # },
    {
        "alias": "deepseek-chat",
        "provider": "deepseek",
        "model": "deepseek-chat",
        "params": {
            "temperature": 0.1,
            "max_tokens": 256,
            "top_p": 0.9,
        },
        "disable_thinking_payload": {"enable_thinking": False},
    },
    {
        "alias": "qwen3.5-flash",
        "provider": "ali",
        "model": "qwen3.5-flash",
        "params": {
            "temperature": 0.1,
            "max_tokens": 256,
            "top_p": 0.9,
        },
        "disable_thinking_payload": {"enable_thinking": False},
    },
]

PROVIDER_CREDENTIALS: dict[str, dict[str, str]] = {
    "glm": {"api_key": GLM_API_KEY, "base_url": GLM_API_URL},
    "deepseek": {"api_key": DEEPSEEK_API_KEY, "base_url": DEEPSEEK_API_URL},
    "ali": {"api_key": Ali_API_KEY, "base_url": Ali_API_URL},
}

RAW_COLUMNS = [
    "executed_at",
    "provider",
    "alias",
    "model",
    "run_index",
    "attempt_count",
    "retries_used",
    "status",
    "ttft_ms",
    "total_ms",
    "output_chars",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cache_tokens",
    "error_message",
    "request_params",
    "disable_thinking_payload",
]

SUMMARY_COLUMNS = [
    "provider",
    "alias",
    "model",
    "total_runs",
    "success_runs",
    "failed_runs",
    "success_rate_pct",
    "ttft_mean_ms",
    "ttft_p50_ms",
    "ttft_p90_ms",
    "ttft_min_ms",
    "ttft_max_ms",
    "total_mean_ms",
    "total_p50_ms",
    "total_p90_ms",
    "total_min_ms",
    "total_max_ms",
]

RAW_HEADERS_ZH = {
    "executed_at": "执行时间",
    "provider": "服务商",
    "alias": "模型别名",
    "model": "模型ID",
    "run_index": "运行序号",
    "attempt_count": "尝试次数",
    "retries_used": "重试次数",
    "status": "状态",
    "ttft_ms": "首包耗时(ms)",
    "total_ms": "总耗时(ms)",
    "output_chars": "输出字符数",
    "prompt_tokens": "输入Token",
    "completion_tokens": "输出Token",
    "total_tokens": "总Token",
    "cache_tokens": "缓存Token",
    "error_message": "错误信息",
    "request_params": "请求参数",
    "disable_thinking_payload": "关闭思考参数",
}

SUMMARY_HEADERS_ZH = {
    "provider": "服务商",
    "alias": "模型别名",
    "model": "模型ID",
    "total_runs": "总运行次数",
    "success_runs": "成功次数",
    "failed_runs": "失败次数",
    "success_rate_pct": "成功率(%)",
    "ttft_mean_ms": "首包均值(ms)",
    "ttft_p50_ms": "首包P50(ms)",
    "ttft_p90_ms": "首包P90(ms)",
    "ttft_min_ms": "首包最小值(ms)",
    "ttft_max_ms": "首包最大值(ms)",
    "total_mean_ms": "总耗时均值(ms)",
    "total_p50_ms": "总耗时P50(ms)",
    "total_p90_ms": "总耗时P90(ms)",
    "total_min_ms": "总耗时最小值(ms)",
    "total_max_ms": "总耗时最大值(ms)",
}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _default_output_path() -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parent / "outputs" / f"model_latency_{ts}.xlsx"


def _deep_merge_dict(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_dict(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _create_clients() -> dict[str, OpenAI]:
    clients: dict[str, OpenAI] = {}
    for provider, cred in PROVIDER_CREDENTIALS.items():
        clients[provider] = OpenAI(
            api_key=cred["api_key"],
            base_url=cred["base_url"],
            timeout=REQUEST_TIMEOUT_SEC,
        )
    return clients


def _validate_model_cfg(model_cfg: dict[str, Any]) -> None:
    for key in ("alias", "provider", "model"):
        value = model_cfg.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid model config field: {key}")
    provider = model_cfg["provider"].strip()
    if provider not in PROVIDER_CREDENTIALS:
        raise ValueError(f"Unknown provider: {provider}")
    params = model_cfg.get("params", {})
    if not isinstance(params, dict):
        raise ValueError(f"Invalid params for model: {model_cfg['alias']}")


def _build_request(model_cfg: dict[str, Any]) -> dict[str, Any]:
    params = copy.deepcopy(model_cfg.get("params", {}))
    messages: list[dict[str, str]] = []
    system_prompt = model_cfg.get("system_prompt")
    if isinstance(system_prompt, str) and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": TEST_PROMPT})
    request: dict[str, Any] = {
        "model": model_cfg["model"],
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    request.update(params)

    if DISABLE_THINKING:
        payload = model_cfg.get("disable_thinking_payload")
        if isinstance(payload, dict) and payload:
            existing = request.get("extra_body")
            if isinstance(existing, dict):
                request["extra_body"] = _deep_merge_dict(existing, payload)
            else:
                request["extra_body"] = copy.deepcopy(payload)

    return request


def _token_usage_to_dict(usage: Any) -> dict[str, int | None]:
    cache_tokens = None
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cache_tokens = getattr(details, "cached_tokens", None)
    return {
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "cache_tokens": cache_tokens,
    }


def _run_once(client: OpenAI, model_cfg: dict[str, Any], run_index: int) -> dict[str, Any]:
    request = _build_request(model_cfg)

    start = time.perf_counter()
    first_chunk_time: float | None = None
    token_usage: dict[str, int | None] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "cache_tokens": None,
    }
    content_parts: list[str] = []
    stream = None
    error_message: str | None = None

    try:
        stream = client.chat.completions.create(**request)
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                token_usage = _token_usage_to_dict(usage)

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = getattr(choices[0], "delta", None)
            if delta is None:
                continue

            content_piece = getattr(delta, "content", None)
            reasoning_piece = getattr(delta, "reasoning_content", None)
            tool_calls = getattr(delta, "tool_calls", None)

            has_first_output = (
                bool(content_piece)
                or bool(reasoning_piece)
                or bool(tool_calls)
            )
            if has_first_output and first_chunk_time is None:
                first_chunk_time = time.perf_counter()

            if content_piece:
                content_parts.append(str(content_piece))

            if tool_calls:
                for tool_call in tool_calls:
                    fn = getattr(tool_call, "function", None)
                    fn_name = getattr(fn, "name", None)
                    fn_args = getattr(fn, "arguments", None)
                    if fn_name:
                        content_parts.append(f"[tool:{fn_name}]")
                    if fn_args:
                        content_parts.append(str(fn_args))

    except Exception as exc:  # noqa: BLE001
        error_message = str(exc)
    finally:
        if stream is not None and hasattr(stream, "close"):
            stream.close()

    end = time.perf_counter()
    ttft_ms = (first_chunk_time - start) * 1000 if first_chunk_time is not None else None
    total_ms = (end - start) * 1000
    output_text = "".join(content_parts).strip()

    base_record: dict[str, Any] = {
        "executed_at": _now_text(),
        "provider": model_cfg["provider"],
        "alias": model_cfg["alias"],
        "model": model_cfg["model"],
        "run_index": run_index,
        "ttft_ms": round(ttft_ms, 3) if ttft_ms is not None else None,
        "total_ms": round(total_ms, 3),
        "output_chars": len(output_text),
        "prompt_tokens": token_usage["prompt_tokens"],
        "completion_tokens": token_usage["completion_tokens"],
        "total_tokens": token_usage["total_tokens"],
        "cache_tokens": token_usage["cache_tokens"],
        "error_message": error_message or "",
        "request_params": json.dumps(model_cfg.get("params", {}), ensure_ascii=False),
        "disable_thinking_payload": json.dumps(
            model_cfg.get("disable_thinking_payload", None),
            ensure_ascii=False,
        ),
    }
    if error_message:
        base_record["status"] = "failed"
    else:
        base_record["status"] = "success"

    return base_record


def _run_with_retry(client: OpenAI, model_cfg: dict[str, Any], run_index: int) -> dict[str, Any]:
    last_record: dict[str, Any] | None = None
    for attempt in range(1, RETRY_TIMES + 1):
        record = _run_once(client, model_cfg, run_index)
        record["attempt_count"] = attempt
        record["retries_used"] = attempt - 1
        last_record = record

        if record["status"] == "success":
            return record

        if attempt < RETRY_TIMES:
            wait_s = RETRY_BACKOFF_SEC * attempt
            print(
                f"[WARN] model={model_cfg['alias']} run={run_index} "
                f"attempt={attempt}/{RETRY_TIMES} failed: {record['error_message']}"
            )
            time.sleep(wait_s)

    if last_record is None:
        raise RuntimeError(f"Unexpected retry state for model={model_cfg['alias']} run={run_index}")
    return last_record


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    index = (len(ordered) - 1) * ratio
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _round_or_none(value: float | None) -> float | None:
    return round(value, 3) if value is not None else None


def _latency_stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {
            "mean": None,
            "p50": None,
            "p90": None,
            "min": None,
            "max": None,
        }
    mean_value = sum(values) / len(values)
    return {
        "mean": _round_or_none(mean_value),
        "p50": _round_or_none(_percentile(values, 0.50)),
        "p90": _round_or_none(_percentile(values, 0.90)),
        "min": _round_or_none(min(values)),
        "max": _round_or_none(max(values)),
    }


def _build_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (record["provider"], record["alias"], record["model"])
        grouped[key].append(record)

    summary_rows: list[dict[str, Any]] = []
    for (provider, alias, model), group in grouped.items():
        success = [r for r in group if r["status"] == "success"]
        failed = [r for r in group if r["status"] != "success"]

        ttft_values = [
            float(r["ttft_ms"])
            for r in success
            if isinstance(r.get("ttft_ms"), (float, int))
        ]
        total_values = [
            float(r["total_ms"])
            for r in success
            if isinstance(r.get("total_ms"), (float, int))
        ]
        ttft_stats = _latency_stats(ttft_values)
        total_stats = _latency_stats(total_values)

        total_runs = len(group)
        success_runs = len(success)
        failed_runs = len(failed)
        success_rate_pct = (success_runs / total_runs * 100.0) if total_runs > 0 else 0.0

        summary_rows.append(
            {
                "provider": provider,
                "alias": alias,
                "model": model,
                "total_runs": total_runs,
                "success_runs": success_runs,
                "failed_runs": failed_runs,
                "success_rate_pct": round(success_rate_pct, 2),
                "ttft_mean_ms": ttft_stats["mean"],
                "ttft_p50_ms": ttft_stats["p50"],
                "ttft_p90_ms": ttft_stats["p90"],
                "ttft_min_ms": ttft_stats["min"],
                "ttft_max_ms": ttft_stats["max"],
                "total_mean_ms": total_stats["mean"],
                "total_p50_ms": total_stats["p50"],
                "total_p90_ms": total_stats["p90"],
                "total_min_ms": total_stats["min"],
                "total_max_ms": total_stats["max"],
            }
        )

    summary_rows.sort(key=lambda x: (x["provider"], x["alias"], x["model"]))
    return summary_rows


def _write_excel(output_path: Path, raw_rows: list[dict[str, Any]], summary_rows: list[dict[str, Any]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import pandas as pd  # type: ignore

        raw_df = pd.DataFrame(raw_rows, columns=RAW_COLUMNS).rename(columns=RAW_HEADERS_ZH)
        summary_df = pd.DataFrame(summary_rows, columns=SUMMARY_COLUMNS).rename(columns=SUMMARY_HEADERS_ZH)
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            raw_df.to_excel(writer, sheet_name="raw", index=False)
            summary_df.to_excel(writer, sheet_name="summary", index=False)
        return
    except ModuleNotFoundError:
        pass

    try:
        from openpyxl import Workbook  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("Missing dependencies: install pandas or openpyxl first.") from exc

    workbook = Workbook()
    ws_raw = workbook.active
    ws_raw.title = "raw"
    ws_raw.append([RAW_HEADERS_ZH[col] for col in RAW_COLUMNS])
    for row in raw_rows:
        ws_raw.append([row.get(col) for col in RAW_COLUMNS])

    ws_summary = workbook.create_sheet("summary")
    ws_summary.append([SUMMARY_HEADERS_ZH[col] for col in SUMMARY_COLUMNS])
    for row in summary_rows:
        ws_summary.append([row.get(col) for col in SUMMARY_COLUMNS])

    workbook.save(output_path)


def main() -> int:
    print("[INFO] model latency benchmark started.")
    print(f"[INFO] prompt={TEST_PROMPT}")
    print(f"[INFO] runs_per_model={RUNS_PER_MODEL}, retry_times={RETRY_TIMES}")
    print(f"[INFO] disable_thinking={DISABLE_THINKING}")

    clients = _create_clients()
    raw_rows: list[dict[str, Any]] = []
    total_tasks = len(MODEL_BENCHMARKS) * RUNS_PER_MODEL
    finished = 0

    for model_cfg in MODEL_BENCHMARKS:
        _validate_model_cfg(model_cfg)
        provider = model_cfg["provider"]
        alias = model_cfg["alias"]
        model = model_cfg["model"]
        print(f"[INFO] benchmark model start: alias={alias}, provider={provider}, model={model}")

        client = clients[provider]
        for run_index in range(1, RUNS_PER_MODEL + 1):
            finished += 1
            print(f"[RUN] {finished}/{total_tasks} alias={alias} run={run_index}/{RUNS_PER_MODEL}")

            row = _run_with_retry(client, model_cfg, run_index)
            raw_rows.append(row)

            if row["status"] == "success":
                print(
                    f"[OK] alias={alias} run={run_index} "
                    f"ttft_ms={row['ttft_ms']} total_ms={row['total_ms']}"
                )
            else:
                print(
                    f"[FAIL] alias={alias} run={run_index} "
                    f"error={row['error_message']}"
                )

    summary_rows = _build_summary(raw_rows)
    output_path = _default_output_path()
    _write_excel(output_path, raw_rows, summary_rows)

    print(f"[INFO] excel written: {output_path}")
    print(f"[INFO] raw rows={len(raw_rows)}, summary rows={len(summary_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
