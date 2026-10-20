# Laya Playground

Local browser UI for running the downloaded Laya and Open JEV checkpoints with editable prompts and typed questions.

## Start

From `D:\PyCode\test`:

```powershell
& .\jev_test\.laya_venv\Scripts\python.exe .\jev_test\laya_playground\server.py
```

Open `http://127.0.0.1:8765`. The server binds only to localhost, loads only local checkpoint paths, and does not call Hugging Face.

## Models

The initial models are registered in `models.json`. The UI can add more local checkpoints using either the `laya_agent` or `open_jev` adapter. New inference backends can be added in `server.py` by implementing the model-load and question/result conversion for the adapter.

## Timing

The first request reports model loading separately from inference. CUDA inference is synchronized before and after the timed `predict`/`decide` call. Warm-up is not performed automatically, so the displayed first inference includes first-call runtime initialization but not checkpoint loading.
