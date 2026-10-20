"""Verify a local JEV-9B snapshot without loading 9B weights into Python."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "jev9b_model"


def main() -> int:
    required = [
        "config.json", "model.safetensors.index.json", "head.safetensors",
        "adapter_vllm/adapter_config.json", "adapter_vllm/adapter_model.safetensors",
        "adapter_vllm/decision_head.json", "chat_template.jinja",
    ]
    missing = [name for name in required if not (MODEL / name).is_file() or (MODEL / name).stat().st_size == 0]
    if missing:
        print("FAIL: missing or empty files: " + ", ".join(missing))
        return 1
    index = json.loads((MODEL / "model.safetensors.index.json").read_text(encoding="utf-8"))
    shards = sorted(set(index.get("weight_map", {}).values()))
    missing_shards = [name for name in shards if not (MODEL / name).is_file()]
    if missing_shards:
        print(f"INCOMPLETE: {len(missing_shards)}/{len(shards)} base shards missing: {', '.join(missing_shards)}")
        return 2
    print(f"PASS: JEV-9B snapshot is complete ({len(shards)} base shards)")
    print(f"model={MODEL}")
    print(f"bytes={sum((MODEL / name).stat().st_size for name in shards):,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
