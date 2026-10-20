# -*- coding: utf-8 -*-
"""ARK-ASR-0.6B 识别器封装 (AutoArk-AI/ARK-ASR-0.6B)。

依赖 transformers 加 trust_remote_code=True 加载自定义 ArkasrForConditionalGeneration。
采样率固定 16k, 单条 audio_max_length = 30s (与官方 README 推理脚本一致)。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import wavfile  # type: ignore
from scipy.signal import resample_poly  # type: ignore

from .base import BaseRecognizer, RecognitionResult


DEFAULT_MODEL_ID = "AutoArk-AI/ARK-ASR-0.6B"
SAMPLE_RATE = 16000
AUDIO_MAX_LENGTH = 30 * SAMPLE_RATE  # 30s
DEFAULT_PROMPT = "Please transcribe this audio."


def _read_wav_float32(audio_path: str | Path, target_sr: int = SAMPLE_RATE) -> np.ndarray:
    sr, audio = wavfile.read(str(audio_path))
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if np.issubdtype(audio.dtype, np.integer):
        info = np.iinfo(audio.dtype)
        scale = float(max(abs(info.min), abs(info.max)))
        audio = audio.astype(np.float32) / scale
    elif np.issubdtype(audio.dtype, np.floating):
        audio = audio.astype(np.float32, copy=False)
    else:
        raise ValueError(f"unsupported wav dtype: {audio.dtype}")
    if sr != target_sr:
        audio = resample_poly(audio, target_sr, sr).astype(np.float32)
    return np.clip(audio, -1.0, 1.0).astype(np.float32, copy=False)


def _build_bad_words_ids(tokenizer) -> list[list[int]]:
    eos_ids = tokenizer.eos_token_id
    keep_ids = {eos_ids} if isinstance(eos_ids, int) else set(eos_ids or [])
    bad_ids = set(tokenizer.all_special_ids) - keep_ids
    bad_ids.update(
        token_id
        for token, token_id in tokenizer.get_added_vocab().items()
        if token.startswith("<") and token.endswith(">") and token_id not in keep_ids
    )
    return [[token_id] for token_id in sorted(bad_ids)]


class ARKASRRecognizer(BaseRecognizer):
    """ARK-ASR-0.6B (AutoArk-AI). 中文 + 19 种语言 ASR, 学生模型, Qwen2 解码器 + Whisper 编码器。"""

    name = "ark_asr"
    display_name = "ARK_ASR"
    is_local_gpu = True

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        device: str = "cuda",
        max_new_tokens: int = 256,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.max_new_tokens = max_new_tokens
        self._processor = None
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._bad_words_ids: list[list[int]] = []

    def setup(self) -> None:
        if self._model is not None:
            return
        import torch  # type: ignore
        from transformers import AutoModelForCausalLM, AutoProcessor, AutoTokenizer  # type: ignore

        self._torch = torch
        if self.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用, 请 --device cpu 或重装支持 CUDA 的 torch")
        dtype = torch.float16 if self.device == "cuda" else torch.float32

        self._processor = AutoProcessor.from_pretrained(self.model_id, trust_remote_code=True)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, trust_remote_code=True)
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            trust_remote_code=True,
            torch_dtype=dtype,
            attn_implementation="sdpa",
        ).to(self.device)
        self._model.eval()
        self._bad_words_ids = _build_bad_words_ids(self._tokenizer)

    def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
        if self._model is None:
            self.setup()
        torch = self._torch
        processor = self._processor
        tokenizer = self._tokenizer
        model = self._model

        started = time.perf_counter()
        try:
            # 校验 wav 存在
            ap = Path(audio_path)
            if not ap.exists():
                raise FileNotFoundError(audio_path)

            conversation = [
                {
                    "role": "user",
                    "content": [
                        {"type": "audio", "path": str(ap)},
                        {"type": "text", "text": DEFAULT_PROMPT},
                    ],
                }
            ]
            inputs = processor.apply_chat_template(
                conversation,
                add_generation_prompt=True,
                return_tensors="pt",
                sampling_rate=SAMPLE_RATE,
                audio_padding="longest",
                text_kwargs={"padding": "longest"},
                audio_max_length=AUDIO_MAX_LENGTH,
            )
            inputs = inputs.to(self.device)
            # audios 张量统一到模型 dtype, 防止 fp16/fp32 不匹配
            if "audios" in inputs:
                inputs["audios"] = inputs["audios"].to(dtype=model.dtype)

            with torch.inference_mode():
                outputs = model.generate(
                    **inputs,
                    do_sample=False,
                    max_new_tokens=self.max_new_tokens,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                    bad_words_ids=self._bad_words_ids,
                )
            decoded = tokenizer.batch_decode(
                outputs[:, inputs.input_ids.shape[1]:],
                skip_special_tokens=True,
            )
            text = (decoded[0].strip() if decoded else "")
            elapsed = round(time.perf_counter() - started, 2)
            if not text:
                return RecognitionResult(text="", elapsed_sec=elapsed,
                                         status="error", error="识别结果为空")
            return RecognitionResult(text=text, elapsed_sec=elapsed)
        except Exception as exc:  # noqa: BLE001
            elapsed = round(time.perf_counter() - started, 2)
            return RecognitionResult(text="", elapsed_sec=elapsed,
                                     status="error", error=str(exc))
