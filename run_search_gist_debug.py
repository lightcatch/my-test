from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
from memobase import ChatBlob, MemoBaseClient


MEMOBASE_COMPOSE_DIR = Path(r"d:\PyCode\gitcode\memobase\src\server")
MEMU_COMPOSE_DIR = Path(r"d:\PyCode\gitcode\memU-1")

QUERIES = [
    "我的长期偏好是什么？",
    "我最近常做什么事情？",
    "我在工作和学习上有什么特点？",
]

# 按 memobase_add.py 风格：每条是 user/assistant 两条消息
BASE_DIALOGS: list[tuple[str, str]] = [
    ("喜欢甜食", "理解"),
    ("不太能吃辣", "好的，我记住了"),
    ("周末喜欢看纪录片", "收到"),
    ("平时更喜欢安静的咖啡馆", "明白"),
    ("常用 Python 做数据分析", "了解"),
    ("最近在学习机器学习", "好的"),
    ("晚上十一点前会休息", "知道了"),
    ("周末会去徒步", "我记住了"),
    ("更喜欢地铁出行", "收到"),
    ("喜欢手冲咖啡", "理解"),
    ("工作中常写技术文档", "好的，我记住了"),
    ("习惯用清单管理任务", "明白"),
    ("常听播客放松", "了解"),
    ("喜欢阅读科幻小说", "好的"),
    ("偏好清淡饮食", "知道了"),
    ("最近在做检索相关项目", "我记住了"),
    ("会定期复盘工作", "收到"),
    ("喜欢小范围社交", "理解"),
    ("关注 AI 工具和应用", "好的，我记住了"),
    ("经常整理知识卡片", "明白"),
]


def build_args() -> argparse.Namespace:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_output = Path(__file__).resolve().parent / "outputs" / f"memory_assoc_compare_{timestamp}.json"
    parser = argparse.ArgumentParser(description="Compare Memobase and MemU memory association results.")
    parser.add_argument("--mem-count", type=int, default=100)
    parser.add_argument("--memobase-url", default="http://localhost:8019")
    parser.add_argument("--memobase-api-key", default="secret")
    parser.add_argument("--memu-url", default="http://localhost:8000")
    parser.add_argument("--topk", type=int, default=10)
    parser.add_argument("--output", default=str(default_output))
    return parser.parse_args()


def run_cmd(command: list[str], cwd: Path) -> None:
    proc = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n"
            f"cwd={cwd}\nstdout=\n{proc.stdout}\nstderr=\n{proc.stderr}"
        )


def start_services() -> None:
    if not MEMOBASE_COMPOSE_DIR.exists():
        raise RuntimeError(f"Path not found: {MEMOBASE_COMPOSE_DIR}")
    if not MEMU_COMPOSE_DIR.exists():
        raise RuntimeError(f"Path not found: {MEMU_COMPOSE_DIR}")
    print("[INFO] docker compose up -d (memobase)")
    run_cmd(["docker", "compose", "up", "-d"], MEMOBASE_COMPOSE_DIR)
    print("[INFO] docker compose up -d (memu)")
    run_cmd(["docker", "compose", "up", "-d"], MEMU_COMPOSE_DIR)


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 3,
    sleep_sec: float = 1.0,
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
                time.sleep(sleep_sec * i)
                continue
            raise RuntimeError(f"{method} {url} failed after {retries} retries: {last_error}") from exc

        if 200 <= resp.status_code < 300:
            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{method} {url} invalid JSON: {resp.text}") from exc

        last_error = f"status={resp.status_code}, body={resp.text}"
        if resp.status_code in non_retryable:
            raise RuntimeError(f"{method} {url} non-retryable error: {last_error}")
        if i < retries:
            time.sleep(sleep_sec * i)

    raise RuntimeError(f"{method} {url} failed: {last_error}")


def wait_healthy(client: httpx.Client, name: str, url: str, checker, timeout_sec: int = 180) -> None:
    deadline = time.time() + timeout_sec
    last = "no response"
    while time.time() < deadline:
        try:
            resp = client.get(url)
            if 200 <= resp.status_code < 300:
                payload = resp.json()
                if checker(payload):
                    print(f"[INFO] {name} healthy")
                    return
                last = f"unexpected payload: {payload}"
            else:
                last = f"status={resp.status_code}, body={resp.text}"
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(3)
    raise RuntimeError(f"{name} health timeout: {last}")


def check_services(memobase_url: str, memobase_api_key: str, memu_url: str) -> None:
    memobase_url = memobase_url.rstrip("/")
    memu_url = memu_url.rstrip("/")
    with httpx.Client(timeout=30) as client:
        wait_healthy(
            client,
            "Memobase",
            f"{memobase_url}/api/v1/healthcheck",
            lambda data: data.get("errno") == 0,
        )
        wait_healthy(
            client,
            "MemU",
            f"{memu_url}/health",
            lambda data: data.get("status") == "healthy",
        )
        request_json(
            client,
            "GET",
            f"{memobase_url}/api/v1/project/users",
            headers={"Authorization": f"Bearer {memobase_api_key}"},
            params={"limit": 1, "offset": 0},
            non_retryable={401, 403},
        )
    print("[INFO] service checks passed")


def generate_dialogs(mem_count: int) -> list[list[dict[str, str]]]:
    dialogs: list[list[dict[str, str]]] = []
    for i in range(mem_count):
        user_text, assistant_text = BASE_DIALOGS[i % len(BASE_DIALOGS)]
        dialog = [
            {"role": "user", "content": f"{user_text}（样本{i + 1}）"},
            {"role": "assistant", "content": assistant_text},
        ]
        dialogs.append(dialog)
    return dialogs


def create_memobase_user(memobase_url: str, memobase_api_key: str, user_id: str):
    client = MemoBaseClient(project_url=memobase_url, api_key=memobase_api_key)
    if not client.ping():
        raise RuntimeError("Memobase ping failed")
    client.add_user(id=user_id)
    return client.get_user(user_id)


def insert_memobase(user, dialogs: list[list[dict[str, str]]]) -> None:
    print(f"[INFO] Memobase inserting {len(dialogs)} dialogs")
    for idx, dialog in enumerate(dialogs, start=1):
        blob = ChatBlob(messages=dialog)
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                user.insert(blob)
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt == 3:
                    raise RuntimeError(f"Memobase insert failed at index={idx}: {exc}") from exc
                time.sleep(attempt)
        if idx % 10 == 0 or idx == len(dialogs):
            print(f"[INFO] Memobase progress {idx}/{len(dialogs)}")
        if last_exc:
            print(f"[WARN] Memobase recovered at index={idx}: {last_exc}")

    print("[INFO] Memobase flush")
    for attempt in range(1, 4):
        try:
            user.flush(sync=True)
            print("[INFO] Memobase flush done")
            return
        except Exception as exc:  # noqa: BLE001
            if attempt == 3:
                raise RuntimeError(f"Memobase flush failed: {exc}") from exc
            time.sleep(attempt)


def insert_memu(memu_url: str, user_id: str, dialogs: list[list[dict[str, str]]]) -> None:
    print(f"[INFO] MemU inserting {len(dialogs)} dialogs")
    with httpx.Client(timeout=120) as client:
        for idx, dialog in enumerate(dialogs, start=1):
            request_json(
                client,
                "POST",
                f"{memu_url.rstrip('/')}/memorize",
                json={"content": json.dumps(dialog, ensure_ascii=False), "user_id": user_id},
                retries=3,
            )
            if idx % 10 == 0 or idx == len(dialogs):
                print(f"[INFO] MemU progress {idx}/{len(dialogs)}")


def query_memobase(
    client: httpx.Client,
    memobase_url: str,
    memobase_api_key: str,
    user_id: str,
    query: str,
    topk: int,
) -> dict:
    return request_json(
        client,
        "GET",
        f"{memobase_url.rstrip('/')}/api/v1/users/event_gist/search/{user_id}",
        headers={"Authorization": f"Bearer {memobase_api_key}"},
        params={
            "query": query,
            "topk": topk,
            "similarity_threshold": 0.2,
            "time_range_in_days": 3650,
        },
    )


def query_memu(client: httpx.Client, memu_url: str, user_id: str, query: str, topk: int) -> dict:
    return request_json(
        client,
        "GET",
        f"{memu_url.rstrip('/')}/recall",
        params={"query": query, "user_id": user_id, "limit": topk},
    )


def count_memobase(raw: dict) -> int:
    data = raw.get("data") or {}
    gists = data.get("gists") or []
    return len(gists) if isinstance(gists, list) else 0


def count_memu(raw: dict) -> int:
    memories = raw.get("memories") or []
    return len(memories) if isinstance(memories, list) else 0


def main() -> int:
    args = build_args()
    if args.mem_count <= 0:
        print("[ERROR] --mem-count must be > 0", file=sys.stderr)
        return 1
    if args.topk <= 0:
        print("[ERROR] --topk must be > 0", file=sys.stderr)
        return 1

    try:
        start_services()
        check_services(args.memobase_url, args.memobase_api_key, args.memu_url)

        user_id = str(uuid4())
        print(f"[INFO] new user_id={user_id}")

        dialogs = generate_dialogs(args.mem_count)
        print(f"[INFO] generated {len(dialogs)} dialogs in memobase_add-style JSON")

        memobase_user = create_memobase_user(args.memobase_url, args.memobase_api_key, user_id)
        insert_memobase(memobase_user, dialogs)
        insert_memu(args.memu_url, user_id, dialogs)

        result = {"user_id": user_id, "memory_count": len(dialogs), "queries": []}

        with httpx.Client(timeout=120) as client:
            for i, q in enumerate(QUERIES, start=1):
                print(f"\n[INFO] query {i}/{len(QUERIES)}: {q}")
                memobase_raw = query_memobase(client, args.memobase_url, args.memobase_api_key, user_id, q, args.topk)
                memu_raw = query_memu(client, args.memu_url, user_id, q, args.topk)
                block = {"query": q, "memobase_raw": memobase_raw, "memu_raw": memu_raw}
                result["queries"].append(block)
                print(json.dumps(block, ensure_ascii=False, indent=2))
                print(f"[INFO] hits -> Memobase={count_memobase(memobase_raw)}, MemU={count_memu(memu_raw)}")

        out_path = Path(args.output).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[INFO] saved: {out_path}")
        return 0

    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
