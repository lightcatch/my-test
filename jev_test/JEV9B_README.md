# JEV-9B

本目录使用 `download_jev9b.py` 下载 `autotrust/JEV-9B` 的完整 Hugging Face 快照，目标目录为 `jev9b_model/`。基础模型约 17.9 GB，下载采用 32 MB Range 分块并支持 `.part` 断点续传。

```powershell
& .\.venv\Scripts\python.exe .\download_jev9b.py --workers 4
& .\.venv\Scripts\python.exe .\verify_jev9b.py
```

文本决策适配器位于 `adapter_vllm/`，视觉决策服务使用 `vl/serve.sh` 中的 `vl/adapter_vllm/`。启动视觉服务后，前端配置在 `laya_playground/models.json` 的端点 `http://127.0.0.1:8000/v1/decide` 即可调用：

```bash
bash jev9b_model/vl/serve.sh
```

9B 权重不能直接放入 12 GB 显存，应使用仓库提供的 vLLM 服务加载；服务脚本会按模型卡说明准备 Qwen3.5-9B 视觉组件。
