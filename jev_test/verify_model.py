"""Load the local model and run representative choice/score/noul inference."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
MODEL_DIR = PROJECT_DIR / "model"
REQUIRED_FILES = (
    "config.json",
    "open_jev_config.json",
    "model.safetensors",
    "head.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "spm.model",
    "typed_decisions/open_jev.py",
    "typed_decisions/encoder.py",
    "typed_decisions/schema.py",
)


def check_files() -> None:
    missing = []
    empty = []
    for relative in REQUIRED_FILES:
        path = MODEL_DIR / relative
        if not path.is_file():
            missing.append(relative)
        elif path.stat().st_size == 0:
            empty.append(relative)
    if missing or empty:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if empty:
            details.append(f"empty: {', '.join(empty)}")
        raise RuntimeError("Model snapshot is incomplete (" + "; ".join(details) + ")")


def main() -> int:
    check_files()

    # The downloaded snapshot contains its own typed_decisions package.
    sys.path.insert(0, str(MODEL_DIR))
    import torch
    from typed_decisions.open_jev import OpenJev

    if torch.cuda.is_available():
        device = "cuda"
    elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"

    model = OpenJev.from_pretrained(str(MODEL_DIR), device=device)
    questions = [
        {
            "type": "choice",
            "instructions": "Which product area is this message about?",
            "options": ["fees & charges", "refund & dispute", "card", "other"],
        },
        {
            "type": "score",
            "instructions": "How positive is this message?",
            "options": ["very negative", "negative", "neutral", "positive", "very positive"],
        },
        {
            "type": "noul",
            "instructions": "The customer is asking for a refund.",
        },
    ]
    state = "I was charged twice for the same order and want my money back."
    results = model.decide(state, questions)

    if len(results) != 3:
        raise AssertionError(f"Expected 3 results, got {len(results)}")

    choice = results[0]
    if choice["choice"] not in questions[0]["options"]:
        raise AssertionError(f"Invalid choice result: {choice}")
    if abs(sum(choice["probabilities"].values()) - 1.0) > 1e-4:
        raise AssertionError(f"Choice probabilities do not sum to 1: {choice}")

    score = results[1]
    if not 0.0 <= score["score"] <= len(questions[1]["options"]) - 1:
        raise AssertionError(f"Invalid score result: {score}")
    if abs(sum(score["probabilities"].values()) - 1.0) > 1e-4:
        raise AssertionError(f"Score probabilities do not sum to 1: {score}")

    noul = results[2]
    if not 0.0 <= noul["noul"] <= 1.0:
        raise AssertionError(f"Invalid noul result: {noul}")

    print("PASS: model snapshot is complete and inference succeeded")
    print(f"model_dir: {MODEL_DIR}")
    print(f"device: {device}")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
