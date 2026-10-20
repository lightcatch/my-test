# -*- coding: utf-8 -*-
"""GLM-ASR-Nano 识别器封装 (zai-org/GLM-ASR-Nano-2512)。

复用 ASR_test/glm_asr_cli.py 里的核心推理逻辑:
- 用 transformers.AutoProcessor + GlmAsrForConditionalGeneration
- 走 prompt="Transcribe the input speech."
- 输入按 processor.feature_extractor.sampling_rate 重采样到模型期望频率
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
from scipy.io import wavfile  # type: ignore
from scipy.signal import resample_poly  # type: ignore

from .base import BaseRecognizer, RecognitionResult


DEFAULT_MODEL_ID = "zai-org/GLM-ASR-Nano-2512"
TRANSCRIPTION_PROMPT = "Transcribe the input speech."
REPETITION_PENALTY = 1.1


def _read_wav_float32(audio_path: str | Path, target_sr: int) -> np.ndarray:
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


class GLMASRRecognizer(BaseRecognizer):
    """GLM-ASR-Nano-2512 本地 GPU 模型。language 参数 GLM 不用, 接受但忽略。"""

    name = "glm_asr"
    display_name = "GLM_ASR"
    is_local_gpu = True

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        device: str = "cuda",
        max_new_tokens: int = 500,
    ) -> None:
        self.model_id = model_id
        self.device = device
        self.max_new_tokens = max_new_tokens
        self._processor = None
        self._model = None
        self._torch = None

    def setup(self) -> None:
        if self._model is not None:
            return
        import torch  # type: ignore
        from transformers import AutoProcessor, GlmAsrForConditionalGeneration  # type: ignore

        self._torch = torch
        device = self.device
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用, 请 --device cpu 或重新装支持 CUDA 的 torch")
        dtype = torch.float16 if device == "cuda" else torch.float32
        self._processor = AutoProcessor.from_pretrained(self.model_id)
        model = GlmAsrForConditionalGeneration.from_pretrained(
            self.model_id, torch_dtype=dtype, use_safetensors=True,
        )
        self._model = model.to(device).eval()

    def _prepare(self, inputs: Any) -> dict[str, Any]:
        torch = self._torch
        model = self._model
        out: dict[str, Any] = {}
        for k, v in inputs.items():
            if isinstance(v, torch.Tensor):  # type: ignore[union-attr]
                if torch.is_floating_point(v):  # type: ignore[union-attr]
                    out[k] = v.to(device=model.device, dtype=model.dtype)  # type: ignore[union-attr]
                else:
                    out[k] = v.to(device=model.device)  # type: ignore[union-attr]
            else:
                out[k] = v
        return out

    def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
        if self._model is None:
            self.setup()
        torch = self._torch
        processor = self._processor
        model = self._model

        started = time.perf_counter()
        try:
            target_sr = processor.feature_extractor.sampling_rate  # type: ignore[union-attr]
            audio = _read_wav_float32(audio_path, target_sr)
            inputs = processor.apply_transcription_request(  # type: ignore[union-attr]
                audio, prompt=TRANSCRIPTION_PROMPT,
            )
            prepared = self._prepare(inputs)
            input_ids = prepared.get("input_ids")
            if not isinstance(input_ids, torch.Tensor):  # type: ignore[union-attr]
                raise RuntimeError("processor 没返回 input_ids")
            if model.device.type == "cuda":  # type: ignore[union-attr]
                torch.cuda.synchronize()  # type: ignore[union-attr]
            with torch.inference_mode():  # type: ignore[union-attr]
                outputs = model.generate(  # type: ignore[union-attr]
                    **prepared,
                    do_sample=False,
                    max_new_tokens=self.max_new_tokens,
                    repetition_penalty=REPETITION_PENALTY,
                    eos_token_id=model.generation_config.eos_token_id,  # type: ignore[union-attr]
                    pad_token_id=processor.tokenizer.pad_token_id,  # type: ignore[union-attr]
                )
            if model.device.type == "cuda":  # type: ignore[union-attr]
                torch.cuda.synchronize()  # type: ignore[union-attr]
            decoded = processor.batch_decode(  # type: ignore[union-attr]
                outputs[:, input_ids.shape[1]:],
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
