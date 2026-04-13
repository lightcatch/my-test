from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


TEST_ROOT = Path(__file__).resolve().parent
OUTPUTS_DIR = TEST_ROOT / "outputs"
MEMU_REPO = Path(r"d:\PyCode\gitcode\memU-1")
MEMU_ENV_FILE = MEMU_REPO / ".env"
MEMU_VENV_PYTHON = MEMU_REPO / ".venv" / "Scripts" / "python.exe"
MEMU_HEALTH_URL = "http://localhost:8000/health"

DEFAULT_QUERIES = [
    "我的长期偏好是什么？",
    "我最近常做什么事情？",
    "我在工作和学习上有什么特点？",
]

DOCKER_DESKTOP_CANDIDATES = [
    Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe"),
    Path(os.getenv("ProgramFiles", "")) / "Docker" / "Docker" / "Docker Desktop.exe",
    Path(os.getenv("LOCALAPPDATA", "")) / "Docker" / "Docker Desktop.exe",
]


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def warn(msg: str) -> None:
    print(f"[WARN] {msg}")


def error(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = OUTPUTS_DIR / f"memu_recall_benchmark_{timestamp}.json"
    parser = argparse.ArgumentParser(
        description="Auto benchmark MemU recall latency: RAG vs LLM (with Docker auto start and auto user_id)."
    )
    parser.add_argument("--user-id", default=None, help="Existing user_id. If omitted, auto-load from latest compare output.")
    parser.add_argument("--from-output", default=None, help="Load user_id from specified compare output JSON.")
    parser.add_argument("--runs", type=int, default=5, help="Measured runs per method.")
    parser.add_argument("--warmup-runs", type=int, default=1, help="Warmup runs per method (not counted).")
    parser.add_argument("--topk", type=int, default=10, help="Top-k memories to keep in each sample.")
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Query text. Can be passed multiple times. If omitted, uses default 3 Chinese queries.",
    )
    parser.add_argument("--output", default=str(default_output), help="Output JSON path.")
    parser.add_argument("--docker-timeout", type=int, default=300, help="Timeout seconds for Docker daemon readiness.")
    parser.add_argument("--health-timeout", type=int, default=180, help="Timeout seconds for MemU health readiness.")
    return parser.parse_args()


def maybe_reexec_into_memu_venv() -> None:
    if os.getenv("MEMU_BENCH_CHILD") == "1":
        return
    if not MEMU_VENV_PYTHON.exists():
        warn(f"MemU venv python not found: {MEMU_VENV_PYTHON}. Continue with current interpreter: {sys.executable}")
        return

    current = Path(sys.executable).resolve()
    target = MEMU_VENV_PYTHON.resolve()
    if current == target:
        return

    info(f"Re-exec with MemU venv python: {target}")
    cmd = [str(target), str(Path(__file__).resolve()), *sys.argv[1:]]
    env = os.environ.copy()
    env["MEMU_BENCH_CHILD"] = "1"
    proc = subprocess.run(cmd, env=env)
    raise SystemExit(proc.returncode)


def run_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout_sec: int | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Command not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timeout: {' '.join(cmd)}") from exc

    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n"
            f"cwd={cwd}\nstdout=\n{proc.stdout}\nstderr=\n{proc.stderr}"
        )
    return proc


def is_docker_ready() -> bool:
    try:
        proc = run_command(["docker", "info"], timeout_sec=20, check=False)
    except RuntimeError:
        return False
    return proc.returncode == 0


def start_docker_desktop() -> Path:
    seen: set[str] = set()
    for candidate in DOCKER_DESKTOP_CANDIDATES:
        candidate_str = str(candidate)
        if candidate_str in seen or not candidate_str.strip():
            continue
        seen.add(candidate_str)
        if not candidate.exists():
            continue
        subprocess.Popen([candidate_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return candidate
    raise RuntimeError(
        "Docker daemon unavailable and Docker Desktop.exe not found. "
        "Please install/start Docker Desktop first."
    )


def ensure_docker_ready(timeout_sec: int) -> None:
    if is_docker_ready():
        info("Docker daemon is ready")
        return

    started_path = start_docker_desktop()
    info(f"Docker daemon not ready, started Desktop: {started_path}")
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if is_docker_ready():
            info("Docker daemon became ready")
            return
        time.sleep(3)
    raise RuntimeError(f"Docker daemon not ready after {timeout_sec}s")


def compose_up_memu_stack() -> None:
    if not MEMU_REPO.exists():
        raise RuntimeError(f"MemU repo not found: {MEMU_REPO}")
    info("Running docker compose up -d for MemU stack")
    run_command(["docker", "compose", "up", "-d"], cwd=MEMU_REPO, timeout_sec=180, check=True)


def wait_memu_health(url: str, timeout_sec: int) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last_error = "no response"
    with httpx.Client(timeout=10.0) as client:
        while time.time() < deadline:
            try:
                resp = client.get(url)
                if 200 <= resp.status_code < 300:
                    payload = resp.json()
                    if payload.get("status") == "healthy":
                        info("MemU health check passed")
                        return payload
                    last_error = f"unexpected payload: {payload}"
                else:
                    last_error = f"status={resp.status_code}, body={resp.text[:200]}"
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(2)
    raise RuntimeError(f"MemU health timeout after {timeout_sec}s: {last_error}")


def parse_dotenv(path: Path) -> dict[str, str]:
    env_map: dict[str, str] = {}
    if not path.exists():
        return env_map
    text = path.read_text(encoding="utf-8", errors="ignore")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        env_map[key] = value
    return env_map


def env_value(name: str, file_env: dict[str, str], default: str = "") -> str:
    val = os.getenv(name)
    if val is not None and val != "":
        return val
    return file_env.get(name, default)


def parse_bool(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url_for_local(raw_url: str) -> str:
    if not raw_url:
        return raw_url
    parts = urlsplit(raw_url)
    host = parts.hostname or ""
    if host.lower() not in {"postgres", "db", "memu-1-postgres-1"}:
        return raw_url

    userinfo = ""
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo = f"{userinfo}:{parts.password}"
    host_port = "localhost"
    if parts.port:
        host_port = f"{host_port}:{parts.port}"
    netloc = f"{userinfo}@{host_port}" if userinfo else host_port
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def build_llm_profiles(file_env: dict[str, str]) -> dict[str, dict[str, str]]:
    api_key = env_value("OPENAI_API_KEY", file_env, "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing in environment and .env")

    base_url = env_value("OPENAI_BASE_URL", file_env, "https://api.openai.com/v1").strip()
    chat_model = env_value("CHAT_MODEL", file_env, "gpt-4o-mini").strip()
    embed_model = env_value("EMBED_MODEL", file_env, "text-embedding-3-small").strip()
    enable_event_embedding = parse_bool(env_value("ENABLE_EVENT_EMBEDDING", file_env, "false"))

    if enable_event_embedding:
        embedding_provider = env_value("EMBEDDING_PROVIDER", file_env, "openai").strip()
        embedding_api_key = env_value("EMBEDDING_API_KEY", file_env, api_key).strip()
        embedding_base_url = env_value("EMBEDDING_BASE_URL", file_env, base_url).strip()
        embedding_model = env_value("EMBEDDING_MODEL", file_env, embed_model).strip()
        return {
            "default": {
                "provider": "openai",
                "base_url": base_url,
                "api_key": api_key,
                "chat_model": chat_model,
                "client_backend": "sdk",
            },
            "embedding": {
                "provider": embedding_provider,
                "base_url": embedding_base_url,
                "api_key": embedding_api_key,
                "embed_model": embedding_model,
                "client_backend": "httpx",
            },
        }

    return {
        "default": {
            "provider": "openai",
            "base_url": base_url,
            "api_key": api_key,
            "chat_model": chat_model,
            "client_backend": "sdk",
        },
        "embedding": {
            "provider": "openai",
            "base_url": base_url,
            "api_key": api_key,
            "embed_model": embed_model,
            "client_backend": "sdk",
        },
    }


def build_database_config(file_env: dict[str, str]) -> dict[str, dict[str, str]]:
    db_url = env_value("DATABASE_URL", file_env, "").strip()
    if db_url:
        dsn = normalize_database_url_for_local(db_url)
    else:
        db_name = env_value("POSTGRES_DB", file_env, "memu").strip()
        db_user = env_value("POSTGRES_USER", file_env, "memu").strip()
        db_password = env_value("POSTGRES_PASSWORD", file_env, "memu123").strip()
        db_port = env_value("POSTGRES_PORT", file_env, "5432").strip()
        dsn = f"postgresql://{db_user}:{db_password}@localhost:{db_port}/{db_name}"
    return {"metadata_store": {"provider": "postgres", "dsn": dsn}}


def latest_compare_output(outputs_dir: Path) -> Path | None:
    candidates = sorted(outputs_dir.glob("memory_assoc_compare*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def resolve_user_id(args: argparse.Namespace) -> tuple[str, str]:
    if args.user_id:
        return args.user_id.strip(), "from --user-id"

    source_path: Path | None
    if args.from_output:
        source_path = Path(args.from_output).expanduser().resolve()
    else:
        source_path = latest_compare_output(OUTPUTS_DIR)

    if source_path is None or not source_path.exists():
        raise RuntimeError(
            "No compare output found for user_id. "
            f"Expected pattern: {OUTPUTS_DIR / 'memory_assoc_compare*.json'}; "
            "or pass --user-id / --from-output."
        )

    try:
        payload = json.loads(source_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to parse output JSON: {source_path}") from exc

    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise RuntimeError(f"user_id missing in output file: {source_path}")

    return user_id.strip(), f"from output file: {source_path}"


def simplify_memories(items: list[Any], topk: int) -> list[dict[str, str]]:
    simplified: list[dict[str, str]] = []
    for item in items[:topk]:
        if isinstance(item, dict):
            simplified.append({
                "summary": str(item.get("summary", "")).strip(),
                "memory_type": str(item.get("memory_type", "unknown")).strip() or "unknown",
            })
        else:
            simplified.append({"summary": str(item), "memory_type": "unknown"})
    return simplified


def calculate_stats(timings_ms: list[float]) -> dict[str, float]:
    if not timings_ms:
        return {"avg_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
    return {
        "avg_ms": sum(timings_ms) / len(timings_ms),
        "min_ms": min(timings_ms),
        "max_ms": max(timings_ms),
    }


def add_memu_src_to_path() -> None:
    src = MEMU_REPO / "src"
    if not src.exists():
        raise RuntimeError(f"MemU src not found: {src}")
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)


async def run_single_round(
    service: Any,
    *,
    method: str,
    user_id: str,
    queries: list[str],
    topk: int,
) -> list[dict[str, Any]]:
    service.retrieve_config.method = method
    outputs: list[dict[str, Any]] = []
    for query in queries:
        result = await service.retrieve(
            queries=[{"role": "user", "content": {"text": query}}],
            where={"user_id": user_id},
        )
        items = result.get("items", []) if isinstance(result, dict) else []
        outputs.append({
            "query": query,
            "items_count": len(items),
            "sample_memories": simplify_memories(items, topk),
        })
    return outputs


async def benchmark_method(
    service: Any,
    *,
    method: str,
    user_id: str,
    queries: list[str],
    runs: int,
    warmup_runs: int,
    topk: int,
) -> dict[str, Any]:
    info(f"Benchmark start: method={method}, warmup={warmup_runs}, runs={runs}")
    for i in range(1, warmup_runs + 1):
        await run_single_round(service, method=method, user_id=user_id, queries=queries, topk=topk)
        info(f"Warmup {method}: {i}/{warmup_runs}")

    timings_ms: list[float] = []
    sample_queries: list[dict[str, Any]] | None = None
    for i in range(1, runs + 1):
        t0 = time.perf_counter()
        round_output = await run_single_round(service, method=method, user_id=user_id, queries=queries, topk=topk)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        timings_ms.append(elapsed_ms)
        if sample_queries is None:
            sample_queries = round_output
        info(f"Measured {method}: {i}/{runs} -> {elapsed_ms:.2f} ms")

    stats = calculate_stats(timings_ms)
    return {
        "status": "ok",
        "runs": runs,
        "warmup_runs": warmup_runs,
        "timings_ms": timings_ms,
        "stats": stats,
        "sample": sample_queries or [],
    }


def build_conclusion(rag_result: dict[str, Any], llm_result: dict[str, Any]) -> dict[str, Any]:
    rag_ok = rag_result.get("status") == "ok"
    llm_ok = llm_result.get("status") == "ok"

    if not rag_ok:
        msg = "RAG 基准失败，无法生成有效对比结论。"
        return {"status": "error", "message": msg}

    rag_avg = float((rag_result.get("stats") or {}).get("avg_ms", 0.0))
    if not llm_ok:
        llm_err = llm_result.get("error", "unknown")
        msg = f"仅完成 RAG 测试；LLM 测试失败：{llm_err}"
        return {
            "status": "partial",
            "message": msg,
            "rag_avg_ms": rag_avg,
            "llm_avg_ms": None,
            "delta_ms": None,
            "llm_over_rag_ratio": None,
        }

    llm_avg = float((llm_result.get("stats") or {}).get("avg_ms", 0.0))
    delta = llm_avg - rag_avg
    ratio = (llm_avg / rag_avg) if rag_avg > 0 else None

    if delta > 0:
        msg = f"RAG 更快，LLM 平均慢 {delta:.2f} ms（约 {ratio:.2f}x）。"
    elif delta < 0:
        msg = f"LLM 更快，平均快 {-delta:.2f} ms（LLM/RAG 约 {ratio:.2f}x）。"
    else:
        msg = "RAG 与 LLM 平均耗时几乎一致。"

    return {
        "status": "ok",
        "message": msg,
        "rag_avg_ms": rag_avg,
        "llm_avg_ms": llm_avg,
        "delta_ms": delta,
        "llm_over_rag_ratio": ratio,
    }


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    if args.runs <= 0:
        raise RuntimeError("--runs must be > 0")
    if args.warmup_runs < 0:
        raise RuntimeError("--warmup-runs must be >= 0")
    if args.topk <= 0:
        raise RuntimeError("--topk must be > 0")

    queries = [q for q in args.query if isinstance(q, str) and q.strip()] or list(DEFAULT_QUERIES)
    user_id, user_id_source = resolve_user_id(args)
    info(f"Using user_id: {user_id} ({user_id_source})")

    ensure_docker_ready(timeout_sec=args.docker_timeout)
    compose_up_memu_stack()
    health_payload = wait_memu_health(MEMU_HEALTH_URL, timeout_sec=args.health_timeout)

    file_env = parse_dotenv(MEMU_ENV_FILE)
    llm_profiles = build_llm_profiles(file_env)
    database_config = build_database_config(file_env)

    add_memu_src_to_path()
    from memu.app import MemoryService

    retrieve_config = {
        "method": "rag",
        "route_intention": False,
        "sufficiency_check": False,
        "category": {"enabled": True, "top_k": 20},
        "item": {"enabled": True, "top_k": max(args.topk, 5), "ranking": "similarity"},
        "resource": {"enabled": True, "top_k": 20},
    }

    info("Initializing MemoryService for direct benchmark")
    service = MemoryService(
        llm_profiles=llm_profiles,
        database_config=database_config,
        retrieve_config=retrieve_config,
    )

    rag_result = await benchmark_method(
        service,
        method="rag",
        user_id=user_id,
        queries=queries,
        runs=args.runs,
        warmup_runs=args.warmup_runs,
        topk=args.topk,
    )

    try:
        llm_result = await benchmark_method(
            service,
            method="llm",
            user_id=user_id,
            queries=queries,
            runs=args.runs,
            warmup_runs=args.warmup_runs,
            topk=args.topk,
        )
    except Exception as exc:  # noqa: BLE001
        llm_result = {
            "status": "error",
            "error": str(exc),
        }
        warn(f"LLM benchmark failed: {exc}")

    conclusion = build_conclusion(rag_result, llm_result)

    now = datetime.now().isoformat(timespec="seconds")
    output = {
        "timestamp": now,
        "user_id": user_id,
        "user_id_source": user_id_source,
        "queries": queries,
        "runs": args.runs,
        "warmup_runs": args.warmup_runs,
        "topk": args.topk,
        "docker": {
            "compose_project_dir": str(MEMU_REPO),
            "health_url": MEMU_HEALTH_URL,
            "health_payload": health_payload,
        },
        "runtime": {
            "python_executable": sys.executable,
            "memu_env_file": str(MEMU_ENV_FILE),
            "database_dsn": database_config["metadata_store"]["dsn"],
        },
        "rag": rag_result,
        "llm": llm_result,
        "summary": conclusion,
    }
    return output


def print_terminal_summary(result: dict[str, Any]) -> None:
    rag = result.get("rag", {})
    llm = result.get("llm", {})
    summary = result.get("summary", {})

    print("\n================ 召回耗时对比结论 ================")
    if rag.get("status") == "ok":
        print(f"RAG 平均耗时: {(rag.get('stats') or {}).get('avg_ms', 0.0):.2f} ms")
        print(f"RAG 最小/最大: {(rag.get('stats') or {}).get('min_ms', 0.0):.2f} / {(rag.get('stats') or {}).get('max_ms', 0.0):.2f} ms")
    else:
        print("RAG 平均耗时: N/A")

    if llm.get("status") == "ok":
        print(f"LLM 平均耗时: {(llm.get('stats') or {}).get('avg_ms', 0.0):.2f} ms")
        print(f"LLM 最小/最大: {(llm.get('stats') or {}).get('min_ms', 0.0):.2f} / {(llm.get('stats') or {}).get('max_ms', 0.0):.2f} ms")
    else:
        print(f"LLM 平均耗时: N/A ({llm.get('error', 'unknown error')})")

    delta = summary.get("delta_ms")
    ratio = summary.get("llm_over_rag_ratio")
    if isinstance(delta, (int, float)):
        print(f"差值(ms): {delta:.2f}")
    else:
        print("差值(ms): N/A")
    if isinstance(ratio, (int, float)):
        print(f"倍率(LLM/RAG): {ratio:.2f}x")
    else:
        print("倍率(LLM/RAG): N/A")
    print(f"结论: {summary.get('message', 'N/A')}")
    print("==================================================\n")


def save_output(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"Saved benchmark result: {output_path}")


def main() -> int:
    maybe_reexec_into_memu_venv()
    args = parse_args()
    output_path = Path(args.output).expanduser().resolve()

    try:
        result = asyncio.run(run_benchmark(args))
        save_output(result, output_path)
        print_terminal_summary(result)
        return 0
    except Exception as exc:  # noqa: BLE001
        error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
