"""conversation-variables 接口封装与对话提示词拼装。

历史上这个模块负责「A/B 摆放固定五轮话术」，改造后 A/B 的提示词正文都搬到了
``config.py``，这里只保留三件事：

1. 调 ``conversation-variables`` 拿到本轮 10 个变量；
2. 用变量把对话提示词模板里的 ``{{占位符}}`` 填掉；
3. 为每个 variant 算一个提示词指纹，方便在报表里区分不同版本。
"""

from __future__ import annotations

import hashlib

import httpx


PILLOW_VARIABLES_API = "http://10.10.10.24:8500/pillow/remote/device/conversation-variables"
PILLOW_API_HEADERS = {"Crknife-Internal-Call": "true", "Accept-Language": "zh-CN"}
PILLOW_API_TIMEOUT = 8.0

# 模板里必须全部存在的占位符，顺序与接口返回无关。
PILLOW_VAR_KEYS: tuple[str, ...] = (
    "worldview",
    "story",
    "memory_chapter",
    "event_section",
    "profile_section",
    "weather",
    "Volume",
    "charging_status",
    "special_scenarios",
    "battery_notification",
)


def fetch_pillow_variables(sn: str, user_input: str) -> dict | None:
    """取本轮对话变量；任何失败都返回 ``None``，由调用方降级为原文发送。"""
    try:
        response = httpx.post(
            PILLOW_VARIABLES_API,
            headers=PILLOW_API_HEADERS,
            json={"sn": sn, "userInput": user_input},
            timeout=PILLOW_API_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - 网络/解析失败一律降级
        print(f"[提示词] 变量接口调用失败：{type(exc).__name__}: {exc}", flush=True)
        return None
    if not isinstance(data, dict):
        print(f"[提示词] 变量接口返回格式异常（{type(data).__name__}）", flush=True)
        return None
    return data


def fill_pillow_prompt(template: str, variables: dict, user_input: str) -> str:
    """把变量逐键填进模板，末尾接上用户原话。"""
    text = template
    for key in PILLOW_VAR_KEYS:
        value = variables.get(key, "")
        if value is None:
            value = ""
        text = text.replace("{{" + key + "}}", str(value))
    return text.rstrip() + "\n" + user_input


def prompt_hash(variant_prompts: dict[str, str]) -> str:
    """对系统提示词 + 对话提示词求指纹，A/B 各自独立。"""
    material = (
        variant_prompts["system_prompt"]
        + "\n---DIALOG---\n"
        + variant_prompts["dialog_prompt"]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
