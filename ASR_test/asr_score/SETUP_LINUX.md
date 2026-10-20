# Linux 端 ASR 打分环境部署指南

从 Windows 迁移到 Linux (Ubuntu 22.04+) 后，用这份文档一步步重建环境。

**假设**：
- 你在 my-server 上, 用户 `tc`
- 代码放在 `/home/tc/local_projects/ljr_code/`
- 数据集放在 `/home/tc/local_projects/integrated_dialects/`
- 模型权重需要自己下载（本文档指路）

---

## 1. 系统级依赖

```bash
# uv (Python 包管理器, 官方一行装)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# 其它系统包
sudo apt update
sudo apt install -y git git-lfs ffmpeg build-essential
git lfs install
```

---

## 2. 环境变量

在 `~/.bashrc` 末尾加：

```bash
export ASR_DATA_ROOT=/home/tc/local_projects/integrated_dialects
```

`source ~/.bashrc` 生效。之后 `run_score.py --root` 就默认走这个目录。

---

## 3. 5 个 venv（每个 ASR 独立环境，不要混用）

进入 `ljr_code/` 目录：

```bash
cd /home/tc/local_projects/ljr_code/
```

### 3.1 项目根 venv（GLM / ARK / Doubao / opencc 用）

```bash
uv venv .venv --python 3.10
uv pip install --python .venv/bin/python \
    "transformers>=4.55" torch torchaudio numpy scipy soundfile openpyxl \
    requests aiohttp huggingface_hub \
    opencc-python-reimplemented \
    librosa
```

注：GLM-ASR-Nano-2512 需要 transformers >= 5.6.0.dev0（含 `GlmAsrForConditionalGeneration`），
如果 pypi 稳定版不够, 用：
```bash
uv pip install --python .venv/bin/python git+https://github.com/huggingface/transformers.git
```

### 3.2 Mega-ASR venv

```bash
uv venv mega_asr/.venv --python 3.10
uv pip install --python mega_asr/.venv/bin/python \
    transformers torch torchaudio numpy scipy soundfile openpyxl peft
```

### 3.3 FireRedASR venv

```bash
uv venv fire_red_asr/.venv --python 3.10
uv pip install --python fire_red_asr/.venv/bin/python \
    torch torchaudio numpy scipy sentencepiece openpyxl \
    editdistance tqdm einops
```

### 3.4 SenseVoice ONNX venv (只需要 sherpa-onnx, 最轻量)

```bash
uv venv sense_voice_onnx/.venv --python 3.10
uv pip install --python sense_voice_onnx/.venv/bin/python \
    sherpa-onnx huggingface_hub numpy scipy soundfile openpyxl
```

---

## 4. 模型权重下载

### 4.1 Mega-ASR (Qwen3-ASR-1.7B + LoRA)

需要科学上网访问 Hugging Face：

```bash
export HF_ENDPOINT=https://hf-mirror.com   # 国内镜像
cd mega_asr
huggingface-cli download --local-dir ckpt/Mega-Base zhifeixie/Mega-ASR
```

具体 repo 名 / LoRA 结构以 `ASR_test/mega_asr/README.md` 为准（如果代码里有）。

### 4.2 FireRedASR2-AED (从 ModelScope)

```bash
cd fire_red_asr
mkdir -p pretrained_models
cd pretrained_models
git lfs install
git clone https://www.modelscope.cn/FireRedTeam/FireRedASR2-AED.git
```

这会下载 ~4.5GB 的 `model.pth.tar` (FP32 1.18B 参数)。

### 4.3 GLM-ASR-Nano-2512

```bash
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download --local-dir ~/.cache/huggingface/hub/models--zai-org--GLM-ASR-Nano-2512 \
    zai-org/GLM-ASR-Nano-2512
```

### 4.4 ARK-ASR-0.6B

```bash
export HF_ENDPOINT=https://hf-mirror.com
huggingface-cli download --local-dir ~/.cache/huggingface/hub/models--AutoArk-AI--ARK-ASR-0.6B \
    AutoArk-AI/ARK-ASR-0.6B
```

### 4.5 SenseVoice ONNX INT8

```bash
cd sense_voice_onnx
mkdir -p model
huggingface-cli download --local-dir model \
    csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17
```

---

## 5. 首次跑通命令

### 5.1 单条 smoke test

```bash
cd /home/tc/local_projects/ljr_code
.venv/bin/python -X utf8 asr_score/run_score.py \
    --asr sense_voice_onnx --device cpu \
    --include /dongbei/ --exclude mixed_noise --limit 5 \
    --out-dir /tmp/smoke_sense_voice
```

### 5.2 全量 15 子集

```bash
mega_asr/.venv/bin/python -X utf8 asr_score/run_score.py --asr mega_asr --device cuda --language auto
fire_red_asr/.venv/bin/python -X utf8 asr_score/run_score.py --asr fire_red_asr --device cuda --language auto
.venv/bin/python -X utf8 asr_score/run_score.py --asr glm_asr --device cuda --language auto
.venv/bin/python -X utf8 asr_score/run_score.py --asr ark_asr --device cuda --language auto
sense_voice_onnx/.venv/bin/python -X utf8 asr_score/run_score.py --asr sense_voice_onnx --device cpu --language auto
```

### 5.3 云端 ASR (要网)

```bash
# 豆包 AUC Flash HTTP
.venv/bin/python -X utf8 asr_score/run_score.py --asr doubao_asr --workers 6 --language auto

# 豆包 SAUC WebSocket
.venv/bin/python -X utf8 asr_score/run_score.py --asr doubao_sauc_asr --workers 6 --language auto
```

### 5.4 合并 summary + 生成总表

```bash
.venv/bin/python -X utf8 asr_score/merge_summary.py $ASR_DATA_ROOT/打分结果/*/
.venv/bin/python -X utf8 asr_score/build_overall_summary.py
.venv/bin/python -X utf8 asr_score/build_speed_summary.py
```

### 5.5 粤语 s2t 修正

```bash
.venv/bin/python -X utf8 asr_score/recompute_with_opencc.py \
    $ASR_DATA_ROOT/打分结果/fire_red_ASR/yue_fire_red_ASR.xlsx \
    $ASR_DATA_ROOT/打分结果/fire_red_ASR/mixed_noise_yue_fire_red_ASR.xlsx
```

---

## 6. 常见 Linux 坑

| 现象 | 处理 |
|---|---|
| `ffmpeg not found` | `sudo apt install ffmpeg` |
| `git lfs: command not found` | `sudo apt install git-lfs; git lfs install` |
| `ImportError: cannot import name 'GlmAsrForConditionalGeneration'` | transformers 版本太老, 用 `pip install git+https://github.com/huggingface/transformers.git` |
| `sherpa_onnx: undefined symbol` | 系统 glibc 版本不够, 装最新的 sherpa-onnx |
| CUDA out of memory | 减 batch size, 或用 `--device cpu` |
| HF 下载 429 / 超时 | `export HF_ENDPOINT=https://hf-mirror.com` |
| 中文文件名乱码 | 确保 locale 是 UTF-8: `export LANG=zh_CN.UTF-8` |

---

## 7. 目录约定 (Linux 版)

```
/home/tc/local_projects/
├── ljr_code/                        ← 代码目录
│   ├── asr_score/                   ← 主打分框架
│   ├── sauc_python/                 ← 豆包 WS demo
│   ├── file_demo/                   ← 豆包 HTTP demo
│   ├── glm_asr_cli.py               ← GLM 独立 CLI
│   ├── data_tools/                  ← 数据集处理脚本
│   ├── mega_asr/                    ← Mega-ASR (代码 + venv + ckpt)
│   ├── fire_red_asr/                ← FireRed (代码 + venv + 权重)
│   ├── sense_voice_onnx/            ← SenseVoice ONNX (venv + model)
│   ├── .venv/                       ← 项目根 venv
│   ├── .clinerules                  ← AI 项目规则
│   └── SETUP_LINUX.md               ← 本文档
└── integrated_dialects/             ← 数据集 (已经在服务器上了)
    ├── dongbei/ ... (15 个方言子集)
    ├── 打分模版.xlsx
    └── 打分结果/                    ← ASR 输出会写到这里
```
