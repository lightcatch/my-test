# -*- coding: utf-8 -*-
"""SenseVoiceSmall ONNX INT8 识别器封装 (k2-fsa sherpa-onnx)。

- 底层模型: FunAudioLLM/SenseVoiceSmall (234M), ONNX INT8 量化版
- 推理引擎: sherpa-onnx (CPU, onnxruntime), 不依赖 PyTorch
- 支持: zh / en / ja / ko / yue, 16k mono
- 模型权重路径: ASR_test/sense_voice_onnx/model/
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import soundfile as sf  # type: ignore

from .base import BaseRecognizer, RecognitionResult


MODEL_DIR = Path(__file__).resolve().parents[2] / "sense_voice_onnx" / "model"
MODEL_FILE = MODEL_DIR / "model.int8.onnx"
TOKENS_FILE = MODEL_DIR / "tokens.txt"

# sherpa-onnx 接受的 language code
_LANG_MAP = {
    "zh": "zh", "yue": "zh",   # 粤语在 SenseVoice 里也作为 zh 处理 (内部会识别)
    "en": "en", "ja": "ja", "ko": "ko",
    "auto": "auto", "": "auto", None: "auto",
}


def _resolve_lang(lang: str | None) -> str:
    if lang is None:
        return "auto"
    return _LANG_MAP.get(lang.strip().lower(), "auto")


class SenseVoiceONNXRecognizer(BaseRecognizer):
    """SenseVoiceSmall ONNX INT8 量化版, sherpa-onnx 推理。"""

    name = "sense_voice_onnx"
    display_name = "SenseVoice_ONNX_INT8"
    # CPU 推理也很快, 视为非 GPU local; 但默认还是串行 (sherpa-onnx 自己内部多线程, 外层串行更稳)
    is_local_gpu = True

    def __init__(
        self,
        model_path: Path | None = None,
        tokens_path: Path | None = None,
        num_threads: int = 4,
        use_itn: bool = True,
        provider: str = "cpu",
    ) -> None:
        self.model_path = Path(model_path) if model_path else MODEL_FILE
        self.tokens_path = Path(tokens_path) if tokens_path else TOKENS_FILE
        self.num_threads = num_threads
        self.use_itn = use_itn
        self.provider = provider
        self._recognizer = None

    def setup(self) -> None:
        if self._recognizer is not None:
            return
        if not self.model_path.exists() or not self.tokens_path.exists():
            raise FileNotFoundError(
                f"SenseVoice ONNX 权重不全:\n  {self.model_path}\n  {self.tokens_path}"
            )
        import sherpa_onnx  # type: ignore

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(self.model_path),
            tokens=str(self.tokens_path),
            num_threads=self.num_threads,
            use_itn=self.use_itn,
            language="auto",  # 默认 auto, 行级语言通过 recognize() 时再覆盖
            provider=self.provider,
            debug=False,
        )

    def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
        if self._recognizer is None:
            self.setup()
        started = time.perf_counter()
        try:
            ap = Path(audio_path)
            if not ap.exists():
                raise FileNotFoundError(audio_path)

            audio, sr = sf.read(str(ap), dtype="float32", always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1).astype(np.float32, copy=False)

            # SenseVoice 训练在 16k, sherpa-onnx 不自重采样
            if sr != 16000:
                # 简单线性重采样作兜底; 我们数据集已经统一 16k 所以基本不会进入这里
                from scipy.signal import resample_poly  # type: ignore
                audio = resample_poly(audio, 16000, sr).astype(np.float32, copy=False)
                sr = 16000

            stream = self._recognizer.create_stream()  # type: ignore[union-attr]
            stream.accept_waveform(sr, audio)
            self._recognizer.decode_stream(stream)  # type: ignore[union-attr]
            text = stream.result.text.strip()

            elapsed = round(time.perf_counter() - started, 2)
            if not text:
                return RecognitionResult(text="", elapsed_sec=elapsed,
                                         status="error", error="识别结果为空")
            return RecognitionResult(text=text, elapsed_sec=elapsed)
        except Exception as exc:  # noqa: BLE001
            elapsed = round(time.perf_counter() - started, 2)
            return RecognitionResult(text="", elapsed_sec=elapsed,
                                     status="error", error=str(exc))
