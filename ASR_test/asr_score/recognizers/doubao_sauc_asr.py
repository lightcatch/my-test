# -*- coding: utf-8 -*-
"""豆包 SAUC WebSocket 大模型 nostream 版 ASR 识别器 (非流式)。

对应火山引擎接口:
  Resource ID = volc.bigasr.sauc.duration
  Model = bigmodel
  Endpoint = wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream

工作方式:
  1. WebSocket 连接 + 4 个 X-Api-* header
  2. 发送 full_client_request 帧 (config JSON, gzip 压缩)
  3. 分片发送 audio_only_request 帧 (最后一帧标 NEG_WITH_SEQUENCE)
  4. 服务端返回一个 SERVER_FULL_RESPONSE 帧, 含完整转写文本

- name="doubao_sauc_asr", display_name="Doubao_SAUC_Nostream", is_local_gpu=False
- 单条延迟通常 1-3s (含 WS 握手 + 分片上传 + 推理)
"""

from __future__ import annotations

import sys as _config_sys
from pathlib import Path as _ConfigPath

_CONFIG_ROOT = str(_ConfigPath(__file__).resolve().parents[3])
if _CONFIG_ROOT not in _config_sys.path:
    _config_sys.path.insert(0, _CONFIG_ROOT)
import config11 as _local_config  # 本机密钥由 .gitignore 排除。


import asyncio
import gzip
import json
import struct
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp

from .base import BaseRecognizer, RecognitionResult


APP_ID = _local_config.ASR_SAUC_APP_ID
ACCESS_TOKEN = _local_config.ASR_SAUC_ACCESS_TOKEN
RESOURCE_ID = "volc.bigasr.sauc.duration"
MODEL_NAME = "bigmodel"
WSS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"

# --- 协议常量 ---
PROTOCOL_V1 = 0b0001
MSG_CLIENT_FULL_REQUEST = 0b0001
MSG_CLIENT_AUDIO_ONLY_REQUEST = 0b0010
MSG_SERVER_FULL_RESPONSE = 0b1001
MSG_SERVER_ERROR_RESPONSE = 0b1111
FLAG_POS_SEQ = 0b0001
FLAG_NEG_WITH_SEQ = 0b0011
SER_JSON = 0b0001
COMP_GZIP = 0b0001

SEGMENT_DURATION_MS = 200


def _header_bytes(msg_type: int, flags: int,
                  serialization: int = SER_JSON,
                  compression: int = COMP_GZIP) -> bytes:
    return bytes([
        (PROTOCOL_V1 << 4) | 1,  # 版本+header size(4bytes)
        (msg_type << 4) | flags,
        (serialization << 4) | compression,
        0x00,  # reserved
    ])


def _build_full_client_request(seq: int) -> bytes:
    payload = {
        "user": {"uid": "demo_uid"},
        "audio": {"format": "wav", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
        "request": {
            "model_name": MODEL_NAME,
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": True,
            "show_utterances": False,
            "enable_nonstream": True,  # 非流式
        },
    }
    body = gzip.compress(json.dumps(payload).encode("utf-8"))
    out = bytearray()
    out.extend(_header_bytes(MSG_CLIENT_FULL_REQUEST, FLAG_POS_SEQ))
    out.extend(struct.pack(">i", seq))
    out.extend(struct.pack(">I", len(body)))
    out.extend(body)
    return bytes(out)


def _build_audio_only(seq: int, segment: bytes, is_last: bool) -> bytes:
    flags = FLAG_NEG_WITH_SEQ if is_last else FLAG_POS_SEQ
    seq_val = -seq if is_last else seq
    body = gzip.compress(segment)
    out = bytearray()
    out.extend(_header_bytes(MSG_CLIENT_AUDIO_ONLY_REQUEST, flags))
    out.extend(struct.pack(">i", seq_val))
    out.extend(struct.pack(">I", len(body)))
    out.extend(body)
    return bytes(out)


def _parse_response(raw: bytes) -> tuple[int, bool, dict | None, int, str]:
    """返回 (message_type, is_last, payload_msg_dict, error_code, error_note)"""
    header_size = raw[0] & 0x0f
    message_type = raw[1] >> 4
    flags = raw[1] & 0x0f
    ser = raw[2] >> 4
    comp = raw[2] & 0x0f
    payload = raw[header_size * 4:]

    is_last = False
    if flags & 0x01:
        payload = payload[4:]  # skip seq
    if flags & 0x02:
        is_last = True
    if flags & 0x04:
        payload = payload[4:]

    code = 0
    if message_type == MSG_SERVER_FULL_RESPONSE:
        payload_size = struct.unpack(">I", payload[:4])[0]
        payload = payload[4:4 + payload_size]
    elif message_type == MSG_SERVER_ERROR_RESPONSE:
        code = struct.unpack(">i", payload[:4])[0]
        payload_size = struct.unpack(">I", payload[4:8])[0]
        payload = payload[8:8 + payload_size]

    if comp == COMP_GZIP and payload:
        try:
            payload = gzip.decompress(payload)
        except Exception:
            pass

    msg_dict = None
    if payload and ser == SER_JSON:
        try:
            msg_dict = json.loads(payload.decode("utf-8"))
        except Exception:
            msg_dict = None

    note = ""
    if code != 0 and isinstance(msg_dict, dict):
        note = str(msg_dict)
    return message_type, is_last, msg_dict, code, note


def _extract_text(payload: dict | None) -> str:
    """从服务端返回的 payload_msg 里抽出完整文本 (类似 doubao_asr._extract_transcript)"""
    if not isinstance(payload, dict):
        return ""
    result = payload.get("result")
    if isinstance(result, dict):
        t = result.get("text")
        if isinstance(t, str) and t.strip():
            return t.strip()
        utts = result.get("utterances")
        if isinstance(utts, list):
            parts = [u.get("text", "").strip() for u in utts
                     if isinstance(u, dict) and isinstance(u.get("text"), str)]
            joined = "".join(parts).strip()
            if joined:
                return joined
    if isinstance(result, list):
        parts = [u.get("text", "").strip() for u in result
                 if isinstance(u, dict) and isinstance(u.get("text"), str)]
        joined = "".join(parts).strip()
        if joined:
            return joined
    # 兜底: 递归搜 "text"
    def _dive(x: Any) -> list[str]:
        acc = []
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("text", "transcript", "sentence") and isinstance(v, str) and v.strip():
                    acc.append(v.strip())
                else:
                    acc.extend(_dive(v))
        elif isinstance(x, list):
            for it in x:
                acc.extend(_dive(it))
        return acc
    return "".join(_dive(payload)).strip()


def _wav_frames_size(data: bytes) -> tuple[int, int, int]:
    """解析 wav 头, 返回 (channels, sample_width_bytes, sample_rate)"""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a valid WAV file")
    channels = struct.unpack("<H", data[22:24])[0]
    sample_rate = struct.unpack("<I", data[24:28])[0]
    bits = struct.unpack("<H", data[34:36])[0]
    return channels, bits // 8, sample_rate


async def _transcribe_async(audio_path: Path, session: aiohttp.ClientSession) -> tuple[str, str]:
    """执行一次识别, 返回 (text, error_msg). error_msg 空表示成功。

    参考原 sauc_websocket_demo 的架构: 发送和接收并发, 服务端最终返回 is_last_package。
    """
    content = audio_path.read_bytes()
    channels, sample_width, sample_rate = _wav_frames_size(content)
    size_per_sec = channels * sample_width * sample_rate
    segment_size = size_per_sec * SEGMENT_DURATION_MS // 1000

    headers = {
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Access-Key": ACCESS_TOKEN,
        "X-Api-App-Key": APP_ID,
    }
    ws = await session.ws_connect(WSS_URL, headers=headers, timeout=aiohttp.ClientWSTimeout(30))
    try:
        # 1. full client request
        seq = 1
        await ws.send_bytes(_build_full_client_request(seq))
        first = await ws.receive(timeout=30)
        if first.type != aiohttp.WSMsgType.BINARY:
            return "", f"unexpected first response type: {first.type}"

        segments = [content[i:i + segment_size] for i in range(0, len(content), segment_size)]
        if not segments:
            segments = [b""]

        text_final = ""
        error_msg = ""

        async def sender():
            nonlocal seq
            for idx, seg in enumerate(segments):
                seq += 1
                is_last = (idx == len(segments) - 1)
                await ws.send_bytes(_build_audio_only(seq, seg, is_last))
                if not is_last:
                    await asyncio.sleep(SEGMENT_DURATION_MS / 1000.0)

        async def receiver():
            nonlocal text_final, error_msg
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive(), timeout=30)
                except asyncio.TimeoutError:
                    error_msg = "server response timeout (30s)"
                    return
                if msg.type != aiohttp.WSMsgType.BINARY:
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                    aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                        return
                    continue
                mtype, is_final, payload_msg, code, note = _parse_response(msg.data)
                if code != 0:
                    error_msg = f"server error code={code} note={note[:200]}"
                    return
                t = _extract_text(payload_msg)
                if t:
                    text_final = t
                if is_final:
                    return

        # 发送和接收并发
        send_task = asyncio.create_task(sender())
        recv_task = asyncio.create_task(receiver())
        try:
            await asyncio.wait_for(asyncio.gather(send_task, recv_task, return_exceptions=True),
                                   timeout=60)
        except asyncio.TimeoutError:
            error_msg = error_msg or "overall timeout (60s)"

        return text_final, error_msg
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def _run_once(audio_path: Path) -> tuple[str, str]:
    async with aiohttp.ClientSession() as sess:
        return await _transcribe_async(audio_path, sess)


class DoubaoSAUCASRRecognizer(BaseRecognizer):
    """豆包 SAUC WebSocket nostream 非流式 ASR。"""

    name = "doubao_sauc_asr"
    display_name = "Doubao_SAUC_Nostream"
    is_local_gpu = False  # 云端 WS, 可 --workers 并发

    def setup(self) -> None:
        # WS 每次 recognize 内部建连接, 不需要提前 warm
        return

    def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
        started = time.perf_counter()
        try:
            ap = Path(audio_path)
            if not ap.exists():
                raise FileNotFoundError(audio_path)

            # 每个线程/调用起自己的 event loop
            try:
                text, err = asyncio.run(_run_once(ap))
            except RuntimeError:
                # 已有 loop 时创建新 loop
                loop = asyncio.new_event_loop()
                try:
                    text, err = loop.run_until_complete(_run_once(ap))
                finally:
                    loop.close()

            elapsed = round(time.perf_counter() - started, 2)
            if err:
                return RecognitionResult(text="", elapsed_sec=elapsed,
                                         status="error", error=err)
            if not text:
                return RecognitionResult(text="", elapsed_sec=elapsed,
                                         status="error", error="识别结果为空")
            return RecognitionResult(text=text, elapsed_sec=elapsed)
        except Exception as exc:  # noqa: BLE001
            elapsed = round(time.perf_counter() - started, 2)
            return RecognitionResult(text="", elapsed_sec=elapsed,
                                     status="error", error=str(exc))
