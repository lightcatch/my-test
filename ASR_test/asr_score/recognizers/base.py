# -*- coding: utf-8 -*-
"""ASR 识别器统一接口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RecognitionResult:
    text: str = ""
    elapsed_sec: float = 0.0
    status: str = "success"  # success / error
    error: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


class BaseRecognizer:
    """所有 ASR 识别器都继承这个基类, 实现 recognize 即可。"""

    name: str = "base"
    #: 输出文件名后缀使用的显示名 (默认与 name 一致)
    display_name: str = ""
    #: True 表示底层是本地 GPU, 建议串行; False 表示是 HTTP/SaaS 接口, 适合并发
    is_local_gpu: bool = False

    def setup(self) -> None:  # pragma: no cover - 默认空实现
        """可选: 预加载模型 / 建会话等。多线程场景下会在主线程调一次。"""

    def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
        raise NotImplementedError

    def teardown(self) -> None:  # pragma: no cover - 默认空实现
        """可选: 释放资源。"""
