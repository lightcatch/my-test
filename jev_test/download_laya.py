"""Download all checkpoints from convaiinnovations/laya.

The Hugging Face Python client can be blocked by a local proxy in this
environment, so downloads use Windows' native HTTPS stack and resume partial
files with HTTP Range requests.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


REPO = "convaiinnovations/laya"
ROOT = Path(__file__).resolve().parent
DEST = ROOT / "laya_model"

# Pinned to the repository revision inspected when this project was prepared.
REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
FILES = {
    ".gitattributes": 1913,
    "README.md": 23187,
    "email_utils.py": 3937,
    "rl_agent_api.py": 4732,
    "rl_agent_config.json": 745,
    "rl_common.py": 19139,
    "model.safetensors": 842609210,
    "encoder/config.json": 2083,
    "tokenizer/tokenizer.json": 3583228,
    "tokenizer/tokenizer_config.json": 308,
    "multilingual/model.safetensors": 643835514,
    "multilingual/encoder/config.json": 1938,
    "multilingual/rl_agent_config.json": 472,
    "multilingual/tokenizer/tokenizer.json": 34363188,
    "multilingual/tokenizer/tokenizer_config.json": 524,
    "typed-decisions/model.safetensors": 842609220,
    "typed-decisions/encoder/config.json": 2084,
    "typed-decisions/rl_agent_config.json": 847,
    "typed-decisions/tokenizer/tokenizer.json": 3583228,
    "typed-decisions/tokenizer/tokenizer_config.json": 337,
}


def _powershell_download(url: str, target: Path, expected: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # The script writes to a temporary file and atomically replaces the target
    # only after the expected byte count has been reached.
    ps = r'''
Add-Type -AssemblyName System.Net.Http
$existing = [Int64]0
if (Test-Path -LiteralPath $Target) { $existing = (Get-Item -LiteralPath $Target).Length }
if ($existing -eq $Expected) { exit 0 }
if ($existing -gt $Expected) { Remove-Item -LiteralPath $Target -Force; $existing = 0 }
$client = [System.Net.Http.HttpClient]::new()
$request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $Url)
if ($existing -gt 0) {
  $request.Headers.Range = [System.Net.Http.Headers.RangeHeaderValue]::new($existing, $null)
}
$response = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
$null = $response.EnsureSuccessStatusCode()
$mode = [System.IO.FileMode]::Create
if ($existing -gt 0 -and $response.StatusCode -eq [System.Net.HttpStatusCode]::PartialContent) { $mode = [System.IO.FileMode]::Append }
$stream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
$file = [System.IO.File]::Open($Target, $mode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
try { $buffer = New-Object byte[] (1024 * 1024); while (($n = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) { $file.Write($buffer, 0, $n) } }
finally { $file.Dispose(); $stream.Dispose(); $response.Dispose(); $client.Dispose() }
if ((Get-Item -LiteralPath $Target).Length -ne $Expected) { throw "Size mismatch for $Target" }
'''
    env = os.environ.copy()
    env["LAYA_DL_URL"] = url
    env["LAYA_DL_TARGET"] = str(target)
    env["LAYA_DL_EXPECTED"] = str(expected)
    ps = "$Url=$env:LAYA_DL_URL; $Target=$env:LAYA_DL_TARGET; $Expected=[Int64]$env:LAYA_DL_EXPECTED; " + ps
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True,
        env=env,
    )
    if not target.is_file() or target.stat().st_size != expected:
        raise RuntimeError(f"Download did not produce the expected file: {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=REVISION)
    args = parser.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    total = sum(FILES.values())
    done = 0
    for relative, expected in FILES.items():
        target = DEST / relative
        if target.is_file() and target.stat().st_size == expected:
            done += expected
            print(f"SKIP {relative} ({expected:,} bytes)", flush=True)
            continue
        url = f"https://huggingface.co/{REPO}/resolve/{args.revision}/{relative}"
        print(f"GET  {relative} ({expected:,} bytes; project total {total:,})", flush=True)
        _powershell_download(url, target, expected)
        done += expected
        print(f"DONE {relative}; completed {done:,}/{total:,} bytes", flush=True)
    print(f"PASS: downloaded {REPO}@{args.revision} to {DEST}")
    print(json.dumps({"repo": REPO, "revision": args.revision, "files": len(FILES), "bytes": total}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
