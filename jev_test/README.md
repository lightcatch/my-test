# open-jev-deberta-v3-large test project

This project downloads and verifies
`com-kotobalabs/open-jev-deberta-v3-large` locally.

## Setup

From the repository root in PowerShell:

```powershell
uv venv --python 3.13 .\jev_test\.venv
uv pip install --python .\jev_test\.venv\Scripts\python.exe `
  torch transformers huggingface_hub safetensors sentencepiece protobuf
```

## Download

```powershell
& .\jev_test\.venv\Scripts\python.exe .\jev_test\download_model.py
```

The complete snapshot is stored in `jev_test/model`.

## Verify

```powershell
& .\jev_test\.venv\Scripts\python.exe .\jev_test\verify_model.py
```

The verifier checks the required files, loads the local model, and runs one
`choice`, one `score`, and one `noul` decision. It uses CUDA when available,
then MPS, otherwise CPU. A successful run prints `PASS` and the JSON results.
