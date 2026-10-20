"""Download the open JEV model into this project."""

from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


REPO_ID = "com-kotobalabs/open-jev-deberta-v3-large"
PROJECT_DIR = Path(__file__).resolve().parent
MODEL_DIR = PROJECT_DIR / "model"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=None, help="Optional Hugging Face revision")
    args = parser.parse_args()

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = snapshot_download(
        repo_id=REPO_ID,
        revision=args.revision,
        local_dir=str(MODEL_DIR),
    )
    print(f"Downloaded {REPO_ID} to: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
