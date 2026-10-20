"""Verify all three local Laya checkpoints without contacting the Hub."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODEL_ROOT = ROOT / "laya_model"
CHECKPOINTS = {
    "english": (MODEL_ROOT, "Duplicate charge; please refund the extra payment."),
    "multilingual": (MODEL_ROOT / "multilingual", "我被重复收费了，请退还多收的款项。"),
    "typed-decisions": (MODEL_ROOT / "typed-decisions", "Duplicate charge; please refund the extra payment."),
}
REQUIRED = (
    "model.safetensors",
    "rl_agent_config.json",
    "encoder/config.json",
    "tokenizer/tokenizer.json",
    "tokenizer/tokenizer_config.json",
)


def check_files(path: Path) -> None:
    missing = [str(p) for p in REQUIRED if not (path / p).is_file()]
    empty = [str(p) for p in REQUIRED if (path / p).is_file() and (path / p).stat().st_size == 0]
    if missing or empty:
        raise RuntimeError(f"Incomplete checkpoint {path}: missing={missing}, empty={empty}")


def validate_result(name: str, result: dict, questions: dict) -> None:
    answers = result.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise AssertionError(f"{name}: invalid answer keys: {result}")
    choice = answers["department"]
    if choice.get("choice") not in questions["department"]["criteria"]:
        raise AssertionError(f"{name}: invalid choice: {choice}")
    probs = choice.get("probabilities", {})
    if abs(sum(probs.values()) - 1.0) > 1e-3:
        raise AssertionError(f"{name}: choice probabilities do not sum to 1")
    score = answers["urgency"]
    if not 0 <= float(score.get("score")) <= 2:
        raise AssertionError(f"{name}: invalid score: {score}")
    if abs(sum(score.get("probabilities", {}).values()) - 1.0) > 1e-3:
        raise AssertionError(f"{name}: score probabilities do not sum to 1")
    noul = float(answers["refund_requested"].get("noul"))
    if not 0 <= noul <= 1:
        raise AssertionError(f"{name}: invalid noul: {noul}")


def main() -> int:
    for path, _ in CHECKPOINTS.values():
        check_files(path)

    # Local path loading prevents huggingface_hub from downloading anything.
    from laya import Agent
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    questions = {
        "department": {
            "type": "choice",
            "instructions": "Which department should handle this request?",
            "criteria": {"billing": "invoices, payments, refunds", "technical": "bugs and outages", "other": "everything else"},
        },
        "urgency": {
            "type": "score",
            "instructions": "How urgent is this request?",
            "criteria": ["not urgent", "soon", "critical or blocking"],
        },
        "refund_requested": {
            "type": "noul",
            "instructions": "Does the user explicitly request a refund?",
        },
    }

    outputs = {}
    for name, (path, state) in CHECKPOINTS.items():
        agent = Agent(str(path), device=device)
        result = agent.predict(state, questions)
        validate_result(name, result, questions)
        outputs[name] = {"device": str(agent.device), "answers": result["answers"]}
        del agent
        if device == "cuda":
            torch.cuda.empty_cache()

    print("PASS: all three local Laya checkpoints loaded and passed choice/score/noul inference")
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
