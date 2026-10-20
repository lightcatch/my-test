# -*- coding: utf-8 -*-
"""豆包 AUC Flash HTTP 同步 ASR 识别器 (非流式)。

对应火山引擎接口:
  Resource ID = volc.bigasr.auc_turbo
  Model = bigmodel
  Endpoint = https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash

- wav 文件 base64 -> POST 一次 -> HTTP 同步返回完整转写文本
- 单条延迟通常 500ms - 2s (含网络 + 服务端推理)
- name="doubao_asr", display_name="Doubao_AUC_Flash", is_local_gpu=False (可并发)
"""

from __future__ import annotations

import sys as _config_sys
from pathlib import Path as _ConfigPath

_CONFIG_ROOT = str(_ConfigPath(__file__).resolve().parents[3])
if _CONFIG_ROOT not in _config_sys.path:
    _config_sys.path.insert(0, _CONFIG_ROOT)
import config11 as _local_config  # 本机密钥由 .gitignore 排除。


import base64
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from .base import BaseRecognizer, RecognitionResult


APP_ID = _local_config.ASR_FLASH_APP_ID
ACCESS_TOKEN = _local_config.ASR_FLASH_ACCESS_TOKEN
RESOURCE_ID = "volc.bigasr.auc_turbo"
MODEL_NAME = "bigmodel"
RECOGNIZE_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash"

TEXT_KEYS = {"text", "transcript", "sentence", "utterance", "result_text", "final_text"}


def _collect_texts(payload: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in TEXT_KEYS and isinstance(value, str):
                t = value.strip()
                if t:
                    texts.append(t)
            else:
                texts.extend(_collect_texts(value))
    elif isinstance(payload, list):
        for item in payload:
            texts.extend(_collect_texts(item))
    return texts


def _extract_transcript(payload: Any) -> str:
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            t = result.get("text")
            if isinstance(t, str) and t.strip():
                return t.strip()
            utterances = result.get("utterances")
            if isinstance(utterances, list):
                parts = [
                    it.get("text", "").strip() for it in utterances
                    if isinstance(it, dict) and isinstance(it.get("text"), str) and it.get("text", "").strip()
                ]
                if parts:
                    return "".join(parts)
        if isinstance(result, list):
            parts = [
                it.get("text", "").strip() for it in result
                if isinstance(it, dict) and isinstance(it.get("text"), str) and it.get("text", "").strip()
            ]
            if parts:
                return "".join(parts)
    return "".join(_collect_texts(payload)).strip()


class DoubaoASRRecognizer(BaseRecognizer):
    """豆包 AUC Flash HTTP 同步 ASR (非流式)。"""

    name = "doubao_asr"
    display_name = "Doubao_AUC_Flash"
    is_local_gpu = False  # 云端 HTTP 接口, 可以并发

    def __init__(
        self,
        appid: str = APP_ID,
        token: str = ACCESS_TOKEN,
        timeout: int = 90,
        enable_itn: bool = True,
        enable_punc: bool = True,
        enable_ddc: bool = True,
    ) -> None:
        self.appid = appid
        self.token = token
        self.timeout = timeout
        self.enable_itn = enable_itn
        self.enable_punc = enable_punc
        self.enable_ddc = enable_ddc
        self._session: requests.Session | None = None

    def setup(self) -> None:
        if self._session is None:
            self._session = requests.Session()

    def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
        if self._session is None:
            self.setup()
        started = time.perf_counter()
        try:
            wav = Path(audio_path)
            if not wav.exists():
                raise FileNotFoundError(audio_path)
            b64 = base64.b64encode(wav.read_bytes()).decode("utf-8")

            headers = {
                "X-Api-App-Key": self.appid,
                "X-Api-Access-Key": self.token,
                "X-Api-Resource-Id": RESOURCE_ID,
                "X-Api-Request-Id": str(uuid.uuid4()),
                "X-Api-Sequence": "-1",
            }
            body = {
                "user": {"uid": self.appid},
                "audio": {"data": b64},
                "request": {
                    "model_name": MODEL_NAME,
                    "enable_itn": self.enable_itn,
                    "enable_punc": self.enable_punc,
                    "enable_ddc": self.enable_ddc,
                },
            }
            resp = self._session.post(  # type: ignore[union-attr]
                RECOGNIZE_URL, json=body, headers=headers, timeout=self.timeout
            )
            elapsed = round(time.perf_counter() - started, 2)
            status_code = resp.headers.get("X-Api-Status-Code", "")
            message = resp.headers.get("X-Api-Message", "")
            if status_code != "20000000":
                return RecognitionResult(
                    text="", elapsed_sec=elapsed, status="error",
                    error=f"API status={status_code} message={message}",
                )
            try:
                payload = resp.json()
            except ValueError:
                return RecognitionResult(
                    text="", elapsed_sec=elapsed, status="error",
                    error=f"invalid JSON: {resp.text[:200]}",
                )
            text = _extract_transcript(payload)
            if not text:
                return RecognitionResult(
                    text="", elapsed_sec=elapsed, status="error",
                    error="识别结果为空",
                )
            return RecognitionResult(text=text, elapsed_sec=elapsed)
        except Exception as exc:  # noqa: BLE001
            elapsed = round(time.perf_counter() - started, 2)
            return RecognitionResult(
                text="", elapsed_sec=elapsed, status="error", error=str(exc)
            )
