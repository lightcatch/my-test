from collections import defaultdict
from io import BytesIO
from pathlib import Path
import csv
import os
import re
import subprocess
import time
from urllib.parse import quote
import wave

from huggingface_hub import HfApi, hf_hub_download
from huggingface_hub.utils import close_session
import pyarrow.parquet as pq


DATASET_ID = "zhifeixie/Voices-in-the-Wild-2M"
DEFAULT_SHARD_COUNTS = {
    "distortion": 57,
    "distortion_dropout": 3,
    "distortion_dropout_noise": 3,
    "distortion_noise": 3,
    "dropout": 57,
    "echo": 57,
    "echo_distortion": 3,
    "echo_distortion_dropout": 3,
    "echo_distortion_dropout_noise": 3,
    "echo_dropout": 3,
    "echo_noise": 3,
    "echo_recording": 3,
    "echo_recording_distortion": 3,
    "echo_recording_distortion_dropout": 3,
    "echo_recording_distortion_dropout_noise": 3,
    "echo_recording_distortion_noise": 3,
    "echo_recording_dropout": 3,
    "echo_recording_dropout_noise": 3,
    "far_field": 57,
    "far_field_distortion": 3,
    "far_field_distortion_dropout": 3,
    "far_field_distortion_dropout_noise": 3,
    "far_field_dropout": 41,
    "far_field_noise": 131,
    "far_field_recording": 40,
    "far_field_recording_distortion": 3,
    "far_field_recording_distortion_dropout": 3,
    "far_field_recording_distortion_dropout_noise": 3,
    "far_field_recording_distortion_noise": 3,
    "far_field_recording_dropout": 3,
    "far_field_recording_dropout_noise": 3,
    "noise": 131,
    "noise_dropout": 40,
    "obstructed": 57,
    "obstructed_distortion": 3,
    "obstructed_distortion_dropout": 3,
    "obstructed_distortion_dropout_noise": 3,
    "obstructed_dropout": 3,
    "obstructed_noise": 3,
    "obstructed_recording": 3,
    "obstructed_recording_distortion": 3,
    "obstructed_recording_distortion_dropout": 3,
    "obstructed_recording_distortion_dropout_noise": 3,
    "obstructed_recording_distortion_noise": 3,
    "obstructed_recording_dropout": 3,
    "obstructed_recording_dropout_noise": 3,
    "recording": 57,
    "recording_distortion": 3,
    "recording_distortion_dropout": 3,
    "recording_distortion_dropout_noise": 3,
    "recording_distortion_noise": 3,
    "recording_dropout": 3,
    "recording_dropout_noise": 3,
    "recording_noise": 3,
}


def optional_int_env(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


# None means export every audio type discovered in data/*.parquet.
# Example for selected types: audio_types = ["far_field", "echo", "dropout"]
audio_types_env = os.getenv("HF_AUDIO_TYPES")
audio_types = [item.strip() for item in audio_types_env.split(",") if item.strip()] if audio_types_env else None

# Set to a small number for testing. None means no limit.
total_limit = optional_int_env("HF_TOTAL_LIMIT", None)
limit_per_type = optional_int_env("HF_LIMIT_PER_TYPE", None)

# Set to 1.0 if you want to skip audio shorter than one second.
min_duration_seconds = 0.0
download_max_attempts = optional_int_env("HF_DOWNLOAD_MAX_ATTEMPTS", 2)
curl_max_attempts = optional_int_env("HF_CURL_MAX_ATTEMPTS", 50)
discover_max_attempts = optional_int_env("HF_DISCOVER_MAX_ATTEMPTS", 10)
use_remote_discovery = os.getenv("HF_USE_REMOTE_DISCOVERY", "0") == "1"
use_curl_only = os.getenv("HF_USE_CURL_ONLY", "0") == "1"

proxy_url = os.getenv("HF_PROXY", "http://127.0.0.1:10809")
if proxy_url:
    os.environ["HTTP_PROXY"] = proxy_url
    os.environ["HTTPS_PROXY"] = proxy_url
    os.environ.pop("ALL_PROXY", None)
    os.environ.pop("all_proxy", None)
    print(f"using proxy: {proxy_url}")

out_root = Path("downloaded_audio")
out_root.mkdir(parents=True, exist_ok=True)
metadata_path = out_root / "metadata.csv"
parquet_cache_dir = Path("ASR_test") / ".parquet_cache"


def discover_parquet_files():
    pattern = re.compile(r"^data/(.+)-(\d{5})-of-(\d{5})\.parquet$")
    groups = defaultdict(list)

    if not use_remote_discovery:
        for audio_type, shard_count in DEFAULT_SHARD_COUNTS.items():
            for shard_index in range(shard_count):
                repo_file = f"data/{audio_type}-{shard_index:05d}-of-{shard_count:05d}.parquet"
                groups[audio_type].append((shard_index, shard_count, repo_file))
        return {
            audio_type: [item[2] for item in sorted(shards)]
            for audio_type, shards in sorted(groups.items())
            if audio_types is None or audio_type in set(audio_types)
        }

    last_error = None
    for attempt in range(1, discover_max_attempts + 1):
        try:
            api = HfApi()
            for repo_file in api.list_repo_files(DATASET_ID, repo_type="dataset"):
                match = pattern.match(repo_file)
                if not match:
                    continue

                audio_type = match.group(1)
                shard_index = int(match.group(2))
                shard_count = int(match.group(3))
                groups[audio_type].append((shard_index, shard_count, repo_file))
            break
        except Exception as exc:
            last_error = exc
            close_session()
            wait_seconds = min(60, attempt * 5)
            print(
                f"file discovery failed ({attempt}/{discover_max_attempts})\n"
                f"{type(exc).__name__}: {exc}\n"
                f"retrying in {wait_seconds}s..."
            )
            time.sleep(wait_seconds)

    if not groups:
        print(f"file discovery failed, using built-in shard list: {last_error}")
        for audio_type, shard_count in DEFAULT_SHARD_COUNTS.items():
            for shard_index in range(shard_count):
                repo_file = f"data/{audio_type}-{shard_index:05d}-of-{shard_count:05d}.parquet"
                groups[audio_type].append((shard_index, shard_count, repo_file))

    selected = set(audio_types) if audio_types else None
    result = {}
    for audio_type, shards in sorted(groups.items()):
        if selected is not None and audio_type not in selected:
            continue
        result[audio_type] = [item[2] for item in sorted(shards)]

    return result


def wav_duration(audio_bytes):
    try:
        with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
            return wav_file.getnframes() / wav_file.getframerate()
    except wave.Error:
        return None


def download_parquet_with_retry(filename):
    if use_curl_only:
        return download_parquet_with_curl(filename)

    last_error = None
    for attempt in range(1, download_max_attempts + 1):
        try:
            return hf_hub_download(
                repo_id=DATASET_ID,
                repo_type="dataset",
                filename=filename,
            )
        except Exception as exc:
            last_error = exc
            close_session()
            wait_seconds = min(60, attempt * 5)
            print(
                f"download failed ({attempt}/{download_max_attempts}): {filename}\n"
                f"{type(exc).__name__}: {exc}\n"
                f"retrying in {wait_seconds}s..."
            )
            time.sleep(wait_seconds)

    print(f"falling back to curl download: {filename}")
    return download_parquet_with_curl(filename, last_error)


def download_parquet_with_curl(filename, last_error=None):
    cache_path = parquet_cache_dir / filename
    part_path = cache_path.with_suffix(cache_path.suffix + ".part")

    if cache_path.exists() and cache_path.stat().st_size > 0:
        return str(cache_path)

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    encoded_filename = quote(filename, safe="/-_.")
    url = f"https://huggingface.co/datasets/{DATASET_ID}/resolve/main/{encoded_filename}"
    args = [
        "curl.exe",
        "-L",
        "--fail",
        "--retry",
        str(curl_max_attempts),
        "--retry-delay",
        "5",
        "--retry-all-errors",
        "--connect-timeout",
        "30",
        "--speed-time",
        "120",
        "--speed-limit",
        "1024",
        "-C",
        "-",
        "-o",
        str(part_path),
        url,
    ]
    if proxy_url:
        args[1:1] = ["-x", proxy_url]

    try:
        subprocess.run(args, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"curl fallback failed: {filename}") from (last_error or exc)

    part_path.replace(cache_path)
    return str(cache_path)


def export_row(row, audio_type, type_row_number, global_row_number, writer):
    audio = row["audio"] or {}
    audio_bytes = audio.get("bytes")
    source_audio_path = row.get("file_name") or row.get("audio_path") or audio.get("path") or ""
    suffix = Path(source_audio_path).suffix or ".wav"
    duration = wav_duration(audio_bytes) if audio_bytes else None

    type_dir = out_root / audio_type
    type_dir.mkdir(parents=True, exist_ok=True)
    dst = type_dir / f"{type_row_number:08d}{suffix}"
    saved_path = dst.relative_to(out_root).as_posix()

    skipped_reason = ""
    if not audio_bytes:
        skipped_reason = "missing_audio_bytes"
    elif duration is not None and duration < min_duration_seconds:
        skipped_reason = "short_audio"
    elif dst.exists():
        skipped_reason = "already_exists"
    else:
        dst.write_bytes(audio_bytes)

    writer.writerow(
        {
            "saved_path": saved_path if skipped_reason != "missing_audio_bytes" else "",
            "audio_type": audio_type,
            "duration_seconds": "" if duration is None else round(duration, 3),
            "text": row.get("text", ""),
            "answer": row.get("answer", ""),
            "question": row.get("question", ""),
            "name": row.get("name", ""),
            "index": row.get("index", ""),
            "subset": row.get("subset", ""),
            "source_audio_path": source_audio_path,
            "global_row_number": global_row_number,
            "type_row_number": type_row_number,
            "skipped_reason": skipped_reason,
        }
    )

    return skipped_reason in ("", "already_exists"), bool(skipped_reason)


saved = 0
skipped = 0
processed = 0
processed_by_type = defaultdict(int)

parquet_files_by_type = discover_parquet_files()
print("audio types:", ", ".join(parquet_files_by_type.keys()))
print("parquet shards:", sum(len(files) for files in parquet_files_by_type.values()))

with metadata_path.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "saved_path",
            "audio_type",
            "duration_seconds",
            "text",
            "answer",
            "question",
            "name",
            "index",
            "subset",
            "source_audio_path",
            "global_row_number",
            "type_row_number",
            "skipped_reason",
        ],
    )
    writer.writeheader()

    for audio_type, parquet_files in parquet_files_by_type.items():
        if total_limit is not None and processed >= total_limit:
            break

        print(f"audio type: {audio_type}, shards: {len(parquet_files)}")

        for filename in parquet_files:
            if total_limit is not None and processed >= total_limit:
                break
            if limit_per_type is not None and processed_by_type[audio_type] >= limit_per_type:
                break

            print(f"downloading/using shard: {filename}")
            parquet_path = download_parquet_with_retry(filename)

            parquet_file = pq.ParquetFile(parquet_path)
            for row_group_index in range(parquet_file.num_row_groups):
                table = parquet_file.read_row_group(row_group_index)
                for row in table.to_pylist():
                    if total_limit is not None and processed >= total_limit:
                        break
                    if limit_per_type is not None and processed_by_type[audio_type] >= limit_per_type:
                        break

                    type_row_number = processed_by_type[audio_type]
                    row_saved, row_skipped = export_row(
                        row=row,
                        audio_type=audio_type,
                        type_row_number=type_row_number,
                        global_row_number=processed,
                        writer=writer,
                    )
                    saved += int(row_saved)
                    skipped += int(row_skipped)
                    processed += 1
                    processed_by_type[audio_type] += 1

                    if processed % 100 == 0:
                        print(f"processed {processed}, saved {saved}, skipped {skipped}")
                        f.flush()

print(f"done: processed {processed}, saved {saved}, skipped {skipped}")
print(f"audio dir: {out_root.resolve()}")
print(f"metadata: {metadata_path.resolve()}")
