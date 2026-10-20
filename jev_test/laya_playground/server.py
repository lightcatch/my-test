"""Local browser UI and inference API for the downloaded Laya/JEV models."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
MODEL_CONFIG = ROOT / "models.json"
INDEX_FILE = ROOT / "index.html"
MAX_BODY_BYTES = 1_000_000
HOST = "127.0.0.1"
PORT = int(os.environ.get("LAYA_PLAYGROUND_PORT", "8765"))

_models_lock = threading.RLock()
_loaded_lock = threading.RLock()
_loaded: dict[str, tuple[object, str, float]] = {}
_inference_lock = threading.Lock()
_torch = None


def _read_models() -> list[dict]:
    with MODEL_CONFIG.open(encoding="utf-8") as f:
        models = json.load(f)
    if not isinstance(models, list):
        raise ValueError("models.json must contain a list")
    return models


def _resolve_model_path(entry: dict) -> Path:
    path = Path(entry["path"])
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _validate_model(entry: dict) -> None:
    backend = entry.get("backend")
    path = _resolve_model_path(entry)
    if backend == "laya_agent":
        required = ("model.safetensors", "rl_agent_config.json", "encoder/config.json", "tokenizer/tokenizer.json")
    elif backend == "open_jev":
        required = ("model.safetensors", "head.safetensors", "config.json", "open_jev_config.json", "typed_decisions/open_jev.py")
    elif backend == "jev_vl_http":
        required = ("config.json", "model.safetensors.index.json", "adapter_vllm/decision_head.json")
    else:
        raise ValueError("backend must be laya_agent, open_jev, or jev_vl_http")
    missing = [name for name in required if not (path / name).is_file()]
    if missing:
        raise ValueError(f"Checkpoint {path} is missing: {', '.join(missing)}")
    if backend == "jev_vl_http":
        index = json.loads((path / "model.safetensors.index.json").read_text(encoding="utf-8"))
        expected_shards = set(index.get("weight_map", {}).values())
        missing_shards = [name for name in expected_shards if not (path / name).is_file()]
        if missing_shards:
            raise ValueError(f"Checkpoint {path} is missing base-model shards: {', '.join(sorted(missing_shards))}")
        for shard in expected_shards:
            expected_size = (path / shard).stat().st_size
            if expected_size <= 0:
                raise ValueError(f"Checkpoint {path} has an empty base-model shard: {shard}")


def _load_model(entry: dict):
    global _torch
    model_id = entry["id"]
    with _loaded_lock:
        if model_id in _loaded:
            model, device, original_load_ms = _loaded[model_id]
            return model, device, 0.0, True

        if _torch is None:
            import torch

            _torch = torch
        device = "cuda" if _torch.cuda.is_available() else "cpu"
        path = _resolve_model_path(entry)
        started = time.perf_counter_ns()
        if entry["backend"] == "laya_agent":
            from laya import Agent

            model = Agent(str(path), device=device)
            device = str(model.device)
        elif entry["backend"] == "open_jev":
            import sys

            typed_decisions_root = str(_resolve_model_path(entry))
            if typed_decisions_root not in sys.path:
                sys.path.insert(0, typed_decisions_root)
            from typed_decisions.open_jev import OpenJev

            model = OpenJev.from_pretrained(str(path), device=device)
            device = str(model.device)
        elif entry["backend"] == "jev_vl_http":
            # JEV vision checkpoints are served by the repository's vLLM
            # server; this process only stores its endpoint and never loads
            # the 56 GB checkpoint into the Laya virtual environment.
            model = {"endpoint": entry.get("endpoint", "http://127.0.0.1:8000/v1/decide")}
            device = "remote"
        else:
            raise ValueError(f"Unsupported backend: {entry['backend']}")
        if device.startswith("cuda"):
            _torch.cuda.synchronize()
        load_ms = (time.perf_counter_ns() - started) / 1_000_000
        _loaded[model_id] = (model, device, load_ms)
        return model, device, load_ms, False


def _normalise_questions(raw_questions: list, global_prompt: str) -> list[dict]:
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError("Add at least one question")
    if len(raw_questions) > 20:
        raise ValueError("A run supports at most 20 questions")
    questions = []
    used_ids: set[str] = set()
    for index, raw in enumerate(raw_questions):
        qid = str(raw.get("id", f"question_{index + 1}")).strip()
        if not qid or qid in used_ids:
            raise ValueError("Question IDs must be non-empty and unique")
        used_ids.add(qid)
        kind = raw.get("type")
        instructions = str(raw.get("instructions", "")).strip()
        if global_prompt.strip():
            instructions = global_prompt.strip() + ("\n\n" + instructions if instructions else "")
        if not instructions:
            raise ValueError(f"Question {qid}: instructions are required")
        options = raw.get("options", [])
        if kind in ("choice", "score"):
            if not isinstance(options, list):
                raise ValueError(f"Question {qid}: options must be a list")
            options = [
                {"label": str(option.get("label", "")).strip(), "description": str(option.get("description", "")).strip()}
                for option in options
            ]
            if any(not option["label"] for option in options):
                raise ValueError(f"Question {qid}: every option needs a label")
            if len({option["label"] for option in options}) != len(options):
                raise ValueError(f"Question {qid}: option labels must be unique")
            limit = 255 if kind == "choice" else 10
            minimum = 2
            if not minimum <= len(options) <= limit:
                raise ValueError(f"Question {qid}: {kind} requires {minimum}..{limit} options")
        elif kind == "noul":
            options = [
                {"label": "false", "description": str(raw.get("false_description", "")).strip()},
                {"label": "true", "description": str(raw.get("true_description", "")).strip()},
            ]
        else:
            raise ValueError(f"Question {qid}: type must be choice, score, or noul")
        questions.append({"id": qid, "type": kind, "instructions": instructions, "options": options})
    return questions


def _run_laya(model, state: str, questions: list[dict]) -> dict:
    laya_questions = {}
    for question in questions:
        instructions = question["instructions"]
        if question["type"] == "choice":
            criteria = {option["label"]: option["description"] or option["label"] for option in question["options"]}
        elif question["type"] == "score":
            definitions = [f"{option['label']}: {option['description']}" for option in question["options"] if option["description"]]
            if definitions:
                instructions += "\n\n等级定义：\n" + "\n".join(definitions)
            criteria = [option["label"] for option in question["options"]]
        else:
            criteria = {
                "false": question["options"][0]["description"],
                "true": question["options"][1]["description"],
            }
            criteria = {key: value for key, value in criteria.items() if value}
        item = {"type": question["type"], "instructions": instructions, "criteria": criteria}
        laya_questions[question["id"]] = item
    return model.predict(state, laya_questions)


def _run_open_jev(model, state: str, questions: list[dict]) -> dict:
    converted = []
    for question in questions:
        instructions = question["instructions"]
        if question["type"] in ("choice", "score"):
            definitions = [f"{option['label']}: {option['description']}" for option in question["options"] if option["description"]]
            if definitions:
                instructions += "\n\n选项定义：\n" + "\n".join(definitions)
            item = {"type": question["type"], "instructions": instructions, "options": [option["label"] for option in question["options"]]}
        else:
            definitions = [f"{option['label']}: {option['description']}" for option in question["options"] if option["description"]]
            if definitions:
                instructions += "\n\n判断标准：\n" + "\n".join(definitions)
            item = {"type": question["type"], "instructions": instructions}
        converted.append(item)
    answers = model.decide(state, converted)
    return {"answers": {question["id"]: answer for question, answer in zip(questions, answers)}}


def _run_jev_vl_http(model, state: str, questions: list[dict]) -> dict:
    """Call a JEV vision checkpoint's native System 1 decision endpoint."""
    answers = {}
    for question in questions:
        if question["type"] == "choice":
            options = [option["label"] for option in question["options"]]
        elif question["type"] == "score":
            options = [option["label"] for option in question["options"]]
        else:
            options = ["false", "true"]
        descriptions = [f"{option['label']}: {option['description']}" for option in question["options"] if option.get("description")]
        prompt = question["instructions"]
        if descriptions:
            prompt += "\n\nOption definitions:\n" + "\n".join(descriptions)
        # JEV-VL's native score head is fixed to 0..5. For custom labels
        # (for example L1..L4), use its choice head so probabilities remain
        # aligned with the labels shown in this UI.
        request_kind = question["type"]
        if request_kind == "score" and options != [str(index) for index in range(6)]:
            request_kind = "choice"
        payload = {"kind": request_kind, "state": state, "question": prompt, "options": options}
        request = urllib.request.Request(
            model["endpoint"],
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"JEV-VL endpoint returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Cannot reach JEV-VL endpoint {model['endpoint']}: {exc.reason}") from exc
        if "error" in result:
            raise RuntimeError(str(result["error"]))
        probabilities = result.get("probabilities", [])
        if not isinstance(probabilities, list) or len(probabilities) != len(options):
            raise RuntimeError("JEV-VL response has no probability for every option")
        choice_index = int(result.get("choice_index", max(range(len(probabilities)), key=probabilities.__getitem__)))
        if not 0 <= choice_index < len(options):
            raise RuntimeError("JEV-VL returned an invalid choice index")
        answer = {
            "type": question["type"],
            "probabilities": {label: float(probability) for label, probability in zip(options, probabilities)},
            "confidence": float(probabilities[choice_index]),
            "choice": options[choice_index],
            "remote_elapsed_seconds": result.get("elapsed_seconds"),
        }
        if question["type"] == "score":
            answer["score"] = options[choice_index]
        elif question["type"] == "noul":
            answer["noul"] = float(probabilities[1])
        answers[question["id"]] = answer
    return {"answers": answers}


def _public_model(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "name": entry["name"],
        "backend": entry["backend"],
        "path": str(_resolve_model_path(entry)),
        "loaded": entry["id"] in _loaded,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "LayaPlayground/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {self.address_string()} {fmt % args}")

    def _send_json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("Request body is empty or exceeds 1 MB")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be valid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route == "/":
            body = INDEX_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/models":
            try:
                with _models_lock:
                    entries = _read_models()
                    self._send_json(200, {"models": [_public_model(entry) for entry in entries]})
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            payload = self._read_json()
            if route == "/api/models":
                self._add_model(payload)
            elif route == "/api/run":
                self._run(payload)
            else:
                self._send_json(404, {"error": "Not found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def _add_model(self, payload: dict) -> None:
        model_id = str(payload.get("id", "")).strip()
        name = str(payload.get("name", "")).strip()
        backend = str(payload.get("backend", "")).strip()
        raw_path = str(payload.get("path", "")).strip()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{2,48}", model_id):
            raise ValueError("Model ID must be 2-48 letters, digits, underscores, or hyphens")
        if not name or not raw_path:
            raise ValueError("Model name and local path are required")
        if backend not in {"laya_agent", "open_jev", "jev_vl_http"}:
            raise ValueError("Unsupported backend")
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        entry = {"id": model_id, "name": name, "backend": backend, "path": str(path)}
        if backend == "jev_vl_http":
            endpoint = str(payload.get("endpoint", "")).strip()
            if not re.fullmatch(r"https?://[^\s]+", endpoint):
                raise ValueError("JEV-VL HTTP models require an http(s) endpoint")
            entry["endpoint"] = endpoint
        _validate_model(entry)
        with _models_lock:
            entries = _read_models()
            if any(existing["id"] == model_id for existing in entries):
                raise ValueError(f"Model ID already exists: {model_id}")
            entries.append(entry)
            temporary = MODEL_CONFIG.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(MODEL_CONFIG)
        self._send_json(201, {"model": _public_model(entry)})

    def _run(self, payload: dict) -> None:
        model_id = str(payload.get("model_id", ""))
        state = str(payload.get("state", "")).strip()
        global_prompt = str(payload.get("global_prompt", ""))
        if not state:
            raise ValueError("State/dialogue text is required")
        if len(state) > 100_000 or len(global_prompt) > 20_000:
            raise ValueError("Input exceeds the maximum supported length")
        questions = _normalise_questions(payload.get("questions"), global_prompt)
        with _models_lock:
            entry = next((item for item in _read_models() if item["id"] == model_id), None)
        if entry is None:
            raise ValueError(f"Unknown model ID: {model_id}")
        _validate_model(entry)
        model, device, load_ms, cached = _load_model(entry)
        torch = _torch
        if device.startswith("cuda"):
            torch.cuda.synchronize()
        # Model inference and CUDA synchronization must not overlap, or displayed
        # per-request latency would include unrelated work from another request.
        with _inference_lock:
            started = time.perf_counter_ns()
            if entry["backend"] == "laya_agent":
                result = _run_laya(model, state, questions)
            elif entry["backend"] == "open_jev":
                result = _run_open_jev(model, state, questions)
            else:
                result = _run_jev_vl_http(model, state, questions)
            if device.startswith("cuda"):
                torch.cuda.synchronize()
            inference_ms = (time.perf_counter_ns() - started) / 1_000_000
        self._send_json(200, {
            "model": {"id": model_id, "name": entry["name"], "backend": entry["backend"], "path": str(_resolve_model_path(entry))},
            "device": device,
            "model_cached": cached,
            "load_latency_ms": round(load_ms, 2),
            "inference_latency_ms": round(inference_ms, 2),
            "answers": result.get("answers", {}),
        })


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Laya Playground ready at http://{HOST}:{PORT}")
    print(f"Model registry: {MODEL_CONFIG}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Laya Playground")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
