# AGENTS.md — 给远程 AI 助手的环境重建操作指南

**读者**：在 my-server (Ubuntu Linux, `/home/tc/local_projects/ljr_code/`) 上工作的 AI 助手 (Cline / Cursor / 其他 agent)。

**你的任务**：把 `ljr_code/` 目录里的 ASR 打分框架跑起来，能对 `../integrated_dialects/` 里的 15 个方言子集打分并输出 CER + 生成总表。

**执行方式**：**严格按本文档的章节顺序**做，每步做完**必须验证**（章节末尾有 verify 命令 + 预期输出）。失败请按"错误诊断"章节处理，**不要跳步**。

---

## 目录预期

开始前，你应该看到：

```
/home/tc/local_projects/
├── ljr_code/                     ← 你在这里工作
│   ├── asr_score/                ← 主打分框架
│   ├── sauc_python/              ← 豆包 SAUC 云端 demo
│   ├── file_demo/                ← 豆包 AUC 云端 demo
│   ├── data_tools/               ← 数据集处理脚本
│   ├── glm_asr_cli.py
│   ├── .clinerules               ← AI 规则文件
│   └── AGENTS.md                 ← 本文档
└── integrated_dialects/          ← 15 子集数据集 (已在服务器上)
    ├── mandarin/  dongbei/  yue/  ...
    ├── 打分模版.xlsx
    └── 打分结果/                 ← 你的 ASR 输出会写到这里
```

Verify：
```bash
ls /home/tc/local_projects/ljr_code/
ls /home/tc/local_projects/integrated_dialects/ | head -20
```

---

## 0. 环境变量（每次会话开始都设）

```bash
export ASR_DATA_ROOT=/home/tc/local_projects/integrated_dialects
export HF_ENDPOINT=https://hf-mirror.com   # 国内镜像加速 HF
export LANG=zh_CN.UTF-8                    # 避免中文乱码
```

**建议加进 `~/.bashrc`**，或者每次跑命令前先 `source` 一下。

Verify：
```bash
echo $ASR_DATA_ROOT
# 期望输出: /home/tc/local_projects/integrated_dialects
```

---

## 1. 系统级依赖

**任务**：装 uv、ffmpeg、git-lfs。

```bash
# 1.1 uv (Python 包管理器)
which uv || (curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env)

# 1.2 系统包
sudo apt update
sudo apt install -y git git-lfs ffmpeg build-essential
git lfs install
```

Verify：
```bash
uv --version && ffmpeg -version | head -1 && git lfs version
# 期望: uv 0.5+, ffmpeg 4.4+, git-lfs 3.x
```

**失败诊断**：
- `sudo: command not found` → 你没 sudo 权限，让人类装
- `curl: (6) Could not resolve host` → 网络没通，检查 `/etc/resolv.conf`

---

## 2. 建 5 个 Python venv

**任务**：为 5 个 ASR 各建一个独立 venv，避免依赖冲突。

**工作目录**：`cd /home/tc/local_projects/ljr_code/`

### 2.1 项目根 venv (GLM / ARK / Doubao / OpenCC 共用)

```bash
uv venv .venv --python 3.10

uv pip install --python .venv/bin/python \
    torch torchaudio numpy scipy soundfile openpyxl \
    requests aiohttp huggingface_hub \
    opencc-python-reimplemented \
    librosa

# GLM-ASR-Nano 需要 transformers >= 5.6.0.dev0
uv pip install --python .venv/bin/python \
    git+https://github.com/huggingface/transformers.git
```

Verify：
```bash
.venv/bin/python -c "import torch, transformers, requests, aiohttp, opencc, librosa, soundfile; print('root venv ok')"
# 期望: root venv ok
```

### 2.2 Mega-ASR venv

```bash
mkdir -p mega_asr
uv venv mega_asr/.venv --python 3.10
uv pip install --python mega_asr/.venv/bin/python \
    transformers torch torchaudio numpy scipy soundfile openpyxl peft \
    huggingface_hub
```

Verify：
```bash
mega_asr/.venv/bin/python -c "import torch, transformers, peft; print('mega venv ok')"
```

### 2.3 FireRedASR venv

```bash
mkdir -p fire_red_asr
uv venv fire_red_asr/.venv --python 3.10
uv pip install --python fire_red_asr/.venv/bin/python \
    torch torchaudio numpy scipy sentencepiece openpyxl \
    editdistance tqdm einops
```

Verify：
```bash
fire_red_asr/.venv/bin/python -c "import torch, sentencepiece, einops; print('fire_red venv ok')"
```

### 2.4 SenseVoice ONNX venv (最轻量, 优先做通它)

```bash
mkdir -p sense_voice_onnx
uv venv sense_voice_onnx/.venv --python 3.10
uv pip install --python sense_voice_onnx/.venv/bin/python \
    sherpa-onnx huggingface_hub numpy scipy soundfile openpyxl
```

Verify：
```bash
sense_voice_onnx/.venv/bin/python -c "import sherpa_onnx; print('sense_voice venv ok, version:', sherpa_onnx.__version__)"
# 期望: sense_voice venv ok, version: 1.13.3+
```

---

## 3. 下载模型权重

**任务**：为每个 ASR 下载对应权重。**优先做 SenseVoice ONNX**（最小 240MB，跑通了才有意义继续）。

**每个 ASR 权重路径预期**：

| ASR | 权重放这 |
|---|---|
| SenseVoice ONNX | `sense_voice_onnx/model/model.int8.onnx` + `tokens.txt` |
| Mega-ASR | `mega_asr/ckpt/...`（具体名字见 recognizer 代码） |
| FireRedASR2-AED | `fire_red_asr/pretrained_models/FireRedASR2-AED/model.pth.tar` (4.5GB) |
| GLM-ASR-Nano | HF cache 里自动（首次 recognize 触发下载） |
| ARK-ASR-0.6B | HF cache 里自动（首次 recognize 触发下载） |

### 3.1 SenseVoice ONNX INT8（**必做，最小最快**）

```bash
cd /home/tc/local_projects/ljr_code

sense_voice_onnx/.venv/bin/python -c "
from huggingface_hub import snapshot_download
p = snapshot_download(
    repo_id='csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17',
    local_dir='sense_voice_onnx/model'
)
print('downloaded to', p)
"
```

Verify：
```bash
ls -la sense_voice_onnx/model/model.int8.onnx sense_voice_onnx/model/tokens.txt
# 期望: model.int8.onnx ~240MB, tokens.txt ~300KB
```

### 3.2 FireRedASR2-AED (ModelScope, 4.5GB)

```bash
cd /home/tc/local_projects/ljr_code/fire_red_asr
mkdir -p pretrained_models
cd pretrained_models
git lfs install
git clone https://www.modelscope.cn/FireRedTeam/FireRedASR2-AED.git

# 需要跑一次 LFS 拉大文件
cd FireRedASR2-AED
git lfs pull
```

Verify：
```bash
ls -la /home/tc/local_projects/ljr_code/fire_red_asr/pretrained_models/FireRedASR2-AED/model.pth.tar
# 期望: -rw-... 4.7G ...
```

### 3.3 GLM-ASR-Nano / ARK-ASR

这两个**首次 recognize 时会自动从 HF 下载**（HF_ENDPOINT 已设为镜像）。可以先手动 pre-download：

```bash
cd /home/tc/local_projects/ljr_code

.venv/bin/python -c "
from huggingface_hub import snapshot_download
snapshot_download(repo_id='zai-org/GLM-ASR-Nano-2512')
snapshot_download(repo_id='AutoArk-AI/ARK-ASR-0.6B')
print('glm + ark downloaded to HF cache')
"
```

Verify：
```bash
du -sh ~/.cache/huggingface/hub/models--zai-org--GLM-ASR-Nano-2512
du -sh ~/.cache/huggingface/hub/models--AutoArk-AI--ARK-ASR-0.6B
# GLM ~3.4GB, ARK ~2.6GB
```

### 3.4 Mega-ASR（跳过）

Mega-ASR 权重较大且依赖内部 recognizer 代码里的 hardcoded 路径。**先不做**，其它 ASR 都通了再回头看。

---

## 4. Smoke Test（一定要跑）

**任务**：每个已经下好权重的 ASR，跑 5 条 dongbei 数据，确认能识别。

工作目录 `cd /home/tc/local_projects/ljr_code`。

### 4.1 SenseVoice ONNX（**先跑这个**）

```bash
sense_voice_onnx/.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr sense_voice_onnx --device cpu \
    --include /dongbei/ --exclude mixed_noise --limit 5 \
    --out-dir /tmp/smoke_sense > /tmp/smoke_sense.log 2>&1
tail -25 /tmp/smoke_sense.log
```

**期望输出**：
```
=== 子集 dongbei: 5 条, 输出 -> /tmp/smoke_sense/dongbei_SenseVoice_ONNX_INT8.xlsx ===
  [1/5] [zh] dongbei_0001_1023136_c31c9c75.wav -> 在孩子记忆最清晰的时候完成记错。  (0.51s)
  ...
  子集完成: 5/5 成功, 平均 CER=X.X%, 用时 X.Xs
```

**如果 5/5 成功、CER < 20%**：SenseVoice OK ✓

**清理**：`rm -rf /tmp/smoke_sense`

### 4.2 FireRedASR

```bash
fire_red_asr/.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr fire_red_asr --device cuda \
    --include /dongbei/ --exclude mixed_noise --limit 5 \
    --out-dir /tmp/smoke_fire > /tmp/smoke_fire.log 2>&1
tail -25 /tmp/smoke_fire.log
```

**期望**：5/5 成功, CER < 10%。

**如果报错**：
- `CUDA out of memory` → 加 `--device cpu` 但会很慢
- `model.pth.tar not found` → 检查 3.2 步骤是否成功下载
- `import fireredasr2` 失败 → 需要装 FireRed 代码：`git clone https://github.com/FireRedTeam/FireRedASR2S.git fire_red_asr/repo` 然后把 `repo/examples_infer/asr/` 加到 PYTHONPATH

### 4.3 GLM-ASR

```bash
.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr glm_asr --device cuda \
    --include /dongbei/ --exclude mixed_noise --limit 5 \
    --out-dir /tmp/smoke_glm > /tmp/smoke_glm.log 2>&1
tail -25 /tmp/smoke_glm.log
```

### 4.4 ARK-ASR

```bash
.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr ark_asr --device cuda \
    --include /dongbei/ --exclude mixed_noise --limit 5 \
    --out-dir /tmp/smoke_ark > /tmp/smoke_ark.log 2>&1
tail -25 /tmp/smoke_ark.log
```

**每个 smoke test 通过后立即清理**：`rm -rf /tmp/smoke_*`

---

## 5. 全量跑分（可选）

**任务**：所有 smoke 都通过后，跑全量 15 个子集打分。**注意每个 ASR 大约要跑 30-60 分钟。**

### 5.1 全量命令模板

```bash
cd /home/tc/local_projects/ljr_code

# 每个 ASR 一条命令
sense_voice_onnx/.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr sense_voice_onnx --device cpu --language auto \
    > logs/sense_voice_full.log 2>&1 &

fire_red_asr/.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr fire_red_asr --device cuda --language auto \
    > logs/fire_red_full.log 2>&1 &

.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr glm_asr --device cuda --language auto \
    > logs/glm_full.log 2>&1 &

.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr ark_asr --device cuda --language auto \
    > logs/ark_full.log 2>&1 &
```

**注意**：本地 GPU ASR **不能同时跑**（共享一张 GPU），要串行。SenseVoice 是 CPU，可以和 GPU ASR 并行。

**监控进度**：
```bash
tail -f logs/sense_voice_full.log
```

### 5.2 全量完成后：合并 summary + 生成总表

```bash
cd /home/tc/local_projects/ljr_code

# 合并每个 ASR 目录的时间戳 summary → _summary.csv
.venv/bin/python -X utf8 asr_score/merge_summary.py \
    $ASR_DATA_ROOT/打分结果/SenseVoice_ONNX_INT8 \
    $ASR_DATA_ROOT/打分结果/fire_red_ASR \
    $ASR_DATA_ROOT/打分结果/GLM_ASR \
    $ASR_DATA_ROOT/打分结果/ARK_ASR

# 生成方言 × 模型 CER 总表
.venv/bin/python -X utf8 asr_score/build_overall_summary.py

# 速度对比总表 (需要先跑 benchmark_speed.py 各个 ASR)
.venv/bin/python -X utf8 asr_score/build_speed_summary.py
```

### 5.3 粤语 s2t 修正（若跑了 fire_red / ARK / SenseVoice）

粤语场景 fire_red / ARK / SenseVoice 输出的是简体普通话写法，需要 s2t 转成繁体粤字才能算准 CER：

```bash
.venv/bin/python -X utf8 asr_score/recompute_with_opencc.py \
    $ASR_DATA_ROOT/打分结果/fire_red_ASR/yue_fire_red_ASR.xlsx \
    $ASR_DATA_ROOT/打分结果/fire_red_ASR/mixed_noise_yue_fire_red_ASR.xlsx \
    $ASR_DATA_ROOT/打分结果/ARK_ASR/yue_ARK_ASR.xlsx \
    $ASR_DATA_ROOT/打分结果/ARK_ASR/mixed_noise_yue_ARK_ASR.xlsx \
    $ASR_DATA_ROOT/打分结果/SenseVoice_ONNX_INT8/yue_SenseVoice_ONNX_INT8.xlsx \
    $ASR_DATA_ROOT/打分结果/SenseVoice_ONNX_INT8/mixed_noise_yue_SenseVoice_ONNX_INT8.xlsx

# 修正后重跑总表
.venv/bin/python -X utf8 asr_score/build_overall_summary.py
```

---

## 6. 错误诊断树

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `ffmpeg not found` | 未装 ffmpeg | 回 §1.2 `sudo apt install ffmpeg` |
| `git lfs: command not found` | 未装 git-lfs | 回 §1.2 |
| `ImportError: cannot import name 'GlmAsrForConditionalGeneration'` | transformers 版本太老 | `uv pip install --python .venv/bin/python git+https://github.com/huggingface/transformers.git` |
| `sherpa_onnx: undefined symbol` | glibc 版本不够 | 升级系统或换轻量 sherpa-onnx 版本 |
| CUDA out of memory | 卡太小 | 减 batch，或 `--device cpu` |
| HF 下载 429 / 超时 | 网络 | `export HF_ENDPOINT=https://hf-mirror.com` |
| `Permission denied: /home/tc/...` | 目录权限 | `chown -R tc:tc /home/tc/local_projects/` |
| 中文文件名乱码 | locale | `export LANG=zh_CN.UTF-8` |
| ASR 输出全部空字符串 | 音频采样率不是 16k | 先跑 `data_tools/resample_to_16k.py` |
| `dongbei` 目录不存在 | 数据集没在 `integrated_dialects/` 里 | 让人类把数据传到 `/home/tc/local_projects/integrated_dialects/` |

---

## 7. 你完成任务后应该输出

一份简短的 status 报告，格式如下：

```
=== ASR 环境部署状态 ===
系统依赖: uv X.Y.Z / ffmpeg X.Y / git-lfs X.Y ✓
venv:
  .venv                  ✓
  mega_asr/.venv         ✓ 或 ✗ (原因)
  fire_red_asr/.venv     ✓ 或 ✗
  sense_voice_onnx/.venv ✓
模型权重:
  SenseVoice ONNX INT8   ✓ 240MB
  FireRedASR2-AED        ✓ 4.5GB 或 ✗
  GLM-ASR-Nano           ✓ 3.4GB 或 缓存到 HF cache
  ARK-ASR-0.6B           ✓ 2.6GB 或 缓存到 HF cache
Smoke test:
  SenseVoice dongbei-5   ✓ CER X.X%
  FireRed dongbei-5      ✓ CER X.X%
  GLM dongbei-5          ✓ 或 ✗
  ARK dongbei-5          ✓ 或 ✗
全量跑分:
  (未跑 / 进行中 / 已完成 with 15 子集)
```

## 8. 遵守 `.clinerules`

**同目录下有 `.clinerules` 文件**，里面写了 Cline 项目规则（终端命令、Python 环境、沟通习惯、Git 约定）。**严格遵守**：

- 长任务（> 30s）用 `> log.txt 2>&1 &` 后台跑，然后 `tail -f log.txt`
- 短命令输出限行：`| head -30` / `| tail -30`
- 不用 `sudo` 除非绝对需要
- 破坏性命令 (`rm -rf`, `git reset --hard`) 需要用户确认

---

**开工提示**：先做 §0、§1、§2.4（SenseVoice venv）、§3.1（SenseVoice 权重）、§4.1（SenseVoice smoke），能跑通就说明整条 pipeline 通了。其它 ASR 按需扩展。
