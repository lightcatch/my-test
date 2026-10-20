# -*- coding: utf-8 -*-
"""Mega-ASR 识别器封装 (复用 ASR_test/mega_asr 里的 MegaASR 实现)。"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from .base import BaseRecognizer, RecognitionResult


MEGA_ASR_DIR = Path(__file__).resolve().parents[2] / "mega_asr"

# Mega-ASR 支持的语种全名, 接受常见短码 (zh / en / yue 等)
_LANGUAGE_ALIAS = {
    "zh": "Chinese", "zh-cn": "Chinese", "cn": "Chinese", "chinese": "Chinese",
    "en": "English", "english": "English",
    "yue": "Cantonese", "cantonese": "Cantonese",
    "ja": "Japanese", "ko": "Korean",
    "ru": "Russian", "ar": "Arabic", "de": "German", "fr": "French",
    "es": "Spanish", "pt": "Portuguese", "it": "Italian",
    "id": "Indonesian", "th": "Thai", "vi": "Vietnamese",
    "tr": "Turkish", "hi": "Hindi", "ms": "Malay", "nl": "Dutch",
    "sv": "Swedish", "da": "Danish", "fi": "Finnish", "pl": "Polish",
    "cs": "Czech", "fa": "Persian", "el": "Greek", "ro": "Romanian",
    "hu": "Hungarian", "mk": "Macedonian", "fil": "Filipino",
}


def _resolve_language(language: str | None) -> str | None:
    if not language:
        return None
    key = language.strip().lower()
    return _LANGUAGE_ALIAS.get(key, language)


def _normalize_text(text: Any) -> str:

    if isinstance(text, (list, tuple)):
        return " ".join(str(item).strip() for item in text if str(item).strip())
    return str(text).strip()


class MegaASRRecognizer(BaseRecognizer):
    name = "mega_asr"
    display_name = "mega_ASR"
    is_local_gpu = True

    def __init__(
        self,
        ckpt_dir: Path | None = None,
        device_map: str = "cuda",
        routing_enabled: bool = True,
        quality_threshold: float = 0.5,
    ) -> None:
        self.ckpt_dir = Path(ckpt_dir) if ckpt_dir else MEGA_ASR_DIR / "ckpt" / "Mega-ASR"
        self.device_map = device_map
        self.routing_enabled = routing_enabled
        self.quality_threshold = quality_threshold
        self._model = None

    def setup(self) -> None:
        if self._model is not None:
            return
        src_dir = MEGA_ASR_DIR / "src"
        if str(src_dir) not in sys.path:
            sys.path.insert(0, str(src_dir))
        base = self.ckpt_dir / "Qwen3-ASR-1.7B"
        lora = self.ckpt_dir / "mega-asr-merged"
        router = self.ckpt_dir / "audio_quality_router" / "best_acc_model.safetensors"
        if not base.exists() or not lora.exists():
            raise FileNotFoundError(
                "未找到 Mega-ASR 模型权重: \n"
                f"  期望: {base} 和 {lora}\n"
                "  请先运行 ASR_test/mega_asr/scripts/download.py 下载权重。"
            )

        from MegaASR.model.megaASR import MegaASR  # type: ignore

        self._model = MegaASR(
            model_path=base,
            lora_dir=lora,
            router_checkpoint=router,
            routing_enabled=self.routing_enabled,
            quality_threshold=self.quality_threshold,
            device_map=self.device_map,
            backend="transformers",
        )

    def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
        if self._model is None:
            self.setup()
        started = time.perf_counter()
        try:
            result = self._model.infer(  # type: ignore[union-attr]
                str(audio_path),
                language=_resolve_language(language),
                return_route=True,
            )
            text = _normalize_text(result.get("text", ""))
            extras = {
                "use_lora": result.get("use_lora", ""),
                "degraded_prob": result.get("degraded_prob", ""),
                "route_source": result.get("route_source", ""),
            }
            elapsed = round(time.perf_counter() - started, 2)
            if not text:
                return RecognitionResult(
                    text="",
                    elapsed_sec=elapsed,
                    status="error",
                    error="识别结果为空",
                    extras=extras,
                )
            return RecognitionResult(text=text, elapsed_sec=elapsed, extras=extras)
        except Exception as exc:  # noqa: BLE001
            elapsed = round(time.perf_counter() - started, 2)
            return RecognitionResult(
                text="",
                elapsed_sec=elapsed,
                status="error",
                error=str(exc),
            )
