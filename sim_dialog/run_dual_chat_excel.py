from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

try:
    from memobase import MemoBaseClient
except ModuleNotFoundError:  # pragma: no cover - environment dependent
    MemoBaseClient = None  # type: ignore[assignment]


REQUIRED_MODEL_KEYS = ("base_url", "api_key", "model")
ASSISTANT_TOOL_CALL_ACK = "好的"
MEMOBASE_PROJECT_URL = "http://localhost:8019"
MEMOBASE_API_KEY = "secret"
MEMOBASE_USER_ID = "399a319a-5f82-4783-8199-fd5f49661c91"
PROMPT_ATTR_BINDINGS: dict[str, str] = {
    "deepseek_user": "DEEPSEEK_PROMPT_BOY",
    "doubao_assistant": "ASSISTANT_PROMPT_ACTIVE",
}
PROMPT_SOURCE_KEYS = (
    "system_prompt",
    "system_prompt_lines",
    "system_prompt_file",
    "system_prompt_attr",
)
MEMOBASE_CONTEXT_PARAMS: dict[str, Any] = {
    "max_token_size": 1024,
    "profile_event_ratio": 0.6,
    "full_profile_and_only_search_event": True,
    "event_similarity_threshold": 0.5,
    "require_event_summary": False,
    "customize_context_prompt": "## 用户经历的事件[{event_section}]",
    "fill_window_with_events": True,
}


@dataclass(frozen=True)
class ReplyResult:
    text: str
    is_tool_call: bool = False


try:
    import config11 as config11_module
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import config11 as config11_module


def parse_args() -> argparse.Namespace:
    default_config = Path(__file__).resolve().parent / "dialog_config.py"
    parser = argparse.ArgumentParser(
        description="Generate dual-model chat (DeepSeek=user, Doubao=assistant) and export Excel."
    )
    parser.add_argument(
        "--config",
        default=str(default_config),
        help=f"Path to Python config file (.py). Default: {default_config}",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output .xlsx file path. Default: outputs/dual_chat_<timestamp>.xlsx",
    )
    parser.add_argument(
        "--print-live",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Print each generated message line in real time. Use --no-print-live to disable.",
    )
    return parser.parse_args()


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    if path.suffix.lower() != ".py":
        raise ValueError(f"Invalid config file type: only .py is supported. Got: {path}")

    module_name = f"_sim_dialog_config_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load config module: {path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to execute config module: {path} ({exc})") from exc

    config = getattr(module, "CONFIG", None)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid config module: missing or invalid 'CONFIG' dict in {path}")
    return config


def _apply_prompt_attr_bindings(config: dict[str, Any], config_path: Path) -> dict[str, Any]:
    config_file = str(config_path)
    for section_name, prompt_attr in PROMPT_ATTR_BINDINGS.items():
        section = config.get(section_name)
        if not isinstance(section, dict):
            continue
        for key in PROMPT_SOURCE_KEYS:
            section.pop(key, None)
        section["system_prompt_file"] = config_file
        section["system_prompt_attr"] = prompt_attr
    return config


def _require_non_empty_str(container: dict[str, Any], key: str, section: str) -> str:
    value = container.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid '{section}.{key}' (non-empty string required).")
    return value


def _validate_optional_model_keys(section_name: str, model_cfg: dict[str, Any]) -> None:
    if "temperature" in model_cfg:
        temperature = model_cfg["temperature"]
        if not isinstance(temperature, (int, float)):
            raise ValueError(f"Invalid '{section_name}.temperature': number required.")
    if "max_tokens" in model_cfg:
        max_tokens = model_cfg["max_tokens"]
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError(f"Invalid '{section_name}.max_tokens': positive int required.")


def _normalize_thinking_control(section_name: str, model_cfg: dict[str, Any]) -> dict[str, Any]:
    raw = model_cfg.get("thinking_control")
    if raw is None:
        return {"enabled": False, "payload": {}}
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid '{section_name}.thinking_control' (object required).")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"Invalid '{section_name}.thinking_control.enabled' (bool required).")

    payload = raw.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid '{section_name}.thinking_control.payload' (object required).")

    return {
        "enabled": enabled,
        "payload": payload,
    }


def _deep_merge_dict(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_prompt_attr_from_py(prompt_path: Path, prompt_attr: str, section_name: str) -> str:
    module_name = f"_sim_dialog_prompt_{section_name}_{abs(hash(str(prompt_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, str(prompt_path))
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load prompt module for '{section_name}': {prompt_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"Failed to execute prompt module for '{section_name}': {prompt_path} ({exc})"
        ) from exc

    active_prompt = getattr(module, prompt_attr, None)
    if not isinstance(active_prompt, str) or not active_prompt.strip():
        raise ValueError(
            f"Invalid prompt attr '{prompt_attr}' for '{section_name}' in module: {prompt_path}. "
            "Prompt attr must be a non-empty string."
        )
    return active_prompt


def _resolve_system_prompt(section_name: str, model_cfg: dict[str, Any], config_dir: Path) -> str:
    has_prompt_str = "system_prompt" in model_cfg
    has_prompt_lines = "system_prompt_lines" in model_cfg
    has_prompt_file = "system_prompt_file" in model_cfg
    source_count = sum((has_prompt_str, has_prompt_lines, has_prompt_file))

    if source_count == 0:
        raise ValueError(
            f"Missing prompt source in '{section_name}'. "
            "Use one of: system_prompt / system_prompt_lines / system_prompt_file."
        )
    if source_count > 1:
        raise ValueError(
            f"Conflicting prompt sources in '{section_name}'. "
            "Only one of system_prompt / system_prompt_lines / system_prompt_file is allowed."
        )

    if has_prompt_str:
        prompt = model_cfg.get("system_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError(f"Invalid '{section_name}.system_prompt' (non-empty string required).")
        return prompt

    if has_prompt_lines:
        lines_or_text = model_cfg.get("system_prompt_lines")
        if isinstance(lines_or_text, str):
            prompt = lines_or_text
        elif isinstance(lines_or_text, list) and lines_or_text:
            for idx, line in enumerate(lines_or_text, start=1):
                if not isinstance(line, str):
                    raise ValueError(f"Invalid '{section_name}.system_prompt_lines[{idx}]' (string required).")
            prompt = "\n".join(lines_or_text)
        else:
            raise ValueError(
                f"Invalid '{section_name}.system_prompt_lines' "
                "(non-empty string or non-empty string list required)."
            )
        if not prompt.strip():
            raise ValueError(f"Invalid '{section_name}.system_prompt_lines' (content cannot be empty).")
        return prompt

    prompt_file = model_cfg.get("system_prompt_file")
    if not isinstance(prompt_file, str) or not prompt_file.strip():
        raise ValueError(f"Invalid '{section_name}.system_prompt_file' (non-empty string required).")
    prompt_path = Path(prompt_file).expanduser()
    if not prompt_path.is_absolute():
        prompt_path = (config_dir / prompt_path).resolve()
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    if prompt_path.suffix.lower() != ".py":
        raise ValueError(
            f"Invalid '{section_name}.system_prompt_file': only .py is supported. Got: {prompt_path}"
        )
    prompt_attr = model_cfg.get("system_prompt_attr")
    if not isinstance(prompt_attr, str) or not prompt_attr.strip():
        raise ValueError(
            f"Invalid '{section_name}.system_prompt_attr' (non-empty string required when using system_prompt_file)."
        )
    return _load_prompt_attr_from_py(prompt_path, prompt_attr.strip(), section_name)


def _normalize_model_cfg(section_name: str, model_cfg: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    normalized = {
        "base_url": model_cfg["base_url"],
        "api_key": model_cfg["api_key"],
        "model": model_cfg["model"],
        "system_prompt": _resolve_system_prompt(section_name, model_cfg, config_dir),
        "thinking_control": _normalize_thinking_control(section_name, model_cfg),
    }
    if "temperature" in model_cfg:
        normalized["temperature"] = model_cfg["temperature"]
    if "max_tokens" in model_cfg:
        normalized["max_tokens"] = model_cfg["max_tokens"]
    return normalized


def _normalize_desc_name_list(raw_cfg: dict[str, Any], key: str) -> list[str]:
    values = raw_cfg.get(key, [])
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError(f"Invalid 'function_call.{key}' (string list required).")
    out: list[str] = []
    for idx, value in enumerate(values, start=1):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid 'function_call.{key}[{idx}]' (non-empty string required).")
        out.append(value.strip())
    return out


def _collect_config11_function_descriptors() -> dict[str, dict[str, Any]]:
    desc_map: dict[str, dict[str, Any]] = {}
    for var_name, value in vars(config11_module).items():
        if not isinstance(value, dict):
            continue
        if value.get("type") != "function":
            continue
        fn = value.get("function")
        if not isinstance(fn, dict):
            continue
        fn_name = fn.get("name")
        if not isinstance(fn_name, str) or not fn_name.strip():
            continue
        desc_map[var_name] = value
    return desc_map


def _load_config11_tools_by_desc_names(
    *,
    tool_desc_names: list[str],
    deduplicate_by_name: bool,
) -> list[dict[str, Any]]:
    if not tool_desc_names:
        raise ValueError("function_call.tools_config11_descs is required when function_call.enabled=true.")

    desc_map = _collect_config11_function_descriptors()
    missing = [name for name in tool_desc_names if name not in desc_map]
    if missing:
        available = ", ".join(sorted(desc_map.keys()))
        raise ValueError(
            "Unknown config11 tool descriptor(s): "
            + ", ".join(missing)
            + f". Available: {available}"
        )

    selected: list[dict[str, Any]] = [desc_map[name] for name in tool_desc_names]
    if not deduplicate_by_name:
        return selected

    seen_names: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for desc_name, tool in zip(tool_desc_names, selected):
        fn_name = ((tool.get("function") or {}).get("name") or "").strip()
        if fn_name in seen_names:
            print(
                f"[WARN] Duplicate function name ignored: {fn_name} ({desc_name})",
                file=sys.stderr,
            )
            continue
        seen_names.add(fn_name)
        deduped.append(tool)
    return deduped


def _normalize_function_call_cfg(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("function_call")
    if raw is None:
        return {
            "enabled": False,
            "source": "config11",
            "apply_to": "assistant",
            "tool_choice": None,
            "deduplicate_by_name": True,
            "tools_config11_descs": [],
            "tools": [],
        }
    if not isinstance(raw, dict):
        raise ValueError("Invalid 'function_call' (object required).")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("Invalid 'function_call.enabled' (bool required).")

    source = raw.get("source", "config11")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Invalid 'function_call.source' (non-empty string required).")
    source = source.strip()
    if source != "config11":
        raise ValueError("Only 'function_call.source = config11' is supported.")

    apply_to = raw.get("apply_to", "assistant")
    if apply_to not in {"assistant", "user", "both"}:
        raise ValueError("Invalid 'function_call.apply_to' (assistant/user/both).")

    tool_choice = raw.get("tool_choice", None)
    if tool_choice is not None and not isinstance(tool_choice, (str, dict)):
        raise ValueError("Invalid 'function_call.tool_choice' (string/object/null).")

    deduplicate_by_name = raw.get("deduplicate_by_name", True)
    if not isinstance(deduplicate_by_name, bool):
        raise ValueError("Invalid 'function_call.deduplicate_by_name' (bool required).")

    tools_config11_descs = _normalize_desc_name_list(raw, "tools_config11_descs")

    tools: list[dict[str, Any]] = []
    if enabled:
        tools = _load_config11_tools_by_desc_names(
            deduplicate_by_name=deduplicate_by_name,
            tool_desc_names=tools_config11_descs,
        )
        if not tools:
            raise ValueError("function_call.enabled=true but no tools loaded from config11.")

    return {
        "enabled": enabled,
        "source": source,
        "apply_to": apply_to,
        "tool_choice": tool_choice,
        "deduplicate_by_name": deduplicate_by_name,
        "tools_config11_descs": tools_config11_descs,
        "tools": tools,
    }


def validate_and_normalize_config(config: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("Config root must be an object.")

    dialog = config.get("dialog")
    if not isinstance(dialog, dict):
        raise ValueError("Missing or invalid 'dialog' object.")

    if "total_messages" in dialog:
        raise ValueError(
            "Deprecated config: 'dialog.total_messages' is no longer supported. "
            "Use 'dialog.loop_count' and 'dialog.rounds_per_loop' instead."
        )

    loop_count = dialog.get("loop_count")
    if not isinstance(loop_count, int) or loop_count <= 0:
        raise ValueError("Missing or invalid 'dialog.loop_count' (positive int required).")

    rounds_per_loop = dialog.get("rounds_per_loop")
    if not isinstance(rounds_per_loop, int) or rounds_per_loop <= 0:
        raise ValueError("Missing or invalid 'dialog.rounds_per_loop' (positive int required).")

    opening_user = dialog.get("opening_user")
    if not isinstance(opening_user, str) or not opening_user.strip():
        raise ValueError("Missing or invalid 'dialog.opening_user' (non-empty string required).")

    request_timeout_sec = dialog.get("request_timeout_sec")
    if not isinstance(request_timeout_sec, (int, float)) or request_timeout_sec <= 0:
        raise ValueError("Missing or invalid 'dialog.request_timeout_sec' (positive number required).")

    retry_times = dialog.get("retry_times")
    if not isinstance(retry_times, int) or retry_times <= 0:
        raise ValueError("Missing or invalid 'dialog.retry_times' (positive int required).")

    retry_backoff_sec = dialog.get("retry_backoff_sec")
    if not isinstance(retry_backoff_sec, (int, float)) or retry_backoff_sec <= 0:
        raise ValueError("Missing or invalid 'dialog.retry_backoff_sec' (positive number required).")

    worksheet_name = dialog.get("worksheet_name", "dialog_jsonl")
    if not isinstance(worksheet_name, str) or not worksheet_name.strip():
        raise ValueError("Invalid 'dialog.worksheet_name' (non-empty string required).")

    context_window_raw = dialog.get("context_window")
    if context_window_raw is None:
        context_window_enabled = True
        context_window_messages = 20
    else:
        if not isinstance(context_window_raw, dict):
            raise ValueError("Invalid 'dialog.context_window' (object required).")
        context_window_enabled = context_window_raw.get("enabled", True)
        if not isinstance(context_window_enabled, bool):
            raise ValueError("Invalid 'dialog.context_window.enabled' (bool required).")
        context_window_messages = context_window_raw.get("window_messages", 20)
        if not isinstance(context_window_messages, int) or context_window_messages <= 0:
            raise ValueError("Invalid 'dialog.context_window.window_messages' (positive int required).")

    deepseek_user = config.get("deepseek_user")
    doubao_assistant = config.get("doubao_assistant")
    if not isinstance(deepseek_user, dict):
        raise ValueError("Missing or invalid 'deepseek_user' object.")
    if not isinstance(doubao_assistant, dict):
        raise ValueError("Missing or invalid 'doubao_assistant' object.")

    for key in REQUIRED_MODEL_KEYS:
        _require_non_empty_str(deepseek_user, key, "deepseek_user")
        _require_non_empty_str(doubao_assistant, key, "doubao_assistant")

    _validate_optional_model_keys("deepseek_user", deepseek_user)
    _validate_optional_model_keys("doubao_assistant", doubao_assistant)
    deepseek_user_normalized = _normalize_model_cfg("deepseek_user", deepseek_user, config_dir)
    doubao_assistant_normalized = _normalize_model_cfg("doubao_assistant", doubao_assistant, config_dir)
    function_call_cfg = _normalize_function_call_cfg(config)

    memobase_raw = config.get("memobase", {})
    if memobase_raw is None:
        memobase_raw = {}
    if not isinstance(memobase_raw, dict):
        raise ValueError("Invalid 'memobase' (object required).")
    memobase_enabled = memobase_raw.get("enabled", True)
    if not isinstance(memobase_enabled, bool):
        raise ValueError("Invalid 'memobase.enabled' (bool required).")

    return {
        "dialog": {
            "loop_count": loop_count,
            "rounds_per_loop": rounds_per_loop,
            "opening_user": opening_user.strip(),
            "request_timeout_sec": float(request_timeout_sec),
            "retry_times": retry_times,
            "retry_backoff_sec": float(retry_backoff_sec),
            "worksheet_name": worksheet_name.strip(),
            "context_window": {
                "enabled": context_window_enabled,
                "window_messages": context_window_messages,
            },
        },
        "deepseek_user": deepseek_user_normalized,
        "doubao_assistant": doubao_assistant_normalized,
        "function_call": function_call_cfg,
        "memobase": {
            "enabled": memobase_enabled,
        },
    }


def build_client(model_cfg: dict[str, Any], timeout_sec: float) -> OpenAI:
    return OpenAI(
        api_key=model_cfg["api_key"],
        base_url=model_cfg["base_url"],
        timeout=timeout_sec,
    )


def build_memobase_user() -> Any | None:
    if MemoBaseClient is None:
        print("[WARN] memobase is not installed, fallback to empty user_event.", file=sys.stderr)
        return None
    try:
        client = MemoBaseClient(
            project_url=MEMOBASE_PROJECT_URL,
            api_key=MEMOBASE_API_KEY,
        )
        return client.get_user(MEMOBASE_USER_ID)
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Memobase init failed, fallback to empty user_event: {exc}", file=sys.stderr)
        return None


def fetch_user_event_with_retry(
    *,
    memobase_user: Any | None,
    user_text: str,
    retries: int,
    backoff_sec: float,
) -> str:
    if memobase_user is None:
        return ""
    query = user_text.strip()
    if not query:
        return ""

    last_exc: Exception | None = None
    chats = [{"role": "user", "content": query}]
    for attempt in range(1, retries + 1):
        try:
            result = memobase_user.context(chats=chats, **MEMOBASE_CONTEXT_PARAMS)
            if isinstance(result, str):
                return result.strip()
            if result is None:
                return ""
            return str(result).strip()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                print(
                    f"[WARN] memobase event query attempt={attempt}/{retries} failed: {exc}",
                    file=sys.stderr,
                )
                time.sleep(backoff_sec * attempt)

    print(f"[WARN] memobase event query failed after retries: {last_exc}", file=sys.stderr)
    return ""


def build_assistant_prompted_history(history: list[dict[str, str]], user_event: str) -> list[dict[str, str]]:
    if not history:
        raise RuntimeError("Cannot generate assistant reply without history.")
    last_msg = history[-1]
    if last_msg.get("role") != "user":
        raise RuntimeError("Assistant turn expects the latest history item to be a user message.")
    user_text = (last_msg.get("content") or "").strip()
    packed_content = f"用户经历的事件:\n{user_event}\n\n用户当前输入:\n{user_text}"
    packed_last = {"role": "user", "content": packed_content}
    return [*history[:-1], packed_last]


def apply_history_window(
    history: list[dict[str, str]],
    *,
    enabled: bool,
    window_messages: int,
) -> list[dict[str, str]]:
    if not enabled:
        return history
    if len(history) <= window_messages:
        return history
    return history[-window_messages:]


def apply_history_window_with_flags(
    history: list[dict[str, str]],
    tool_call_flags: list[bool],
    *,
    enabled: bool,
    window_messages: int,
) -> tuple[list[dict[str, str]], list[bool]]:
    if len(history) != len(tool_call_flags):
        raise RuntimeError(
            f"History/tool_call_flags length mismatch: history={len(history)}, flags={len(tool_call_flags)}."
        )
    if not enabled:
        return history, tool_call_flags
    if len(history) <= window_messages:
        return history, tool_call_flags
    return history[-window_messages:], tool_call_flags[-window_messages:]


def map_history_for_deepseek(history: list[dict[str, str]]) -> list[dict[str, str]]:
    mapped: list[dict[str, str]] = []
    for msg in history:
        if msg["role"] == "user":
            mapped_role = "assistant"
        elif msg["role"] == "assistant":
            mapped_role = "user"
        else:
            raise ValueError(f"Unexpected role in history: {msg['role']}")
        mapped.append({"role": mapped_role, "content": msg["content"]})
    return mapped


def build_history_for_user_view(
    history: list[dict[str, str]],
    tool_call_flags: list[bool],
    ack_text: str = ASSISTANT_TOOL_CALL_ACK,
) -> list[dict[str, str]]:
    if len(history) != len(tool_call_flags):
        raise RuntimeError(
            f"History/tool_call_flags length mismatch: history={len(history)}, flags={len(tool_call_flags)}."
        )

    visible_history: list[dict[str, str]] = []
    for msg, is_tool_call in zip(history, tool_call_flags):
        role = msg.get("role")
        content = msg.get("content", "")
        if role == "assistant" and is_tool_call:
            visible_history.append({"role": "assistant", "content": ack_text})
            continue
        visible_history.append({"role": str(role), "content": str(content)})
    return visible_history


def extract_text_content(response: Any) -> ReplyResult:
    message = response.choices[0].message

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        rendered: list[str] = []
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            fn_name = getattr(fn, "name", "unknown_function")
            fn_args = getattr(fn, "arguments", "")
            rendered.append(f"tool_name={fn_name}; args={fn_args}".strip())
        # When a tool is called, content should be the tool name and parameters.
        merged = " | ".join(rendered).strip()
        if merged:
            return ReplyResult(text=merged, is_tool_call=True)
        return ReplyResult(text="[EMPTY_TOOL_CALL]", is_tool_call=True)

    content = message.content
    if isinstance(content, str):
        return ReplyResult(text=content.strip(), is_tool_call=False)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        merged = "\n".join(parts).strip()
        if merged:
            return ReplyResult(text=merged, is_tool_call=False)

    refusal = getattr(message, "refusal", None)
    if isinstance(refusal, str) and refusal.strip():
        return ReplyResult(text=refusal.strip(), is_tool_call=False)
    return ReplyResult(text="", is_tool_call=False)


def create_reply_once(
    *,
    client: OpenAI,
    model_cfg: dict[str, Any],
    history: list[dict[str, str]],
    mapped: bool,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any | None = None,
) -> ReplyResult:
    msg_history = map_history_for_deepseek(history) if mapped else history
    messages: list[dict[str, str]] = [{"role": "system", "content": model_cfg["system_prompt"]}]
    messages.extend(msg_history)

    req: dict[str, Any] = {
        "model": model_cfg["model"],
        "messages": messages,
    }
    if "temperature" in model_cfg:
        req["temperature"] = model_cfg["temperature"]
    if "max_tokens" in model_cfg:
        req["max_tokens"] = model_cfg["max_tokens"]
    thinking_control = model_cfg.get("thinking_control", {})
    if isinstance(thinking_control, dict) and thinking_control.get("enabled"):
        payload = thinking_control.get("payload", {})
        if isinstance(payload, dict) and payload:
            base_extra = req.get("extra_body", {})
            if not isinstance(base_extra, dict):
                base_extra = {}
            req["extra_body"] = _deep_merge_dict(base_extra, payload)
    if tools:
        req["tools"] = tools
        if tool_choice is not None:
            req["tool_choice"] = tool_choice

    response = client.chat.completions.create(**req)
    reply = extract_text_content(response)
    if not reply.text:
        finish_reason = getattr(response.choices[0], "finish_reason", "unknown")
        return ReplyResult(text=f"[EMPTY_RESPONSE finish_reason={finish_reason}]", is_tool_call=False)
    return reply


def create_reply_with_retry(
    *,
    client: OpenAI,
    model_cfg: dict[str, Any],
    history: list[dict[str, str]],
    mapped: bool,
    retries: int,
    backoff_sec: float,
    turn: int,
    role: str,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any | None = None,
) -> ReplyResult:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return create_reply_once(
                client=client,
                model_cfg=model_cfg,
                history=history,
                mapped=mapped,
                tools=tools,
                tool_choice=tool_choice,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < retries:
                print(
                    f"[WARN] turn={turn} role={role} attempt={attempt}/{retries} failed: {exc}",
                    file=sys.stderr,
                )
                time.sleep(backoff_sec * attempt)
            else:
                break
    raise RuntimeError(f"Failed at turn={turn} role={role} after retries: {last_exc}") from last_exc


def validate_generated_history(history: list[dict[str, str]], expected_messages: int) -> None:
    if len(history) != expected_messages:
        raise RuntimeError(f"Generated {len(history)} messages, expected {expected_messages}.")

    user_count = 0
    assistant_count = 0
    for idx, msg in enumerate(history, start=1):
        expected_role = "user" if idx % 2 == 1 else "assistant"
        role = msg.get("role")
        content = msg.get("content")
        if role != expected_role:
            raise RuntimeError(f"Role order mismatch at line {idx}: expected {expected_role}, got {role}.")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"Empty content at line {idx}.")
        if role == "user":
            user_count += 1
        else:
            assistant_count += 1

    expected_user_count = (expected_messages + 1) // 2
    expected_assistant_count = expected_messages // 2
    if user_count != expected_user_count or assistant_count != expected_assistant_count:
        raise RuntimeError(
            "Role counts mismatch: "
            f"expected user={expected_user_count}, assistant={expected_assistant_count}; "
            f"got user={user_count}, assistant={assistant_count}."
        )


def default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(__file__).resolve().parent.parent / "outputs" / f"dual_chat_{stamp}.xlsx"


def write_excel_lines(
    output_path: Path,
    sheet_name: str,
    session_ids: list[int],
    lines: list[str],
    user_events: list[str],
) -> None:
    if len(session_ids) != len(lines) or len(lines) != len(user_events):
        raise RuntimeError(
            "Excel column length mismatch: "
            f"session_id={len(session_ids)}, json_line={len(lines)}, user_event={len(user_events)}."
        )

    try:
        import pandas as pd  # type: ignore

        df = pd.DataFrame({"session_id": session_ids, "json_line": lines, "user_event": user_events})
        df.to_excel(output_path, sheet_name=sheet_name, index=False)
        return
    except ModuleNotFoundError:
        pass

    try:
        from openpyxl import Workbook  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Missing dependency: install pandas/openpyxl via 'uv sync' "
            "and run via 'uv run ...'."
        ) from exc

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(["session_id", "json_line", "user_event"])
    for session_id, line, user_event in zip(session_ids, lines, user_events):
        ws.append([session_id, line, user_event])
    wb.save(output_path)


def main() -> int:
    args = parse_args()
    try:
        config_path = Path(args.config).expanduser().resolve()
        loaded_config = load_config(config_path)
        bound_config = _apply_prompt_attr_bindings(loaded_config, config_path)
        config = validate_and_normalize_config(bound_config, config_path.parent)
        dialog_cfg = config["dialog"]
        loop_count: int = dialog_cfg["loop_count"]
        rounds_per_loop: int = dialog_cfg["rounds_per_loop"]

        output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        deepseek_cfg = config["deepseek_user"]
        doubao_cfg = config["doubao_assistant"]
        function_call_cfg = config["function_call"]
        memobase_cfg = config["memobase"]

        timeout_sec = dialog_cfg["request_timeout_sec"]
        deepseek_client = build_client(deepseek_cfg, timeout_sec)
        doubao_client = build_client(doubao_cfg, timeout_sec)
        memobase_enabled = memobase_cfg["enabled"]
        memobase_user = build_memobase_user() if memobase_enabled else None
        assistant_use_event_packaging = memobase_enabled
        if not memobase_enabled:
            print("[INFO] memobase is disabled by config.")
            print("[INFO] assistant event packaging is disabled with memobase.")

        retry_times = dialog_cfg["retry_times"]
        backoff_sec = dialog_cfg["retry_backoff_sec"]
        context_window_cfg = dialog_cfg["context_window"]
        context_window_enabled: bool = context_window_cfg["enabled"]
        context_window_messages: int = context_window_cfg["window_messages"]
        if context_window_enabled:
            print(f"[INFO] context window enabled: {context_window_messages} messages")
        else:
            print("[INFO] context window disabled: full history will be used.")

        session_ids: list[int] = []
        lines: list[str] = []
        user_events: list[str] = []

        enabled = function_call_cfg["enabled"]
        apply_to = function_call_cfg["apply_to"]
        tools = function_call_cfg["tools"]
        tool_choice = function_call_cfg["tool_choice"]
        if enabled:
            tool_count = len(tools)
            print(f"[INFO] function_call enabled: source=config11, apply_to={apply_to}, tools={tool_count}")
            print(
                "[INFO] selected config11 descriptors: "
                + ", ".join(function_call_cfg["tools_config11_descs"])
            )
            print(
                "[INFO] enabled function names: "
                + ", ".join([(t.get("function") or {}).get("name", "unknown") for t in tools])
            )

        print(
            f"[INFO] loop sessions={loop_count}, rounds_per_loop={rounds_per_loop}, "
            f"model_calls={loop_count * rounds_per_loop}"
        )

        for session_id in range(1, loop_count + 1):
            history: list[dict[str, str]] = []
            tool_call_flags: list[bool] = []
            session_lines: list[str] = []
            session_user_events: list[str] = []

            first_msg = {"role": "user", "content": dialog_cfg["opening_user"]}
            history.append(first_msg)
            tool_call_flags.append(False)
            first_line = json.dumps(first_msg, ensure_ascii=False)
            session_lines.append(first_line)
            first_user_event = fetch_user_event_with_retry(
                memobase_user=memobase_user,
                user_text=first_msg["content"],
                retries=retry_times,
                backoff_sec=backoff_sec,
            )
            session_user_events.append(first_user_event)
            if args.print_live:
                print(f"[S{session_id}] {first_line}")

            for round_idx in range(1, rounds_per_loop + 1):
                if len(history) != len(tool_call_flags):
                    raise RuntimeError(
                        f"History/tool_call_flags length mismatch at session={session_id}, round={round_idx}: "
                        f"history={len(history)}, flags={len(tool_call_flags)}."
                    )

                call_idx = (session_id - 1) * rounds_per_loop + round_idx

                if round_idx % 2 == 1:
                    role = "assistant"
                    assistant_tools = tools if enabled and apply_to in {"assistant", "both"} else None
                    if len(session_lines) != len(session_user_events):
                        raise RuntimeError(
                            f"Record length mismatch before assistant at session={session_id}, round={round_idx}: "
                            f"json_line={len(session_lines)}, user_event={len(session_user_events)}."
                        )
                    assistant_source_history = apply_history_window(
                        history,
                        enabled=context_window_enabled,
                        window_messages=context_window_messages,
                    )
                    if assistant_use_event_packaging:
                        assistant_history = build_assistant_prompted_history(
                            assistant_source_history, session_user_events[-1]
                        )
                    else:
                        assistant_history = assistant_source_history
                    if args.print_live:
                        print(f"[GEN] session={session_id} round={round_idx} role={role} generating...", flush=True)
                    reply_result = create_reply_with_retry(
                        client=doubao_client,
                        model_cfg=doubao_cfg,
                        history=assistant_history,
                        mapped=False,
                        retries=retry_times,
                        backoff_sec=backoff_sec,
                        turn=call_idx,
                        role=role,
                        tools=assistant_tools,
                        tool_choice=tool_choice if assistant_tools else None,
                    )
                else:
                    role = "user"
                    user_tools = tools if enabled and apply_to in {"user", "both"} else None
                    user_window_history, user_window_flags = apply_history_window_with_flags(
                        history,
                        tool_call_flags,
                        enabled=context_window_enabled,
                        window_messages=context_window_messages,
                    )
                    user_visible_history = build_history_for_user_view(user_window_history, user_window_flags)
                    if args.print_live:
                        print(f"[GEN] session={session_id} round={round_idx} role={role} generating...", flush=True)
                    reply_result = create_reply_with_retry(
                        client=deepseek_client,
                        model_cfg=deepseek_cfg,
                        history=user_visible_history,
                        mapped=True,
                        retries=retry_times,
                        backoff_sec=backoff_sec,
                        turn=call_idx,
                        role=role,
                        tools=user_tools,
                        tool_choice=tool_choice if user_tools else None,
                    )

                record = {"role": role, "content": reply_result.text.strip()}
                history.append(record)
                tool_call_flags.append(role == "assistant" and reply_result.is_tool_call)
                line = json.dumps(record, ensure_ascii=False)
                session_lines.append(line)
                if role == "user":
                    user_event = fetch_user_event_with_retry(
                        memobase_user=memobase_user,
                        user_text=record["content"],
                        retries=retry_times,
                        backoff_sec=backoff_sec,
                    )
                    session_user_events.append(user_event)
                else:
                    session_user_events.append("")
                if args.print_live:
                    print(f"[S{session_id}] {line}")

            validate_generated_history(history, rounds_per_loop + 1)

            if len(session_lines) != len(session_user_events):
                raise RuntimeError(
                    f"Session row length mismatch at session={session_id}: "
                    f"json_line={len(session_lines)}, user_event={len(session_user_events)}."
                )

            session_ids.extend([session_id] * len(session_lines))
            lines.extend(session_lines)
            user_events.extend(session_user_events)

        sheet_name = dialog_cfg["worksheet_name"]
        write_excel_lines(output_path, sheet_name, session_ids, lines, user_events)

        print(f"[INFO] Wrote Excel: {output_path}")
        print(f"[INFO] Sheet: {sheet_name}, sessions: {loop_count}, rows: {len(lines)}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
