# -*- coding: utf-8 -*-
"""FireRedASR2-AED ONNX INT8 识别器封装 (k2-fsa sherpa-onnx)。

- 底层模型: 小红书 FireRedTeam/FireRedASR2-AED, sherpa-onnx 转换的 ONNX INT8 量化版
- 推理引擎: sherpa-onnx (CPU, onnxruntime), 不依赖 PyTorch
- 支持: zh / en / 多方言, 16k mono
- 模型权重路径: ASR_test/fire_red_asr/pretrained_models/sherpa-onnx-fire-red-asr2-zh_en-int8-2026-02-26/

language 参数对它没作用 (AED 自动判别), 仍接受但忽略。
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import soundfile as sf  # type: ignore

from .base import BaseRecognizer, RecognitionResult


def _register_cuda_dll_dirs() -> None:
    """把 pip 装的 nvidia-*-cu12 wheel 里的 bin 目录加入 DLL 搜索路径。

    Windows 下 site-packages/nvidia/*/bin 默认不在搜索路径, 不加会报
    cublasLt64_12.dll missing。onnxruntime 通过导入表间接加载 CUDA 库,
    这类依赖只认 PATH, 所以两手都上: add_dll_directory + PATH 前插。
    仅在需要 CUDA provider 时调用。
    """
    try:
        import nvidia  # type: ignore
    except ImportError:
        return
    bins: list[str] = []
    for base in nvidia.__path__:  # type: ignore[attr-defined]
        if not os.path.isdir(base):
            continue
        for sub in os.listdir(base):
            binp = os.path.join(base, sub, "bin")
            if os.path.isdir(binp):
                bins.append(binp)
                try:
                    os.add_dll_directory(binp)
                except OSError:
                    pass
    if bins:
        os.environ["PATH"] = os.pathsep.join(bins) + os.pathsep + os.environ.get("PATH", "")


MODEL_DIR = (
    Path(__file__).resolve().parents[2]
    / "fire_red_asr"
    / "pretrained_models"
    / "sherpa-onnx-fire-red-asr2-zh_en-int8-2026-02-26"
)
ENCODER_FILE = MODEL_DIR / "encoder.int8.onnx"
DECODER_FILE = MODEL_DIR / "decoder.int8.onnx"
TOKENS_FILE = MODEL_DIR / "tokens.txt"


class FireRedASR2INT8Recognizer(BaseRecognizer):
    """FireRedASR2-AED ONNX INT8 量化版, sherpa-onnx 推理。"""

    name = "fire_red_asr2_int8"
    display_name = "FireRed2_ONNX_INT8"
    is_local_gpu = True

    def __init__(
        self,
        encoder_path: Path | None = None,
        decoder_path: Path | None = None,
        tokens_path: Path | None = None,
        num_threads: int = 4,
        provider: str = "cpu",
    ) -> None:
        self.encoder_path = Path(encoder_path) if encoder_path else ENCODER_FILE
        self.decoder_path = Path(decoder_path) if decoder_path else DECODER_FILE
        self.tokens_path = Path(tokens_path) if tokens_path else TOKENS_FILE
        self.num_threads = num_threads
        self.provider = provider
        self._recognizer = None

    def setup(self) -> None:
        if self._recognizer is not None:
            return
        missing = [p for p in (self.encoder_path, self.decoder_path, self.tokens_path)
                   if not p.exists()]
        if missing:
            raise FileNotFoundError(
                "FireRedASR2 ONNX INT8 权重不全:\n  " + "\n  ".join(str(p) for p in missing)
            )
        if self.provider == "cuda":
            _register_cuda_dll_dirs()
        import sherpa_onnx  # type: ignore

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_fire_red_asr(
            encoder=str(self.encoder_path),
            decoder=str(self.decoder_path),
            tokens=str(self.tokens_path),
            num_threads=self.num_threads,
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

            # FireRedASR 训练在 16k, sherpa-onnx 不自重采样; 数据集已统一 16k, 这里只做兜底
            if sr != 16000:
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
