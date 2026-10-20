# 项目测试入口

模型测试请使用 [model_test/AI_USAGE.md](model_test/AI_USAGE.md)。统一入口为：

```powershell
python model_test/run_model_test_suite.py --tests all
```

## Git 源码同步

仓库保留源码、提示词、测试用例与依赖清单。模型权重、虚拟环境、下载音频、生成报表、向量数据库、缓存及压缩包仅保留在本地，由 `.gitignore` 排除。

首次克隆后，在项目根目录复制配置模板，再填入自己的密钥和地址：

```powershell
Copy-Item config.example.py config.py
Copy-Item config11.example.py config11.py
```

已有本地配置时不要执行上述复制命令，以免覆盖。根目录的 `config.py`、`config11.py` 不纳入 Git；子项目中用于提示词和运行参数的配置文件仍正常纳入 Git。模型测试和 ASR 脚本的密钥统一从本机 `config11.py` 读取，字段见 `config11.example.py`。

根据 `pyproject.toml` 和 `uv.lock` 重建 Python 环境。模型和音频需另行下载；`ASR_test/mega_asr` 是独立第三方仓库，由其上游恢复：

```powershell
git clone https://github.com/xzf-thu/Mega-ASR.git ASR_test/mega_asr
```

`nana_prompt_ab` 的运行说明见 [nana_prompt_ab/README.md](nana_prompt_ab/README.md)。
