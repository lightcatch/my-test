# -*- coding: utf-8 -*-
"""FireRedASR2-AED 识别器封装 (复用 ASR_test/fire_red_asr 里的 fireredasr2)."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from .base import BaseRecognizer, RecognitionResult


FIRE_RED_DIR = Path(__file__).resolve().parents[2] / "fire_red_asr"
DEFAULT_MODEL_DIR = FIRE_RED_DIR / "pretrained_models" / "FireRedASR2-AED"


def _normalize_text(text: Any) -> str:
    if isinstance(text, (list, tuple)):
        return " ".join(str(item).strip() for item in text if str(item).strip())
    return str(text).strip()


class FireRedASRRecognizer(BaseRecognizer):
    """FireRedASR2-AED 本地 GPU 模型 (普通话 + 多方言 + 英文)。

    language 参数对它没作用 (AED 自动判别), 仍接受但忽略。
    """

    name = "fire_red_asr"
    display_name = "fire_red_ASR"
    is_local_gpu = True

    def __init__(
        self,
        model_dir: Path | None = None,
        use_gpu: bool = True,
        use_half: bool = False,
        beam_size: int = 3,
        decode_max_len: int = 300,
    ) -> None:
        self.model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
        self.use_gpu = use_gpu
        self.use_half = use_half
        self.beam_size = beam_size
        self.decode_max_len = decode_max_len
        self._model = None

    def setup(self) -> None:
        if self._model is not None:
            return
        # fireredasr2 库放在 examples_infer/asr 下, 包名 fireredasr2
        src_dir = FIRE_RED_DIR / "examples_infer" / "asr"
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))

        required = ["model.pth.tar", "cmvn.ark", "dict.txt", "train_bpe1000.model"]
        missing = [f for f in required if not (self.model_dir / f).is_file()]
        too_small = [
            f for f in ("model.pth.tar",)
            if (self.model_dir / f).is_file() and (self.model_dir / f).stat().st_size < 1_000_000
        ]
        if missing or too_small:
            raise FileNotFoundError(
                f"FireRedASR2-AED 权重不完整。缺失={missing} 疑似LFS指针={too_small}\n"
                f"期望目录: {self.model_dir}"
            )

        from fireredasr2.asr import FireRedAsr2, FireRedAsr2Config  # type: ignore

        config = FireRedAsr2Config(
            use_gpu=self.use_gpu,
            use_half=self.use_half,
            beam_size=self.beam_size,
            decode_max_len=self.decode_max_len,
        )
        self._model = FireRedAsr2.from_pretrained("aed", str(self.model_dir), config)

    def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
        if self._model is None:
            self.setup()
        started = time.perf_counter()
        try:
            uid = Path(audio_path).stem
            results = self._model.transcribe([uid], [str(audio_path)])  # type: ignore[union-attr]
            result = results[0] if results else {}
            text = _normalize_text(result.get("text", ""))
            extras = {
                "confidence": result.get("confidence", ""),
                "dur_s": result.get("dur_s", ""),
                "rtf": result.get("rtf", ""),
            }
            elapsed = round(time.perf_counter() - started, 2)
            if not text:
                return RecognitionResult(
                    text="", elapsed_sec=elapsed,
                    status="error", error="识别结果为空", extras=extras,
                )
            return RecognitionResult(text=text, elapsed_sec=elapsed, extras=extras)
        except Exception as exc:  # noqa: BLE001
            elapsed = round(time.perf_counter() - started, 2)
            return RecognitionResult(
                text="", elapsed_sec=elapsed, status="error", error=str(exc),
            )
