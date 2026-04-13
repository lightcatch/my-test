from __future__ import annotations

import argparse
import asyncio
import base64
import datetime
import gzip
import hashlib
import hmac
import json
import os
import statistics
import struct
import sys
import time
import urllib.parse
import uuid
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import dashscope
import pandas as pd
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

try:
    import websocket
except Exception:  # pragma: no cover - runtime optional dependency
    websocket = None


# Avoid Proactor overlapped-handle cleanup errors on Windows when SDK uses asyncio internals.
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass


# Change this to: ali | doubao | xunfei
ACTIVE_PROVIDER = "doubao"

# Aliyun FunASR
ALI_API_KEY = "REDACTED_CREDENTIAL"
ALI_ENDPOINT = "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
ALI_DEFAULT_MODEL_16K = "paraformer-realtime-v1"
ALI_DEFAULT_MODEL_8K = "fun-asr-flash-8k-realtime"

# Doubao ASR v3
DOUBAO_APP_ID = "6314392664"
DOUBAO_ACCESS_KEY = "REDACTED_CREDENTIAL"
# DOUBAO_API_KEY = "REDACTED_CREDENTIAL"
# DOUBAO_APP_KEY = "REDACTED_CREDENTIAL"
DOUBAO_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
DOUBAO_DEFAULT_MODEL_16K = "volc.bigasr.sauc.duration"
DOUBAO_DEFAULT_MODEL_8K = ""
DOUBAO_USER_ID = "default_user"
DOUBAO_LANGUAGE = "zh-CN"
DOUBAO_ENABLE_ITN = True
DOUBAO_ENABLE_PUNC = True
DOUBAO_RESULT_TYPE = "single"
DOUBAO_TRANSPORT_CHUNK_BYTES = 3200
DOUBAO_CONNECT_TIMEOUT_S = 10
DOUBAO_READ_TIMEOUT_S = 3
DOUBAO_RESULT_TIMEOUT_S = 40

# Xunfei RTASR-LLM
XUNFEI_APP_ID = "f8d4ff4a"
XUNFEI_ACCESS_KEY_ID = "REDACTED_CREDENTIAL"
XUNFEI_ACCESS_KEY_SECRET = "REDACTED_CREDENTIAL"
XUNFEI_ENDPOINT = "wss://office-api-ast-dx.iflyaisol.com/ast/communicate/v1"
XUNFEI_DEFAULT_MODEL_16K = "rtasr-llm-16k"
XUNFEI_DEFAULT_MODEL_8K = "rtasr-llm-8k"
XUNFEI_LANG = "autodialect"
XUNFEI_AUDIO_ENCODE = "pcm_s16le"
XUNFEI_TRANSPORT_CHUNK_BYTES_16K = 1280
XUNFEI_TRANSPORT_CHUNK_BYTES_8K = 640
XUNFEI_SEND_INTERVAL_S = 0.04
XUNFEI_CONNECT_TIMEOUT_S = 10
XUNFEI_READ_TIMEOUT_S = 3
XUNFEI_HANDSHAKE_WAIT_S = 5
XUNFEI_RESULT_TIMEOUT_S = 40

DEFAULT_AUDIO_SUBDIR = "vad_audio"
DEFAULT_EXCEL_PREFIX = "funasr_vad_asr_result"

# backward-compatible aliases used by existing CLI/options
DEFAULT_ENDPOINT = ALI_ENDPOINT
DEFAULT_MODEL_16K = ALI_DEFAULT_MODEL_16K
DEFAULT_MODEL_8K = ALI_DEFAULT_MODEL_8K

# Doubao binary protocol constants
DOUBAO_PROTOCOL_VERSION = 0x1
DOUBAO_HEADER_SIZE_WORD = 0x1
DOUBAO_MESSAGE_TYPE_FULL_CLIENT_REQUEST = 0x1
DOUBAO_MESSAGE_TYPE_AUDIO_ONLY_REQUEST = 0x2
DOUBAO_MESSAGE_TYPE_FULL_SERVER_RESPONSE = 0x9
DOUBAO_MESSAGE_TYPE_SERVER_ACK = 0xB
DOUBAO_MESSAGE_TYPE_SERVER_ERROR_RESPONSE = 0xF

DOUBAO_FLAG_NO_SEQUENCE = 0x0
DOUBAO_FLAG_POS_SEQUENCE = 0x1
DOUBAO_FLAG_NEG_SEQUENCE = 0x2
DOUBAO_FLAG_NEG_WITH_SEQUENCE = 0x3

DOUBAO_SERIALIZATION_NONE = 0x0
DOUBAO_SERIALIZATION_JSON = 0x1
DOUBAO_COMPRESSION_NONE = 0x0
DOUBAO_COMPRESSION_GZIP = 0x1


@dataclass
class FileAsrResult:
    file_path: Path
    status: str
    reason: str
    sample_rate: int | None
    duration_s: float | None
    model: str | None
    transcript: str
    first_packet_delay_ms: float | None
    tail_packet_delay_ms: float | None
    total_stream_elapsed_s: float | None
    rtf: float | None
    request_id: str | None


@dataclass
class ProviderRunResult:
    status: str
    reason: str
    model: str | None
    transcript: str
    first_packet_delay_ms: float | None
    tail_packet_delay_ms: float | None
    total_stream_elapsed_s: float | None
    request_id: str | None


class AsrProvider(ABC):
    def __init__(self, provider_key: str, provider_name: str, endpoint: str) -> None:
        self.provider_key = provider_key
        self.provider_name = provider_name
        self.endpoint = endpoint

    @abstractmethod
    def validate_config(self) -> str | None:
        pass

    @abstractmethod
    def select_model(self, sample_rate: int, model_8k: str, model_16k: str) -> tuple[str | None, str | None]:
        pass

    @abstractmethod
    def recognize(self, audio_bytes: bytes, sample_rate: int, duration_s: float, model_name: str) -> ProviderRunResult:
        pass

    def startup_lines(self) -> list[str]:
        return [
            f"Provider: {self.provider_name} ({self.provider_key})",
            f"Endpoint: {self.endpoint}",
        ]


class StreamCallback(RecognitionCallback):
    def __init__(self) -> None:
        super().__init__()
        self.completed_sentences: list[str] = []
        self.interim_sentence: str = ""
        self.first_result_ts: float | None = None
        self.error_message: str = ""
        self.last_message: str = ""
        self.is_done = False

    def on_open(self) -> None:
        return

    def on_complete(self, message: Any | None = None) -> None:
        self.is_done = True
        if message is not None:
            self.last_message = str(message)

    def on_error(self, result: Any) -> None:
        self.error_message = getattr(result, "message", "") or str(result)
        self.last_message = str(result)

    def on_event(self, result: Any) -> None:
        sentence: Any = None
        if hasattr(result, "get_sentence"):
            sentence = result.get_sentence()
        elif isinstance(result, dict):
            sentence = result.get("sentence")
        if not isinstance(sentence, dict):
            return

        text = str(sentence.get("text", "")).strip()
        if not text:
            return

        if self.first_result_ts is None:
            self.first_result_ts = time.perf_counter()

        if hasattr(result, "is_sentence_end") and result.is_sentence_end(sentence):
            self.completed_sentences.append(text)
            self.interim_sentence = ""
            return

        self.interim_sentence = text

    def on_data(self, data: RecognitionResult) -> None:
        self.last_message = str(data)

    def transcript(self) -> str:
        parts = list(self.completed_sentences)
        if self.interim_sentence:
            parts.append(self.interim_sentence)
        return "".join(parts).strip()


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "ok", "done", "end", "final", "finished"}
    return False


def _json_loads_safely(raw: str | bytes | bytearray | None) -> Any:
    if raw is None:
        return None
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        return json.loads(raw)
    except Exception:
        return None


def _normalize_provider_name(raw: str) -> str:
    value = (raw or "").strip().lower()
    aliases = {
        "ali": "ali",
        "aliyun": "ali",
        "dashscope": "ali",
        "funasr": "ali",
        "doubao": "doubao",
        "bytedance": "doubao",
        "volc": "doubao",
        "xunfei": "xunfei",
        "iflytek": "xunfei",
        "xfyun": "xunfei",
    }
    return aliases.get(value, value)


def _default_models_for_provider(provider_key: str) -> tuple[str, str]:
    if provider_key == "doubao":
        return DOUBAO_DEFAULT_MODEL_8K, DOUBAO_DEFAULT_MODEL_16K
    if provider_key == "xunfei":
        return XUNFEI_DEFAULT_MODEL_8K, XUNFEI_DEFAULT_MODEL_16K
    return ALI_DEFAULT_MODEL_8K, ALI_DEFAULT_MODEL_16K


def _default_endpoint_for_provider(provider_key: str) -> str:
    if provider_key == "doubao":
        return DOUBAO_ENDPOINT
    if provider_key == "xunfei":
        return XUNFEI_ENDPOINT
    return ALI_ENDPOINT


def _normalize_delay_ms(value: float | None) -> float | None:
    if value is None:
        return None
    if value < 0:
        return None
    if value > 24 * 60 * 60 * 1000:
        return None
    return value


def _safe_get_delay_ms(recognition: Recognition, getter_name: str) -> float | None:
    try:
        getter = getattr(recognition, getter_name)
        raw_value = getter()
    except Exception:
        return None
    return _normalize_delay_ms(_coerce_float(raw_value))


def _safe_average(values: list[float | None]) -> float | None:
    valid_values = [v for v in values if v is not None]
    if not valid_values:
        return None
    return statistics.mean(valid_values)


def _iter_binary_chunks(payload: bytes, chunk_bytes: int) -> list[bytes]:
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be > 0")
    if not payload:
        return []
    return [payload[i : i + chunk_bytes] for i in range(0, len(payload), chunk_bytes)]


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.1f} ms"


def _fmt_s(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.3f} s"


def _fmt_rtf(value: float | None) -> str:
    if value is None:
        return "N/A"
    return f"{value:.4f}"


def _validate_audio_format(wf: wave.Wave_read) -> str:
    if wf.getnchannels() != 1:
        return "only mono WAV is supported"
    if wf.getsampwidth() != 2:
        return "only 16-bit PCM WAV is supported"
    if wf.getcomptype() != "NONE":
        return "compressed WAV is not supported"
    return ""


def _sanitize_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text


def _collect_common_texts(payload: Any) -> list[str]:
    texts: list[str] = []
    key_candidates = {"text", "transcript", "sentence", "utterance", "result_text", "final_text"}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in key_candidates and isinstance(value, str):
                text = _sanitize_text(value)
                if text:
                    texts.append(text)
            texts.extend(_collect_common_texts(value))
        return texts
    if isinstance(payload, list):
        for item in payload:
            texts.extend(_collect_common_texts(item))
        return texts
    return texts


def _xunfei_extract_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    texts: list[str] = []
    cn = data.get("cn")
    if isinstance(cn, dict):
        st = cn.get("st")
        if isinstance(st, dict):
            rt_list = st.get("rt")
            if isinstance(rt_list, list):
                for rt in rt_list:
                    if not isinstance(rt, dict):
                        continue
                    ws_list = rt.get("ws")
                    if not isinstance(ws_list, list):
                        continue
                    for ws_item in ws_list:
                        if not isinstance(ws_item, dict):
                            continue
                        cw_list = ws_item.get("cw")
                        if not isinstance(cw_list, list):
                            continue
                        # cw is often an n-best candidate list for the same token slot.
                        # Keep only one best token to avoid duplicate words in transcript.
                        token = ""
                        for cw in cw_list:
                            if not isinstance(cw, dict):
                                continue
                            token = _sanitize_text(cw.get("w"))
                            if token:
                                break
                        if token:
                            texts.append(token)
    if texts:
        return "".join(texts).strip()
    fallback = _collect_common_texts(data)
    if fallback:
        return "".join(fallback).strip()
    return ""


def _doubao_extract_text(payload: Any) -> tuple[str, int | None]:
    if not isinstance(payload, dict):
        return "", None
    seg_id = _coerce_int(payload.get("seq")) or _coerce_int(payload.get("segment_id")) or _coerce_int(payload.get("seg_id"))
    texts: list[str] = []

    result = payload.get("result")
    if isinstance(result, dict):
        seg_id = seg_id or _coerce_int(result.get("seq")) or _coerce_int(result.get("segment_id")) or _coerce_int(
            result.get("seg_id")
        )
        utterances = result.get("utterances")
        if isinstance(utterances, list):
            for item in utterances:
                if not isinstance(item, dict):
                    continue
                text = _sanitize_text(item.get("text"))
                if text:
                    texts.append(text)
        if not texts:
            text = _sanitize_text(result.get("text"))
            if text:
                texts.append(text)
    elif isinstance(result, list):
        for item in result:
            if not isinstance(item, dict):
                continue
            seg_id = seg_id or _coerce_int(item.get("seq")) or _coerce_int(item.get("segment_id")) or _coerce_int(
                item.get("seg_id")
            )
            text = _sanitize_text(item.get("text"))
            if text:
                texts.append(text)

    if not texts:
        texts.extend(_collect_common_texts(payload))
    if not texts:
        return "", seg_id
    return "".join(texts).strip(), seg_id


def _payload_has_final_flag(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key in (
            "ls",
            "is_final",
            "is_last",
            "is_end",
            "end",
            "finished",
            "final",
            "done",
            "last_package",
            "is_last_package",
        ):
            if key in payload and _as_bool(payload.get(key)):
                return True
        for value in payload.values():
            if _payload_has_final_flag(value):
                return True
    elif isinstance(payload, list):
        for item in payload:
            if _payload_has_final_flag(item):
                return True
    return False


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _overlap_suffix_prefix(a: str, b: str) -> int:
    max_k = min(len(a), len(b))
    for k in range(max_k, 0, -1):
        if a.endswith(b[:k]):
            return k
    return 0


def _merge_incremental_text(current: str, incoming: str) -> str:
    cur = _sanitize_text(current)
    inc = _sanitize_text(incoming)
    if not inc:
        return cur
    if not cur:
        return inc
    if inc == cur:
        return cur

    # Typical incremental growth.
    if inc.startswith(cur):
        return inc
    # Ignore shorter rollback interim chunks.
    if cur.startswith(inc):
        return cur

    # Typical decoder correction: same beginning, changed tail.
    lcp = _common_prefix_len(cur, inc)
    min_len = min(len(cur), len(inc))
    if min_len > 0 and lcp >= 3 and (lcp / min_len) >= 0.6:
        return inc

    # Different pieces with overlap, append non-overlap suffix.
    overlap = _overlap_suffix_prefix(cur, inc)
    if overlap > 0:
        return cur + inc[overlap:]
    return cur + inc


def _merge_text_sequence(texts: list[str]) -> str:
    merged = ""
    for text in texts:
        clean = _sanitize_text(text)
        if not clean:
            continue
        merged = _merge_incremental_text(merged, clean)
    return _sanitize_text(merged)


def _doubao_build_header(
    message_type: int,
    flags: int,
    serialization: int,
    compression: int,
) -> bytes:
    first = (DOUBAO_PROTOCOL_VERSION << 4) | DOUBAO_HEADER_SIZE_WORD
    second = ((message_type & 0x0F) << 4) | (flags & 0x0F)
    third = ((serialization & 0x0F) << 4) | (compression & 0x0F)
    return bytes([first, second, third, 0x00])


def _doubao_build_frame(
    message_type: int,
    flags: int,
    sequence: int | None,
    payload: bytes,
    serialization: int,
    compression: int,
) -> bytes:
    body = bytearray()
    if sequence is not None:
        body.extend(struct.pack(">i", int(sequence)))
    body.extend(struct.pack(">I", len(payload)))
    body.extend(payload)
    return _doubao_build_header(
        message_type=message_type,
        flags=flags,
        serialization=serialization,
        compression=compression,
    ) + bytes(body)


def _doubao_parse_frame(raw: bytes) -> dict[str, Any]:
    if len(raw) < 4:
        return {
            "message_type": None,
            "flags": None,
            "serialization": None,
            "compression": None,
            "sequence": None,
            "payload": raw,
            "payload_json": None,
            "error": "frame too short",
        }

    header_words = raw[0] & 0x0F
    header_size = max(4, header_words * 4)
    message_type = (raw[1] >> 4) & 0x0F
    flags = raw[1] & 0x0F
    serialization = (raw[2] >> 4) & 0x0F
    compression = raw[2] & 0x0F

    idx = header_size
    if idx > len(raw):
        idx = 4
    sequence: int | None = None
    if flags in {DOUBAO_FLAG_POS_SEQUENCE, DOUBAO_FLAG_NEG_SEQUENCE, DOUBAO_FLAG_NEG_WITH_SEQUENCE} and len(raw) >= idx + 4:
        sequence = struct.unpack(">i", raw[idx : idx + 4])[0]
        idx += 4

    payload = b""
    if len(raw) >= idx + 4:
        declared_size = struct.unpack(">I", raw[idx : idx + 4])[0]
        idx += 4
        if declared_size <= len(raw) - idx:
            payload = raw[idx : idx + declared_size]
        else:
            payload = raw[idx:]
    elif len(raw) > idx:
        payload = raw[idx:]

    if compression == DOUBAO_COMPRESSION_GZIP and payload:
        try:
            payload = gzip.decompress(payload)
        except Exception:
            pass

    payload_json = None
    if serialization == DOUBAO_SERIALIZATION_JSON and payload:
        payload_json = _json_loads_safely(payload)

    return {
        "message_type": message_type,
        "flags": flags,
        "serialization": serialization,
        "compression": compression,
        "sequence": sequence,
        "payload": payload,
        "payload_json": payload_json,
        "error": "",
    }

class AliFunAsrProvider(AsrProvider):
    def __init__(self, api_key: str, endpoint: str) -> None:
        super().__init__(provider_key="ali", provider_name="Aliyun FunASR", endpoint=endpoint)
        self.api_key = api_key.strip()

    def validate_config(self) -> str | None:
        if not self.api_key:
            return "Ali provider requires API key (set ALI_API_KEY or pass --api-key)."
        return None

    def select_model(self, sample_rate: int, model_8k: str, model_16k: str) -> tuple[str | None, str | None]:
        if sample_rate == 8000:
            model_name = model_8k.strip()
            if not model_name:
                return None, "8k model is empty for ali provider"
            return model_name, None
        if sample_rate == 16000:
            model_name = model_16k.strip()
            if not model_name:
                return None, "16k model is empty for ali provider"
            return model_name, None
        return None, f"unsupported sample rate: {sample_rate} (only 8000/16000)"

    def startup_lines(self) -> list[str]:
        lines = super().startup_lines()
        masked_key = f"{self.api_key[:6]}...{self.api_key[-4:]}" if len(self.api_key) >= 12 else "<set>"
        lines.append(f"ApiKey: {masked_key}")
        return lines

    def recognize(self, audio_bytes: bytes, sample_rate: int, duration_s: float, model_name: str) -> ProviderRunResult:
        if not audio_bytes:
            return ProviderRunResult(
                status="SKIPPED",
                reason="no readable PCM frames found",
                model=model_name,
                transcript="",
                first_packet_delay_ms=None,
                tail_packet_delay_ms=None,
                total_stream_elapsed_s=None,
                request_id=None,
            )

        callback = StreamCallback()
        recognition = Recognition(
            model=model_name,
            format="pcm",
            sample_rate=sample_rate,
            callback=callback,
        )

        first_send_ts: float | None = None
        finish_task_sent_ts: float | None = None
        task_finished_ts: float | None = None
        request_id: str | None = None

        dashscope.api_key = self.api_key
        dashscope.base_websocket_api_url = self.endpoint

        started = False
        try:
            recognition.start()
            started = True

            first_send_ts = time.perf_counter()
            recognition.send_audio_frame(audio_bytes)

            finish_task_sent_ts = time.perf_counter()
            recognition.stop()
            task_finished_ts = time.perf_counter()
            started = False

            request_id = recognition.get_last_request_id()

        except Exception as exc:
            if started:
                if finish_task_sent_ts is None:
                    finish_task_sent_ts = time.perf_counter()
                try:
                    recognition.stop()
                    task_finished_ts = time.perf_counter()
                except Exception:
                    pass
            try:
                request_id = recognition.get_last_request_id()
            except Exception:
                pass

            sdk_first_ms = _safe_get_delay_ms(recognition, "get_first_package_delay")
            sdk_tail_ms = _safe_get_delay_ms(recognition, "get_last_package_delay")

            fallback_first_ms: float | None = None
            if first_send_ts is not None and callback.first_result_ts is not None:
                fallback_first_ms = (callback.first_result_ts - first_send_ts) * 1000

            fallback_tail_ms: float | None = None
            if finish_task_sent_ts is not None and task_finished_ts is not None:
                fallback_tail_ms = (task_finished_ts - finish_task_sent_ts) * 1000

            first_packet_delay_ms = sdk_first_ms if sdk_first_ms is not None else fallback_first_ms
            tail_packet_delay_ms = sdk_tail_ms if sdk_tail_ms is not None else fallback_tail_ms

            total_stream_elapsed_s: float | None = None
            if first_send_ts is not None and task_finished_ts is not None:
                total_stream_elapsed_s = task_finished_ts - first_send_ts
            elif first_send_ts is not None:
                total_stream_elapsed_s = time.perf_counter() - first_send_ts

            callback_error = callback.error_message.strip()
            callback_last = callback.last_message.strip()
            reason = f"SDK runtime error: {type(exc).__name__}: {exc}"
            if callback_error:
                reason = f"{reason}; callback_error: {callback_error}"
            elif callback_last:
                reason = f"{reason}; callback_message: {callback_last}"

            return ProviderRunResult(
                status="FAILED",
                reason=reason,
                model=model_name,
                transcript=callback.transcript(),
                first_packet_delay_ms=first_packet_delay_ms,
                tail_packet_delay_ms=tail_packet_delay_ms,
                total_stream_elapsed_s=total_stream_elapsed_s,
                request_id=request_id,
            )

        sdk_first_ms = _safe_get_delay_ms(recognition, "get_first_package_delay")
        sdk_tail_ms = _safe_get_delay_ms(recognition, "get_last_package_delay")

        fallback_first_ms: float | None = None
        if first_send_ts is not None and callback.first_result_ts is not None:
            fallback_first_ms = (callback.first_result_ts - first_send_ts) * 1000

        fallback_tail_ms: float | None = None
        if finish_task_sent_ts is not None and task_finished_ts is not None:
            fallback_tail_ms = (task_finished_ts - finish_task_sent_ts) * 1000

        first_packet_delay_ms = sdk_first_ms if sdk_first_ms is not None else fallback_first_ms
        tail_packet_delay_ms = sdk_tail_ms if sdk_tail_ms is not None else fallback_tail_ms

        total_stream_elapsed_s: float | None = None
        if first_send_ts is not None and task_finished_ts is not None:
            total_stream_elapsed_s = task_finished_ts - first_send_ts
        elif first_send_ts is not None:
            total_stream_elapsed_s = time.perf_counter() - first_send_ts

        transcript = callback.transcript()
        callback_error = callback.error_message.strip()
        if callback_error:
            return ProviderRunResult(
                status="FAILED",
                reason=callback_error,
                model=model_name,
                transcript=transcript,
                first_packet_delay_ms=first_packet_delay_ms,
                tail_packet_delay_ms=tail_packet_delay_ms,
                total_stream_elapsed_s=total_stream_elapsed_s,
                request_id=request_id,
            )

        return ProviderRunResult(
            status="SUCCESS",
            reason="",
            model=model_name,
            transcript=transcript,
            first_packet_delay_ms=first_packet_delay_ms,
            tail_packet_delay_ms=tail_packet_delay_ms,
            total_stream_elapsed_s=total_stream_elapsed_s,
            request_id=request_id,
        )


class DoubaoAsrProvider(AsrProvider):
    def __init__(
        self,
        endpoint: str,
        app_id: str,
        access_key: str,
        resource_id: str,
        user_id: str,
        language: str,
        enable_itn: bool,
        enable_punc: bool,
        result_type: str,
        chunk_bytes: int,
        connect_timeout_s: int,
        read_timeout_s: int,
        result_timeout_s: int,
    ) -> None:
        super().__init__(provider_key="doubao", provider_name="Doubao ASR v3", endpoint=endpoint)
        self.app_id = app_id.strip()
        # v3 auth uses headers: X-Api-App-Key(APPID) + X-Api-Access-Key(access token).
        self.app_key_header = self.app_id
        self.access_key = access_key.strip()
        self.resource_id = resource_id.strip()
        self.user_id = user_id.strip() or "default_user"
        self.language = language.strip() or "zh-CN"
        self.enable_itn = bool(enable_itn)
        self.enable_punc = bool(enable_punc)
        self.result_type = result_type.strip() or "single"
        self.chunk_bytes = max(320, int(chunk_bytes))
        self.connect_timeout_s = max(2, int(connect_timeout_s))
        self.read_timeout_s = max(1, int(read_timeout_s))
        self.result_timeout_s = max(5, int(result_timeout_s))

    def validate_config(self) -> str | None:
        if websocket is None:
            return "Doubao provider requires websocket-client package. Please install: uv add websocket-client"
        if not self.endpoint:
            return "Doubao endpoint is empty."
        if not self.app_key_header:
            return "Doubao APPID is empty (DOUBAO_APP_ID)."
        if not self.access_key:
            return "Doubao access key is empty (DOUBAO_ACCESS_KEY)."
        if not self.resource_id:
            return "Doubao resource id/model is empty (DOUBAO_DEFAULT_MODEL_16K)."
        return None

    def select_model(self, sample_rate: int, model_8k: str, model_16k: str) -> tuple[str | None, str | None]:
        if sample_rate != 16000:
            return None, f"doubao provider currently supports 16k only, got {sample_rate}"
        model_name = model_16k.strip() or self.resource_id
        if not model_name:
            return None, "16k model is empty for doubao provider"
        return model_name, None

    def startup_lines(self) -> list[str]:
        lines = super().startup_lines()
        lines.append(f"AppKeyHeader(APPID): {self.app_key_header}")
        lines.append(f"ResourceId(16k): {self.resource_id}")
        lines.append(f"TransportChunkBytes: {self.chunk_bytes}")
        return lines

    def _build_headers(self, model_name: str, connect_id: str) -> list[str]:
        return [
            f"X-Api-App-Key: {self.app_key_header}",
            f"X-Api-Access-Key: {self.access_key}",
            f"X-Api-Connect-Id: {connect_id}",
            f"X-Api-Resource-Id: {model_name}",
        ]

    def _build_full_request_payload(self, sample_rate: int, model_name: str) -> bytes:
        payload_obj = {
            "user": {
                "uid": self.user_id,
            },
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": sample_rate,
                "bits": 16,
                "channel": 1,
                "language": self.language,
            },
            "request": {
                "model_name": model_name,
                "enable_itn": self.enable_itn,
                "enable_punc": self.enable_punc,
                "result_type": self.result_type,
            },
        }
        raw = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
        return gzip.compress(raw)

    def recognize(self, audio_bytes: bytes, sample_rate: int, duration_s: float, model_name: str) -> ProviderRunResult:
        if not audio_bytes:
            return ProviderRunResult(
                status="SKIPPED",
                reason="no readable PCM frames found",
                model=model_name,
                transcript="",
                first_packet_delay_ms=None,
                tail_packet_delay_ms=None,
                total_stream_elapsed_s=None,
                request_id=None,
            )

        connect_id = str(uuid.uuid4())
        ws = None
        first_send_ts: float | None = None
        first_result_ts: float | None = None
        finish_task_sent_ts: float | None = None
        task_finished_ts: float | None = None
        reason = ""
        sequence = 1

        segment_texts: dict[int, str] = {}
        fallback_texts: list[str] = []
        saw_server_frame = False

        request_id = connect_id
        try:
            ws = websocket.create_connection(
                self.endpoint,
                header=self._build_headers(model_name=model_name, connect_id=connect_id),
                timeout=self.connect_timeout_s,
                enable_multithread=True,
            )
            ws.settimeout(self.read_timeout_s)

            try:
                hs_headers = getattr(getattr(ws, "handshake_response", None), "headers", {}) or {}
                if isinstance(hs_headers, dict):
                    request_id = hs_headers.get("X-Tt-Logid") or hs_headers.get("X-Api-Connect-Id") or connect_id
            except Exception:
                request_id = connect_id

            full_payload = self._build_full_request_payload(sample_rate=sample_rate, model_name=model_name)
            first_send_ts = time.perf_counter()
            ws.send_binary(
                _doubao_build_frame(
                    message_type=DOUBAO_MESSAGE_TYPE_FULL_CLIENT_REQUEST,
                    flags=DOUBAO_FLAG_POS_SEQUENCE,
                    sequence=sequence,
                    payload=full_payload,
                    serialization=DOUBAO_SERIALIZATION_JSON,
                    compression=DOUBAO_COMPRESSION_GZIP,
                )
            )
            sequence += 1

            if not audio_bytes:
                return ProviderRunResult(
                    status="SKIPPED",
                    reason="no transferable PCM chunk generated",
                    model=model_name,
                    transcript="",
                    first_packet_delay_ms=None,
                    tail_packet_delay_ms=None,
                    total_stream_elapsed_s=None,
                    request_id=request_id,
                )
            # Business semantics: VAD sliced WAV is treated as a single full unit.
            # We send one full audio packet (no secondary chunking).
            ws.send_binary(
                _doubao_build_frame(
                    message_type=DOUBAO_MESSAGE_TYPE_AUDIO_ONLY_REQUEST,
                    flags=DOUBAO_FLAG_POS_SEQUENCE,
                    sequence=sequence,
                    payload=audio_bytes,
                    serialization=DOUBAO_SERIALIZATION_NONE,
                    compression=DOUBAO_COMPRESSION_NONE,
                )
            )
            sequence += 1

            finish_task_sent_ts = time.perf_counter()
            ws.send_binary(
                _doubao_build_frame(
                    message_type=DOUBAO_MESSAGE_TYPE_AUDIO_ONLY_REQUEST,
                    flags=DOUBAO_FLAG_NEG_WITH_SEQUENCE,
                    sequence=-sequence,
                    payload=b"",
                    serialization=DOUBAO_SERIALIZATION_NONE,
                    compression=DOUBAO_COMPRESSION_NONE,
                )
            )

            done = False
            deadline = time.perf_counter() + self.result_timeout_s
            while not done and time.perf_counter() < deadline:
                timeout_left = max(0.1, min(float(self.read_timeout_s), deadline - time.perf_counter()))
                ws.settimeout(timeout_left)
                raw_msg = ws.recv()

                if raw_msg is None:
                    continue

                payload_obj: Any = None
                message_type: int | None = None
                msg_seq: int | None = None

                if isinstance(raw_msg, str):
                    payload_obj = _json_loads_safely(raw_msg)
                elif isinstance(raw_msg, (bytes, bytearray)):
                    parsed = _doubao_parse_frame(bytes(raw_msg))
                    saw_server_frame = True
                    message_type = parsed.get("message_type")
                    msg_seq = parsed.get("sequence")
                    msg_flags = parsed.get("flags")
                    payload_obj = parsed.get("payload_json")
                    if payload_obj is None and parsed.get("payload"):
                        payload_obj = _json_loads_safely(parsed.get("payload"))
                    if message_type == DOUBAO_MESSAGE_TYPE_SERVER_ERROR_RESPONSE and not reason:
                        reason = f"doubao server error response: {payload_obj or parsed.get('payload')}"
                    # Server may mark final packet with NEG_WITH_SEQUENCE flag even when seq is positive.
                    if msg_flags in (DOUBAO_FLAG_NEG_SEQUENCE, DOUBAO_FLAG_NEG_WITH_SEQUENCE):
                        done = True
                        task_finished_ts = time.perf_counter()

                text = ""
                seg_id = None
                if payload_obj is not None:
                    text, seg_id = _doubao_extract_text(payload_obj)
                    if not reason and isinstance(payload_obj, dict):
                        err_msg = _sanitize_text(payload_obj.get("message") or payload_obj.get("error_msg"))
                        err_code = payload_obj.get("code") or payload_obj.get("error_code")
                        if err_msg and err_code not in (None, 0, "0"):
                            reason = f"doubao error {err_code}: {err_msg}"

                if text:
                    if first_result_ts is None:
                        first_result_ts = time.perf_counter()
                    if seg_id is None:
                        if not fallback_texts or fallback_texts[-1] != text:
                            fallback_texts.append(text)
                    else:
                        segment_texts[seg_id] = text

                if msg_seq is not None and msg_seq < 0:
                    done = True
                    task_finished_ts = time.perf_counter()
                    break

                if payload_obj is not None and _payload_has_final_flag(payload_obj):
                    done = True
                    task_finished_ts = time.perf_counter()
                    break

                if message_type == DOUBAO_MESSAGE_TYPE_SERVER_ERROR_RESPONSE:
                    done = True
                    task_finished_ts = time.perf_counter()
                    break

            if task_finished_ts is None:
                task_finished_ts = time.perf_counter()
                if not reason:
                    reason = f"result timeout: no final response within {self.result_timeout_s}s"

        except Exception as exc:
            closed_ok = (
                websocket is not None
                and isinstance(exc, websocket.WebSocketConnectionClosedException)
                and saw_server_frame
                and not reason
            )
            if not reason and not closed_ok:
                reason = f"provider runtime error: {type(exc).__name__}: {exc}"
            if task_finished_ts is None:
                task_finished_ts = time.perf_counter()
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

        first_packet_delay_ms: float | None = None
        if first_send_ts is not None and first_result_ts is not None:
            first_packet_delay_ms = (first_result_ts - first_send_ts) * 1000

        tail_packet_delay_ms: float | None = None
        if finish_task_sent_ts is not None and task_finished_ts is not None:
            tail_packet_delay_ms = (task_finished_ts - finish_task_sent_ts) * 1000

        total_stream_elapsed_s: float | None = None
        if first_send_ts is not None and task_finished_ts is not None:
            total_stream_elapsed_s = task_finished_ts - first_send_ts

        ordered_segments = [segment_texts[idx] for idx in sorted(segment_texts.keys())]
        transcript = _merge_text_sequence(ordered_segments + fallback_texts)

        if reason:
            return ProviderRunResult(
                status="FAILED",
                reason=reason,
                model=model_name,
                transcript=transcript,
                first_packet_delay_ms=first_packet_delay_ms,
                tail_packet_delay_ms=tail_packet_delay_ms,
                total_stream_elapsed_s=total_stream_elapsed_s,
                request_id=request_id,
            )
        return ProviderRunResult(
            status="SUCCESS",
            reason="",
            model=model_name,
            transcript=transcript,
            first_packet_delay_ms=first_packet_delay_ms,
            tail_packet_delay_ms=tail_packet_delay_ms,
            total_stream_elapsed_s=total_stream_elapsed_s,
            request_id=request_id,
        )


class XunfeiRtasrLlmProvider(AsrProvider):
    def __init__(
        self,
        endpoint: str,
        app_id: str,
        access_key_id: str,
        access_key_secret: str,
        lang: str,
        audio_encode: str,
        chunk_bytes_16k: int,
        chunk_bytes_8k: int,
        send_interval_s: float,
        connect_timeout_s: int,
        read_timeout_s: int,
        handshake_wait_s: int,
        result_timeout_s: int,
    ) -> None:
        super().__init__(provider_key="xunfei", provider_name="Xunfei RTASR-LLM", endpoint=endpoint)
        self.app_id = app_id.strip()
        self.access_key_id = access_key_id.strip()
        self.access_key_secret = access_key_secret.strip()
        self.lang = lang.strip() or "autodialect"
        self.audio_encode = audio_encode.strip() or "pcm_s16le"
        self.chunk_bytes_16k = max(320, int(chunk_bytes_16k))
        self.chunk_bytes_8k = max(320, int(chunk_bytes_8k))
        self.send_interval_s = max(0.0, float(send_interval_s))
        self.connect_timeout_s = max(2, int(connect_timeout_s))
        self.read_timeout_s = max(1, int(read_timeout_s))
        self.handshake_wait_s = max(2, int(handshake_wait_s))
        self.result_timeout_s = max(5, int(result_timeout_s))

    def validate_config(self) -> str | None:
        if websocket is None:
            return "Xunfei provider requires websocket-client package. Please install: uv add websocket-client"
        if not self.endpoint:
            return "Xunfei endpoint is empty."
        if not self.app_id:
            return "Xunfei app id is empty (XUNFEI_APP_ID)."
        if not self.access_key_id:
            return "Xunfei access key id is empty (XUNFEI_ACCESS_KEY_ID)."
        if not self.access_key_secret:
            return "Xunfei access key secret is empty (XUNFEI_ACCESS_KEY_SECRET)."
        return None

    def select_model(self, sample_rate: int, model_8k: str, model_16k: str) -> tuple[str | None, str | None]:
        if sample_rate == 8000:
            model_name = model_8k.strip()
            if not model_name:
                return None, "8k model is empty for xunfei provider"
            return model_name, None
        if sample_rate == 16000:
            model_name = model_16k.strip()
            if not model_name:
                return None, "16k model is empty for xunfei provider"
            return model_name, None
        return None, f"unsupported sample rate: {sample_rate} (only 8000/16000)"

    def startup_lines(self) -> list[str]:
        lines = super().startup_lines()
        lines.append(f"AudioEncode: {self.audio_encode}")
        lines.append(f"TransportChunkBytes(16k/8k): {self.chunk_bytes_16k}/{self.chunk_bytes_8k}")
        return lines

    def _build_signed_url(self, sample_rate: int) -> str:
        utc = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%dT%H:%M:%S%z")
        params = {
            "accessKeyId": self.access_key_id,
            "appId": self.app_id,
            "uuid": str(uuid.uuid4()),
            "utc": utc,
            "audio_encode": self.audio_encode,
            "lang": self.lang,
            "samplerate": str(sample_rate),
        }
        sorted_items = sorted(params.items(), key=lambda item: item[0])
        base_string = urllib.parse.urlencode(sorted_items, quote_via=urllib.parse.quote, safe="")
        signature = base64.b64encode(
            hmac.new(self.access_key_secret.encode("utf-8"), base_string.encode("utf-8"), hashlib.sha1).digest()
        ).decode("utf-8")
        params["signature"] = signature
        query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe="")
        return f"{self.endpoint}?{query}"

    def _parse_server_message(self, message: Any) -> dict[str, Any]:
        if isinstance(message, bytes):
            payload = _json_loads_safely(message)
        else:
            payload = _json_loads_safely(str(message))
        if not isinstance(payload, dict):
            return {"action": "", "code": None, "desc": "invalid server message", "data": None, "sid": None}
        data = payload.get("data")
        data_action = _sanitize_text(data.get("action")) if isinstance(data, dict) else ""
        top_action = _sanitize_text(payload.get("action") or payload.get("msg_type"))
        sid = _sanitize_text(payload.get("sid") or payload.get("sessionId"))
        if not sid and isinstance(data, dict):
            sid = _sanitize_text(data.get("sid") or data.get("sessionId"))
        return {
            "action": data_action or top_action,
            "msg_type": _sanitize_text(payload.get("msg_type")),
            "data_action": data_action,
            "code": payload.get("code"),
            "desc": _sanitize_text(payload.get("desc") or payload.get("message")),
            "data": data,
            "sid": sid,
            "raw": payload,
        }

    def recognize(self, audio_bytes: bytes, sample_rate: int, duration_s: float, model_name: str) -> ProviderRunResult:
        if not audio_bytes:
            return ProviderRunResult(
                status="SKIPPED",
                reason="no readable PCM frames found",
                model=model_name,
                transcript="",
                first_packet_delay_ms=None,
                tail_packet_delay_ms=None,
                total_stream_elapsed_s=None,
                request_id=None,
            )

        ws = None
        first_send_ts: float | None = None
        first_result_ts: float | None = None
        finish_task_sent_ts: float | None = None
        task_finished_ts: float | None = None
        reason = ""
        session_id = ""
        final_segments: dict[int, str] = {}
        final_fallback = ""
        interim_last = ""

        try:
            url = self._build_signed_url(sample_rate=sample_rate)
            ws = websocket.create_connection(url, timeout=self.connect_timeout_s, enable_multithread=True)
            ws.settimeout(self.read_timeout_s)

            handshake_deadline = time.perf_counter() + self.handshake_wait_s
            got_started = False
            while time.perf_counter() < handshake_deadline:
                timeout_left = max(0.1, min(float(self.read_timeout_s), handshake_deadline - time.perf_counter()))
                ws.settimeout(timeout_left)
                try:
                    server_raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                msg = self._parse_server_message(server_raw)
                action = msg.get("action", "")
                code = msg.get("code")
                if code not in (None, 0, "0"):
                    reason = f"xunfei handshake error {code}: {msg.get('desc')}"
                    break
                if msg.get("sid"):
                    session_id = msg["sid"]
                if action == "started":
                    got_started = True
                    break
                if action == "error":
                    reason = f"xunfei handshake error: {msg.get('desc') or msg.get('raw')}"
                    break
            if not reason and not got_started:
                reason = f"handshake timeout: no started event within {self.handshake_wait_s}s"
            if reason:
                return ProviderRunResult(
                    status="FAILED",
                    reason=reason,
                    model=model_name,
                    transcript="",
                    first_packet_delay_ms=None,
                    tail_packet_delay_ms=None,
                    total_stream_elapsed_s=None,
                    request_id=session_id or None,
                )

            if not audio_bytes:
                return ProviderRunResult(
                    status="SKIPPED",
                    reason="no transferable PCM chunk generated",
                    model=model_name,
                    transcript="",
                    first_packet_delay_ms=None,
                    tail_packet_delay_ms=None,
                    total_stream_elapsed_s=None,
                    request_id=session_id or None,
                )

            first_send_ts = time.perf_counter()
            # Business semantics: VAD sliced WAV is treated as one full unit.
            # Send full audio once, no secondary chunking.
            ws.send(audio_bytes, opcode=websocket.ABNF.OPCODE_BINARY)

            finish_task_sent_ts = time.perf_counter()
            end_payload: dict[str, Any] = {"end": True}
            if session_id:
                end_payload["sessionId"] = session_id
            ws.send(json.dumps(end_payload, ensure_ascii=False))

            done = False
            deadline = time.perf_counter() + self.result_timeout_s
            while not done and time.perf_counter() < deadline:
                timeout_left = max(0.1, min(float(self.read_timeout_s), deadline - time.perf_counter()))
                ws.settimeout(timeout_left)
                try:
                    server_raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                msg = self._parse_server_message(server_raw)
                action = msg.get("action", "")
                code = msg.get("code")
                data = msg.get("data")
                if msg.get("sid"):
                    session_id = msg["sid"]

                if code not in (None, 0, "0"):
                    reason = f"xunfei error {code}: {msg.get('desc')}"
                    task_finished_ts = time.perf_counter()
                    break

                if action == "error":
                    reason = f"xunfei error: {msg.get('desc') or msg.get('raw')}"
                    task_finished_ts = time.perf_counter()
                    break

                if isinstance(data, dict):
                    text = _xunfei_extract_text(data)
                    seg_id = _coerce_int(data.get("seg_id"))
                    is_final = _as_bool(data.get("ls"))
                    if text:
                        if first_result_ts is None:
                            first_result_ts = time.perf_counter()
                        if is_final:
                            if seg_id is None:
                                final_fallback = _merge_incremental_text(final_fallback, text)
                            else:
                                prev = final_segments.get(seg_id, "")
                                final_segments[seg_id] = _merge_incremental_text(prev, text)
                        else:
                            interim_last = text
                    if is_final:
                        task_finished_ts = time.perf_counter()
                        done = True
                        break

            if task_finished_ts is None:
                task_finished_ts = time.perf_counter()
                if not reason:
                    reason = f"result timeout: no final response within {self.result_timeout_s}s"

        except Exception as exc:
            if not reason:
                reason = f"provider runtime error: {type(exc).__name__}: {exc}"
            if task_finished_ts is None:
                task_finished_ts = time.perf_counter()
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass

        first_packet_delay_ms: float | None = None
        if first_send_ts is not None and first_result_ts is not None:
            first_packet_delay_ms = (first_result_ts - first_send_ts) * 1000

        tail_packet_delay_ms: float | None = None
        if finish_task_sent_ts is not None and task_finished_ts is not None:
            tail_packet_delay_ms = (task_finished_ts - finish_task_sent_ts) * 1000

        total_stream_elapsed_s: float | None = None
        if first_send_ts is not None and task_finished_ts is not None:
            total_stream_elapsed_s = task_finished_ts - first_send_ts

        ordered_final = [final_segments[idx] for idx in sorted(final_segments.keys())]
        merged_final = _merge_text_sequence(ordered_final)
        transcript = _sanitize_text(merged_final or final_fallback or interim_last)

        if reason:
            return ProviderRunResult(
                status="FAILED",
                reason=reason,
                model=model_name,
                transcript=transcript,
                first_packet_delay_ms=first_packet_delay_ms,
                tail_packet_delay_ms=tail_packet_delay_ms,
                total_stream_elapsed_s=total_stream_elapsed_s,
                request_id=session_id or None,
            )
        return ProviderRunResult(
            status="SUCCESS",
            reason="",
            model=model_name,
            transcript=transcript,
            first_packet_delay_ms=first_packet_delay_ms,
            tail_packet_delay_ms=tail_packet_delay_ms,
            total_stream_elapsed_s=total_stream_elapsed_s,
            request_id=session_id or None,
        )


def build_provider(args: argparse.Namespace) -> AsrProvider:
    provider_key = _normalize_provider_name(ACTIVE_PROVIDER)
    if provider_key == "ali":
        api_key = args.api_key.strip() or ALI_API_KEY.strip() or os.getenv("DASHSCOPE_API_KEY", "").strip()
        endpoint = args.endpoint.strip() or ALI_ENDPOINT
        return AliFunAsrProvider(api_key=api_key, endpoint=endpoint)

    if provider_key == "doubao":
        endpoint = args.endpoint.strip() or DOUBAO_ENDPOINT
        return DoubaoAsrProvider(
            endpoint=endpoint,
            app_id=DOUBAO_APP_ID,
            access_key=DOUBAO_ACCESS_KEY,
            resource_id=DOUBAO_DEFAULT_MODEL_16K,
            user_id=DOUBAO_USER_ID,
            language=DOUBAO_LANGUAGE,
            enable_itn=DOUBAO_ENABLE_ITN,
            enable_punc=DOUBAO_ENABLE_PUNC,
            result_type=DOUBAO_RESULT_TYPE,
            chunk_bytes=DOUBAO_TRANSPORT_CHUNK_BYTES,
            connect_timeout_s=DOUBAO_CONNECT_TIMEOUT_S,
            read_timeout_s=DOUBAO_READ_TIMEOUT_S,
            result_timeout_s=DOUBAO_RESULT_TIMEOUT_S,
        )

    if provider_key == "xunfei":
        endpoint = args.endpoint.strip() or XUNFEI_ENDPOINT
        return XunfeiRtasrLlmProvider(
            endpoint=endpoint,
            app_id=XUNFEI_APP_ID,
            access_key_id=XUNFEI_ACCESS_KEY_ID,
            access_key_secret=XUNFEI_ACCESS_KEY_SECRET,
            lang=XUNFEI_LANG,
            audio_encode=XUNFEI_AUDIO_ENCODE,
            chunk_bytes_16k=XUNFEI_TRANSPORT_CHUNK_BYTES_16K,
            chunk_bytes_8k=XUNFEI_TRANSPORT_CHUNK_BYTES_8K,
            send_interval_s=XUNFEI_SEND_INTERVAL_S,
            connect_timeout_s=XUNFEI_CONNECT_TIMEOUT_S,
            read_timeout_s=XUNFEI_READ_TIMEOUT_S,
            handshake_wait_s=XUNFEI_HANDSHAKE_WAIT_S,
            result_timeout_s=XUNFEI_RESULT_TIMEOUT_S,
        )

    raise ValueError(f"Unsupported ACTIVE_PROVIDER: {ACTIVE_PROVIDER}")


def run_single_file(
    provider: AsrProvider,
    file_path: Path,
    model_8k: str,
    model_16k: str,
) -> FileAsrResult:
    try:
        with wave.open(str(file_path), "rb") as wf:
            format_error = _validate_audio_format(wf)
            if format_error:
                return FileAsrResult(
                    file_path=file_path,
                    status="SKIPPED",
                    reason=format_error,
                    sample_rate=wf.getframerate(),
                    duration_s=wf.getnframes() / wf.getframerate() if wf.getframerate() else None,
                    model=None,
                    transcript="",
                    first_packet_delay_ms=None,
                    tail_packet_delay_ms=None,
                    total_stream_elapsed_s=None,
                    rtf=None,
                    request_id=None,
                )

            sample_rate = wf.getframerate()
            model_name, model_reason = provider.select_model(
                sample_rate=sample_rate,
                model_8k=model_8k,
                model_16k=model_16k,
            )
            if not model_name:
                return FileAsrResult(
                    file_path=file_path,
                    status="SKIPPED",
                    reason=model_reason or f"unsupported sample rate: {sample_rate}",
                    sample_rate=sample_rate,
                    duration_s=wf.getnframes() / sample_rate if sample_rate else None,
                    model=None,
                    transcript="",
                    first_packet_delay_ms=None,
                    tail_packet_delay_ms=None,
                    total_stream_elapsed_s=None,
                    rtf=None,
                    request_id=None,
                )

            total_frames = wf.getnframes()
            if total_frames <= 0:
                return FileAsrResult(
                    file_path=file_path,
                    status="SKIPPED",
                    reason="empty WAV file",
                    sample_rate=sample_rate,
                    duration_s=0.0,
                    model=model_name,
                    transcript="",
                    first_packet_delay_ms=None,
                    tail_packet_delay_ms=None,
                    total_stream_elapsed_s=None,
                    rtf=None,
                    request_id=None,
                )

            duration_s = total_frames / sample_rate
            audio_bytes = wf.readframes(total_frames)
            if not audio_bytes:
                return FileAsrResult(
                    file_path=file_path,
                    status="SKIPPED",
                    reason="no readable PCM frames found",
                    sample_rate=sample_rate,
                    duration_s=duration_s,
                    model=model_name,
                    transcript="",
                    first_packet_delay_ms=None,
                    tail_packet_delay_ms=None,
                    total_stream_elapsed_s=None,
                    rtf=None,
                    request_id=None,
                )

            provider_result = provider.recognize(
                audio_bytes=audio_bytes,
                sample_rate=sample_rate,
                duration_s=duration_s,
                model_name=model_name,
            )

            total_stream_elapsed_s = provider_result.total_stream_elapsed_s
            rtf: float | None = None
            if total_stream_elapsed_s is not None and duration_s > 0:
                rtf = total_stream_elapsed_s / duration_s

            return FileAsrResult(
                file_path=file_path,
                status=provider_result.status,
                reason=provider_result.reason,
                sample_rate=sample_rate,
                duration_s=duration_s,
                model=provider_result.model or model_name,
                transcript=provider_result.transcript,
                first_packet_delay_ms=provider_result.first_packet_delay_ms,
                tail_packet_delay_ms=provider_result.tail_packet_delay_ms,
                total_stream_elapsed_s=provider_result.total_stream_elapsed_s,
                rtf=rtf,
                request_id=provider_result.request_id,
            )

    except wave.Error as exc:
        return FileAsrResult(
            file_path=file_path,
            status="SKIPPED",
            reason=f"invalid WAV file: {exc}",
            sample_rate=None,
            duration_s=None,
            model=None,
            transcript="",
            first_packet_delay_ms=None,
            tail_packet_delay_ms=None,
            total_stream_elapsed_s=None,
            rtf=None,
            request_id=None,
        )
    except Exception as exc:
        return FileAsrResult(
            file_path=file_path,
            status="FAILED",
            reason=f"unexpected runtime error: {type(exc).__name__}: {exc}",
            sample_rate=None,
            duration_s=None,
            model=None,
            transcript="",
            first_packet_delay_ms=None,
            tail_packet_delay_ms=None,
            total_stream_elapsed_s=None,
            rtf=None,
            request_id=None,
        )

def print_file_report(index: int, total: int, result: FileAsrResult) -> None:
    print("=" * 90)
    print(f"[{index}/{total}] {result.file_path}")
    print(f"Status: {result.status}")
    if result.sample_rate is not None:
        print(f"SampleRate: {result.sample_rate}")
    if result.model:
        print(f"Model: {result.model}")
    if result.duration_s is not None:
        print(f"Duration: {_fmt_s(result.duration_s)}")
    print(f"FirstPacket: {_fmt_ms(result.first_packet_delay_ms)}")
    print(f"TailPacket: {_fmt_ms(result.tail_packet_delay_ms)}")
    print(f"TotalStream: {_fmt_s(result.total_stream_elapsed_s)}")
    print(f"RTF: {_fmt_rtf(result.rtf)}")
    if result.request_id:
        print(f"RequestId: {result.request_id}")
    if result.transcript:
        print("Transcript:")
        print(result.transcript)
    else:
        print("Transcript: <empty>")
    if result.reason:
        print(f"Reason: {result.reason}")


def build_summary(results: list[FileAsrResult]) -> dict[str, Any]:
    total_count = len(results)
    success_items = [r for r in results if r.status == "SUCCESS"]
    failed_items = [r for r in results if r.status == "FAILED"]
    skipped_items = [r for r in results if r.status == "SKIPPED"]

    avg_first = _safe_average([r.first_packet_delay_ms for r in success_items])
    avg_tail = _safe_average([r.tail_packet_delay_ms for r in success_items])
    avg_rtf = _safe_average([r.rtf for r in success_items])

    return {
        "total": total_count,
        "success": len(success_items),
        "failed": len(failed_items),
        "skipped": len(skipped_items),
        "avg_first_packet_ms": avg_first,
        "avg_tail_packet_ms": avg_tail,
        "avg_rtf": avg_rtf,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def print_summary(results: list[FileAsrResult]) -> dict[str, Any]:
    print("\n" + "#" * 90)
    print("Summary")
    print("#" * 90)

    summary = build_summary(results)
    total_count = int(summary["total"])
    success_items = [r for r in results if r.status == "SUCCESS"]
    failed_items = [r for r in results if r.status == "FAILED"]
    skipped_items = [r for r in results if r.status == "SKIPPED"]

    avg_first = summary["avg_first_packet_ms"]
    avg_tail = summary["avg_tail_packet_ms"]
    avg_rtf = summary["avg_rtf"]

    print(f"Total Files: {total_count}")
    print(f"Success: {len(success_items)}")
    print(f"Failed: {len(failed_items)}")
    print(f"Skipped: {len(skipped_items)}")
    print(f"Avg FirstPacket: {_fmt_ms(avg_first)}")
    print(f"Avg TailPacket: {_fmt_ms(avg_tail)}")
    print(f"Avg RTF: {_fmt_rtf(avg_rtf)}")

    if failed_items:
        print("\nFailed Files:")
        for item in failed_items:
            print(f"- {item.file_path.name}: {item.reason}")

    if skipped_items:
        print("\nSkipped Files:")
        for item in skipped_items:
            print(f"- {item.file_path.name}: {item.reason}")

    return summary


def build_default_excel_path() -> Path:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_dir = Path(__file__).resolve().parent
    return (base_dir / f"{DEFAULT_EXCEL_PREFIX}_{stamp}.xlsx").resolve()


def write_excel_report(results: list[FileAsrResult], summary: dict[str, Any], excel_path: Path) -> None:
    excel_path.parent.mkdir(parents=True, exist_ok=True)

    raw_columns = [
        "file_name",
        "file_path",
        "status",
        "reason",
        "sample_rate",
        "duration_s",
        "model",
        "transcript",
        "first_packet_ms",
        "tail_packet_ms",
        "total_stream_s",
        "rtf",
        "request_id",
    ]
    raw_rows: list[dict[str, Any]] = []
    for item in results:
        raw_rows.append(
            {
                "file_name": item.file_path.name,
                "file_path": str(item.file_path),
                "status": item.status,
                "reason": item.reason,
                "sample_rate": item.sample_rate,
                "duration_s": item.duration_s,
                "model": item.model,
                "transcript": item.transcript,
                "first_packet_ms": item.first_packet_delay_ms,
                "tail_packet_ms": item.tail_packet_delay_ms,
                "total_stream_s": item.total_stream_elapsed_s,
                "rtf": item.rtf,
                "request_id": item.request_id,
            }
        )
    raw_df = pd.DataFrame(raw_rows, columns=raw_columns)

    summary_columns = [
        "total",
        "success",
        "failed",
        "skipped",
        "avg_first_packet_ms",
        "avg_tail_packet_ms",
        "avg_rtf",
        "generated_at",
    ]
    summary_df = pd.DataFrame([summary], columns=summary_columns)

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        raw_df.to_excel(writer, sheet_name="raw", index=False)
        summary_df.to_excel(writer, sheet_name="summary", index=False)


def parse_args() -> argparse.Namespace:
    provider_key = _normalize_provider_name(ACTIVE_PROVIDER)
    default_model_8k, default_model_16k = _default_models_for_provider(provider_key)
    default_endpoint = _default_endpoint_for_provider(provider_key)
    default_audio_dir = Path(__file__).resolve().parent / DEFAULT_AUDIO_SUBDIR

    parser = argparse.ArgumentParser(description="Multi-provider ASR VAD full-audio batch test.")
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=default_audio_dir,
        help=f"Audio directory to traverse (default: {default_audio_dir})",
    )
    parser.add_argument(
        "--model-16k",
        default=default_model_16k,
        help=f"Model id for 16k WAV (default: {default_model_16k}).",
    )
    parser.add_argument(
        "--model-8k",
        default=default_model_8k,
        help=f"Model id for 8k WAV (default: {default_model_8k}).",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Ali API key override (only used when ACTIVE_PROVIDER=ali).",
    )
    parser.add_argument(
        "--endpoint",
        default=default_endpoint,
        help=f"Provider websocket endpoint (default: {default_endpoint}).",
    )
    parser.add_argument(
        "--excel-path",
        type=Path,
        default=None,
        help="Excel output path. Default: voice_test/funasr_vad_asr_result_<timestamp>.xlsx",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    provider_key = _normalize_provider_name(ACTIVE_PROVIDER)
    try:
        provider = build_provider(args)
    except Exception as exc:
        print(f"Error: failed to build provider from ACTIVE_PROVIDER={ACTIVE_PROVIDER!r}: {exc}")
        return 2

    config_error = provider.validate_config()
    if config_error:
        print(f"Error: {config_error}")
        return 2

    audio_dir = args.audio_dir.expanduser().resolve()
    if not audio_dir.exists() or not audio_dir.is_dir():
        print(f"Error: audio directory does not exist: {audio_dir}")
        return 2

    wav_files = sorted(audio_dir.rglob("*.wav"))
    excel_path = args.excel_path.expanduser().resolve() if args.excel_path else build_default_excel_path()

    print("ASR VAD Full-Audio Batch Test")
    print(f"ActiveProvider: {provider_key}")
    for line in provider.startup_lines():
        print(line)
    print(f"AudioDir: {audio_dir}")
    print(f"FileCount: {len(wav_files)}")
    print("SendMode: full-audio(single-frame)")
    print(f"Model16k: {args.model_16k}")
    print(f"Model8k: {args.model_8k}")
    print(f"ExcelPath: {excel_path}")

    if not wav_files:
        print(f"No WAV files found in: {audio_dir}. An empty Excel report will still be generated.")

    results: list[FileAsrResult] = []
    for index, wav_file in enumerate(wav_files, start=1):
        result = run_single_file(
            provider=provider,
            file_path=wav_file,
            model_8k=args.model_8k,
            model_16k=args.model_16k,
        )
        print_file_report(index, len(wav_files), result)
        results.append(result)

    summary = print_summary(results)
    write_excel_report(results=results, summary=summary, excel_path=excel_path)
    print(f"\nExcel report written: {excel_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
