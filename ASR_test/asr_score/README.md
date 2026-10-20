# ASR 跑分操作指南

本文档面向新接手项目的 AI / 人。读完应该能：理解数据结构、选对 venv、跑出正确格式的打分结果，并新增一个 ASR 适配。

---

## 1. 目标

在 `downloaded_audio/integrated_dialects/` 下用 ASR 跑 15 个方言/噪声子集，输出符合"打分模版"结构的 Excel + 一个 `_summary.csv`，CER 用混合粒度（中文按字 / 英文按词 / 中英混合自动分别算）。

---

## 2. 数据结构约定

### 2.1 顶层目录

```
downloaded_audio/integrated_dialects/
├── dongbei/                 # 东北话, 200 条
├── en/                      # 英语, 200 条
├── erbao/                   # 二宝(角色专属), 20 条
├── henan/                   # 河南话, 200 条
├── mandarin/                # 普通话, 400 条
├── mixed_noise_dongbei/     # 东北话+噪音叠加, 100 条
├── mixed_noise_henan/       # 河南话+噪音叠加, 100 条
├── mixed_noise_shandong/    # 山东话+噪音叠加, 100 条
├── mixed_noise_sichuan/     # 四川话+噪音叠加, 100 条
├── mixed_noise_yue/         # 粤语+噪音叠加, 100 条
├── noises_en/               # 英文带噪音原始样本, 255 条
├── noises_zh/               # 中文带噪音原始样本, 245 条
├── shandong/                # 山东话, 200 条
├── sichuan/                 # 四川话, 200 条
├── yue/                     # 粤语, 200 条
├── 打分模版.xlsx            # 打分输出模板
├── 打分结果/                # ASR 输出位置
│   ├── mega_ASR/
│   ├── fire_red_ASR/
│   ├── GLM_ASR/
│   └── ARK_ASR/
└── (工具脚本: create_score_template.py / split_noises.py / resample_to_16k.py / restructure.py)
```

共 15 个子集 / 2625 条 wav，全部统一为 **16kHz / 16bit / mono**。

### 2.2 每个子集必须满足"三件套"

```
<subset>/
├── wav/                     # 16kHz / 16bit / mono 单声道
├── metadata.csv             # 表头固定 10 列, UTF-8 with BOM
└── xx_映射表.xlsx           # 给人看的可视化版, sheet 名 = metadata, 内容与 csv 一致
```

### 2.3 `metadata.csv` 表头（固定 10 列）

| 列名 | 说明 |
|---|---|
| 编号 | 全局唯一, 如 `dongbei_0001` |
| 语言 | 中文标签, 如 `东北话` / `英语` / `粤语` / `噪音_中文` |
| 文本 | 参考文本 (ground truth) |
| saved_path | wav 相对路径, 形如 `wav/xxx.wav` |
| 文件名 | wav 文件名 |
| 时长 | 秒, float |
| id | 内部 id |
| speaker_id | 说话人 id (如有) |
| sample_index | 子集内序号 |
| dialect | 英文方言标签 |

### 2.4 `打分模版.xlsx` 表头（固定 16 列）

前 10 列与 metadata 完全一致，再追加 6 列：

| 列号 | 列名 | 说明 |
|---:|---|---|
| 11 | 识别出的文字 | ASR 输出 (hypothesis) |
| 12 | 替换错误数S | substitutions |
| 13 | 删除错误数D | deletions |
| 14 | 插入错误数I | insertions |
| 15 | 参考总字数N | reference token 数 (按 7.2 切分) |
| 16 | 字错率CER(%) | `=IF(OR(N="",N=0),"",ROUND((S+D+I)/N*100,2))` 公式自动算 |

模板里 CER 列对前 200 行预置了公式。如需扩容，编辑 `create_score_template.py` 改 `PREFILL_ROWS` 后重跑。

---

## 3. 代码与目录

```
ASR_test/asr_score/
├── run_score.py             # 主入口
├── cer.py                   # CER 算法 (混合粒度)
├── merge_summary.py         # 合并多次跑批的 _summary
├── recognizers/
│   ├── base.py              # BaseRecognizer 接口
│   ├── mega_asr.py
│   ├── fire_red_asr.py
│   ├── glm_asr.py
│   ├── ark_asr.py
│   └── sense_voice_onnx.py
└── README.md                # 本文档
```

---

## 4. ASR 阵容（截至当前）

全部本地部署，断网可跑。每个 ASR 有自己的 venv 或共用项目根 venv，**不要乱混**。

| ASR | 输出后缀 | 适用 venv | 权重位置 |
|---|---|---|---|
| `mega_asr` (Mega-ASR Qwen3-ASR-1.7B + LoRA + 路由器) | `mega_ASR` | `ASR_test/mega_asr/.venv` | `ASR_test/mega_asr/ckpt/Mega-ASR/` |
| `fire_red_asr` (FireRedASR2-AED, 小红书) | `fire_red_ASR` | `ASR_test/fire_red_asr/.venv` | `ASR_test/fire_red_asr/pretrained_models/FireRedASR2-AED/` |
| `glm_asr` (GLM-ASR-Nano-2512, 智谱) | `GLM_ASR` | `d:\PyCode\test\.venv` (项目根) | HF cache: `~/.cache/huggingface/hub/models--zai-org--GLM-ASR-Nano-2512` |
| `ark_asr` (ARK-ASR-0.6B, AutoArk; Qwen2 decoder + Whisper encoder; 中 + 18 种语言) | `ARK_ASR` | `d:\PyCode\test\.venv` (项目根; 需额外装 `librosa soundfile`) | HF cache: `~/.cache/huggingface/hub/models--AutoArk-AI--ARK-ASR-0.6B` |
| `sense_voice_onnx` (SenseVoiceSmall 234M, k2-fsa ONNX INT8 量化, sherpa-onnx 推理; 中/英/日/韩/粤; CPU 也飞快) | `SenseVoice_ONNX_INT8` | `ASR_test/sense_voice_onnx/.venv` (依赖 sherpa-onnx + soundfile + openpyxl) | `ASR_test/sense_voice_onnx/model/model.int8.onnx` + `tokens.txt` |

特性：

- **mega_asr / glm_asr / ark_asr** 都用 transformers，本身会处理重采样到模型需要的频率。
- **fire_red_asr** 期望输入 16kHz，**不自重采样**；非 16k wav 直接喂会输出空字符串。已经通过 `resample_to_16k.py` 把数据集统一到 16k。
- **sense_voice_onnx** 是 sherpa-onnx 引擎纯 CPU 推理（onnxruntime + INT8 量化），不依赖 PyTorch/CUDA，**RTF ≈ 0.02**（每条音频 0.15–0.3s），跑完 2625 条只要 10 分钟，是目前阵容里最快的。
- 五家都是 `is_local_gpu = True`，runner 自动强制 workers=1。

---

## 5. 跑批命令

### 5.1 全量跑（推荐）

```powershell
# Mega-ASR
ASR_test\mega_asr\.venv\Scripts\python.exe -X utf8 `
  ASR_test\asr_score\run_score.py `
  --root downloaded_audio\integrated_dialects `
  --asr mega_asr --device cuda --language auto `
  --out-dir downloaded_audio\integrated_dialects\打分结果\mega_ASR

# FireRedASR
ASR_test\fire_red_asr\.venv\Scripts\python.exe -X utf8 `
  ASR_test\asr_score\run_score.py `
  --root downloaded_audio\integrated_dialects `
  --asr fire_red_asr --device cuda --language auto `
  --out-dir downloaded_audio\integrated_dialects\打分结果\fire_red_ASR

# GLM-ASR-Nano (用项目根 venv, 因为依赖 transformers >= 5.6 dev)
.venv\Scripts\python.exe -X utf8 `
  ASR_test\asr_score\run_score.py `
  --root downloaded_audio\integrated_dialects `
  --asr glm_asr --device cuda --language auto `
  --out-dir downloaded_audio\integrated_dialects\打分结果\GLM_ASR

# ARK-ASR-0.6B (用项目根 venv; 依赖 librosa + soundfile, 没装请 `uv pip install librosa soundfile`)
.venv\Scripts\python.exe -X utf8 `
  ASR_test\asr_score\run_score.py `
  --root downloaded_audio\integrated_dialects `
  --asr ark_asr --device cuda --language auto `
  --out-dir downloaded_audio\integrated_dialects\打分结果\ARK_ASR

# SenseVoice ONNX INT8 (sherpa-onnx, CPU 推理飞快, RTF~0.02)
ASR_test\sense_voice_onnx\.venv\Scripts\python.exe -X utf8 `
  ASR_test\asr_score\run_score.py `
  --root downloaded_audio\integrated_dialects `
  --asr sense_voice_onnx --device cpu --language auto `
  --out-dir downloaded_audio\integrated_dialects\打分结果\SenseVoice_ONNX_INT8
```

跑完之后合并 summary（每个 ASR 目录独立合并）：

```powershell
.venv\Scripts\python.exe -X utf8 ASR_test\asr_score\merge_summary.py `
  downloaded_audio\integrated_dialects\打分结果\mega_ASR `
  downloaded_audio\integrated_dialects\打分结果\fire_red_ASR `
  downloaded_audio\integrated_dialects\打分结果\GLM_ASR `
  downloaded_audio\integrated_dialects\打分结果\ARK_ASR
```

`merge_summary.py` 会把零散 `_summary_<时间戳>.csv` 合并为 `_summary.csv`，按 (name, language) 去重保留最新结果，然后删除时间戳文件。如果目录里已经有 `_summary.csv`，也会一并并入，不会丢历史。

### 5.2 调试用 / 跑某一两个子集

```powershell
# 只跑 dongbei 前 5 条 (smoke test)
ASR_test\mega_asr\.venv\Scripts\python.exe -X utf8 `
  ASR_test\asr_score\run_score.py `
  --root downloaded_audio\integrated_dialects `
  --include /dongbei/ --exclude mixed_noise `
  --asr mega_asr --device cuda --language auto --limit 5 `
  --out-dir downloaded_audio\integrated_dialects\打分结果\mega_ASR_smoke
```

参数说明：

- `--include` / `--exclude`：按 `metadata.csv` 相对路径子串匹配；`/dongbei/` 形式可避免命中 `mixed_noise_dongbei`。
- `--language`：默认 `auto`，**行级**按参考文本判断 zh/en/yue。也可显式 `zh` / `en` / `yue`；空字符串让模型自判。
- `--limit N`：每个子集最多跑 N 条，用于 smoke test。
- `--workers`：本地 GPU 自动强制 1；接口型 ASR 才会用到这个参数。

跑完一定要清理 smoke 产物：

```powershell
Remove-Item 'downloaded_audio\integrated_dialects\打分结果\mega_ASR_smoke' -Recurse -Force
```

### 5.3 走 HF 代理下载权重

新模型首次跑会自动从 Hugging Face 下权重，国内通常需要代理：

```powershell
$env:https_proxy="http://127.0.0.1:7897"
$env:http_proxy="http://127.0.0.1:7897"
# 然后再跑 run_score.py / huggingface-cli download
```

---

## 6. 输出格式约定

每个 ASR 的输出目录都长这样：

```
打分结果/<DisplayName>/
├── dongbei_<DisplayName>.xlsx           # 每个子集一个, 表头 16 列
├── en_<DisplayName>.xlsx
├── ...
└── _summary.csv                          # 15 行汇总, 列: name,language,total,success,avg_cer,elapsed_sec,out_path
```

每个 Excel：
- Sheet 名固定 `metadata`，第 1 行表头与 `打分模版.xlsx` 一致。
- 前 10 列复制自 `metadata.csv`。
- 第 11 列 `识别出的文字` 写 ASR 原始输出（不做大小写/标点处理；CER 内部会标准化）。
- 第 12–15 列 S/D/I/N 是按 `cer.compute_cer` 算出来的整数。
- 第 16 列 `字错率CER(%)`：模板里前 200 行预置了 Excel 公式，按 S/D/I/N 自动算；超过 200 行时 runner 自动补公式。

`_summary.csv` 列：

| 列 | 说明 |
|---|---|
| name | 子集名（与目录同名） |
| language | 跑该子集时传给模型的语种, `auto` 表示行级判断 |
| total | 子集 metadata 行数 |
| success | ASR 输出非空的条数 |
| avg_cer | 该子集所有 N>0 行的算术平均 CER (百分数) |
| elapsed_sec | 跑该子集耗时 (秒) |
| out_path | 该子集对应 Excel 绝对路径 |

---

## 7. CER 与语言处理

### 7.1 文本规范化

`cer.normalize_text()`：

1. NFKC 标准化（全角→半角）
2. 标点（中英文常见 30+ 个）替换为单空格
3. 字母小写
4. 折叠多空格

### 7.2 Token 切分

`cer.tokenize()`：

- CJK 字符（中日韩汉字 / 假名）：**每个字一个 token**
- 英文/数字连续段：**整段为一个 token**（按词）
- 其它单字符：单独成 token
- 空格只做分隔

举例：`你hello123好` → `['你', 'hello', '123', '好']`（4 个 token）。

### 7.3 错误统计

按 Levenshtein 编辑距离对齐参考与识别结果，回溯计 S/D/I/N，公式：

```
CER = (S + D + I) / N × 100%
```

- 纯中文 → 即 CER
- 纯英文 → 等价 WER
- 中英混合 → mixed error rate（业界常用做法）

### 7.4 语种判断（行级）

`run_score.py:infer_row_language()`：

1. 看参考文本里 CJK 字符数 vs 英文字母数，多的一方决定 `zh` / `en`。
2. 当子集目录是 `yue` 时强制 `yue`（无法从字面区分粤语简体/普通话简体）。
3. 都没有时回退到 metadata 的"语言"字段 → 子集目录推断 → 最终默认 `zh`。

这个语种最终会传给 ASR 的 `recognize(language=...)` 参数；模型支不支持由各自 recognizer 决定（mega_asr 用得到，fire_red_asr / glm_asr / ark_asr 都是自动判别，传了也忽略）。

---

## 8. 新接一个 ASR 怎么做

1. 在 `recognizers/` 下加 `xxx_asr.py`：

   ```python
   from .base import BaseRecognizer, RecognitionResult

   class XxxRecognizer(BaseRecognizer):
       name = "xxx_asr"          # CLI 用的 key
       display_name = "Xxx_ASR"  # 输出文件名后缀
       is_local_gpu = True       # True=本地 GPU 必须串行; False=HTTP/SaaS, 可 --workers N

       def __init__(self, ...): ...

       def setup(self) -> None:
           # 加载模型 (重复调用要幂等)
           ...

       def recognize(self, audio_path: str, language: str | None = None) -> RecognitionResult:
           # 返回 RecognitionResult(text=..., elapsed_sec=..., status="success"|"error", error="...")
           ...
   ```

2. `run_score.py:build_recognizer()` 加分支，`--asr` choices 加名字。

3. 用对应 venv 跑 smoke test（`--include xxx --limit 5`）。

4. 全量跑，最后 `merge_summary.py`。

5. 在本 README 第 4 节加一行登记 ASR 信息。

---

## 9. 常见坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 大量空 hypothesis，集中在某种采样率 | 模型不自重采样, 输入 wav 不是 16kHz | 跑 `resample_to_16k.py` 统一到 16k |
| 终端中文乱码 | Windows PowerShell GBK | runner 内部已经 `reconfigure(encoding='utf-8')`；终端再加 `chcp 65001` 或用文件查看 |
| `ImportError: cannot import name 'GlmAsrForConditionalGeneration'` | 该 venv 的 transformers 版本太老 | 用 `d:\PyCode\test\.venv`（transformers ≥ 5.6.0.dev0） |
| `ImportError: No module named 'librosa' / 'soundfile'` (ARK-ASR) | 项目根 venv 缺音频依赖 | `uv pip install --python .venv\Scripts\python.exe librosa soundfile` |
| `_summary.csv` 行数不对 | 多次跑批产生时间戳文件 | 跑完用 `merge_summary.py` 合并 |
| `_summary.csv` 第二次合并变空 | 旧脚本会把刚生成的 `_summary.csv` 一起删 | 已修：合并时会把 `_summary.csv` 自己作为输入读入，不再丢数据 |
| 跑批中断，部分子集没输出 | GPU OOM / 异常 | 重新跑同样命令；输出 Excel 会覆盖，summary 会追加 |
| FireRed 在英文上 CER 异常高 | FireRedASR2-AED 对带噪英文短句不擅长 | 接受这个能力差距, 或换模型 |
| 下载 HF 权重一直 stuck | 国内网络 | 设置 `$env:https_proxy="http://127.0.0.1:7897"` 走代理 |

---

## 10. 当前打分结果对比（参考）

跑批时间：2026-06-26 ~ 06-29，配置 RTX GPU + CUDA 12.8 + torch 2.10.

| 子集 | 条数 | mega_ASR | fire_red_ASR | GLM_ASR | ARK_ASR | SenseVoice_ONNX_INT8 |
|---|---:|---:|---:|---:|---:|---:|
| dongbei | 200 | 9.38% | **5.62%** | 12.63% | 14.73% | 11.76% |
| en | 200 | **10.34%** | 17.60% | 15.42% | 12.83% | 19.76% |
| erbao | 20 | **8.26%** | 9.51% | 15.66% | 18.82% | 27.62% |
| henan | 200 | 5.78% | **3.77%** | 12.15% | 11.03% | 13.36% |
| mandarin | 400 | 3.38% | **0.91%** | 5.49% | 5.44% | 5.37% |
| mixed_noise_dongbei | 100 | 12.22% | **10.02%** | 14.37% | 15.56% | 14.36% |
| mixed_noise_henan | 100 | 7.02% | **4.44%** | 14.68% | 12.98% | 12.55% |
| mixed_noise_shandong | 100 | 16.56% | **4.93%** | 13.86% | 10.84% | 15.40% |
| mixed_noise_sichuan | 100 | 6.04% | 6.04% | 14.90% | 16.56% | **10.68%** |
| mixed_noise_yue | 100 | 22.51% | 32.88% | **14.11%** | 36.32% | 34.68% |
| noises_en | 255 | **9.59%** | 15.79% | 14.10% | 13.45% | 19.52% |
| noises_zh | 245 | 7.00% | **6.93%** | 13.92% | 10.83% | 18.78% |
| shandong | 200 | 6.20% | **4.34%** | 12.80% | 10.31% | 15.60% |
| sichuan | 200 | 6.22% | 7.37% | 15.55% | 16.11% | **10.37%** |
| yue | 200 | **5.92%** | 34.09% | 13.17% | 36.40% | 34.97% |

**速览**

- **mandarin / henan / shandong / dongbei / sichuan**：FireRedASR 最好（普通话 < 1%，方言 4–7%）。
- **yue（粤语，繁体）**：mega_asr 最好（5.92%）。FireRedASR 和 ARK_ASR 都把粤语字面"翻译"成简体普通话写法，CER 看上去 34–36% 但其实意思对；GLM 介于两者之间（13.17%）。
- **en（纯英文）**：mega_asr 最好（10.34%），ARK_ASR 12.83% 紧随，FireRed 17.60% 最弱。
- **mixed_noise_yue**：GLM 反而最好（14.11%），mega/fire_red/ARK 都明显高。
- **noises_en**：mega_asr 9.59% > ARK 13.45% > GLM 14.10% > fire_red 15.79%（修了采样率之后 fire_red 才正常）。

**ARK-ASR-0.6B（0.6B 小模型）观察**

- 参数量只有 mega/glm 的 1/3，但 mandarin (5.44%) 和 noises_zh (10.83%) 跟 GLM-Nano (5.49% / 13.92%) 几乎打平甚至略胜。
- 英文 (12.83%) 比 GLM (15.42%) 和 fire_red (17.60%) 更好，仅次于 mega_asr。
- 普通话/河南/山东等中文方言 5–15% 区间，介于 FireRed 和 GLM 之间。
- 粤语和繁体粤字面映射是它最大的弱点（yue 36.40%，mixed_noise_yue 36.32%），跟 FireRed 一样会被字符级 CER 算法严重惩罚。
- 推理速度比 mega/glm 略快，适合资源受限场景。

**SenseVoice_ONNX_INT8（234M, INT8 量化, CPU 推理）观察**

- 推理速度碾压：CPU 单线程 RTF≈0.02，**全 15 子集 2625 条只用 ~10 分钟**（其它 ASR 全部 30–40 分钟）。
- mandarin (5.37%) 和 mixed_noise_sichuan (10.68%) / sichuan (10.37%) 是 5 个 ASR 中**最好**或并列最好。
- 英文场景偏弱（en 19.76% / noises_en 19.52%），SenseVoice 训练数据中文占比高，纯英文比 mega/ARK 弱。
- 粤语 / mixed_noise_yue 仍然是繁→简字面映射问题（35% 量级），和 FireRed/ARK 同类问题。
- erbao 表现垫底（27.62%），角色专属语音和它训练分布距离大。
- **适合作为：实时场景 / 端侧部署 / 低成本 fallback。** 用 CPU 跑就能达到接近 GLM-ASR 的水平，部署门槛极低。

**总体冠军**

| 维度 | 冠军 |
|---|---|
| 普通话 (mandarin 0.91%) / 中文方言 dongbei/henan/shandong/mixed_noise_zh | **FireRedASR** |
| 四川话 / mixed_noise_sichuan | **SenseVoice_ONNX_INT8** |
| 英文 (en 10.34%) / 粤语字面 (yue 5.92%) / noises_en | **Mega-ASR** |
| mixed_noise_yue (14.11%) | **GLM-ASR** |
| 小参数 + 中文方言 + 英文均衡 | **ARK-ASR**（0.6B 这个体量是惊喜） |
| 部署最简 + 速度最快 + 端侧友好 | **SenseVoice_ONNX_INT8** |

---

## 11. 附录：单次跑批日志要点

跑批中如果中断，summary 文件的命名是 `_summary_<时间戳>.csv`，每个子集完成时实时追加一行（崩了也不会丢前面跑过的子集数据）。

恢复办法：

1. 不动现有 `_summary_*.csv` 和已生成的 Excel
2. 用 `--include` 单独跑没产出的子集（命令同 5.1，但加 `--include xxx`）
3. 跑完 `merge_summary.py` 合并

如果想跑跨多天的多次实验合并：`merge_summary.py` 会**保留已存在的 `_summary.csv`** 作为输入，并以每行 `(name, language)` 为 key 取时间戳最新的版本写回去。
