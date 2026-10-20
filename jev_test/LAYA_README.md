# Laya checkpoint test project

This directory contains all three checkpoints from
`convaiinnovations/laya`, kept separate from the existing JEV model in
`jev_test/model`.

## Setup

```powershell
uv venv --python 3.13 .\jev_test\.laya_venv
```

Install the Laya runtime (`laya==0.3.20`) plus its required runtime packages:

```powershell
uv pip install --python .\jev_test\.laya_venv\Scripts\python.exe `
  laya==0.3.20 torch transformers safetensors huggingface_hub numpy
```

## Download

```powershell
& .\jev_test\.laya_venv\Scripts\python.exe .\jev_test\download_laya.py
```

The complete snapshot is saved in `jev_test/laya_model`:

- `laya_model/`: English checkpoint
- `laya_model/multilingual/`: multilingual checkpoint
- `laya_model/typed-decisions/`: typed-decisions checkpoint

The downloader verifies every expected file size and resumes partial files.

## Verify

```powershell
& .\jev_test\.laya_venv\Scripts\python.exe .\jev_test\verify_laya.py
```

The verifier loads all three checkpoints strictly from local paths, prefers
CUDA when available, and runs `choice`, `score`, and `noul` questions. A
successful run prints `PASS` and JSON answers.
