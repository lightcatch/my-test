from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx


DEFAULT_QUERIES = [
    "我的长期偏好是什么？",
    "我最近常做什么事情？",
    "我在工作和学习上有什么特点？",
]


def parse_args() -> argparse.Namespace:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = Path(__file__).resolve().parent / "outputs" / f"memory_retrieve_only_{timestamp}.json"
    parser = argparse.ArgumentParser(description="Retrieve-only comparison for existing user memories in Memobase and MemU.")
    parser.add_argument("--user-id", default=None, help="Existing user_id. If omitted, auto-load from latest compare output.")
    parser.add_argument("--from-output", default=None, help="Load user_id from specified output json.")
    parser.add_argument("--memobase-url", default="http://localhost:8019")
    parser.add_argument("--memobase-api-key", default="secret")
    parser.add_argument("--memu-url", default="http://localhost:8000")
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--output", default=str(default_output))
    return parser.parse_args()


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 3,
    interval: float = 1.0,
    non_retryable: set[int] | None = None,
    **kwargs,
) -> dict:
    non_retryable = non_retryable or {400, 401, 403, 404}
    last_error = "unknown"
    for i in range(1, retries + 1):
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            last_error = str(exc)
            if i < retries:
                time.sleep(interval * i)
                continue
            raise RuntimeError(f"{method} {url} failed after retries: {last_error}") from exc

        if 200 <= resp.status_code < 300:
            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{method} {url} returned invalid JSON: {resp.text}") from exc

        last_error = f"status={resp.status_code}, body={resp.text}"
        if resp.status_code in non_retryable:
            raise RuntimeError(f"{method} {url} non-retryable error: {last_error}")
        if i < retries:
            time.sleep(interval * i)
    raise RuntimeError(f"{method} {url} failed: {last_error}")


def wait_healthy(client: httpx.Client, name: str, url: str, checker, timeout_sec: int = 120) -> None:
    deadline = time.time() + timeout_sec
    last_error = "no response"
    while time.time() < deadline:
        try:
            resp = client.get(url)
            if 200 <= resp.status_code < 300:
                payload = resp.json()
                if checker(payload):
                    print(f"[INFO] {name} healthy")
                    return
                last_error = f"unexpected payload: {payload}"
            else:
                last_error = f"status={resp.status_code}, body={resp.text}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"{name} health timeout: {last_error}")


def latest_output_file(outputs_dir: Path) -> Path | None:
    candidates = sorted(outputs_dir.glob("memory_assoc_compare*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def resolve_user_id(args: argparse.Namespace) -> str:
    if args.user_id:
        return args.user_id

    path: Path | None = None
    if args.from_output:
        path = Path(args.from_output).expanduser().resolve()
    else:
        path = latest_output_file(Path(__file__).resolve().parent / "outputs")

    if path is None or not path.exists():
        raise RuntimeError("No output file found to infer user_id. Pass --user-id or --from-output.")

    data = json.loads(path.read_text(encoding="utf-8"))
    user_id = data.get("user_id")
    if not isinstance(user_id, str) or not user_id.strip():
        raise RuntimeError(f"Cannot resolve user_id from file: {path}")

    print(f"[INFO] Using user_id from output file: {user_id} ({path.name})")
    return user_id


def count_memobase(raw: dict) -> int:
    gists = (raw.get("data") or {}).get("gists") or []
    return len(gists) if isinstance(gists, list) else 0


def count_memu(raw: dict) -> int:
    memories = raw.get("memories") or []
    return len(memories) if isinstance(memories, list) else 0


def main() -> int:
    args = parse_args()

    if args.topk <= 0:
        print("[ERROR] --topk must be > 0", file=sys.stderr)
        return 1

    try:
        user_id = resolve_user_id(args)

        memobase_url = args.memobase_url.rstrip("/")
        memu_url = args.memu_url.rstrip("/")

        with httpx.Client(timeout=60.0) as client:
            wait_healthy(client, "Memobase", f"{memobase_url}/api/v1/healthcheck", lambda d: d.get("errno") == 0)
            wait_healthy(client, "MemU", f"{memu_url}/health", lambda d: d.get("status") == "healthy")

            request_json(
                client,
                "GET",
                f"{memobase_url}/api/v1/project/users",
                headers={"Authorization": f"Bearer {args.memobase_api_key}"},
                params={"limit": 1, "offset": 0},
                non_retryable={401, 403},
            )

            result = {
                "user_id": user_id,
                "topk": args.topk,
                "queries": [],
            }

            for i, query in enumerate(DEFAULT_QUERIES, start=1):
                print(f"\n[INFO] Query {i}/{len(DEFAULT_QUERIES)}: {query}")
                memobase_raw = request_json(
                    client,
                    "GET",
                    f"{memobase_url}/api/v1/users/event_gist/search/{user_id}",
                    headers={"Authorization": f"Bearer {args.memobase_api_key}"},
                    params={
                        "query": query,
                        "topk": args.topk,
                        "similarity_threshold": 0.2,
                        "time_range_in_days": 3650,
                    },
                )
                memu_raw = request_json(
                    client,
                    "GET",
                    f"{memu_url}/recall",
                    params={"query": query, "user_id": user_id, "limit": args.topk},
                )

                block = {"query": query, "memobase_raw": memobase_raw, "memu_raw": memu_raw}
                result["queries"].append(block)
                print(json.dumps(block, ensure_ascii=False, indent=2))
                print(f"[INFO] Hits -> Memobase={count_memobase(memobase_raw)}, MemU={count_memu(memu_raw)}")

        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[INFO] Saved retrieval-only result: {output_path}")
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

