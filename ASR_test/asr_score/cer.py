# -*- coding: utf-8 -*-
"""字错率 CER 计算工具 (中英混合友好)。

对齐规则:
- 文本规范化: 全角->半角, 字母小写, 标点替换成空格 (不再去掉)
- 切分粒度: 中文/日文等 CJK 按"字"算, 英文/数字按"词" (用空格分隔), 其它单字
- N 取参考序列长度。空格本身不计入。
- 公式: (S + D + I) / N * 100% (业内常称 mixed error rate / MER, 中文场景与 CER 等价)

这样:
  纯中文 -> CER
  纯英文 -> WER
  中英混合 -> 中文按字, 英文按词
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# 标点 (中英文)。会被替换成空格, 不会和相邻 token 粘连。
_PUNCT_PATTERN = re.compile(
    r"["
    r",.!?;:\"'`~@#$%^&*()_+\-=\[\]{}|\\/<>"
    r"，。！？；：、""''《》【】（）—…·"
    r"]"
)

# 一个"字符 token"的判定:
# - CJK 统一汉字 / 扩展区 / 兼容汉字 / 假名 (按字算)
# - 阿拉伯/中东等也按字算更稳, 这里按 CJK 处理即可
_CJK_RANGES = (
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Extension A
    (0x20000, 0x2A6DF),  # CJK Extension B
    (0x2A700, 0x2B73F),  # CJK Extension C
    (0x2B740, 0x2B81F),  # CJK Extension D
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x3040, 0x309F),    # Hiragana
    (0x30A0, 0x30FF),    # Katakana
)


def _is_cjk_char(ch: str) -> bool:
    cp = ord(ch)
    for lo, hi in _CJK_RANGES:
        if lo <= cp <= hi:
            return True
    return False


def normalize_text(text: str) -> str:
    """规范化: NFKC + 小写 + 标点替空格 + 折叠多空格。"""
    if text is None:
        return ""
    text = unicodedata.normalize("NFKC", str(text))
    text = _PUNCT_PATTERN.sub(" ", text)
    text = text.lower()
    # 折叠空白
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tokenize(text: str) -> list[str]:
    """切分为 token 列表:
    - CJK 字符: 每个字一个 token
    - 英文/数字: 连续段为一个 token (按词)
    - 其它单字 (希腊字母, 符号, 表情等): 每个一个 token
    - 空格只做分隔, 不进入 token
    """
    tokens: list[str] = []
    buf: list[str] = []

    def flush_word() -> None:
        if buf:
            tokens.append("".join(buf))
            buf.clear()

    for ch in text:
        if ch.isspace():
            flush_word()
            continue
        if _is_cjk_char(ch):
            flush_word()
            tokens.append(ch)
        elif ch.isalnum():
            buf.append(ch)
        else:
            # 其它符号 (本来标点已替成空格了, 这里很少进)
            flush_word()
            tokens.append(ch)
    flush_word()
    return tokens


@dataclass
class CERResult:
    s: int  # substitutions
    d: int  # deletions
    i: int  # insertions
    n: int  # reference length
    cer: float  # 百分数, 保留 2 位

    @property
    def total_errors(self) -> int:
        return self.s + self.d + self.i


def compute_cer(ref: str, hyp: str) -> CERResult:
    """计算 mixed CER, 返回 S/D/I/N/CER。"""
    ref_norm = normalize_text(ref)
    hyp_norm = normalize_text(hyp)
    ref_tokens = tokenize(ref_norm)
    hyp_tokens = tokenize(hyp_norm)

    n = len(ref_tokens)
    m = len(hyp_tokens)

    if n == 0:
        return CERResult(s=0, d=0, i=m, n=0, cer=0.0)

    INF = float("inf")
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        ri = ref_tokens[i - 1]
        for j in range(1, m + 1):
            if ri == hyp_tokens[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(
                    dp[i - 1][j - 1],  # 替换
                    dp[i - 1][j],      # 删除
                    dp[i][j - 1],      # 插入
                )

    s = d = ins = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref_tokens[i - 1] == hyp_tokens[j - 1]:
            i -= 1
            j -= 1
            continue
        sub_cost = dp[i - 1][j - 1] if i > 0 and j > 0 else INF
        del_cost = dp[i - 1][j] if i > 0 else INF
        ins_cost = dp[i][j - 1] if j > 0 else INF
        best = min(sub_cost, del_cost, ins_cost)
        if best == sub_cost:
            s += 1
            i -= 1
            j -= 1
        elif best == del_cost:
            d += 1
            i -= 1
        else:
            ins += 1
            j -= 1

    cer = round((s + d + ins) / n * 100.0, 2)
    return CERResult(s=s, d=d, i=ins, n=n, cer=cer)


if __name__ == "__main__":
    cases = [
        # 纯中文: 按字
        ("在孩子记忆最清晰的时候完成记错", "在孩子记忆最清晰的时候，完成记错。"),
        ("计息起始日为可转债发行首日", "计息起始日为可转债发行手日"),
        # 纯英文: 按词
        ("hello world", "Hello, World!"),
        ("Where will you go", "Where will you go?"),
        ("The Beatles were famous English", "The beatles were famouz English"),
        # 中英混合
        ("我有一个 apple 和 banana", "我有1个 apple 和 banana"),
        # 数字
        ("abc 123", "abc 124"),
        # 空参考
        ("", "anything"),
    ]
    for ref, hyp in cases:
        r = compute_cer(ref, hyp)
        print(f"N={r.n:>3}  S={r.s}  D={r.d}  I={r.i}  CER={r.cer:>6}%   ref={ref!r}  hyp={hyp!r}")
