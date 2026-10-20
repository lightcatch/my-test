"""Download autotrust/JEV-9B with resumable ranged HTTPS requests."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.request import urlopen


REPO = "autotrust/JEV-9B"
ROOT = Path(__file__).resolve().parent
DEST = ROOT / "jev9b_model"
DEFAULT_REVISION = "main"
CHUNK_SIZE = 8 * 1024 * 1024


def _files_from_hub(revision: str) -> dict[str, int]:
    # The Hub tree API defaults to 50 entries; this repository has additional
    # tokenizer and vision-serving files after that boundary.
    api = f"https://huggingface.co/api/models/{REPO}/tree/{revision}?recursive=true&expand=true&limit=100"
    try:
        with urlopen(api, timeout=60) as response:
            entries = json.load(response)
    except Exception as first_error:
        command = f"(Invoke-RestMethod -Uri '{api}') | ConvertTo-Json -Depth 8 -Compress"
        try:
            raw = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", command], text=True)
            entries = json.loads(raw)
        except Exception as second_error:
            raise RuntimeError(f"Could not query Hugging Face metadata: {first_error}; {second_error}") from second_error
    files = {entry["path"]: int(entry["size"]) for entry in entries if entry.get("type") == "file" and entry.get("size") is not None}
    if not files:
        raise RuntimeError("Hugging Face returned no file sizes")
    return files


def _download(url: str, target: Path, expected: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    chunk = target.with_name(target.name + ".range")
    headers = target.with_name(target.name + ".headers")
    if part.exists() and part.stat().st_size > expected:
        part.unlink()
    existing = part.stat().st_size if part.exists() else 0
    with part.open("ab") as output:
        while existing < expected:
            end = min(expected - 1, existing + CHUNK_SIZE - 1)
            wanted = end - existing + 1
            for attempt in range(1, 11):
                result = subprocess.run(
                    ["curl.exe", "--silent", "--show-error", "--fail", "--location",
                     "--proxy", os.environ.get("JEV_CURL_PROXY", "http://127.0.0.1:10809"),
                     "--range", f"{existing}-{end}", "--connect-timeout", "30", "--max-time", "300",
                     "--dump-header", str(headers), "--output", str(chunk), url],
                    text=True, capture_output=True,
                )
                text_headers = headers.read_text(encoding="latin-1", errors="replace") if headers.exists() else ""
                matches = re.findall(r"(?im)^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", text_headers)
                received = chunk.stat().st_size if chunk.exists() else -1
                if result.returncode == 0 and matches:
                    start, finish, total = map(int, matches[-1])
                    if (start, finish, total, received) == (existing, end, expected, wanted):
                        with chunk.open("rb") as source:
                            while block := source.read(1024 * 1024):
                                output.write(block)
                        output.flush()
                        existing += wanted
                        break
                if attempt == 10:
                    raise RuntimeError(f"range {existing}-{end} failed: {result.stderr.strip() or 'invalid response'}")
                time.sleep(min(30, attempt * 2))
            else:
                raise AssertionError("unreachable")
    if part.stat().st_size != expected:
        raise RuntimeError(f"size mismatch for {part}")
    os.replace(part, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--metadata", help="Saved JSON list from the Hub tree API")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("--workers must be between 1 and 8")
    if args.metadata:
        raw = json.loads(Path(args.metadata).read_text(encoding="utf-8"))
        entries = raw if isinstance(raw, list) else raw.get("value", raw.get("siblings", []))
        files = {entry["path"] if "path" in entry else entry["rfilename"]: int(entry["size"])
                 for entry in entries if entry.get("size") is not None}
    else:
        files = _files_from_hub(args.revision)
    DEST.mkdir(parents=True, exist_ok=True)
    total = sum(files.values())

    def one(item: tuple[str, int]) -> tuple[str, int, bool]:
        relative, expected = item
        target = DEST / relative
        if target.is_file() and target.stat().st_size == expected:
            return relative, expected, True
        print(f"GET {relative} ({expected:,} bytes)", flush=True)
        _download(f"https://huggingface.co/{REPO}/resolve/{args.revision}/{relative}", target, expected)
        return relative, expected, False

    complete = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(one, item) for item in files.items()]
        for future in as_completed(futures):
            relative, size, skipped = future.result()
            complete += size
            print(f"{'SKIP' if skipped else 'DONE'} {relative}; {complete:,}/{total:,}", flush=True)
    print(f"PASS: downloaded {REPO}@{args.revision} to {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
